#!/usr/bin/env python3
"""Generate the Home Assistant brand assets for this integration.

Kept in the repo so the mark can be tweaked and regenerated rather than being
an opaque binary nobody can change. Run it from the repository root:

    venv/bin/python scripts/generate_brand_icon.py
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

OUT = pathlib.Path("custom_components/cover_control/brand")

# Drawn at 4x and downsampled, which is cheaper than hand-rolling antialiasing.
SUPERSAMPLE = 4
BASE = 256

BACKGROUND = (22, 50, 79, 255)  # deep blue, reads well on light and dark
SUN = (255, 194, 77, 255)  # amber
SLAT = (245, 247, 250, 255)  # near white


def draw(size: int) -> Image.Image:
    """Draw the mark: a sun seen through the slats of a lowered blind."""
    s = size * SUPERSAMPLE
    unit = s / BASE
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)

    canvas.rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=int(56 * unit), fill=BACKGROUND
    )

    centre_x, centre_y, sun_radius = 128 * unit, 112 * unit, 56 * unit
    canvas.ellipse(
        [
            centre_x - sun_radius,
            centre_y - sun_radius,
            centre_x + sun_radius,
            centre_y + sun_radius,
        ],
        fill=SUN,
    )

    # Four slats across the face. The gaps let the sun through, which is the
    # whole idea: shading, not blacking out.
    for top in (52, 96, 140, 184):
        canvas.rounded_rectangle(
            [36 * unit, top * unit, 220 * unit, (top + 20) * unit],
            radius=int(10 * unit),
            fill=SLAT,
        )

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        image = draw(size)
        image.save(OUT / name, "PNG", optimize=True)
        print(f"  {OUT / name}  {size}x{size}")
    # The mark is square, so the logo is the same artwork.
    for source, target in (("icon.png", "logo.png"), ("icon@2x.png", "logo@2x.png")):
        (OUT / target).write_bytes((OUT / source).read_bytes())
        print(f"  {OUT / target}  (copy of {source})")


if __name__ == "__main__":
    main()
