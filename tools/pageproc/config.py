"""Central configuration for the pageproc pipeline.

Two interchangeable backends:
- anthropic: Sonnet 4.6 (claude-sonnet-4-6) -> Opus 4.8 (claude-opus-4-8)
- openai:    gpt-4o-mini -> gpt-4o   (override via env / this file)

Select with `provider` here or the PAGEPROC_PROVIDER env var.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # --- backend selection ---
    provider: str = "anthropic"     # "anthropic" | "openai"

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

    # --- resolved model names by provider ---
    @property
    def first_model(self) -> str:
        return self.openai_first if self.provider == "openai" else self.anthropic_first

    @property
    def escalate_model(self) -> str:
        return self.openai_escalate if self.provider == "openai" else self.anthropic_escalate

    @property
    def reconcile_model(self) -> str:
        return self.escalate_model

    # --- paths ---
    @property
    def pages_dir(self) -> Path:
        return self.root / "pages"

    @property
    def docs_dir(self) -> Path:
        return self.root / "docs"

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
    # per-provider model overrides
    if v := os.environ.get("PAGEPROC_FIRST_MODEL"):
        cfg.openai_first = cfg.anthropic_first = v
    if v := os.environ.get("PAGEPROC_ESCALATE_MODEL"):
        cfg.openai_escalate = cfg.anthropic_escalate = v
    # auto-pick provider if only one key is present and provider wasn't forced
    if "PAGEPROC_PROVIDER" not in os.environ:
        if os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
            cfg.provider = "openai"
    return cfg
