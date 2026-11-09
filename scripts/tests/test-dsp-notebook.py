#!/usr/bin/env python3
"""Host-only tests of the DSP notebook's configuration and result guards."""

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
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = json.loads((ROOT / "DSP_Tutorial.ipynb").read_text())
CELLS = {cell["id"]: "".join(cell["source"]) for cell in NOTEBOOK["cells"]
         if cell["cell_type"] == "code"}


class DSPNotebookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rvp-dsp-notebook-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.namespace = {}
        self.stdout = io.StringIO()
        environment = patch.dict(os.environ, {"RVP_EXAMPLE_ROOT": str(ROOT),
                                               "RVP_DSP_OUT": str(self.directory / "output")},
                                 clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        runner = patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", ""))
        self.run = runner.start()
        self.addCleanup(runner.stop)
        self.execute("configuration")
        self.run.assert_not_called()

    def execute(self, cell):
        self.stdout.seek(0)
        self.stdout.truncate()
        with redirect_stdout(self.stdout):
            exec(compile(CELLS[cell], "DSP_Tutorial.ipynb#" + cell, "exec"), self.namespace)

    def report(self):
        config, _ = self.namespace["_selection"]()
        return {
            "build_configuration": config,
            "tests": {"cases": 7, "failures": 0},
            "python_oracle": {"dot_terms": 17, "fir_outputs": 64},
            "negative_controls": {"scalar_without_p": "pass", "packed_without_p": "SIGILL"},
            "alignment_checks": {"scalar_with_misaligned_traps": "pass",
                                 "packed_with_misaligned_support": "pass",
                                 "packed_with_misaligned_traps": "SIGBUS" if config["alignment"] == "hardware" else "pass"},
            "hardware_speedup": None,
            "instruction_counts": [
                {"workload": workload, "kernel": kernel, "layout": layout, "guest_instructions": 10}
                for workload in ("dot", "fir") for kernel in ("scalar", "p")
                for layout in ("aligned", "unaligned")],
            "kernel_footprint": {f"q15_{workload}_{kernel}": {"text_bytes": 8, "static_frame_bytes": 0}
                                 for workload in ("dot", "fir") for kernel in ("scalar", "p")},
        }

    def write_report(self, candidate=None):
        _, out = self.namespace["_selection"]()
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(self.report() if candidate is None else candidate))
        (out / "dsp.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n')

    def build_success(self):
        self.write_report()
        self.execute("build-and-test")
        self.assertIsNotNone(self.namespace["result"])

    def assert_displays_blocked(self):
        self.run.reset_mock()
        for cell in ("measured-results", "image-output"):
            with self.subTest(cell=cell), \
                    patch.object(Path, "read_text", side_effect=AssertionError("Stale read")), \
                    patch.object(Path, "is_file", side_effect=AssertionError("Stale image lookup")):
                with self.assertRaises(ValueError):
                    self.execute(cell)
                self.assertEqual(self.stdout.getvalue(), "")
                self.run.assert_not_called()

    def test_verified_preview_is_labeled_and_numeric_outputs_are_not_saved(self):
        for cell in NOTEBOOK["cells"]:
            if cell["cell_type"] == "code":
                self.assertIsNone(cell["execution_count"])
                if cell["id"] == "image-output":
                    self.assertEqual(len(cell["outputs"]), 1)
                    output = cell["outputs"][0]
                    self.assertEqual(output["output_type"], "display_data")
                    svg = "".join(output["data"]["image/svg+xml"])
                    self.assertEqual(ET.fromstring(svg).tag, "{http://www.w3.org/2000/svg}svg")
                    preview = NOTEBOOK["metadata"]["rvp_dsp_preview"]
                    self.assertEqual((preview["xlen"], preview["alignment"], preview["optimization"]),
                                     (32, "hardware", "-O3"))
                    self.assertEqual(preview["source_result"], "rv32-hardware/result.json")
                    self.assertIn("Verified Q15", "".join(output["data"]["text/plain"]))
                else:
                    self.assertEqual(cell["outputs"], [])
        self.assert_displays_blocked()

    def test_current_configuration_is_rebuilt_for_all_targets_and_policies(self):
        for xlen in (32, 64):
            for alignment in ("hardware", "strict"):
                with self.subTest(xlen=xlen, alignment=alignment):
                    self.namespace.update(XLEN=xlen, ALIGNMENT=alignment, OPTFLAGS="-O2")
                    self.build_success()
                    environment = self.run.call_args.kwargs["env"]
                    self.assertEqual((environment["XLEN"], environment["ALIGNMENT"], environment["OPTFLAGS"]),
                                     (str(xlen), alignment, "-O2"))
                    self.assertEqual(environment["OUT"], os.environ["RVP_DSP_OUT"])
                    self.assertEqual(self.run.call_args.kwargs["timeout"], 60)
                    self.execute("measured-results")
                    self.assertIn("Guest instructions", self.stdout.getvalue())
                    self.assertIn("Kernel footprint", self.stdout.getvalue())

    def test_default_outputs_separate_target_policy_and_optimization(self):
        del os.environ["RVP_DSP_OUT"]
        outputs = set()
        for xlen in (32, 64):
            for alignment in ("hardware", "strict"):
                for optimization in ("-O2", "-O3", "-Os"):
                    self.namespace.update(XLEN=xlen, ALIGNMENT=alignment, OPTFLAGS=optimization)
                    _, out = self.namespace["_selection"]()
                    outputs.add(out)
        self.assertEqual(len(outputs), 12)
        self.run.assert_not_called()

    def test_configuration_selection_clears_old_results_even_if_root_is_invalid(self):
        self.build_success()
        os.environ["RVP_EXAMPLE_ROOT"] = str(self.directory / "missing-root")
        with self.assertRaises(RuntimeError):
            self.execute("configuration")
        self.assertIsNone(self.namespace["result"])
        self.assert_displays_blocked()

    def test_failed_build_and_timeout_cannot_republish_old_results(self):
        for error in (subprocess.CalledProcessError(1, ["dsp.sh"]),
                      subprocess.TimeoutExpired(["dsp.sh"], 60)):
            with self.subTest(error=type(error).__name__):
                self.run.side_effect = None
                self.build_success()
                self.run.side_effect = error
                with self.assertRaises(type(error)):
                    self.execute("build-and-test")
                self.assertIsNone(self.namespace["result"])
                self.assertIsNone(self.namespace["_result_output"])
                self.assert_displays_blocked()

    def test_invalid_selection_and_output_are_fail_closed(self):
        for key, value in (("XLEN", 128), ("XLEN", 32.0), ("ALIGNMENT", "bad"), ("OPTFLAGS", "-O0")):
            with self.subTest(key=key):
                self.execute("configuration")
                self.build_success()
                self.namespace[key] = value
                self.run.reset_mock()
                with self.assertRaises(ValueError):
                    self.execute("build-and-test")
                self.run.assert_not_called()
                self.assertIsNone(self.namespace["result"])
                self.assert_displays_blocked()
        self.execute("configuration")
        for output in ("", str(self.directory / "space path")):
            with self.subTest(output=output):
                os.environ["RVP_DSP_OUT"] = output
                with self.assertRaises(ValueError):
                    self.execute("build-and-test")
                self.assertIsNone(self.namespace["result"])
                self.assert_displays_blocked()

    def test_configuration_fields_are_exact_and_current(self):
        for key, value in (("xlen", 64), ("xlen", 32.0), ("alignment", "strict"),
                           ("optimization", "-O2"), ("abi", "ilp32d"), ("runtime_arch", "rv32gc")):
            with self.subTest(key=key, value=value):
                self.build_success()
                candidate = copy.deepcopy(self.namespace["result"])
                candidate["build_configuration"][key] = value
                self.write_report(candidate)
                with self.assertRaises(ValueError):
                    self.execute("build-and-test")
                self.assertIsNone(self.namespace["result"])
                self.assert_displays_blocked()

    def test_required_validation_proofs_cannot_be_missing_or_failed(self):
        changes = (("tests", "cases", 0), ("tests", "cases", True),
                   ("tests", "failures", 1), ("tests", "failures", False),
                   ("python_oracle", "dot_terms", 17.0), ("python_oracle", "fir_outputs", 63),
                   ("negative_controls", "scalar_without_p", "fail"),
                   ("negative_controls", "packed_without_p", "pass"),
                   ("alignment_checks", "scalar_with_misaligned_traps", "SIGBUS"),
                   ("alignment_checks", "packed_with_misaligned_support", "SIGBUS"),
                   ("alignment_checks", "packed_with_misaligned_traps", "pass"))
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                candidate = self.report()
                candidate[section][key] = value
                self.write_report(candidate)
                with self.assertRaises(ValueError):
                    self.execute("build-and-test")
                self.assertIsNone(self.namespace["result"])
                self.assert_displays_blocked()
        for missing in ("negative_controls", "alignment_checks", "hardware_speedup"):
            candidate = self.report()
            del candidate[missing]
            self.write_report(candidate)
            with self.assertRaises(ValueError):
                self.execute("build-and-test")
        candidate = self.report()
        candidate["hardware_speedup"] = 2.0
        self.write_report(candidate)
        with self.assertRaises(ValueError):
            self.execute("build-and-test")

    def test_incomplete_counts_and_footprints_are_not_published(self):
        candidates = []
        candidate = self.report()
        candidate["instruction_counts"].pop()
        candidates.append(candidate)
        candidate = self.report()
        candidate["instruction_counts"][0] = candidate["instruction_counts"][1]
        candidates.append(candidate)
        candidate = self.report()
        candidate["instruction_counts"][0]["guest_instructions"] = 10.0
        candidates.append(candidate)
        candidate = self.report()
        del candidate["kernel_footprint"]["q15_fir_p"]
        candidates.append(candidate)
        candidate = self.report()
        candidate["kernel_footprint"]["q15_fir_p"]["static_frame_bytes"] = -1
        candidates.append(candidate)
        for index, candidate in enumerate(candidates):
            with self.subTest(index=index):
                self.write_report(candidate)
                with self.assertRaises(ValueError):
                    self.execute("build-and-test")
                self.assertIsNone(self.namespace["result"])
                self.assert_displays_blocked()

    def test_settings_or_output_change_block_old_displays(self):
        for key, value in (("XLEN", 64), ("ALIGNMENT", "strict"), ("OPTFLAGS", "-O2"),
                           ("OUT", self.directory / "another-output")):
            with self.subTest(key=key):
                self.execute("configuration")
                self.build_success()
                self.namespace[key] = value
                self.assert_displays_blocked()
        self.execute("configuration")
        self.build_success()
        os.environ["RVP_DSP_OUT"] = str(self.directory / "changed-output")
        self.assert_displays_blocked()

    def test_malformed_json_does_not_republish_an_earlier_success(self):
        self.build_success()
        (self.namespace["OUT"] / "result.json").write_text("bad JSON\n")
        with self.assertRaises(json.JSONDecodeError):
            self.execute("build-and-test")
        self.assertIsNone(self.namespace["result"])
        self.assert_displays_blocked()

    def test_verified_svg_display_and_missing_ipython_fallback(self):
        self.build_success()
        display_module = ModuleType("IPython.display")
        display_module.SVG = Mock(return_value="verified SVG")
        display_module.display = Mock()
        with patch.dict(sys.modules, {"IPython": ModuleType("IPython"), "IPython.display": display_module}):
            self.execute("image-output")
        display_module.SVG.assert_called_once_with(filename=str(self.namespace["OUT"] / "dsp.svg"))
        display_module.display.assert_called_once_with("verified SVG")
        with patch.dict(sys.modules, {"IPython": None, "IPython.display": None}):
            self.execute("image-output")
        self.assertIn("Open the verified visualization:", self.stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
