"""Image loading, preprocessing, and cropping.

Primary path uses Pillow + numpy. If those aren't installed, a degraded
fallback using macOS `sips` + a JXA/CoreGraphics crop keeps `slice` working
(upscale + crop only — no CLAHE / binarize / deskew / auto-segmentation).
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:  # pragma: no cover - fallback path
    HAS_PIL = False


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #

def b64(path: Path) -> tuple[str, str]:
    """Return (base64_data, media_type) for an image, for the vision API."""
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    suffix = path.suffix.lower().lstrip(".")
    media = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}
    return data, f"image/{media.get(suffix, 'png')}"


def preprocess(src: Path, dst: Path, *, upscale: int, binarize: bool, deskew: bool) -> Path:
    """Clean a scan for reading: upscale -> grayscale -> CLAHE -> (binarize) -> (deskew) -> trim."""
    if not HAS_PIL:
        return _sips_upscale(src, dst, upscale)

    img = Image.open(src).convert("L")          # grayscale
    if upscale > 1:
        img = img.resize((img.width * upscale, img.height * upscale), Image.LANCZOS)

    arr = np.asarray(img, dtype=np.float32)
    arr = _clahe(arr)                            # local contrast — big win on faded ink
    if deskew:
        arr = _deskew(arr)
    if binarize:
        arr = _sauvola(arr)
    arr = _trim_border(arr)

    out = Image.fromarray(arr.astype("uint8"))
    out.save(dst)
    return dst


def crop(src: Path, dst: Path, x0: float, x1: float, y0: float, y1: float) -> Path:
    """Crop a fractional box [x0,x1]x[y0,y1] of `src` into `dst` (origin top-left)."""
    if not HAS_PIL:
        return _jxa_crop(src, dst, x0, x1, y0, y1)
    img = Image.open(src)
    w, h = img.size
    box = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
    img.crop(box).save(dst)
    return dst


def size(src: Path) -> tuple[int, int]:
    if HAS_PIL:
        with Image.open(src) as im:
            return im.size
    out = subprocess.check_output(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(src)], text=True
    )
    w = h = 0
    for line in out.splitlines():
        if "pixelWidth" in line:
            w = int(line.split(":")[1])
        if "pixelHeight" in line:
            h = int(line.split(":")[1])
    return w, h


def column_projection(src: Path) -> "np.ndarray":
    """Per-x ink density (0..1), high where there's dark ink. Pillow path only."""
    if not HAS_PIL:
        raise RuntimeError("auto segmentation needs numpy/Pillow; use --cols/--bounds")
    arr = np.asarray(Image.open(src).convert("L"), dtype=np.float32)
    ink = 1.0 - arr / 255.0                      # invert: ink -> high
    col = ink.mean(axis=0)
    return col


# --------------------------------------------------------------------------- #
# Pillow/numpy internals
# --------------------------------------------------------------------------- #

