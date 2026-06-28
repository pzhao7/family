"""Whole-page coherence pass (stronger model): enforce name/place/era/世系
consistency, finalize uncertainty markers, and produce 简体 + 白话 + info table.
"""

from __future__ import annotations

from .config import Config

RECONCILE_SCHEMA = {
    "type": "object",
    "properties": {
        "continuous_traditional": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "simplified": {"type": "string"},
        "vernacular_points": {"type": "array", "items": {"type": "string"}},
        "info": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        },
        "colophon": {"type": "string"},
    },
    "required": ["continuous_traditional", "columns", "simplified",
                 "vernacular_points", "info", "colophon"],
    "additionalProperties": False,
}


def _markup(chars: list[dict], cfg: Config) -> str:
    out = []
    for c in chars:
        ch, conf = c["char"], c["confidence"]
        if ch == "□" or conf < cfg.bracket_min:
            out.append("□")
        elif conf < cfg.plain_min:
            out.append(f"〔{ch}〕")
        else:
            out.append(ch)
    return "".join(out)


def reconcile(backend, cfg: Config, columns: list[dict]) -> dict:
    """columns: ordered right-to-left list of extract_column() results."""
    lines = [f"第{i}列（右起）: {_markup(col['chars'], cfg)}" for i, col in enumerate(columns, 1)]
    prompt = (cfg.prompts_dir / "reconcile.txt").read_text().replace("{columns}", "\n".join(lines))
    return backend.text_json(cfg.reconcile_model, prompt, RECONCILE_SCHEMA, cfg.escalate_effort)
