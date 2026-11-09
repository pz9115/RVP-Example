#!/usr/bin/env python3
"""Build, check and measure Q15 dot/FIR kernels; no hardware timing claims."""

from collections import Counter
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys

from demo_config import ROOT, configuration
from dsp_report import render, require, verify_demo, verify_trace


SUCCESS_FILES = ("result.json", "tests.json", "demo.json", "dsp.svg")


def clear_results(out):
    for name in SUCCESS_FILES:
        (out / name).unlink(missing_ok=True)


def run(command, destination=None, allow_failure=False):
    command = list(map(str, command))
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or "", error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        if destination is not None:
            destination.write_text(stdout + stderr)
        print(stdout, end="")
        print(stderr, end="", file=sys.stderr)
        raise
    if destination is not None:
        destination.write_text(completed.stdout + completed.stderr)
    if not allow_failure and completed.returncode:
        print(completed.stdout, end="")
        print(completed.stderr, end="", file=sys.stderr)
        completed.check_returncode()
    return completed


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def symbol_code(bindir, prefix, executable, name, symbols, out):
    functions = []
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[2] in ("T", "t"):
            if fields[3] == name or fields[3].startswith(name + "."):
                functions.append((int(fields[0], 16), int(fields[1], 16), fields[3]))
    require(any(symbol == name for _, _, symbol in functions), f"Missing {name}")
    instructions, operands, disassemblies = {}, {}, []
    for _, _, symbol in functions:
        dis = run([bindir / (prefix + "objdump"), "-d", "--disassemble=" + symbol,
                   executable]).stdout
        disassemblies.append(dis)
        for address, opcode, arguments in re.findall(
                r"^\s*([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)([^\n]*)", dis, re.M):
            require(opcode not in ("call", "tail", "jal", "jalr", "jr",
                                   "c.jal", "c.jalr", "c.jr"),
                    f"Out-of-line call/jump in {symbol}: {opcode}")
            require(not opcode.startswith("v"), "Unexpected RVV instruction")
            require(not (opcode.startswith("f") and not opcode.startswith("fence")),
                    "Unexpected floating-point instruction")
            instructions[int(address, 16)] = opcode
            operands[int(address, 16)] = arguments
    require(instructions, f"Empty disassembly for {name}")
    for pc, opcode in instructions.items():
        if opcode in ("j", "c.j", "c.beqz", "c.bnez") or re.fullmatch(
                r"b(?:eq|ne|ge|lt|le|gt)u?z?", opcode):
            target = re.search(r"(?:^|,)\s*([0-9a-f]+)\s*<", operands[pc])
            require(target is not None and int(target[1], 16) in instructions,
                    f"Branch leaves counted kernel: {name} at {pc:x}")
    (out / (name + ".dis")).write_text("\n".join(disassemblies))
    return functions, instructions


