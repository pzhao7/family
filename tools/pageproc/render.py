"""Render the final markdown for a page (matches the style of 封面.md / 序.md)."""

from __future__ import annotations

from .config import Config
from .reconcile import _markup


def render(page_no: int, columns: list[dict], page: dict, cfg: Config) -> str:
    out: list[str] = [f"# 第 {page_no} 页", ""]

    out += ["## 性质", "",
            "竖排手写行书，**从右往左、从上往下**阅读。"
            "本文由 `pageproc` 自动转录（Sonnet 初读 + Opus 复核，逐字 3 次自洽投票），"
            "并经全页一致性校订。", ""]

    out += ["---", "", "## 原文（连读·繁體）", "",
            "> `〔字〕`＝存疑或据上下文补入；`□`＝暂不能确认；标点为整理时所加。", "",
            page.get("continuous_traditional", "").strip() or "（无）", ""]

    if col := page.get("colophon", "").strip():
        out += ["", f"**落款**：{col}", ""]

    out += ["---", "", "## 逐列原文（含逐字置信标记）", ""]
    rec_cols = page.get("columns") or []
    for i, c in enumerate(columns, 1):
        text = rec_cols[i - 1] if i - 1 < len(rec_cols) else _markup(c["chars"], cfg)
        tag = "·Opus复核" if c.get("escalated") else ""
        out.append(f"**第 {i} 列（右起）{tag}**　{text}")
    out.append("")

    if simp := page.get("simplified", "").strip():
        out += ["---", "", "## 简体", "", simp, ""]

    if pts := page.get("vernacular_points"):
        out += ["---", "", "## 白话大意", ""]
        out += [f"{i}. {p}" for i, p in enumerate(pts, 1)]
        out.append("")

    if info := page.get("info"):
        out += ["---", "", "## 信息一览", "", "| 项目 | 内容 |", "|------|------|"]
        out += [f"| {row['key']} | {row['value']} |" for row in info]
        out.append("")

    # honest coverage footer
    low = sum(1 for c in columns for ch in c["chars"] if ch["confidence"] < cfg.bracket_min)
    esc = sum(1 for c in columns if c.get("escalated"))
    out += ["---", "",
            f"> 自动转录质量：{len(columns)} 列，其中 {esc} 列经 Opus 复核；"
            f"仍有 {low} 字低置信（标记为 □）。如需更高精度，提供 300 dpi 以上清晰扫描件再跑。", ""]
    return "\n".join(out)
