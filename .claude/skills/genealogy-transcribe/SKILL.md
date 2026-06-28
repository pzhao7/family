---
name: genealogy-transcribe
description: Transcribe a scanned vertical right-to-left handwritten Chinese genealogy page (page_N.png) into markdown WITHOUT any LLM API — the mechanical slicing runs locally and the reading is done by the agent's own vision. Use when the user wants to extract/transcribe a 家谱/族谱 page, or asks to do it "the free way" / "without the API". Produces docs/page_N.md in the same format as 封面.md / 序.md.
---

# Genealogy page transcription (no API, free)

This skill reproduces how `序.md` was originally made from `page_2.png`:
**local upscale + per-column crops → the agent reads the crops with its own
vision → assemble markdown.** It does NOT call OpenAI/Anthropic; there is no
billing. (The `pageproc run` command is the *paid* automation — this skill is
the manual, zero-cost path.)

## Inputs

A page image path, e.g. `page_2.png` (vertical text, read **right-to-left,
top-to-bottom**, traditional characters, aged handwriting).

## Steps

1. **Slice the page locally (mechanical, offline).** Prefer the project tool;
   it preprocesses (upscale → CLAHE → binarize → deskew → trim) and auto-detects
   columns right-to-left:

   ```sh
   PYTHONPATH=tools tools/family/bin/python -m pageproc slice <image>
   ```

   Crops land in `tools/pageproc/.cache/<stem>/colNN_0.png`, ordered col 1 =
   rightmost. If Pillow/the venv isn't available, fall back to the no-dep
   slicer: `sips` to upscale + the JXA/CoreGraphics crop in
   `tools/pageproc/image.py` (`_sips_upscale` / `_jxa_crop`), or hand-crop
   vertical strips right-to-left.

2. **Read each column crop with the Read tool**, in order col 1 → col N
   (right-to-left = reading order). For a hard column, re-crop it tighter /
   larger and read again rather than guessing.

3. **Transcribe faithfully — never invent.**
   - Output only glyphs actually visible. Do not pad or auto-complete with
     common genealogical phrases.
   - Traditional characters (繁體), reproduce the written form.
   - Confidence markers: confident = plain `字`; ambiguous/context-filled =
     `〔字〕`; illegible = `□`. A short partly-`□` column is correct; a long
     fluent guess is wrong.
   - Use cross-column context (surname, ancestor names, place names, era names
     like 清·乾隆, 干支 years, 落款) only to disambiguate similar cursive forms,
     not to manufacture text.

4. **Write `docs/page_N.md`** in the established format (match `序.md`):
   - `# 第 N 页`
   - `## 性质` — what the page is (序/世系/题词…), reading direction.
   - `## 原文（连读·繁體）` — columns joined into continuous text with `〔〕`/`□`
     markers and editorial punctuation; note "标点为整理时所加".
   - `## 逐列原文` — one line per column, right-to-left, with markers.
   - `## 简体` — simplified rendering.
   - `## 白话大意` — numbered modern-Chinese summary.
   - `## 信息一览` — table of extracted facts (family/surname, ancestors,
     dates, places, compiler, generations, colophon) — only what the text
     supports.
   - A closing honesty note: which characters remain low-confidence and that a
     higher-dpi scan would improve accuracy. Link related pages with `[[封面]]`.

5. **Report** a short summary: surname/family, key facts, and which columns/chars
   were uncertain. Surface anything surprising (e.g. surname differs from what
   the user expected) rather than burying it.

## Rules

- Zero API calls. The transcription is the agent's own reading of the crops.
- Accuracy over completeness: mark uncertainty honestly; do not fabricate.
- Leave scratch crops in `tools/pageproc/.cache/` (gitignored); clean up any
  extra temp crops you create outside it.
