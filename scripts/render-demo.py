#!/usr/bin/env python3
"""Render the actual PGM pixels and verified search costs as a small SVG."""

import base64
import csv
import importlib.util
from pathlib import Path
import struct
import sys
import zlib


def grayscale_png(width, height, pixels):
    """Encode the original pixels without per-pixel SVG rasterization seams."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    rows = b"".join(b"\0" + pixels[y * width:(y + 1) * width]
                    for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "build/present"
spec = importlib.util.spec_from_file_location(
    "sad_report", root / "examples/rvp-image-sad/report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
report.verify_images(out / "images")
svg = ['<svg xmlns="http://www.w3.org/2000/svg" '
       'xmlns:xlink="http://www.w3.org/1999/xlink" width="720" height="270" '
       'viewBox="0 0 720 270" role="img" aria-labelledby="title desc">',
       '<title id="title">RV64 P image block matching</title>',
       '<desc id="desc">Reference and shifted grayscale images. All 289 '
       'scalar and P search costs agree. Best offset is 5, minus 3, SAD zero.</desc>',
       '<rect width="720" height="270" fill="#fff"/>',
       '<g font-family="sans-serif" fill="#172b4d">',
       '<text x="20" y="27" font-size="18">RV64 P: grayscale block matching</text>']
for index, (name, label) in enumerate((('reference', 'Reference block'),
                                      ('shifted', 'Matched block: (+5, -3)'))):
    width, height, pixels = report.read_pgm(out / "images" / (name + ".pgm"))
    x0 = 20 + index * 230
    svg.append(f'<text x="{x0}" y="55" font-size="14">{label}</text>')
    svg.append(f'<g transform="translate({x0},65) scale(2)" shape-rendering="crispEdges">')
    png = base64.b64encode(grayscale_png(width, height, pixels)).decode("ascii")
    svg.append(f'<image width="{width}" height="{height}" '
               f'xlink:href="data:image/png;base64,{png}" '
               'style="image-rendering:pixelated"/>')
    x, y = (32, 32) if index == 0 else (37, 29)
    svg.append(f'<rect x="{x}" y="{y}" width="16" height="16" '
               'fill="none" stroke="#ff5030" stroke-width="1"/></g>')
rows = list(csv.DictReader((out / "images/costs.csv").open()))
maximum = max(int(row['p_sad']) for row in rows)
svg.append('<text x="480" y="55" font-size="14">Search SAD (darker = lower)</text>')
for row in rows:
    dx, dy, cost = (int(row[key]) for key in ('dx', 'dy', 'p_sad'))
    shade = round(235 * cost / maximum) + 20
    x, y = 480 + (dx + 8) * 9, 65 + (dy + 8) * 9
    svg.append(f'<rect x="{x}" y="{y}" width="9" height="9" '
               f'fill="rgb({shade},{shade},{shade})"/>')
    if (dx, dy) == (5, -3):
        best_x, best_y = x, y
svg.append(f'<rect x="{best_x}" y="{best_y}" width="9" height="9" '
           'fill="none" stroke="#ff5030" stroke-width="2"/>')
svg += ['<text x="20" y="250" font-size="14">289/289 costs verified independently; '
        'best SAD = 0. Functional demonstration, not hardware performance.</text>',
        '</g></svg>']
destination = out / "demo.svg"
destination.write_text('\n'.join(svg) + '\n')
print(destination)