def _clahe(arr: "np.ndarray", tiles: int = 8, clip: float = 3.0) -> "np.ndarray":
    """Lightweight contrast-limited adaptive histogram equalization."""
    h, w = arr.shape
    out = np.empty_like(arr)
    ys = np.linspace(0, h, tiles + 1, dtype=int)
    xs = np.linspace(0, w, tiles + 1, dtype=int)
    for i in range(tiles):
        for j in range(tiles):
            blk = arr[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            if blk.size == 0:
                continue
            hist, _ = np.histogram(blk, bins=256, range=(0, 255))
            limit = clip * blk.size / 256.0
            excess = np.maximum(hist - limit, 0).sum()
            hist = np.minimum(hist, limit) + excess / 256.0
            cdf = hist.cumsum()
            cdf = (cdf - cdf.min()) / max(cdf.max() - cdf.min(), 1e-6) * 255.0
            out[ys[i]:ys[i + 1], xs[j]:xs[j + 1]] = np.interp(blk.ravel(), np.arange(256), cdf).reshape(blk.shape)
    return out


def _sauvola(arr: "np.ndarray", window: int = 25, k: float = 0.2) -> "np.ndarray":
    """Sauvola adaptive binarization — robust to uneven aging/staining."""
    from numpy.lib.stride_tricks import sliding_window_view  # local import keeps top clean

    pad = window // 2
    p = np.pad(arr, pad, mode="reflect")
    # integral images for fast local mean / std
    ii = p.cumsum(0).cumsum(1)
    ii2 = (p * p).cumsum(0).cumsum(1)

    def box(im, y, x, r):
        return im[y + r, x + r] - im[y - r - 1, x + r] - im[y + r, x - r - 1] + im[y - r - 1, x - r - 1]

    h, w = arr.shape
    ys, xs = np.meshgrid(np.arange(pad, pad + h), np.arange(pad, pad + w), indexing="ij")
    n = window * window
    s1 = box(np.pad(ii, 1)[1:, 1:], ys, xs, pad)
    s2 = box(np.pad(ii2, 1)[1:, 1:], ys, xs, pad)
    mean = s1 / n
    std = np.sqrt(np.maximum(s2 / n - mean * mean, 0))
    thresh = mean * (1 + k * (std / 128.0 - 1))
    return np.where(arr > thresh, 255, 0).astype(np.float32)


def _deskew(arr: "np.ndarray") -> "np.ndarray":
    """Correct small rotation by maximizing row-ink variance over candidate angles."""
    ink = 255.0 - arr
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-4, 4.01, 0.5):
        rot = _rotate(ink, angle)
        score = (rot.sum(axis=1) ** 2).sum()
        if score > best_score:
            best_score, best_angle = score, angle
    if abs(best_angle) < 0.25:
        return arr
    return 255.0 - _rotate(ink, best_angle)


def _rotate(arr: "np.ndarray", angle: float) -> "np.ndarray":
    img = Image.fromarray(arr.astype("uint8"))
    return np.asarray(img.rotate(angle, resample=Image.BILINEAR, fillcolor=0), dtype=np.float32)


def _trim_border(arr: "np.ndarray", margin: int = 4) -> "np.ndarray":
    ink = arr < 128
    rows, cols = np.any(ink, 1), np.any(ink, 0)
    if not rows.any() or not cols.any():
        return arr
    y0, y1 = np.argmax(rows), len(rows) - np.argmax(rows[::-1])
    x0, x1 = np.argmax(cols), len(cols) - np.argmax(cols[::-1])
    y0, x0 = max(0, y0 - margin), max(0, x0 - margin)
    y1, x1 = min(arr.shape[0], y1 + margin), min(arr.shape[1], x1 + margin)
    return arr[y0:y1, x0:x1]


# --------------------------------------------------------------------------- #
# No-Pillow fallback (macOS sips + JXA/CoreGraphics) — slice path only
# --------------------------------------------------------------------------- #

def _sips_upscale(src: Path, dst: Path, factor: int) -> Path:
    w, h = size(src)
    subprocess.check_call(
        ["sips", "-z", str(h * factor), str(w * factor), str(src), "--out", str(dst)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return dst


_JXA = r"""
ObjC.import('Foundation'); ObjC.import('AppKit'); ObjC.import('CoreGraphics');
function load(p){var d=$.NSData.dataWithContentsOfFile(p);var s=$.CGImageSourceCreateWithData(d,$());return $.CGImageSourceCreateImageAtIndex(s,0,$());}
function save(cg,p){var r=$.NSBitmapImageRep.alloc.initWithCGImage(cg);var png=r.representationUsingTypeProperties($.NSBitmapImageFileTypePNG,$());png.writeToFileAtomically(p,true);}
var a=$.NSProcessInfo.processInfo.arguments,v=[];for(var i=0;i<a.count;i++)v.push(ObjC.unwrap(a.objectAtIndex(i)));v=v.slice(4);
var img=load(v[0]),W=$.CGImageGetWidth(img),H=$.CGImageGetHeight(img);
var x0=parseFloat(v[2])*W,x1=parseFloat(v[3])*W,y0=parseFloat(v[4])*H,y1=parseFloat(v[5])*H;
var sub=$.CGImageCreateWithImageInRect(img,$.CGRectMake(x0,y0,x1-x0,y1-y0));save(sub,v[1]);
"""


def _jxa_crop(src: Path, dst: Path, x0: float, x1: float, y0: float, y1: float) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_JXA)
        script = f.name
    subprocess.check_call(
        ["osascript", "-l", "JavaScript", script, str(src), str(dst),
         str(x0), str(x1), str(y0), str(y1)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return dst
