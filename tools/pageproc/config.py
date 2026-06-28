"""Central configuration for the pageproc pipeline.

Interchangeable backends:
- anthropic: Sonnet 4.6 (claude-sonnet-4-6) -> Opus 4.8 (claude-opus-4-8)
- openai:    gpt-4o-mini -> gpt-4o   (or any OpenAI-compatible endpoint via OPENAI_BASE_URL)
- ollama:    local Qwen2.5-VL on your Mac (OpenAI-compatible at localhost:11434)

Select with `provider` here or the PAGEPROC_PROVIDER env var.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # --- backend selection ---
    provider: str = "anthropic"     # "anthropic" | "openai" | "ollama"

    # OpenAI-compatible endpoint override (vLLM / OpenRouter / DashScope / Ollama).
    # Empty = real OpenAI. Set via OPENAI_BASE_URL or PAGEPROC_BASE_URL.
    openai_base_url: str = ""

    # --- anthropic models (tiered: first pass -> escalate low-confidence) ---
    anthropic_first: str = "claude-sonnet-4-6"
    anthropic_escalate: str = "claude-opus-4-8"
    first_effort: str = "low"
    escalate_effort: str = "high"

    # --- openai models (tiered) ---
    openai_first: str = "gpt-4o-mini"
    openai_escalate: str = "gpt-4o"
    openai_temperature: float = 0.4   # >0 so the 3 self-consistency reads differ
    max_tokens: int = 1500            # a column is short; keeps per-call tokens low

    # --- ollama (local Qwen2.5-VL on Apple Silicon) ---
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5vl:3b"   # easy e2e; bump to :7b for better 行书

    # --- self-consistency ---
    samples: int = 3                # reads per column; char-level majority vote
    escalate_threshold: float = 0.75   # column escalates if any char < this

    # --- confidence -> markup thresholds ---
    plain_min: float = 0.90         # >= : print char as-is
    bracket_min: float = 0.60       # [bracket_min..plain_min) : 〔字〕 ; < : □

    # --- preprocessing ---
    upscale: int = 5
    binarize: bool = True
    deskew: bool = True

    # --- segmentation ---
    min_column_frac: float = 0.015
    split_tall_ratio: float = 15.0   # single-line columns read whole (1 call, no seam dupes)

    root: Path = field(default_factory=lambda: Path.cwd())
    out: str = "docs"   # output dir for rendered markdown (override for test runs)

    # --- resolved model names by provider ---
    @property
    def first_model(self) -> str:
        return {"openai": self.openai_first,
                "ollama": self.ollama_model}.get(self.provider, self.anthropic_first)

    @property
    def escalate_model(self) -> str:
        # ollama has no second tier locally — reuse the same model
        return {"openai": self.openai_escalate,
                "ollama": self.ollama_model}.get(self.provider, self.anthropic_escalate)

    @property
    def reconcile_model(self) -> str:
        return self.escalate_model

    # --- OpenAI-compatible endpoint resolution ---
    @property
    def resolved_base_url(self) -> str:
        if self.provider == "ollama":
            return self.ollama_base_url
        return self.openai_base_url   # "" => real OpenAI

    @property
    def is_openai_compat(self) -> bool:
        """True when talking to a non-OpenAI server (param/structured-output quirks)."""
        url = self.resolved_base_url
        return bool(url) and "api.openai.com" not in url

    # --- paths ---
    @property
    def scans_dir(self) -> Path:
        return self.root / "scans"

    @property
    def docs_dir(self) -> Path:
        return self.root / self.out

    @property
    def cache_dir(self) -> Path:
        return self.root / "tools" / "pageproc" / ".cache"

    @property
    def prompts_dir(self) -> Path:
        return Path(__file__).parent / "prompts"

    def cache_for(self, page_stem: str) -> Path:
        d = self.cache_dir / page_stem
        d.mkdir(parents=True, exist_ok=True)
        return d


def load() -> Config:
    cfg = Config()
    if v := os.environ.get("PAGEPROC_PROVIDER"):
        cfg.provider = v
    if v := os.environ.get("PAGEPROC_SAMPLES"):
        cfg.samples = int(v)
    if v := os.environ.get("PAGEPROC_UPSCALE"):
        cfg.upscale = int(v)
    if v := os.environ.get("PAGEPROC_ROOT"):
        cfg.root = Path(v)
    if v := os.environ.get("PAGEPROC_OUT"):
        cfg.out = v
    # endpoint override (vLLM / OpenRouter / DashScope)
    if v := os.environ.get("PAGEPROC_BASE_URL") or os.environ.get("OPENAI_BASE_URL"):
        cfg.openai_base_url = v
    # per-provider model overrides
    if v := os.environ.get("PAGEPROC_FIRST_MODEL"):
        cfg.openai_first = cfg.anthropic_first = v
    if v := os.environ.get("PAGEPROC_ESCALATE_MODEL"):
        cfg.openai_escalate = cfg.anthropic_escalate = v
    if v := os.environ.get("PAGEPROC_MODEL"):     # set both tiers + ollama at once
        cfg.openai_first = cfg.openai_escalate = cfg.ollama_model = v
        cfg.anthropic_first = cfg.anthropic_escalate = v
    # auto-pick provider if only one key is present and provider wasn't forced
    if "PAGEPROC_PROVIDER" not in os.environ:
        if os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
            cfg.provider = "openai"
    return cfg