def measure(out, config, bindir, prefix, qemu, executable):
    symbols = run([bindir / (prefix + "nm"), "-S", "--defined-only", executable]).stdout
    rows, footprint, cases = [], {}, {}
    for workload in ("dot", "fir"):
        for kernel in ("scalar", "p"):
            name = f"q15_{workload}_{kernel}"
            functions, instructions = symbol_code(bindir, prefix, executable,
                                                  name, symbols, out)
            frames = []
            for line in (out / f"q15-{kernel}.su").read_text().splitlines():
                location, size, kind = line.split("\t")
                function = location.rsplit(":", 1)[-1]
                if function == name or function.startswith(name + "."):
                    require(kind == "static", f"Dynamic stack frame in {name}")
                    frames.append(int(size))
            require(frames, f"Missing stack usage for {name}")
            footprint[name] = {"text_bytes": sum(size for _, size, _ in functions),
                               "static_frame_bytes": max(frames)}
            entry = next(start for start, _, symbol in functions if symbol == name)
            ranges = ",".join(f"0x{start:x}+0x{size:x}" for start, size, _ in functions)
            for layout in ("aligned", "unaligned"):
                runs = []
                for repetition in range(2):
                    stem = f"{workload}-{kernel}-{layout}-{repetition}"
                    trace = out / (stem + ".log")
                    command = [qemu, "-R", "512M", "-cpu", config["qemu_cpu"],
                               "-one-insn-per-tb", "-d", "exec,nochain",
                               "-dfilter", ranges, "-D", trace, executable,
                               "--trace", workload, kernel, layout]
                    case = json.loads(run(command).stdout)
                    require((case["workload"], case["kernel"], case["layout"])
                            == (workload, kernel, layout), "Wrong trace fixture")
                    expected = verify_trace(case)
                    data_keys = (("a", "b") if workload == "dot"
                                 else ("coefficients", "history", "input"))
                    fixture = [case[key] for key in data_keys]
                    require(cases.setdefault(workload, fixture) == fixture,
                            "Inputs differ across repetitions, kernels or alignments")
                    save_json(out / (stem + ".json"), case)
                    pcs = []
                    with trace.open() as stream:
                        for line in stream:
                            if not line.startswith("Trace "):
                                continue
                            match = re.search(r"\[[0-9a-f]+/([0-9a-f]+)/", line)
                            require(match is not None, "Unrecognized QEMU trace line")
                            pc = int(match[1], 16)
                            require(pc in instructions, "Unexpected PC in filtered trace")
                            pcs.append(pc)
                    require(pcs and pcs[0] == entry and instructions[pcs[-1]] == "ret",
                            f"Incomplete trace for {name}")
                    counts = Counter(instructions[pc] for pc in pcs)
                    require(pcs.count(entry) == 1 and counts["ret"] == 1,
                            "Trace must contain exactly one kernel call")
                    packed = sum(value for op, value in counts.items()
                                 if re.fullmatch(r"pm(?:2w|4)add[a]?\.h", op))
                    products = 1024 if workload == "dot" else 32 * 64
                    expected_packed = products // (config["xlen"] // 16) if kernel == "p" else 0
                    require(packed == expected_packed, f"Unexpected packed MAC count: {counts}")
                    if kernel == "p" and config["alignment"] == "hardware":
                        require(not any(counts[op] for op in ("lb", "lbu", "lh", "lhu")),
                                "Split loads in a full-width hardware-mode packed trace")
                        wide = counts["lw"] + counts["lwu"] if config["xlen"] == 32 else counts["ld"]
                        require(wide >= 2 * expected_packed, "Missing native packed loads")
                    if kernel == "scalar":
                        require(not any(op.startswith("p") for op in counts),
                                "P instruction in scalar baseline")
                    runs.append({"guest_instructions": len(pcs), "opcodes": dict(counts),
                                 "result": expected, "trace": trace.name,
                                 "command": list(map(str, command))})
                for field in ("guest_instructions", "opcodes", "result"):
                    require(runs[0][field] == runs[1][field], "Non-repeatable kernel trace")
                rows.append({"workload": workload, "kernel": kernel, "layout": layout,
                             "guest_instructions": runs[0]["guest_instructions"], "runs": runs})
                print(f"RV{config['xlen']} {workload} {kernel} {layout}: "
                      f"{runs[0]['guest_instructions']} guest instructions", flush=True)
    return rows, footprint


def negative_controls(qemu, config, executable):
    cpu = config["qemu_cpu"].replace("x-p=true", "x-p=false")
    runner = [qemu, "-R", "512M", "-cpu", cpu, executable, "--trace"]
    for workload in ("dot", "fir"):
        scalar = json.loads(run([*runner, workload, "scalar", "aligned"]).stdout)
        require((scalar["workload"], scalar["kernel"], scalar["layout"])
                == (workload, "scalar", "aligned"), "Wrong P-disabled scalar fixture")
        verify_trace(scalar)
        packed = run([*runner, workload, "p", "aligned"], allow_failure=True)
        require(packed.returncode in (-signal.SIGILL, 128 + signal.SIGILL),
                f"P-disabled {workload} did not raise SIGILL: {packed.returncode}")
    return {"scalar_without_p": "pass", "packed_without_p": "SIGILL"}


def check_alignment(out, config, gcc, qemu):
    """Run the actual kernel objects without a potentially unaligned libc."""
    source = ROOT / "examples/rvp-q15-dsp/tests/alignment.c"
    commands, binaries = [], {}
    for kernel in ("scalar", "p"):
        executable = out / f"alignment-{kernel}"
        command = [gcc, "-O2", "-mtune=size", "-mstrict-align",
                   "-march=" + config["baseline_arch"], "-mabi=" + config["abi"],
                   "-fno-tree-vectorize", "-fno-tree-slp-vectorize", "-ffreestanding",
                   "-fno-pie", "-fno-stack-protector", "-fno-lto", "-nostdlib",
                   "-static", "-no-pie", "-Wl,-e,_start",
                   "-DDOT_KERNEL=q15_dot_" + kernel, "-DFIR_KERNEL=q15_fir_" + kernel,
                   source, out / f"q15-{kernel}.o", "-o", executable]
        run(command, out / f"alignment-{kernel}-build.log")
        commands.append(list(map(str, command)))
        binaries[kernel] = executable
    cpu = ",".join(part for part in config["qemu_cpu"].split(",")
                   if not part.startswith("zicclsm="))
    for kernel, supported in (("scalar", False), ("p", True), ("p", False)):
        command = [qemu, "-R", "512M", "-cpu",
                   cpu + ",zicclsm=" + ("true" if supported else "false"), binaries[kernel]]
        completed = run(command, allow_failure=True)
        fault = kernel == "p" and not supported and config["alignment"] == "hardware"
        require(completed.returncode in (-signal.SIGBUS, 128 + signal.SIGBUS) if fault
                else completed.returncode == 0,
                f"Unexpected alignment-probe result: {kernel}, {supported}, {completed.returncode}")
        commands.append({"command": list(map(str, command)), "returncode": completed.returncode,
                         "stdout": completed.stdout, "stderr": completed.stderr})
    return {"scope": "Libc-free probe of the measured dot and FIR objects",
            "scalar_with_misaligned_traps": "pass", "packed_with_misaligned_support": "pass",
            "packed_with_misaligned_traps": "SIGBUS" if config["alignment"] == "hardware" else "pass",
            "commands": commands}


