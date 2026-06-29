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

A page image path under `scans/`, e.g. `scans/page_2.png` (vertical text, read
**right-to-left, top-to-bottom**, traditional characters, aged handwriting).
Raw scans live in `scans/`; transcriptions are written to `docs/`.

**Two source registers, two confidence baselines.** Scans may be either
**手写抄本** (aged 行书 — the hard case the preprocessing is tuned for) or a
**雕版刻本/印本** (woodblock *print* — clean regular script, slices come out
razor-sharp and confidence is high). Note which in the frontmatter (`edition:`)
and the 转录说明; for a 刻本, the heavy CLAHE/Sauvola/deskew is overkill but
harmless — keep it, just expect (and state) high confidence.

**Multiple editions of the same lineage** live in **per-edition subfolders**
under `docs/` (e.g. `docs/1982-抄本/`, `docs/1765-洞庭刻本/`), each with its own
`目录.md`, plus a **master `docs/目录.md`** that links both and records how they
互证 (shared 始祖, the generation where they connect). Scan refs from a
subfolder use `../../scans/`.

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

4. **Name and write the output file.** Filename is
   **`docs/NN-<中文名>.md`** where `NN` is the zero-padded page number (from
   `page_N.png`, so `page_2.png` -> `02-…`) and `<中文名>` is a concise Chinese
   name for the page's TYPE, which you determine while reading. Common types:
   `封面`(题词/扉页), `序`(序言), `凡例`, `目录`, `字辈排列`(派语), `世系`(世系图),
   `家训`, `祠堂`, `墓图`, `跋`. e.g. `docs/02-序.md`, `docs/03-字辈排列.md`.

   - **卷-organized editions (printed 宗譜).** When the book's meaningful unit is
     the **卷 (juan)** rather than a leaf page number — pages are sparse/large
     (670, 1430…) and several map to one 卷 — name by 卷 instead:
     `卷<卷次>-<中文名>.md` (e.g. `卷首-序-沈德潛.md`, `卷五-世系-六至十世.md`),
     written into that edition's subfolder. Put the leaf page in `page:` and the
     scan in `source:`. Add an `edition:` frontmatter field and, for 世系, a
     `branch:` field (the 支系, e.g. `保二公下孟昇公支`).

   - **Duplicate / ambiguous type** (e.g. several 世系 pages would all be
     `世系`): do NOT silently auto-number. **Stop and ask the user** what
     distinguishing name to use (e.g. `世系一` vs `世系-梅公支`), then write it.
   - **Frontmatter** (top of every file, for traceability + clean wikilinks):
     ```
     ---
     title: 序
     page: 2
     source: scans/page_2.png
     type: 序言
     aliases: [序, 序言]
     ---
     ```
     The `aliases` let `[[序]]` resolve even though the file is `02-序.md` —
     always cross-link other pages by their plain Chinese name (`[[封面]]`,
     `[[字辈排列]]`), never by filename.
   - **Update `docs/目录.md`** — add/refresh the row for this page
     (页码 ↔ 文件 ↔ 类型 ↔ 扫描件); create the index if missing.

   Body format (match the existing pages):
   - `# 第 N 页 · <中文名>`
   - `## 原件扫描` (placed at the TOP, above 性质) — embed the raw scan with a
     width-controlled relative HTML tag (docs/ -> ../scans/), then a `---`:
     `<img src="../scans/page_N.png" width="600" alt="第 N 页 原件扫描">`
     (use the file's actual pixel width if much smaller than 600).
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

   ### Page-type variant — 世系录 (lineage register)

   A page headed `世系` whose body is a grid of ancestor entries (each entry
   `N世祖 〈名〉公 〈字/號/小注〉`, the annotation often in 双行小字) is a
   **lineage register**, not prose. Handle it differently:
   - **Name it by generation range**: `NN-世系-<起>至<止>世.md`
     (e.g. `04-世系-一至九世.md`, `05-世系-九至廿世.md`). Frontmatter
     `type: 世系`, `aliases: [世系, 世系-<起>至<止>世]`, and add a
     `generations: <起>-<止>` field.
   - **Replace `原文（连读）` with a table** — one row per ancestor, in document
     order (世序 ascending; mind the RTL column layout — entries usually read
     right-column-first, top-to-bottom):
     ```
     | 世 | 名讳 | 字号·小注 |
     |----|------|-----------|
     | 一世祖 | 〇〇公 | 字…，〔小注〕 |
     ```
     Put 双行小字 annotations in the 字号·小注 column; mark uncertainty with
     `〔〕`/`□` as usual. Keep `逐列原文` (faithful per-column dump),
     `简体`, `白话大意`, and `信息一览` (range, ancestor count, notable names).
   - Multiple 世系 pages chain: ensure 世序 continuity across files (a page may
     re-state the last generation of the previous page — note overlaps).
   - **字辈 cross-check (use it!).** Validate each entry against `[[字辈排列]]`:
     在本谱中**字辈自第 16 世起用**，对应
     16 肇 · 17 起 · 18 新 · 19 模 · 20 大 · 21 長 · 22 思 · 23 世 · 24 德 ·
     25 賢 · 26 習 · 27 勤 · 28 能 · 29 務 · 30 本 · 31 孝 · 32 因 · 33 自 ·
     34 純 · 35 全（派语「肇起新模大　長思世德賢　習勤能務本　孝因自純全」）。
     For any generation ≥16, the **first character of the given name should equal
     the 字辈 character for that generation** — use this to (a) pin an unreadable
     世序 number, and (b) disambiguate the name's first glyph. If the name's first
     char does NOT match the expected 字辈, do not force it — transcribe what you
     see and flag the mismatch in the note. (Generations 1–15 predate the 字辈 and
     use 行第 / 单名 / 官称, e.g. 一世「承事公」、二世「三十四公」, so no anchor there.)

   ### Page-type variant — 世系圖 (lineage chart / 吊線圖)

   A printed 宗譜 volume page headed `…宗譜卷N` + a 支系 line (`X公下Y公支`) whose
   body is a **2-D hanging-line chart**, NOT a linear list. Do not read it as the
   `世系录` variant — column-by-column there destroys the tree. Its geometry:
   - **Each vertical column = one father→son descent line**, read **top→bottom =
     ancestor→descendant** (top of the column is the elder generation).
   - **A separate 「世」band-ruler column** (`六世 / 七世 / 八世 …` stacked
     top-to-bottom) fixes which vertical position belongs to which generation —
     **find it first** and use it to assign 世 to every name.
   - **双行小字 annotations carry the structure**: `X長子`/`X次子` → the person's
     **父** (parent); `子N` → number of sons; plus `葬…`/`字…`/`早世` notes.
   - The header often cross-refs earlier generations (`〔始祖以來前見一卷〕` =
     1–N世 are in a previous 卷). Note the compiler colophon (`十五世孫…重輯`).

   Handle it as:
   - **Name** `卷N-世系-<起>至<止>世.md`; frontmatter `type: 世系图`,
     `branch: <支系>`, `generations: <起>-<止>`, `edition:`.
   - **Replace the linear table with a 世/名/父/小注 table** — one row per person,
     世 from the ruler column, 父 from the `X長子/次子` note, the rest in 小注:
     ```
     | 世 | 名 | 父 | 小注 |
     |----|----|----|------|
     | 六世 | 孟昇 | 保二 | 保二公之子；葬折澗橋山；子一 |
     | 七世 | 仁   | 孟昇 | 孟昇長子；子一 |
     ```
   - **Reading strategy**: trace the main trunk (eldest-son chain) top→bottom
     first — it's the clearest; then pick up sibling branches (`次子`/`三子`) and
     lower generations, which are usually fainter. Keep `逐列原文` (faithful
     per-column dump, labeled by descent line / ruler), `简体`, `白话`, `信息一览`.
   - **字辈 cross-check** still applies for generations ≥16 (see above); pre-16
     charts use 行第/單名 so no anchor — but cross-link the same ancestor in the
     other edition when present (e.g. 六世孟昇公 also in `[[世系-一至十八世]]`).
   - **Faint lower branches**: re-crop that sub-region tighter/larger and re-read
     rather than guessing; mark `〔〕`/`□` and say so. A partly-`□` lower tree is
     correct; a fluent invented one is wrong.

5. **Report** a short summary: surname/family, key facts, and which columns/chars
   were uncertain. Surface anything surprising (e.g. surname differs from what
   the user expected) rather than burying it.

## Rules

- Zero API calls. The transcription is the agent's own reading of the crops.
- Accuracy over completeness: mark uncertainty honestly; do not fabricate.
- Leave scratch crops in `tools/pageproc/.cache/` (gitignored); clean up any
  extra temp crops you create outside it.
