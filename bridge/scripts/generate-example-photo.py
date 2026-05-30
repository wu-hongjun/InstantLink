#!/usr/bin/env python3
"""Generate the synthetic example photo used for the Adjustments live preview.

Produces ``bridge/src/instantlink_bridge/imaging/_example_photo.jpg``
(480×480 px, JPEG quality 85) from four colour bands + geometric elements
so every adjustment axis (saturation, exposure, sharpness, hue, vignette)
has visible texture to exercise.

Run from the repository root::

    python bridge/scripts/generate-example-photo.py

Re-run any time the desired band colours or geometry change; the result
is committed as a package data file loaded via ``importlib.resources``.

Design notes
------------
Bands (each 120 px tall):
  1. Sky      — cool blue gradient #7AB3D6 → #B0D5E8 with 8 % noise
  2. Foliage  — mid green #6B8E5A with 20 % noise + ragged tree silhouettes
  3. Skin     — warm peach #E8B68F with 15 % noise
  4. Shadow   — dark #2E2A26 with 10 % noise

Geometric overlays (drawn after banding so sharpness axis has hard edges):
  - Horizon line: 1 px stroke at y=240 in a slightly darker grey
  - Two tree silhouettes: irregular triangles against the sky (dark fill)
  - Ground line: 1 px stroke at y=360 (foliage/skin boundary)

Copyright year 2026.
"""

from __future__ import annotations

import os
import random
import sys

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_OUTPUT = os.path.join(
    _SCRIPT_DIR,
    "..",
    "src",
    "instantlink_bridge",
    "imaging",
    "_example_photo.jpg",
)

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

WIDTH = 480
HEIGHT = 480
QUALITY = 85

# Row 0: sky     y=0..119
# Row 1: foliage y=120..239
# Row 2: skin    y=240..359
# Row 3: shadow  y=360..479
BAND_H = HEIGHT // 4

# Sky: cool blue gradient left=top-sky, right=hazy
SKY_LEFT = (0x7A, 0xB3, 0xD6)
SKY_RIGHT = (0xB0, 0xD5, 0xE8)

FOLIAGE_BASE = (0x6B, 0x8E, 0x5A)
SKIN_BASE = (0xE8, 0xB6, 0x8F)
SHADOW_BASE = (0x2E, 0x2A, 0x26)

TREE_DARK = (0x18, 0x22, 0x18)
HORIZON_COLOUR = (0x55, 0x70, 0x85)
GROUND_COLOUR = (0x45, 0x52, 0x3A)


def _lerp_colour(
    c1: tuple[int, int, int], c2: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    return (
        round(c1[0] + (c2[0] - c1[0]) * t),
        round(c1[1] + (c2[1] - c1[1]) * t),
        round(c1[2] + (c2[2] - c1[2]) * t),
    )


def _clamp(v: int) -> int:
    return max(0, min(255, v))


def _noise(rng: random.Random, strength: float) -> int:
    """Return an integer noise offset in [-strength*255, +strength*255]."""
    return round((rng.random() * 2 - 1) * strength * 255)


def main() -> None:
    rng = random.Random(42)  # deterministic seed

    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    px = img.load()
    if px is None:
        sys.exit("Could not load pixel access object")

    # ------------------------------------------------------------------
    # Band 1: Sky (y=0..BAND_H-1) — horizontal gradient + light noise
    # ------------------------------------------------------------------
    for y in range(BAND_H):
        for x in range(WIDTH):
            t = x / (WIDTH - 1)
            base = _lerp_colour(SKY_LEFT, SKY_RIGHT, t)
            n = _noise(rng, 0.08)
            px[x, y] = (
                _clamp(base[0] + n),
                _clamp(base[1] + n),
                _clamp(base[2] + n),
            )

    # ------------------------------------------------------------------
    # Band 2: Foliage (y=BAND_H..2*BAND_H-1) — green + heavy noise
    # ------------------------------------------------------------------
    for y in range(BAND_H, 2 * BAND_H):
        for x in range(WIDTH):
            nr = _noise(rng, 0.20)
            ng = _noise(rng, 0.20)
            nb = _noise(rng, 0.20)
            px[x, y] = (
                _clamp(FOLIAGE_BASE[0] + nr),
                _clamp(FOLIAGE_BASE[1] + ng),
                _clamp(FOLIAGE_BASE[2] + nb),
            )

    # ------------------------------------------------------------------
    # Band 3: Skin / warm earth (y=2*BAND_H..3*BAND_H-1)
    # ------------------------------------------------------------------
    for y in range(2 * BAND_H, 3 * BAND_H):
        for x in range(WIDTH):
            nr = _noise(rng, 0.15)
            ng = _noise(rng, 0.15)
            nb = _noise(rng, 0.15)
            px[x, y] = (
                _clamp(SKIN_BASE[0] + nr),
                _clamp(SKIN_BASE[1] + ng),
                _clamp(SKIN_BASE[2] + nb),
            )

    # ------------------------------------------------------------------
    # Band 4: Shadow (y=3*BAND_H..HEIGHT-1) — dark + light noise
    # ------------------------------------------------------------------
    for y in range(3 * BAND_H, HEIGHT):
        for x in range(WIDTH):
            n = _noise(rng, 0.10)
            px[x, y] = (
                _clamp(SHADOW_BASE[0] + n),
                _clamp(SHADOW_BASE[1] + n),
                _clamp(SHADOW_BASE[2] + n),
            )

    # ------------------------------------------------------------------
    # Geometric overlays
    # ------------------------------------------------------------------
    draw = ImageDraw.Draw(img)

    # Horizon line at y=240 (sky/foliage boundary)
    draw.line([(0, 2 * BAND_H), (WIDTH - 1, 2 * BAND_H)], fill=HORIZON_COLOUR, width=2)

    # Ground line at y=360 (foliage/skin boundary)
    draw.line([(0, 3 * BAND_H), (WIDTH - 1, 3 * BAND_H)], fill=GROUND_COLOUR, width=1)

    # Tree silhouette 1 — left third, spanning sky into foliage
    tree1 = [
        (60, 2 * BAND_H),  # base left
        (100, 2 * BAND_H),  # base right
        (80, BAND_H // 3),  # apex in sky
    ]
    draw.polygon(tree1, fill=TREE_DARK)

    # Sub-tree branches (give the silhouette ragged edges)
    draw.polygon(
        [(50, 2 * BAND_H - 20), (110, 2 * BAND_H - 20), (80, BAND_H // 2)],
        fill=TREE_DARK,
    )

    # Tree silhouette 2 — right third
    tree2 = [
        (340, 2 * BAND_H),
        (390, 2 * BAND_H),
        (365, BAND_H // 4),
    ]
    draw.polygon(tree2, fill=TREE_DARK)
    draw.polygon(
        [(330, 2 * BAND_H - 30), (400, 2 * BAND_H - 30), (365, BAND_H // 2)],
        fill=TREE_DARK,
    )

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    out_path = os.path.normpath(_OUTPUT)
    img.save(out_path, format="JPEG", quality=QUALITY, optimize=True)
    print(f"Saved {WIDTH}×{HEIGHT} px JPEG to {out_path}")


if __name__ == "__main__":
    main()
