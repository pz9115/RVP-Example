#!/usr/bin/env python3
"""Check that P execution and the independent image oracle can fail."""

import importlib.util
import json
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1]).resolve()
config = json.loads((out / "build-config.json").read_text())
xlen = config["xlen"]
assert xlen in (32, 64)
assert "x-p=true" in config["qemu_cpu"]
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
runner = [str(root / f"qemu/bin/qemu-riscv{xlen}"), "-R", "512M", "-cpu",
          config["qemu_cpu"].replace("x-p=true", "x-p=false"), str(out / "sad-demo")]
scalar = subprocess.run(runner + ["--trace", "scalar", "aligned"],
                        capture_output=True, text=True, timeout=30)
assert scalar.returncode == 0, scalar
expected = json.loads((out / "instruction-counts.json").read_text())["results"][0]
assert json.loads(scalar.stdout)["sad"] == expected["runs"][0]["checksum"]
result = subprocess.run(
    runner + ["--trace", "p", "aligned"],
    capture_output=True, text=True, timeout=30)
assert result.returncode in (-signal.SIGILL, 128 + signal.SIGILL), result
spec = importlib.util.spec_from_file_location(
    "sad_report", root / "examples/rvp-image-sad/report.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix="rvp-example-negative-") as tmp:
    images = Path(tmp) / "images"
    shutil.copytree(out / "images", images)
    module.verify_images(images)
    pixels = bytearray((images / "reference.pgm").read_bytes())
    header_size = len(pixels) - 96 * 80
    pixels[header_size + 32 * 96 + 32] ^= 0xff
    (images / "reference.pgm").write_bytes(pixels)
    try:
        module.verify_images(images)
    except AssertionError:
        pass
    else:
        raise AssertionError("Image oracle accepted corrupted image data")
print(f"PASS: RV{xlen} scalar runs without P; packed execution raises SIGILL; "
      "image oracle rejects corruption")
