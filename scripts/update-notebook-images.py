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
                        help="validated demo output, e.g. build/rv32-hardware")
    args = parser.parse_args()
    out = args.output.resolve()
    result = json.loads((out / "result.json").read_text())
    config = result["build_configuration"]
    xlen, alignment = config["xlen"], config["alignment"]
    if xlen not in (32, 64) or alignment not in ("hardware", "strict"):
        parser.error("Invalid target or alignment policy in result.json")
    if result["tests"]["failures"] != 0:
        parser.error("Only a validated run can supply the saved preview")
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
                    str(out)], check=True, timeout=60)
    destination = ROOT / "docs/images/image-block-matching.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([converter, "-background", "white", "-density", "144",
                    str(out / "demo.svg"), "-resize", "1440x540", "-depth", "8",
                    "-strip", "PNG24:" + str(destination)], check=True,
                   timeout=60)
    payload = destination.read_bytes()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Image conversion did not produce a PNG")
    # Numerical outputs from a previous target must not accompany this image.
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    label = (f"RV{xlen} P, {alignment} alignment policy: "
             "reference image, match (+5, -3), and verified SAD search map")
    cells[0]["outputs"] = [{
        "output_type": "display_data",
        "data": {
            "image/png": base64.b64encode(payload).decode("ascii"),
            "text/plain": [label],
        },
        "metadata": {"image/png": {"width": 720, "height": 270}},
    }]
    # Saved illustration output does not imply that other cells were executed.
    cells[0]["execution_count"] = None
    notebook["metadata"]["rvp_example_preview"] = {
        "xlen": xlen, "alignment": alignment,
        "scope": "Verified image illustration, not saved benchmark results",
    }
    notebook_path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n")
    print("Embedded image-block-matching.png in RVP_Tutorial.ipynb")


if __name__ == "__main__":
    main()
