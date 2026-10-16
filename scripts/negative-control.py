#!/usr/bin/env python3
"""Check that P execution and the independent image oracle can fail."""

import importlib.util
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1]).resolve()
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
result = subprocess.run(
    [str(root / "qemu/bin/qemu-riscv64"), "-R", "512M", "-cpu",
     "rv64,x-p=false,zmmul=true,zba=true,zbb=true", str(out / "sad-demo"),
     "--trace", "p", "aligned"], capture_output=True, text=True, timeout=30)
assert result.returncode in (-signal.SIGILL, 128 + signal.SIGILL), result
spec = importlib.util.spec_from_file_location(
    "sad_report", root / "examples/rvp-image-sad/report.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix="rvp-na-negative-") as tmp:
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
print("PASS: P-disabled execution raises SIGILL; image oracle rejects corruption")
