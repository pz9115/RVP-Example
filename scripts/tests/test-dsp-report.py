#!/usr/bin/env python3
"""Host-only Q15 oracle, report rejection, and runner accounting regressions."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import dsp_report as REPORT
from demo_config import configuration

SPEC = importlib.util.spec_from_file_location("run_dsp", SCRIPTS / "run-dsp.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def fir_fixture(taps):
    coefficients = [16384, -4096, 2048] + [0] * (taps - 3)
    history = [i * 7 - 600 for i in range(taps - 1)]
    signal = [i * 31 - 900 for i in range(64)]
    raw, output = REPORT.fir_reference(coefficients, history, signal)
    return {"coefficients": coefficients, "history": history, "input": signal,
            "raw_q30": raw, "output_q15": output}


def trace_fixture(workload="dot", kernel="scalar", layout="aligned"):
    case = {"workload": workload, "kernel": kernel, "layout": layout}
    if workload == "dot":
        case.update(a=[1] * 1024, b=[1] * 1024, count=1024,
                    sum_q30=1024, q15=0, checksum=1024)
    else:
        case.update(fir_fixture(32))
        case.update(taps=32, outputs=64, checksum=sum(case["output_q15"]))
    return case


def demo_fixture():
    a = [-32768, -32768] + list(range(15))
    b = [-32768, -32768] + list(range(15, 0, -1))
    total = REPORT.dot_reference(a, b)
    fir = fir_fixture(7)
    output = fir.pop("output_q15")
    fir.update(scalar_q15=list(output), p_q15=list(output))
    return {"dot": {"a": a, "b": b, "sum_scalar_q30": total, "sum_p_q30": total},
            "fir": fir}


class IntegerOracleTests(unittest.TestCase):
    def test_asymmetric_causal_order_and_nonzero_history(self):
        raw, values = REPORT.fir_reference([8192, -4096, 2048], [4096, -8192],
                                           [16384, -16384, 24576, -24576])
        self.assertEqual(raw, [176160768, -218103808, 301989888, -335544320])
        self.assertEqual(values, [5376, -6656, 9216, -10240])

    def test_rounding_ties_away_from_zero(self):
        for raw, expected in ((0, 0), (16383, 0), (16384, 1), (16385, 1),
                              (-16383, 0), (-16384, -1), (-16385, -1),
                              (49152, 2), (-49152, -2)):
            with self.subTest(raw=raw):
                self.assertEqual(REPORT.quantize(raw), expected)

    def test_round_only_after_complete_accumulation(self):
        self.assertEqual(REPORT.fir_reference([16384, 16384], [1], [1, -1, -1]),
                         ([32768, 0, -32768], [1, 0, -1]))

    def test_clamping_and_pair_sum_beyond_int32(self):
        self.assertEqual(REPORT.dot_reference([-32768] * 2, [-32768] * 2), 1 << 31)
        self.assertEqual(REPORT.fir_reference([-32768, -32768], [-32768],
                                             [-32768, 32767, 32767]),
                         ([1 << 31, 32768, -2147418112], [32767, 1, -32768]))
        self.assertEqual(REPORT.quantize((32767 << 15) + 16384), 32767)
        self.assertEqual(REPORT.quantize((-32768 << 15) - 16384), -32768)

    def test_full_range_65536_term_64_bit_accumulation(self):
        self.assertEqual(REPORT.dot_reference([-32768] * 65536, [-32768] * 65536), 1 << 46)
        negative = -(1 << 46) + (1 << 31)
        self.assertEqual(REPORT.dot_reference([-32768] * 65536, [32767] * 65536), negative)
        self.assertEqual(REPORT.fir_reference([-32768] * 65536, [-32768] * 65535, [-32768]),
                         ([1 << 46], [32767]))
        self.assertEqual(REPORT.fir_reference([-32768] * 65536, [32767] * 65535, [32767]),
                         ([negative], [-32768]))

    def test_empty_workloads_and_length_bounds(self):
        self.assertEqual(REPORT.dot_reference([], []), 0)
        self.assertEqual(REPORT.fir_reference([1], [], []), ([], []))
        invalid = ((REPORT.dot_reference, ([1], [])),
                   (REPORT.dot_reference, ([0] * 65537, [0] * 65537)),
                   (REPORT.fir_reference, ([], [], [1])),
                   (REPORT.fir_reference, ([1, 2], [], [1])),
                   (REPORT.fir_reference, ([1, 2], [1, 2], [1])),
                   (REPORT.fir_reference, ([0] * 65537, [0] * 65536, [])))
        for function, arguments in invalid:
            with self.subTest(function=function.__name__, lengths=tuple(map(len, arguments))):
                with self.assertRaises(ValueError):
                    function(*arguments)

    def test_malformed_sample_arrays(self):
        for value in (None, "1", (1,), [True], [False], [1.0], ["1"], [-32769], [32768]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    REPORT.samples(value)


class ReportValidationTests(unittest.TestCase):
    def test_valid_trace_and_demo_fixtures(self):
        self.assertEqual(REPORT.verify_trace(trace_fixture()), 1024)
        fir = trace_fixture("fir")
        self.assertEqual(REPORT.verify_trace(fir), fir["output_q15"])
        checked = REPORT.verify_demo(demo_fixture())
        self.assertEqual((checked["dot_terms"], checked["fir_outputs"]), (17, 64))

    def test_one_corrupted_input_or_output_is_rejected(self):
        mutations = (("dot", "a", 0), ("dot", "b", 0),
                     ("fir", "input", 0), ("fir", "history", -1),
                     ("fir", "coefficients", 0), ("fir", "scalar_q15", 0),
                     ("fir", "p_q15", 0), ("fir", "raw_q30", 0))
        for workload, field, index in mutations:
            with self.subTest(workload=workload, field=field):
                demo = demo_fixture()
                demo[workload][field][index] += 8
                with self.assertRaises(ValueError):
                    REPORT.verify_demo(demo)
        for field in ("sum_scalar_q30", "sum_p_q30"):
            demo = demo_fixture()
            demo["dot"][field] += 1
            with self.assertRaises(ValueError):
                REPORT.verify_demo(demo)

    def test_trace_corruption_and_truncation_are_rejected(self):
        for workload, fields in (("dot", ("a", "b")),
                                ("fir", ("coefficients", "history", "input", "output_q15", "raw_q30"))):
            for field in fields:
                for mutation in ("corrupt", "truncate"):
                    with self.subTest(workload=workload, field=field, mutation=mutation):
                        case = trace_fixture(workload)
                        if mutation == "truncate":
                            case[field].pop()
                        else:
                            # Mutate an active history tap, not a zero-weight
                            # older sample that cannot change the FIR result.
                            case[field][-1 if field == "history" else 0] += 8
                        with self.assertRaises(ValueError):
                            REPORT.verify_trace(case)

    def test_jointly_truncated_demo_is_rejected(self):
        demo = demo_fixture()
        for field in ("a", "b"):
            demo["dot"][field].pop()
        total = REPORT.dot_reference(demo["dot"]["a"], demo["dot"]["b"])
        demo["dot"].update(sum_scalar_q30=total, sum_p_q30=total)
        with self.assertRaises(ValueError):
            REPORT.verify_demo(demo)
        demo = demo_fixture()
        for field in ("input", "scalar_q15", "p_q15", "raw_q30"):
            demo["fir"][field].pop()
        with self.assertRaises(ValueError):
            REPORT.verify_demo(demo)

    def test_noninteger_results_are_rejected(self):
        for workload, field in (("dot", "sum_q30"), ("dot", "q15"),
                                ("dot", "checksum"), ("fir", "checksum")):
            with self.subTest(workload=workload, field=field):
                case = trace_fixture(workload)
                case[field] = float(case[field])
                with self.assertRaises(ValueError):
                    REPORT.verify_trace(case)
        for field in ("output_q15", "raw_q30"):
            case = trace_fixture("fir")
            case[field] = list(map(float, case[field]))
            with self.assertRaises(ValueError):
                REPORT.verify_trace(case)
        case = trace_fixture()
        case["q15"] = False
        with self.assertRaises(ValueError):
            REPORT.verify_trace(case)
        for section, field in (("dot", "sum_scalar_q30"), ("dot", "sum_p_q30"),
                               ("fir", "scalar_q15"), ("fir", "p_q15"), ("fir", "raw_q30")):
            demo = demo_fixture()
            value = demo[section][field]
            demo[section][field] = list(map(float, value)) if isinstance(value, list) else float(value)
            with self.assertRaises(ValueError):
                REPORT.verify_demo(demo)

    def test_trace_metadata_is_not_ignored(self):
        for workload, field in (("dot", "count"), ("dot", "checksum"),
                                ("fir", "taps"), ("fir", "outputs"), ("fir", "checksum")):
            for mutation in ("wrong", "float"):
                with self.subTest(workload=workload, field=field, mutation=mutation):
                    case = trace_fixture(workload)
                    case[field] = case[field] + 1 if mutation == "wrong" else float(case[field])
                    with self.assertRaises(ValueError):
                        REPORT.verify_trace(case)
        for field, value in (("workload", "unknown"), ("kernel", "unknown"), ("layout", "unknown")):
            case = trace_fixture()
            case[field] = value
            with self.assertRaises(ValueError):
                REPORT.verify_trace(case)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rvp-dsp-host-test-")
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def seed_reports(self):
        for name in RUNNER.SUCCESS_FILES:
            (self.out / name).write_text("old success\n")
        (self.out / "sentinel.txt").write_text("preserve\n")

    def assert_clean(self):
        self.assertTrue(all(not (self.out / name).exists() for name in RUNNER.SUCCESS_FILES))
        self.assertEqual((self.out / "sentinel.txt").read_text(), "preserve\n")

    def test_timeout_replaces_stale_log_with_partial_diagnostics(self):
        for stdout, stderr in ((b"partial output\n", b"partial error\n"),
                               ("partial output\n", "partial error\n")):
            destination = self.out / "build.log"
            destination.write_text("stale successful build\n")
            error = subprocess.TimeoutExpired(["make"], 60, output=stdout, stderr=stderr)
            with patch.object(RUNNER.subprocess, "run", side_effect=error) as run, \
                    redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                with self.assertRaises(subprocess.TimeoutExpired):
                    RUNNER.run(["make"], destination)
            self.assertEqual(destination.read_text(), "partial output\npartial error\n")
            self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_failed_command_logs_before_raising_and_allow_failure_is_explicit(self):
        completed = subprocess.CompletedProcess(["fake"], 2, "stdout\n", "stderr\n")
        destination = self.out / "failed.log"
        with patch.object(RUNNER.subprocess, "run", return_value=completed), \
                redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            with self.assertRaises(subprocess.CalledProcessError):
                RUNNER.run(["fake"], destination)
            self.assertIs(RUNNER.run(["fake"], allow_failure=True), completed)
        self.assertEqual(destination.read_text(), "stdout\nstderr\n")

    def test_invalid_configuration_clears_only_success_files(self):
        for setting in ({"XLEN": "bad"}, {"XLEN": "128"}, {"ALIGNMENT": "bad"},
                        {"ALIGNFLAGS": "-mstrict-align"}, {"OPTFLAGS": "-O0"}):
            with self.subTest(setting=setting):
                self.seed_reports()
                with patch.dict(os.environ, {"OUT": str(self.out), **setting}, clear=True), \
                        patch.object(RUNNER.resource, "setrlimit"), \
                        patch.object(RUNNER, "build_and_check") as build:
                    with self.assertRaises(ValueError):
                        RUNNER.main()
                    build.assert_not_called()
                self.assert_clean()

    def test_build_exception_clears_new_and_old_success_files(self):
        for error in (subprocess.CalledProcessError(1, ["make"]),
                      subprocess.TimeoutExpired(["make"], 60)):
            with self.subTest(error=type(error).__name__):
                self.seed_reports()

                def fail(out, config):
                    self.assert_clean()
                    (out / "result.json").write_text("new but incomplete\n")
                    raise error

                with patch.dict(os.environ, {"OUT": str(self.out)}, clear=True), \
                        patch.object(RUNNER.resource, "setrlimit"), \
                        patch.object(RUNNER, "build_and_check", side_effect=fail):
                    with self.assertRaises(type(error)):
                        RUNNER.main()
                self.assert_clean()

    def test_symbol_accounting_rejects_calls_external_branches_and_other_isas(self):
        name = "q15_dot_scalar"
        symbols = f"00001000 0000000c T {name}\n"
        for opcode, arguments in (("jal", "2000 <helper>"), ("jalr", "a5"),
                                  ("j", "2000 <helper>"), ("beqz", "a0,2000 <helper>"),
                                  ("vadd.vv", "v0,v1,v2"), ("fadd.s", "fa0,fa1,fa2")):
            with self.subTest(opcode=opcode):
                dis = f"1000: 00000013 {opcode} {arguments}\n1004: 8082 ret\n"
                with patch.object(RUNNER, "run", return_value=subprocess.CompletedProcess([], 0, dis, "")):
                    with self.assertRaises(ValueError):
                        RUNNER.symbol_code(self.out, "", self.out / "demo", name, symbols, self.out)
        dis = "1000: 00000013 beqz a0,1008 <q15_dot_scalar+0x8>\n1004: 00000013 add a0,a0,a1\n1008: 8082 ret\n"
        with patch.object(RUNNER, "run", return_value=subprocess.CompletedProcess([], 0, dis, "")):
            functions, instructions = RUNNER.symbol_code(self.out, "", self.out / "demo", name, symbols, self.out)
        self.assertEqual(sum(size for _, size, _ in functions), 12)
        self.assertEqual(set(instructions), {0x1000, 0x1004, 0x1008})

    def test_same_result_different_first_repeat_input_is_rejected(self):
        (self.out / "q15-scalar.su").write_text("file.c:1:1:q15_dot_scalar\t0\tstatic\n")
        traces = []

        def fake_run(command, **kwargs):
            if "--defined-only" in command:
                return subprocess.CompletedProcess(command, 0, "", "")
            case = trace_fixture()
            if not traces:
                case["a"][0], case["a"][1] = 2, 0
            trace = Path(command[command.index("-D") + 1])
            trace.write_text("Trace 0: [0/1000/0/0]\n")
            traces.append(trace)
            return subprocess.CompletedProcess(command, 0, json.dumps(case), "")

        with patch.object(RUNNER, "run", side_effect=fake_run), \
                patch.object(RUNNER, "symbol_code", return_value=(
                    [(0x1000, 2, "q15_dot_scalar")], {0x1000: "ret"})):
            with self.assertRaisesRegex(ValueError, "Inputs differ"):
                RUNNER.measure(self.out, configuration(32, "strict"), self.out, "", "qemu", "demo")
        self.assertEqual(len(traces), 2)

    def test_svg_is_valid_and_labels_instruction_counts_not_hardware_speedup(self):
        rows = [{"workload": workload, "layout": "aligned", "kernel": kernel,
                 "guest_instructions": 200 if kernel == "scalar" else 100}
                for workload in ("dot", "fir") for kernel in ("scalar", "p")]
        config = dict(configuration(32, "hardware"), optimization="-O3")
        destination = self.out / "dsp.svg"
        REPORT.render({"build_configuration": config, "instruction_counts": rows},
                      demo_fixture(), destination)
        tree = ET.fromstring(destination.read_text())
        labels = " ".join(tree.itertext())
        self.assertEqual(labels.count("Hardware timing not measured."), 1)
        self.assertIn("Executed guest instructions", labels)
        self.assertNotIn("times faster", labels)
        self.assertNotIn("cycles per", labels)


if __name__ == "__main__":
    unittest.main()
