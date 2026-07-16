#!/usr/bin/env bash
# Regenerate raster brand assets from the SVG masters.
#
#   brand/render-assets.sh
#
# Requires a Python with cairosvg + Pillow (the Bridge dev venv has both).
# Set PY to point at it; defaults to `python3`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-python3}"
ICON_SVG="${ROOT}/brand/instantlink-icon.svg"

IOS_ICONSET="${ROOT}/ios/InstantLink/Resources/Assets.xcassets/AppIcon.appiconset"
SPLASH="${ROOT}/bridge/assets/boot-splash.rgb565"

"${PY}" - "$ICON_SVG" "$IOS_ICONSET" "$SPLASH" <<'PYEOF'
import sys
from pathlib import Path

import cairosvg
from PIL import Image

icon_svg, ios_iconset, splash = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])

# 1) iOS app icon — single 1024 PNG (Xcode 14+ single-size appiconset).
ios_iconset.mkdir(parents=True, exist_ok=True)
cairosvg.svg2png(
    url=icon_svg,
    write_to=str(ios_iconset / "icon-1024.png"),
    output_width=1024,
    output_height=1024,
)

# 2) Bridge boot splash — 240x240 RGB565 little-endian raw framebuffer.
png_240 = cairosvg.svg2png(url=icon_svg, output_width=240, output_height=240)
tmp = splash.parent / "_splash-240.png"
tmp.write_bytes(png_240)
img = Image.open(tmp).convert("RGB")
out = bytearray()
for r, g, b in img.getdata():
    value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    out += value.to_bytes(2, "little")
splash.write_bytes(bytes(out))
tmp.unlink()

print(f"wrote {ios_iconset / 'icon-1024.png'}")
print(f"wrote {splash} ({len(out)} bytes)")
PYEOF

# 3) macOS app icon (.icns) — only where iconutil exists (macOS). Rasterizes
# the SVG into a standard .iconset, then packs it. Retires the old hardcoded
# scripts/generate-icon.py.
if command -v iconutil >/dev/null 2>&1; then
  ICONSET="$(mktemp -d)/InstantLink.iconset"
  mkdir -p "${ICONSET}"
  "${PY}" - "$ICON_SVG" "$ICONSET" <<'PYEOF'
import sys
from pathlib import Path
import cairosvg

icon_svg, iconset = sys.argv[1], Path(sys.argv[2])
# name -> pixel size for the macOS .iconset convention.
sizes = {
    "icon_16x16": 16, "icon_16x16@2x": 32,
    "icon_32x32": 32, "icon_32x32@2x": 64,
    "icon_128x128": 128, "icon_128x128@2x": 256,
    "icon_256x256": 256, "icon_256x256@2x": 512,
    "icon_512x512": 512, "icon_512x512@2x": 1024,
}
for name, px in sizes.items():
    cairosvg.svg2png(url=icon_svg, write_to=str(iconset / f"{name}.png"),
                     output_width=px, output_height=px)
print(f"rasterized {len(sizes)} macOS icon sizes")
PYEOF
  iconutil -c icns "${ICONSET}" -o "${ROOT}/macos/Resources/AppIcon.icns"
  cp "${ICONSET}/icon_512x512@2x.png" "${ROOT}/macos/Resources/AppIcon.png"
  rm -rf "$(dirname "${ICONSET}")"
  echo "wrote ${ROOT}/macos/Resources/AppIcon.icns"
else
  echo "iconutil not found; skipped macOS .icns (run on macOS to regenerate)"
fi
