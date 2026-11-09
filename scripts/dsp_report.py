#!/usr/bin/env python3
"""Independent integer references and small SVG views for the Q15 examples."""

from html import escape


def require(condition, message):
    if not condition:
        raise ValueError(message)


def samples(values):
    require(isinstance(values, list), "Expected a sample array")
    require(all(type(value) is int and -32768 <= value <= 32767
                for value in values), "Sample outside signed Q15 range")
    return values


def integer(value):
    require(type(value) is int, "Expected an integer result")
    return value


def integers(values):
    require(isinstance(values, list), "Expected an integer array")
    return [integer(value) for value in values]


def quantize(raw):
    """Round Q30 once, nearest with ties away from zero, then clamp to Q15."""
    rounded = (abs(raw) + 16384) // 32768
    return max(-32768, min(32767, -rounded if raw < 0 else rounded))


def dot_reference(a, b):
    samples(a)
    samples(b)
    require(len(a) == len(b) <= 65536, "Invalid dot-product length")
    return sum(x * y for x, y in zip(a, b))


def fir_reference(coefficients, history, signal):
    """Natural causal order: h[0] multiplies the current input sample."""
    h, history, signal = map(samples, (coefficients, history, signal))
    require(1 <= len(h) <= 65536, "Invalid FIR tap count")
    require(len(history) == len(h) - 1, "Invalid FIR history length")
    raw = []
    for n in range(len(signal)):
        total = 0
        for j, coefficient in enumerate(h):
            index = n - j
            value = signal[index] if index >= 0 else history[len(history) + index]
            total += coefficient * value
        raw.append(total)
    return raw, [quantize(value) for value in raw]


def verify_trace(case):
    workload = case["workload"]
    require(case["kernel"] in ("scalar", "p"), "Invalid kernel")
    require(case["layout"] in ("aligned", "unaligned"), "Invalid layout")
    if workload == "dot":
        expected = dot_reference(case["a"], case["b"])
        require(len(case["a"]) == 1024, "Unexpected dot trace size")
        require(integer(case["count"]) == 1024, "Wrong dot trace metadata")
        require(integer(case["sum_q30"]) == expected, "Dot trace disagrees with Python")
        require(integer(case["q15"]) == quantize(expected), "Dot rounding mismatch")
        require(integer(case["checksum"]) == expected, "Wrong dot checksum")
        return expected
    require(workload == "fir", "Invalid workload")
    raw, expected = fir_reference(case["coefficients"], case["history"], case["input"])
    require(len(raw) == 64 and len(case["coefficients"]) == 32,
            "Unexpected FIR trace size")
    require(integer(case["taps"]) == 32 and integer(case["outputs"]) == 64,
            "Wrong FIR trace metadata")
    require(integers(case["raw_q30"]) == raw, "FIR trace raw sums disagree with Python")
    require(samples(case["output_q15"]) == expected, "FIR trace disagrees with Python")
    require(integer(case["checksum"]) == sum(expected), "Wrong FIR checksum")
    return expected


def verify_demo(demo):
    dot, fir = demo["dot"], demo["fir"]
    total = dot_reference(dot["a"], dot["b"])
    require(len(dot["a"]) == 17, "Unexpected dot demo length")
    require(integer(dot["sum_scalar_q30"]) == integer(dot["sum_p_q30"]) == total,
            "Dot demo disagrees with Python")
    raw, expected = fir_reference(fir["coefficients"], fir["history"], fir["input"])
    require(len(fir["coefficients"]) == 7 and len(expected) == 64,
            "Unexpected FIR demo size")
    require(samples(fir["scalar_q15"]) == samples(fir["p_q15"]) == expected,
            "FIR demo disagrees with Python")
    require(integers(fir["raw_q30"]) == raw, "FIR raw sums disagree with Python")
    return {"dot_terms": len(dot["a"]), "fir_outputs": len(expected),
            "coefficient_order": "h[0] multiplies the current input",
            "rounding": "nearest, ties away from zero; clamp after complete sum"}


def render(report, demo, destination):
    """No plotting dependency: emit vector graphics from validated numbers."""
    config = report["build_configuration"]
    width, height = 1100, 830
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#f5f7fb"/>']

    def text(x, y, value, size=18, color="#18334d"):
        parts.append(f'<text x="{x}" y="{y}" font-family="sans-serif" '
                     f'font-size="{size}" fill="{color}">{escape(str(value))}</text>')

    def line(x1, y1, x2, y2, color="#d5dde6"):
        parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}"/>')

    text(40, 45, f"RV{config['xlen']} P: Q15 dot product and FIR", 28)
    text(40, 77, f"{config['alignment']} alignment; {config['optimization']}; "
         "exact 64-bit accumulation", 17)
    for column, workload in enumerate(("dot", "fir")):
        x, y = 55 + 530 * column, 135
        rows = [row for row in report["instruction_counts"]
                if row["workload"] == workload and row["layout"] == "aligned"]
        require(len(rows) == 2, "Missing instruction chart data")
        text(x, y, "Dot: 1,024 terms" if workload == "dot" else "FIR: 32 taps, 64 outputs", 22)
        maximum = max(row["guest_instructions"] for row in rows)
        for index, row in enumerate(rows):
            by = y + 30 + index * 60
            count = row["guest_instructions"]
            bw = 315 * count / maximum
            color = "#ed8335" if row["kernel"] == "p" else "#486d91"
            text(x, by + 24, "P" if row["kernel"] == "p" else "Scalar", 17)
            parts.append(f'<rect x="{x+65}" y="{by}" width="{bw:.1f}" height="34" fill="{color}"/>')
            text(x + 73 + bw, by + 24, f"{count:,}", 17)
    text(40, 325, "Executed guest instructions, including kernel entry and return.", 17)
    text(40, 375, "FIR signal: input and verified Q15 output", 23)
    signal, filtered = demo["fir"]["input"], demo["fir"]["p_q15"]
    left, right, top, bottom = 80, 1045, 420, 700
    for value in (-32768, -16384, 0, 16384, 32767):
        y = top + (32767 - value) * (bottom - top) / 65535
        line(left, y, right, y)
        text(8, y + 5, value, 13)
    for values, color in ((signal, "#a8b7c7"), (filtered, "#ed8335")):
        points = " ".join(f"{left+i*(right-left)/max(1,len(values)-1):.2f},"
                          f"{top+(32767-value)*(bottom-top)/65535:.2f}"
                          for i, value in enumerate(values))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5"/>')
    text(80, 732, "Input", 17, "#70869b")
    text(175, 732, "FIR output", 17, "#c56824")
    text(850, 732, "Sample index", 15)
    text(40, 780, "Nearest rounding, ties away from zero; saturation after the complete dot product.", 17)
    text(40, 812, "Measurement: QEMU guest instructions. Hardware timing not measured.", 12)
    parts.append('</svg>')
    destination.write_text("\n".join(parts) + "\n")
