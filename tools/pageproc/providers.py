"""Pluggable LLM backends — Anthropic (Claude) and OpenAI (GPT).

Both expose the same two structured-output calls used by the pipeline:
    vision_json(model, crop_path, prompt, schema, effort) -> dict
    text_json(model, prompt, schema, effort) -> dict

The pipeline (extract.py / reconcile.py) is provider-agnostic and talks only to
this interface, so switching backends is a config change, not a code change.

Errors are normalized: a permanent out-of-credit condition raises QuotaExceeded
(no retry — actionable message); transient rate limits / timeouts / 5xx are
retried with exponential backoff that honors a Retry-After header when present.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

from . import image
from .config import Config

MAX_RETRIES = 8
MAX_DELAY = 60.0


class QuotaExceeded(RuntimeError):
    """The account is out of credit/quota — retrying will not help."""


def make(cfg: Config):
    if cfg.provider in ("openai", "ollama"):
        return OpenAIBackend(cfg)
    if cfg.provider == "anthropic":
        return AnthropicBackend(cfg)
    raise ValueError(f"unknown provider: {cfg.provider!r} (use 'anthropic', 'openai', or 'ollama')")


def _retry(fn, *, transient, is_quota, retry_after, quota_msg, label):
    """Call fn(); retry transient failures with backoff; fail fast on quota."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn()
        except transient as e:
            if is_quota(e):
                raise QuotaExceeded(quota_msg) from None
            if attempt == MAX_RETRIES:
                raise
            # Grow exponentially; honor Retry-After only if it's LONGER. A
            # saturated per-minute token bucket needs tens of seconds to drain,
            # so a tiny server-suggested wait must not short-circuit the backoff.
            backoff = min(MAX_DELAY, 2 ** attempt + random.random())
            delay = max(backoff, retry_after(e) or 0)
            print(f"[pageproc] {type(e).__name__} on {label}; "
                  f"retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)


def _retry_after_header(e):
    resp = getattr(e, "response", None)
    if resp is not None:
        v = resp.headers.get("retry-after")
        if v:
            try:
                return float(v)
            except ValueError:
                return None
    return None


# --------------------------------------------------------------------------- #
# Anthropic (Claude)
# --------------------------------------------------------------------------- #

class AnthropicBackend:
    def __init__(self, cfg: Config):
        import anthropic
        self.cfg = cfg
        self.client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
        self._transient = (anthropic.RateLimitError, anthropic.APITimeoutError,
                           anthropic.APIConnectionError, anthropic.InternalServerError)

    def _run(self, fn, label):
        return _retry(
            fn, transient=self._transient,
            is_quota=lambda e: False,          # Anthropic 429 == rate limit; retry it
            retry_after=_retry_after_header,
            quota_msg="", label=label,
        )

    def _call(self, model, effort, content, schema, label):
        def go():
            resp = self.client.messages.create(
                model=model,
                max_tokens=self.cfg.max_tokens,
                thinking={"type": "adaptive"},
                output_config={"effort": effort,
                               "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": content}],
            )
            text = next((b.text for b in resp.content if b.type == "text"), "{}")
            return json.loads(text)
        return self._run(go, label)

    def vision_json(self, model, crop_path: Path, prompt, schema, effort):
        data, media = image.b64(crop_path)
        content = [
            {"type": "image",
             "source": {"type": "base64", "media_type": media, "data": data},
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": prompt},
        ]
        return self._call(model, effort, content, schema, f"vision/{crop_path.name}")

    def text_json(self, model, prompt, schema, effort):
        return self._call(model, effort, [{"type": "text", "text": prompt}], schema, "reconcile")


# --------------------------------------------------------------------------- #
# OpenAI (GPT)
# --------------------------------------------------------------------------- #

_OPENAI_QUOTA_MSG = (
    "OpenAI API quota exhausted (insufficient_quota). This is a billing issue, "
    "not a bug — the request was well-formed.\n"
    "  1. Add credit at https://platform.openai.com/account/billing\n"
    "  2. Confirm the key's org/project at https://platform.openai.com/api-keys\n"
    "  (API billing is separate from a ChatGPT Plus subscription.)\n"
    "Then re-run the same command."
)


class OpenAIBackend:
    """OpenAI and any OpenAI-compatible server (vLLM / OpenRouter / DashScope / Ollama)."""

    def __init__(self, cfg: Config):
        import openai
        self.cfg = cfg
        self.compat = cfg.is_openai_compat            # non-OpenAI server -> looser params
        base_url = cfg.resolved_base_url or None
        # Local/compat servers don't need a real key; OpenAI reads OPENAI_API_KEY from env.
        api_key = "ollama" if cfg.provider == "ollama" else None
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self._transient = (openai.RateLimitError, openai.APITimeoutError,
                           openai.APIConnectionError, openai.InternalServerError)

    @staticmethod
    def _is_quota(e) -> bool:
        if getattr(e, "code", None) == "insufficient_quota":
            return True
        body = getattr(e, "body", None)
        if isinstance(body, dict) and body.get("error", {}).get("code") == "insufficient_quota":
            return True
        return "insufficient_quota" in str(e)

    def _run(self, fn, label):
        return _retry(
            fn, transient=self._transient, is_quota=self._is_quota,
            retry_after=_retry_after_header, quota_msg=_OPENAI_QUOTA_MSG, label=label,
        )

    @staticmethod
    def _loads(text: str) -> dict:
        """Parse JSON, tolerating ```json fences and leading/trailing prose."""
        t = text.strip()
        if t.startswith("```"):
            t = t.split("```", 2)[1]
            t = t[4:] if t.lower().startswith("json") else t
        i, j = t.find("{"), t.rfind("}")
        return json.loads(t[i:j + 1] if i != -1 and j != -1 else t)

    def _call(self, model, content, schema, label):
        kwargs = {}
        # reasoning models (o-series / gpt-5*) reject temperature; everything else
        # (incl. Qwen) uses it for self-consistency diversity across the 3 reads.
        if not model.startswith(("o1", "o3", "o4", "gpt-5")):
            kwargs["temperature"] = self.cfg.openai_temperature

        if self.compat:
            # Local/compat servers vary in support for strict json_schema and use the
            # legacy max_tokens name -> ask for a json_object and inline the schema.
            kwargs["max_tokens"] = self.cfg.max_tokens
            kwargs["response_format"] = {"type": "json_object"}
            content = content + [{"type": "text", "text":
                "仅返回符合以下 JSON Schema 的 JSON 对象（不要解释、不要 markdown 代码块）：\n"
                + json.dumps(schema, ensure_ascii=False)}]
        else:
            kwargs["max_completion_tokens"] = self.cfg.max_tokens
            kwargs["response_format"] = {"type": "json_schema",
                "json_schema": {"name": "pageproc", "schema": schema, "strict": True}}

        def go():
            resp = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                **kwargs,
            )
            return self._loads(resp.choices[0].message.content)
        return self._run(go, label)

    def vision_json(self, model, crop_path: Path, prompt, schema, effort):
        data, media = image.b64(crop_path)
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:{media};base64,{data}", "detail": "high"}},
        ]
        return self._call(model, content, schema, f"vision/{crop_path.name}")

    def text_json(self, model, prompt, schema, effort):
        return self._call(model, [{"type": "text", "text": prompt}], schema, "reconcile")
