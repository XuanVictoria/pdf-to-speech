"""Build the web app's icon: assets/app_icon.png, used as `page_icon`.

Source is the same artwork as the macOS app (`../PDFtoSpeech/assets/source_icon.jpg`).
That file has a white margin and is slightly non-square, which reads badly as a
browser favicon, so this script trims the margin, crops to a square, and gives the
result transparent rounded corners — so it sits cleanly on a dark browser tab
instead of appearing as a white block.

Build-time only; run it when the artwork changes:

    python make_favicon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

# 256 keeps the icon crisp on a 3x retina tab (32px * 3 = 96px) with room to
# spare, at ~1/3 the bytes of 512 — it is fetched on every page load.
SIZE = 256
CORNER_RADIUS = round(SIZE * 0.18)  # Matches the Apple rounded-rect curvature.
WHITE_TOLERANCE = 18  # How far from pure white still counts as background.

HERE = Path(__file__).parent
OUT = HERE / "assets" / "app_icon.png"
SOURCE_CANDIDATES = [
    HERE / "assets" / "source_icon.jpg",
    HERE.parent / "PDFtoSpeech" / "assets" / "source_icon.jpg",
    HERE.parent / "PDF_SpeechApp.jpg",
]


def find_source() -> Path:
    for path in SOURCE_CANDIDATES:
        if path.exists():
            return path
    raise SystemExit(
        "No source artwork found. Looked in:\n  "
        + "\n  ".join(str(p) for p in SOURCE_CANDIDATES)
    )


def trim_white_margin(im: Image.Image) -> Image.Image:
    """Crop away the near-white border so the artwork fills the icon."""
    rgb = im.convert("RGB")
    background = Image.new("RGB", rgb.size, (255, 255, 255))
    mask = ImageChops.difference(rgb, background).convert("L")
    mask = mask.point(lambda p: 255 if p > WHITE_TOLERANCE else 0)
    bbox = mask.getbbox()
    return im.crop(bbox) if bbox else im


def square_cover(im: Image.Image, size: int) -> Image.Image:
    """Scale to *cover* a square and center-crop — no letterboxing."""
    scale = size / min(im.width, im.height)
    scaled = im.resize(
        (max(size, round(im.width * scale)), max(size, round(im.height * scale))),
        Image.LANCZOS,
    )
    left = (scaled.width - size) // 2
    top = (scaled.height - size) // 2
    return scaled.crop((left, top, left + size, top + size))


def main() -> None:
    src = find_source()
    im = Image.open(src).convert("RGBA")
    im = square_cover(trim_white_margin(im), SIZE)

    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, SIZE - 1, SIZE - 1], radius=CORNER_RADIUS, fill=255
    )
    im.putalpha(mask)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(HERE)} ({SIZE}x{SIZE}) from {src.name}")


if __name__ == "__main__":
    main()
