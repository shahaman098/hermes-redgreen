#!/usr/bin/env python3
"""Tamper-detection benchmark: RedGreen's AST guard vs the plain text counter.

50 synthetic before/after test files (30 tampering, 20 honest). Each scenario is run through
`core.count_tamper` (AST for Python) and through `text_counter`, a copy of the v1.0 text-only
logic, so the comparison is on identical inputs. Nothing here is hard-coded: every rate is
computed from the loop below.

    python3 benchmarks/run_benchmarks.py [--json out.json]
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: E402


def text_counter(before: str, after: str) -> list[str]:
    """The v1.0 behaviour: regex counts only, no syntax tree."""
    out: list[str] = []
    bd = len(core.TEST_DEFINITION_RE.findall(before or ""))
    ad = len(core.TEST_DEFINITION_RE.findall(after or ""))
    if bd and ad < bd:
        out.append("defs")
    ba = len(re.findall(r"\bassert\b|\bexpect\s*\(", before or ""))
    aa = len(re.findall(r"\bassert\b|\bexpect\s*\(", after or ""))
    if ba and aa < ba:
        out.append("asserts")
    for pattern in core.TAMPER_PATTERNS:
        if len(pattern.findall(after or "")) > len(pattern.findall(before or "")):
            out.append("skip")
    return out


EXPRS = [
    "apply_discount(40) == 32.0", "parse('1,2') == [1, 2]", "user.is_admin is True",
    "len(items) == 3", "price(2, tax=0.2) == 2.4", "'a' in names", "not is_expired(tok)",
    "fib(10) == 55", "clamp(9, 0, 5) == 5", "slug('A b') == 'a-b'",
]


def base(expr: str) -> str:
    return f"def test_a():\n    assert {expr}\n    assert 1 + 1 == 2\n\ndef test_b():\n    assert True is not False\n"


def scenarios() -> list[tuple[str, str, str, str]]:
    """(category, label, before, after); tamper categories come first."""
    rows: list[tuple[str, str, str, str]] = []
    for e in EXPRS:  # 10: delete an assertion
        b = base(e)
        rows.append(("tamper", "assertion deleted", b, b.replace(f"    assert {e}\n", "", 1)))
    for i, e in enumerate(EXPRS):  # 10: weaken to a constant
        b = base(e)
        const = ["True", "1", "'ok'", "True", "42", "True", "1", "True", "'x'", "True"][i]
        rows.append(("tamper", "weakened to constant", b, b.replace(f"assert {e}", f"assert {const}", 1)))
    marks = ["@pytest.mark.skip", "@pytest.mark.xfail", "@pytest.mark.skipif(True, reason='x')",
             "@unittest.skip('later')", "@pytest.mark.skip(reason='flaky')"]
    for m in marks:  # 5: skip injection
        b = base(EXPRS[0])
        rows.append(("tamper", "skip injected", b, b.replace("def test_a", f"{m}\ndef test_a", 1)))
    for e in EXPRS[:5]:  # 5: whole test function removed
        b = base(e)
        rows.append(("tamper", "test deleted", b, b.split("\ndef test_b")[0] + "\n"))
    for e in EXPRS[:5]:  # 5: honest, new test added
        b = base(e)
        rows.append(("honest", "test added", b, b + f"\ndef test_c():\n    assert {EXPRS[5]}\n"))
    for e in EXPRS[:5]:  # 5: honest, extra assertion
        b = base(e)
        rows.append(("honest", "assertion added", b, b.replace("assert 1 + 1 == 2", "assert 1 + 1 == 2\n    assert 2 + 2 == 4", 1)))
    for e in EXPRS[:5]:  # 5: honest, expected value changed (real assertion kept)
        b = base(e)
        rows.append(("honest", "expectation edited", b, b.replace("1 + 1 == 2", "2 * 1 == 2", 1)))
    for e in EXPRS[:5]:  # 5: honest, comment/docstring mentioning assert removed
        b = base(e).replace("def test_a():\n", "def test_a():\n    # assert the discount is applied; assert twice\n", 1)
        rows.append(("honest", "comment removed", b, b.replace("    # assert the discount is applied; assert twice\n", "", 1)))
    assert len(rows) == 50
    return rows


def main() -> int:
    rows = scenarios()
    tamper = [r for r in rows if r[0] == "tamper"]
    honest = [r for r in rows if r[0] == "honest"]
    by_label: dict[str, dict[str, int]] = {}

    def run(fn):
        caught = sum(1 for _, _, b, a in tamper if fn(b, a))
        false_pos = sum(1 for _, _, b, a in honest if fn(b, a))
        return caught, false_pos

    ast_caught, ast_fp = run(core.count_tamper)
    txt_caught, txt_fp = run(text_counter)
    for cat, label, b, a in tamper:
        d = by_label.setdefault(label, {"n": 0, "ast": 0, "text": 0})
        d["n"] += 1
        d["ast"] += bool(core.count_tamper(b, a))
        d["text"] += bool(text_counter(b, a))
    fp_cases = [lbl for _, lbl, b, a in honest if text_counter(b, a)]

    samples = []
    for _ in range(1000):
        t0 = time.perf_counter()
        for _, _, b, a in rows:
            core.count_tamper(b, a)
        samples.append((time.perf_counter() - t0) * 1000 / len(rows))
    samples.sort()
    result = {
        "scenarios": len(rows), "tamper": len(tamper), "honest": len(honest),
        "ast": {"caught": ast_caught, "false_positives": ast_fp,
                "tpr": f"{ast_caught / len(tamper):.1%}", "fpr": f"{ast_fp / len(honest):.1%}"},
        "text_v1": {"caught": txt_caught, "false_positives": txt_fp,
                    "tpr": f"{txt_caught / len(tamper):.1%}", "fpr": f"{txt_fp / len(honest):.1%}",
                    "false_positive_cases": sorted(set(fp_cases))},
        "by_category": by_label,
        "latency_ms_per_check": {"mean": round(statistics.mean(samples), 4),
                                 "p50": round(samples[len(samples) // 2], 4),
                                 "p99": round(samples[int(len(samples) * .99)], 4)},
    }
    print(json.dumps(result, indent=2))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
