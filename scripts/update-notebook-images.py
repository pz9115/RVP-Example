#!/usr/bin/env python3
"""Embed the verified image-search figure in the notebook's saved output."""

import argparse
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path,
                        help="validated demo output, e.g. build/acceptance/O3")
    args = parser.parse_args()
    out = args.output.resolve()
    notebook_path = ROOT / "RVP_Tutorial.ipynb"
    notebook = json.loads(notebook_path.read_text())
    cells = [cell for cell in notebook["cells"]
             if cell["cell_type"] == "code"
             and "scripts/render-demo.py" in "".join(cell["source"])]
    if len(cells) != 1:
        parser.error("Expected exactly one image-rendering cell")
    converter = shutil.which("magick") or shutil.which("convert")
    if not converter:
        parser.error("Install ImageMagick to refresh saved notebook images")
    # render-demo.py checks the image costs before creating the figure.
    subprocess.run([sys.executable, str(ROOT / "scripts/render-demo.py"),
                    str(out)], check=True)
    destination = ROOT / "docs/images/image-block-matching.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([converter, "-background", "white", "-density", "144",
                    str(out / "demo.svg"), "-resize", "1440x540", "-depth", "8",
                    "-strip", "PNG24:" + str(destination)], check=True)
    payload = destination.read_bytes()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Image conversion did not produce a PNG")
    cells[0]["outputs"] = [{
        "output_type": "display_data",
        "data": {
            "image/png": base64.b64encode(payload).decode("ascii"),
            "text/plain": ["Reference image, matched block (+5, -3), and SAD search map"],
        },
        "metadata": {"image/png": {"width": 720, "height": 270}},
    }]
    # Saved illustration output does not imply that other cells were executed.
    cells[0]["execution_count"] = None
    notebook_path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n")
    print("Embedded image-block-matching.png in RVP_Tutorial.ipynb")


if __name__ == "__main__":
    main()
