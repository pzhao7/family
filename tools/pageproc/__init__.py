"""pageproc — extract vertical right-to-left handwritten Chinese genealogy pages.

Pipeline: preprocess -> segment (columns, RTL) -> extract (tiered LLM vision,
3-sample self-consistency) -> reconcile (whole-page coherence) -> render markdown.

See README.md in the repo root tools/ for usage.
"""

__version__ = "0.1.0"
