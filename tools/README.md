# pageproc — genealogy page extraction

Extracts vertical, right-to-left **handwritten Chinese** genealogy pages into
markdown (繁體原文 + 简体 + 白话 + 信息表), the same format as `封面.md` / `序.md`.

Classical OCR fails on aged 行书 cursive, so the quality strategy is **heavy
preprocessing → per-column crops → a reasoning vision model that disambiguates
by context**, with self-consistency voting and a whole-page coherence pass.

## Pipeline

```
page_N.png
  ├─ preprocess  upscale 5× (Lanczos) → gray → CLAHE → Sauvola binarize → deskew → trim
  ├─ segment     ink-projection → right-to-left columns  (override: --cols / --bounds)
  │              tall columns auto-split top/bottom for closer reading
  ├─ extract     PASS 1 Sonnet ×3 → char-level majority vote
  │              PASS 2 Opus ×3 on any column with a sub-threshold character
  ├─ reconcile   whole-page Opus pass: name/place/干支/世系 coherence, finalize markers
  └─ render      docs/page_N.md  (繁體連讀 · 逐列 · 简体 · 白话 · 信息表 · 落款)
```

Confidence drives markup: `≥0.90` plain · `0.60–0.90` `〔字〕` · `<0.60` `□`.
Nothing is silently guessed.

## Setup

```sh
pip install -r tools/requirements.txt
```

Pick a backend with `PAGEPROC_PROVIDER` (or let it auto-detect from whichever
API key is set):

```sh
# OpenAI
export OPENAI_API_KEY=sk-...
export PAGEPROC_PROVIDER=openai          # optional; auto-selected if only this key is set

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export PAGEPROC_PROVIDER=anthropic
```

| provider | first pass (cheap) | escalate / reconcile |
|----------|--------------------|----------------------|
| `anthropic` | `claude-sonnet-4-6` | `claude-opus-4-8` |
| `openai`    | `gpt-4o-mini`       | `gpt-4o`             |

Override models with `PAGEPROC_FIRST_MODEL` / `PAGEPROC_ESCALATE_MODEL` (e.g.
`gpt-4.1`, `o4-mini`). Both backends go through the same provider-agnostic
pipeline — switching is a config change, not a code change.

## Usage

Run from the repo root (`family/`):

```sh
# offline — just preprocess + slice, eyeball the crops in tools/pageproc/.cache/
python -m pageproc slice pages/page_2.png

# full pipeline -> docs/page_2.md
python -m pageproc run pages/page_2.png

# overrides when auto-segmentation is off
python -m pageproc run pages/page_2.png --cols 10
python -m pageproc run pages/page_2.png --bounds 0,0.15,0.33,0.51,0.69,0.87,1.0
```

Env knobs: `PAGEPROC_SAMPLES` (votes/column, default 3), `PAGEPROC_UPSCALE`
(default 5), `PAGEPROC_ROOT` (project root).

## Layout

```
tools/
├─ requirements.txt
└─ pageproc/
   ├─ cli.py          slice · extract · run
   ├─ config.py       provider, models, scales, thresholds, paths
   ├─ providers.py    Anthropic + OpenAI backends (same interface)
   ├─ image.py        preprocess + crop (Pillow/numpy; sips+JXA fallback)
   ├─ segment.py      auto ink-projection columns + --cols/--bounds
   ├─ extract.py      tiered vision reads + char-level voting (provider-agnostic)
   ├─ reconcile.py    whole-page coherence -> 简体/白话/info
   ├─ render.py       markdown assembly
   ├─ prompts/        column.txt · reconcile.txt
   └─ .cache/         per-page crops + raw JSON (gitignored)
```

## Notes

- Without Pillow/numpy, `slice` still works via macOS `sips` + JXA (upscale +
  crop only — no CLAHE/binarize/deskew/auto-segmentation); `--cols`/`--bounds`
  required there. Install the requirements for full quality.
- Image `cache_control` is set on column reads so the 3 same-image samples can
  share the prefix (only helps above the model's min-cacheable size).
- Quality scales with scan resolution. 300 dpi+, even lighting, flattened
  creases materially improve accuracy.
