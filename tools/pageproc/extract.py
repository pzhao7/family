"""LLM vision extraction with tiered models + self-consistency voting.

Per column: read N times with the cheap first-tier model, majority-vote per
character. If any voted character falls below the escalation threshold, re-read
N times with the stronger model and re-vote. Backend (Anthropic or OpenAI) is
chosen in config; this module is provider-agnostic.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .config import Config

# Structured-output schema. Kept constraint-free (no min/max/length) so it's
# valid for both Anthropic json_schema and OpenAI strict json_schema.
COLUMN_SCHEMA = {
    "type": "object",
    "properties": {
        "chars": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "char": {"type": "string"},
                    "confidence": {"type": "number"},
                    "note": {"type": "string"},
                },
                "required": ["char", "confidence", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["chars"],
    "additionalProperties": False,
}


def _vote(samples: list[list[dict]]) -> list[dict]:
    """Char-level majority vote across N reads of the same column.

    Aligns by position up to the modal length. Confidence = (fraction agreeing)
    times the mean model-confidence of the agreeing reads, so both disagreement
    and low model certainty pull a character down.
    """
    samples = [s for s in samples if s]
    if not samples:
        return []
    modal_len = Counter(len(s) for s in samples).most_common(1)[0][0]
    usable = [s for s in samples if len(s) == modal_len] or samples
    voted: list[dict] = []
    for i in range(modal_len):
        picks = [s[i] for s in usable if i < len(s)]
        chars = Counter(p["char"] for p in picks)
        char, agree = chars.most_common(1)[0]
        conf_vals = [float(p.get("confidence", 0)) for p in picks if p["char"] == char]
        agree_frac = agree / len(picks)
        conf = agree_frac * (sum(conf_vals) / len(conf_vals))
        notes = [p.get("note", "") for p in picks if p["char"] == char and p.get("note")]
        voted.append({"char": char, "confidence": round(conf, 3), "note": notes[0] if notes else ""})
    return voted


def extract_column(backend, cfg: Config, crop_paths: list[Path], context: str) -> dict:
    """Extract one logical column (possibly several stacked sub-crops), tiered.

    Returns {text, chars, model, escalated}.
    """
    prompt = (cfg.prompts_dir / "column.txt").read_text().replace("{context}", context or "")

    def read_all(model, effort):
        chars: list[dict] = []
        for cp in crop_paths:                      # stitch sub-crops top->bottom
            samples = [backend.vision_json(model, cp, prompt, COLUMN_SCHEMA, effort).get("chars", [])
                       for _ in range(cfg.samples)]
            chars.extend(_vote(samples))
        return chars

    chars = read_all(cfg.first_model, cfg.first_effort)
    model_used, escalated = cfg.first_model, False

    if chars and min(c["confidence"] for c in chars) < cfg.escalate_threshold:
        strong = read_all(cfg.escalate_model, cfg.escalate_effort)
        if strong and _avg_conf(strong) >= _avg_conf(chars):
            chars, model_used, escalated = strong, cfg.escalate_model, True

    return {"text": "".join(c["char"] for c in chars), "chars": chars,
            "model": model_used, "escalated": escalated}


def _avg_conf(chars: list[dict]) -> float:
    return sum(c["confidence"] for c in chars) / len(chars) if chars else 0.0
