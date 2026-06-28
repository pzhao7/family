"""pageproc CLI.

    python -m pageproc slice   pages/page_2.png [--cols N | --bounds a,b,..]
    python -m pageproc extract pages/page_2.png [--cols N | --bounds ...]
    python -m pageproc run     pages/page_2.png        # full pipeline -> docs/page_2.md

`slice` is offline (no API key). `extract`/`run` need ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import config, extract, image, providers, reconcile, render, segment


def _page_no(src: Path) -> int:
    m = re.search(r"(\d+)", src.stem)
    return int(m.group(1)) if m else 0


def _columns_for(src: Path, args, cfg: config.Config) -> list[segment.Column]:
    if args.cols:
        return segment.even(args.cols)
    if args.bounds:
        return segment.from_bounds([float(x) for x in args.bounds.split(",")])
    return segment.detect(src, min_column_frac=cfg.min_column_frac)


def _prep_and_slice(src: Path, args, cfg: config.Config):
    """Returns (clean_path, [(Column, [crop_paths...]), ...]) right-to-left."""
    cache = cfg.cache_for(src.stem)
    clean = cache / "clean.png"
    image.preprocess(src, clean, upscale=cfg.upscale, binarize=cfg.binarize, deskew=cfg.deskew)

    cols = _columns_for(clean, args, cfg)
    result = []
    for col in cols:
        subs = segment.split_tall(col, clean, ratio=cfg.split_tall_ratio)
        crops = []
        for j, sub in enumerate(subs):
            cp = cache / f"col{col.index:02d}_{j}.png"
            image.crop(clean, cp, sub.x0, sub.x1, sub.y0, sub.y1)
            crops.append(cp)
        result.append((col, crops))
    return clean, result


def cmd_slice(args):
    cfg = config.load()
    src = Path(args.image)
    clean, sliced = _prep_and_slice(src, args, cfg)
    print(f"preprocessed -> {clean}")
    for col, crops in sliced:
        print(f"  col {col.index:>2} (x {col.x0:.3f}-{col.x1:.3f}): {', '.join(str(c) for c in crops)}")
    print(f"{len(sliced)} columns. (offline — no API used)")


def cmd_extract(args):
    cfg = config.load()
    src = Path(args.image)
    clean, sliced = _prep_and_slice(src, args, cfg)
    backend = providers.make(cfg)
    print(f"provider: {cfg.provider} ({cfg.first_model} -> {cfg.escalate_model})", file=sys.stderr)

    columns = []
    for k, (col, crops) in enumerate(sliced):
        prev = columns[-1]["text"] if columns else ""
        context = (f"Context: this is column {col.index} (reading right-to-left). "
                   f"The previous column read: 「{prev}」. Continue coherently." if prev
                   else f"Context: this is the first (rightmost) column.")
        res = extract.extract_column(backend, cfg, crops, context)
        res["index"] = col.index
        columns.append(res)
        flag = f" [escalated:{res['model']}]" if res["escalated"] else ""
        print(f"col {col.index:>2}{flag}: {res['text']}", file=sys.stderr)

    out = cfg.cache_for(src.stem) / "cols.json"
    out.write_text(json.dumps(columns, ensure_ascii=False, indent=2))
    print(f"\nwrote {out}")
    return columns


def cmd_run(args):
    cfg = config.load()
    src = Path(args.image)
    columns = cmd_extract(args)
    backend = providers.make(cfg)

    print(f"reconciling whole page ({cfg.reconcile_model})...", file=sys.stderr)
    page = reconcile.reconcile(backend, cfg, columns)
    (cfg.cache_for(src.stem) / "page.json").write_text(json.dumps(page, ensure_ascii=False, indent=2))

    md = render.render(_page_no(src), columns, page, cfg)
    cfg.docs_dir.mkdir(parents=True, exist_ok=True)
    dst = cfg.docs_dir / f"page_{_page_no(src)}.md"
    dst.write_text(md)
    print(f"wrote {dst}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="pageproc", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("slice", cmd_slice), ("extract", cmd_extract), ("run", cmd_run)):
        sp = sub.add_parser(name)
        sp.add_argument("image")
        sp.add_argument("--cols", type=int, help="even split into N columns")
        sp.add_argument("--bounds", help="explicit fractional cut lines, e.g. 0,0.2,0.45,1.0")
        sp.set_defaults(func=fn)
    args = p.parse_args(argv)
    try:
        args.func(args)
    except providers.QuotaExceeded as e:
        print(f"\n[pageproc] {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
