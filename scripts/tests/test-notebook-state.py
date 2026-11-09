#!/usr/bin/env python3
"""Check notebook result-state transitions without compiling or running QEMU."""

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


NOTEBOOK = Path(__file__).resolve().parents[2] / "RVP_Tutorial.ipynb"
CELLS = {cell["id"]: "".join(cell["source"])
         for cell in json.loads(NOTEBOOK.read_text())["cells"]
         if cell["cell_type"] == "code"}


class NotebookStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rvp-notebook-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "VERSION.json").write_text("{}\n")
        self.namespace = {}
        self.stdout = io.StringIO()
        environment = patch.dict(os.environ, {"RVP_EXAMPLE_ROOT": str(self.root)},
                                 clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        subprocess_patch = patch("subprocess.run", return_value=subprocess.CompletedProcess(
            [], 0, "", ""))
        self.run = subprocess_patch.start()
        self.addCleanup(subprocess_patch.stop)
        self.execute("configuration")
        self.run.reset_mock()

    def execute(self, cell, source=None):
        self.stdout.seek(0)
        self.stdout.truncate()
        code = compile(CELLS[cell] if source is None else source,
                       str(NOTEBOOK) + "#" + cell, "exec")
        with redirect_stdout(self.stdout):
            exec(code, self.namespace)

    def report(self):
        return {
            "build_configuration": {"xlen": self.namespace["XLEN"],
                                    "alignment": self.namespace["ALIGNMENT"],
                                    "optimization": self.namespace["OPTFLAGS"]},
            "tests": {"cases": 82640, "failures": 0},
            "independent_image_check": {"python_oracle_candidates": 289,
                                        "displacement": [5, -3]},
            "instruction_counts": {"results": []},
            "code_generation": {"text_bytes": {"scalar": 108, "p": 204},
                                "stack_usage": {}},
            "hardware_speedup": None,
        }

    def write_report(self, report=None):
        out = self.namespace["OUT"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(self.report() if report is None else report))
        (out / "sad-p.dis").write_text("pabdsumu.b current assembly\n")
        (out / "demo.svg").write_text("<svg/>\n")

    def build_success(self):
        self.write_report()
        self.execute("build-and-test")
        self.assertIsNotNone(self.namespace["result"])

    def assert_displays_blocked(self):
        self.run.reset_mock()
        for cell in ("image-output", "measured-results"):
            with self.subTest(display_cell=cell), \
                    patch.object(Path, "read_text", side_effect=AssertionError("Stale file read")):
                with self.assertRaises(RuntimeError):
                    self.execute(cell)
                self.assertEqual(self.stdout.getvalue(), "")
                self.run.assert_not_called()

    def test_displays_require_a_successful_build(self):
        self.assertIsNone(self.namespace["result"])
        self.assert_displays_blocked()

    def test_selection_clears_results_before_host_failure(self):
        self.build_success()
        self.run.side_effect = subprocess.CalledProcessError(1, ["check-host.py"])
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute("configuration")
        self.assertIsNone(self.namespace["result"])
        self.assertIsNone(self.namespace["_result_output"])
        self.assert_displays_blocked()

    def test_invalid_selection_clears_results(self):
        self.build_success()
        with self.assertRaises(AssertionError):
            self.execute("configuration", CELLS["configuration"].replace("XLEN = 32", "XLEN = 128"))
        self.assertIsNone(self.namespace["result"])
        self.assert_displays_blocked()

    def test_failed_build_and_timeout_do_not_republish_old_results(self):
        for failure in (subprocess.CalledProcessError(1, ["present.sh"]),
                        subprocess.TimeoutExpired(["present.sh"], 60)):
            with self.subTest(failure=type(failure).__name__):
                self.run.side_effect = None
                self.build_success()
                self.run.side_effect = failure
                with self.assertRaises(type(failure)):
                    self.execute("build-and-test")
                self.assertIsNone(self.namespace["result"])
                self.assertIsNone(self.namespace["_result_output"])
                self.assert_displays_blocked()

    def test_mismatched_or_failed_candidate_is_not_published(self):
        changes = (("build_configuration", "xlen", 64),
                   ("build_configuration", "alignment", "strict"),
                   ("build_configuration", "optimization", "-O2"),
                   ("tests", "failures", 1), ("tests", "cases", 1),
                   ("independent_image_check", "python_oracle_candidates", 1),
                   ("independent_image_check", "displacement", [0, 0]))
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                self.build_success()
                candidate = copy.deepcopy(self.namespace["result"])
                candidate[section][key] = value
                self.write_report(candidate)
                with self.assertRaises(RuntimeError):
                    self.execute("build-and-test")
                self.assertIsNone(self.namespace["result"])
                self.assert_displays_blocked()

    def test_malformed_report_does_not_republish_old_results(self):
        self.build_success()
        (self.namespace["OUT"] / "result.json").write_text("not JSON\n")
        with self.assertRaises(json.JSONDecodeError):
            self.execute("build-and-test")
        self.assertIsNone(self.namespace["result"])
        self.assert_displays_blocked()

    def test_setting_or_output_change_blocks_display(self):
        for key, value in (("XLEN", 64), ("ALIGNMENT", "strict"),
                           ("OPTFLAGS", "-O2"), ("OUT", self.root / "another-output")):
            with self.subTest(key=key):
                self.execute("configuration")
                self.build_success()
                self.namespace[key] = value
                self.assert_displays_blocked()

    def test_build_uses_current_optimization_setting(self):
        self.namespace["OPTFLAGS"] = "-O2"
        self.build_success()
        self.assertEqual(self.run.call_args.kwargs["env"]["OPTFLAGS"], "-O2")
        self.assertEqual(self.namespace["result"]["build_configuration"]["optimization"], "-O2")

    def test_current_success_can_render_and_display_measurements(self):
        self.build_success()
        display_module = ModuleType("IPython.display")
        display_module.SVG = Mock(return_value="current SVG")
        display_module.display = Mock()
        with patch.dict(sys.modules, {"IPython": ModuleType("IPython"),
                                      "IPython.display": display_module}):
            self.execute("image-output")
        display_module.SVG.assert_called_once_with(filename=str(self.namespace["OUT"] / "demo.svg"))
        display_module.display.assert_called_once_with("current SVG")
        self.execute("measured-results")
        self.assertIn("current assembly", self.stdout.getvalue())
        self.assertIn("Hardware performance: not measured", self.stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