def build_and_check(out, config):
    out.mkdir(parents=True, exist_ok=True)
    save_json(out / "build-config.json", config)
    run([sys.executable, ROOT / "scripts/check-host.py", "--xlen", config["xlen"],
         "--output", out / "host.json"], out / "host.log")
    bindir = ROOT / config["toolchain_directory"] / "bin"
    prefix = config["target"] + "-"
    gcc = bindir / (prefix + "gcc")
    qemu = ROOT / "qemu/bin" / f"qemu-riscv{config['xlen']}"
    run(["make", "-C", ROOT / "examples/rvp-q15-dsp", "-j2", "-B", f"BUILD={out}",
         f"CC={gcc}", f"XLEN={config['xlen']}", f"ALIGNMENT={config['alignment']}",
         f"OPTFLAGS={config['optimization']}"], out / "build.log")
    executable = out / "q15-demo"
    for name in ("q15-p.o", "q15-scalar.o", "q15-demo"):
        attributes = run([bindir / (prefix + "readelf"), "-A", out / name]).stdout
        (out / (name + ".attributes")).write_text(attributes)
        require(f"rv{config['xlen']}i" in attributes, "Wrong object architecture")
        require(("_p0p6" in attributes) == (name != "q15-scalar.o"), "Wrong P version attributes")
        if config["xlen"] == 32:
            require(not re.search(r"_(?:f|d|v)\d+p\d+", attributes), "Unexpected RV32 FP/RVV ISA")
    runner = [qemu, "-R", "512M", "-cpu", config["qemu_cpu"], executable]
    tests = json.loads(run([*runner, "--test"]).stdout)
    require(type(tests["failures"]) is int and tests["failures"] == 0
            and type(tests["cases"]) is int and tests["cases"] > 0, "C tests failed")
    save_json(out / "tests.json", tests)
    demo = json.loads(run([*runner, "--demo"]).stdout)
    oracle = verify_demo(demo)
    save_json(out / "demo.json", demo)
    alignment = check_alignment(out, config, gcc, qemu)
    rows, footprint = measure(out, config, bindir, prefix, qemu, executable)
    negative = negative_controls(qemu, config, executable)
    report = {"build_configuration": config, "tests": tests, "python_oracle": oracle,
              "instruction_counts": rows, "kernel_footprint": footprint,
              "negative_controls": negative,
              "alignment_checks": alignment,
              "tested_versions": json.loads((ROOT / "VERSION.json").read_text())["versions"],
              "metric": "Executed guest kernel instructions, including return",
              "method": "QEMU one instruction per TB; no chaining; symbol filter; two repeats",
              "scope": "Prepared data only; excludes history/coefficients setup and harness",
              "stack_scope": "Static kernel frames, not whole-program maximum stack",
              "hardware_speedup": None,
              "warning": "Not hardware cycles, memory latency, throughput or speedup"}
    render(report, demo, out / "dsp.svg")
    save_json(out / "result.json", report)
    print(f"PASS: {tests['cases']} C checks; independent Python dot/FIR reference", flush=True)
    print(f"Results: {out / 'result.json'}", flush=True)


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    limit = 3 * 1024 ** 3
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (min(limit, soft) if soft != -1 else limit, hard))
    supplied = os.environ.get("OUT")
    require(supplied != "", "OUT must not be empty")
    out = Path(supplied).resolve() if supplied is not None else None
    try:
        if out is not None:
            clear_results(out)
        config = configuration(int(os.environ.get("XLEN", "32")),
                               os.environ.get("ALIGNMENT", "hardware"))
        if out is None:
            out = ROOT / "build" / f"dsp-rv{config['xlen']}-{config['alignment']}"
            clear_results(out)
        require(not any(c.isspace() for c in str(ROOT) + str(out)),
                "Use project and output paths without whitespace")
        require(not os.environ.get("ALIGNFLAGS"), "Select ALIGNMENT instead of ALIGNFLAGS")
        config["optimization"] = os.environ.get("OPTFLAGS", "-O3")
        require(config["optimization"] in ("-O2", "-O3", "-Os"), "Use OPTFLAGS=-O2|-O3|-Os")
        build_and_check(out, config)
    except BaseException:
        if out is not None:
            clear_results(out)
        raise


if __name__ == "__main__":
    main()
