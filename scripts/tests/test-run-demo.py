#!/usr/bin/env python3
"""Exercise runner failure cleanup without starting a compiler or emulator."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("run_demo", SCRIPTS / "run-demo.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
SUCCESS_REPORTS = (
    "result.json", "instruction-counts.json", "tests.json", "demo.json",
    "compiler-regression.json", "alignment-checks.json",
)


class FailureCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rvp-runner-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.out = self.directory / "output"
        self.seed_reports(self.out)

    def seed_reports(self, out):
        out.mkdir(parents=True, exist_ok=True)
        for name in SUCCESS_REPORTS:
            (out / name).write_text('{"old_success": true}\n')
        (out / "unrelated-sentinel.txt").write_text("keep me\n")

    def assert_clean(self, out):
        for name in SUCCESS_REPORTS:
            self.assertFalse((out / name).exists(), name)
        self.assertEqual((out / "unrelated-sentinel.txt").read_text(), "keep me\n")

    def test_invalid_settings_clear_explicit_output(self):
        for setting in ({"XLEN": "invalid"}, {"XLEN": "128"},
                        {"ALIGNMENT": "invalid"}, {"ALIGNMENT": ""},
                        {"ALIGNFLAGS": "-mstrict-align"}):
            with self.subTest(setting=setting):
                self.seed_reports(self.out)
                environment = {"OUT": str(self.out), **setting}
                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(RUNNER, "run") as run:
                    with self.assertRaises(ValueError):
                        RUNNER.main()
                    run.assert_not_called()
                self.assert_clean(self.out)

    def test_empty_output_is_rejected_without_guessing_a_directory(self):
        previous = Path.cwd()
        try:
            os.chdir(self.out)
            with patch.dict(os.environ, {"OUT": ""}, clear=True), \
                    patch.object(RUNNER, "run") as run:
                with self.assertRaisesRegex(ValueError, "OUT must not be empty"):
                    RUNNER.main()
                run.assert_not_called()
        finally:
            os.chdir(previous)
        for name in SUCCESS_REPORTS:
            self.assertTrue((self.out / name).is_file(), name)
        self.assertEqual((self.out / "unrelated-sentinel.txt").read_text(), "keep me\n")

    def test_whitespace_output_clears_reports_before_rejection(self):
        for name in ("space path", "   "):
            with self.subTest(name=name):
                out = self.directory / name
                self.seed_reports(out)
                with patch.dict(os.environ, {"OUT": str(out)}, clear=True), \
                        patch.object(RUNNER, "run") as run:
                    with self.assertRaisesRegex(ValueError, "without whitespace"):
                        RUNNER.main()
                    run.assert_not_called()
                self.assert_clean(out)

    def test_whitespace_project_clears_explicit_output_before_rejection(self):
        with patch.dict(os.environ, {"OUT": str(self.out)}, clear=True), \
                patch.object(RUNNER, "ROOT", self.directory / "project path"), \
                patch.object(RUNNER, "run") as run:
            with self.assertRaisesRegex(ValueError, "without whitespace"):
                RUNNER.main()
            run.assert_not_called()
        self.assert_clean(self.out)

    def test_build_failure_and_timeout_clear_success_reports(self):
        failures = (subprocess.CalledProcessError(2, ["make"]),
                    subprocess.TimeoutExpired(["make"], 60))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.seed_reports(self.out)

                def fake_run(command, destination=None, combined=False):
                    self.assert_clean(self.out)
                    if command[0] == "make":
                        raise failure
                    return subprocess.CompletedProcess(command, 0, "", "")

                with patch.dict(os.environ, {"OUT": str(self.out)}, clear=True), \
                        patch.object(RUNNER, "run", side_effect=fake_run) as run:
                    with self.assertRaises(type(failure)):
                        RUNNER.main()
                    self.assertEqual(run.call_count, 2)
                self.assert_clean(self.out)

    def test_late_timeout_clears_reports_created_during_this_run(self):
        def fake_run(command, destination=None, combined=False):
            if any(Path(str(argument)).name == "report.py" for argument in command):
                self.seed_reports(self.out)
            if any(Path(str(argument)).name == "render-demo.py" for argument in command):
                self.assertTrue((self.out / "result.json").exists())
                raise subprocess.TimeoutExpired(command, 60)
            return subprocess.CompletedProcess(command, 0, "/mock/tool\n", "")

        with patch.dict(os.environ, {"OUT": str(self.out)}, clear=True), \
                patch.object(RUNNER, "run", side_effect=fake_run):
            with self.assertRaises(subprocess.TimeoutExpired):
                RUNNER.main()
        self.assert_clean(self.out)

    def test_default_output_is_cleaned_on_build_failure(self):
        out = self.directory / "build/rv32-hardware"
        self.seed_reports(out)
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(RUNNER, "ROOT", self.directory), \
                patch.object(RUNNER, "run", side_effect=subprocess.CalledProcessError(
                    2, ["check-host.py"])):
            with self.assertRaises(subprocess.CalledProcessError):
                RUNNER.main()
        self.assert_clean(out)

    def test_default_output_is_cleaned_before_rejecting_alignflags(self):
        out = self.directory / "build/rv32-hardware"
        self.seed_reports(out)
        with patch.dict(os.environ, {"ALIGNFLAGS": "-mstrict-align"}, clear=True), \
                patch.object(RUNNER, "ROOT", self.directory), \
                patch.object(RUNNER, "run") as run:
            with self.assertRaisesRegex(ValueError, "Use ALIGNMENT"):
                RUNNER.main()
            run.assert_not_called()
        self.assert_clean(out)


if __name__ == "__main__":
    unittest.main()
