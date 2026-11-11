#!/usr/bin/env python3
"""Reproducible Falsify demo. No model, no network, no API key.

It creates a small git repository with a real bug, plays a scripted agent that
"fixes" it with a test that cannot fail, and then runs the same engine the
Hermes plugin uses to show the veto and the proof.

    python3 demo.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core
from report import STATUS_COPY, render_certificate, render_terminal_certificate

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"


def say(prefix: str, text: str, color: str = "") -> None:
    print(f"{color}{prefix}{RESET} {text}")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def pytest(repo: Path) -> core.RunResult:
    return core.run_command("python3 -m pytest -q", repo, timeout=30)


def main() -> int:
    print()
    print(f"{BOLD}FALSIFY{RESET}  {DIM}a test only proves a fix when it fails without the fix{RESET}")
    print()

    demo_root = os.environ.get("FALSIFY_DEMO_DIR")
    with tempfile.TemporaryDirectory(prefix="falsify-demo-") as tmp:
        repo = Path(demo_root) if demo_root else Path(tmp) / "shopcart"
        if demo_root:
            shutil.rmtree(repo, ignore_errors=True)
        repo.mkdir(parents=True)
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "demo@falsify.local")
        git(repo, "config", "user.name", "Falsify Demo")

        write(
            repo / "pricing.py",
            """
            def apply_discount(subtotal, percent=20.0, cap=50.0):
                \"\"\"Return the total after a percentage discount.\"\"\"
                discount = subtotal * (percent / 100.0)
                return round(subtotal - discount, 2)
            """,
        )
        write(
            repo / "tests" / "test_pricing.py",
            """
            from pricing import apply_discount

            def test_small_order():
                assert apply_discount(40) == 32.0

            def test_zero_percent():
                assert apply_discount(80, percent=0) == 80.0
            """,
        )
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "pricing without the discount cap")
        baseline, baseline_kind = core.capture_baseline(repo)

        say("[repo]", "shopcart · 1 module · 2 tests", DIM)
        say("[baseline]", f"{baseline[:10]} ({baseline_kind})", DIM)
        print()

        say("[agent]", "User: orders over 100 should get 20% off, capped at 50. Fix it.")
        write(
            repo / "pricing.py",
            """
            def apply_discount(subtotal, percent=20.0, cap=50.0):
                \"\"\"Return the total after a percentage discount, capped at cap.\"\"\"
                discount = min(subtotal * (percent / 100.0), cap)
                return round(subtotal - discount, 2)
            """,
        )
        write(
            repo / "tests" / "test_pricing.py",
            """
            from pricing import apply_discount

            def test_small_order():
                assert apply_discount(40) == 32.0

            def test_zero_percent():
                assert apply_discount(80, percent=0) == 80.0

            def test_discount_is_a_number():
                assert apply_discount(100) == 80.0
            """,
        )
        run = pytest(repo)
        say("[agent]", f"ran `python3 -m pytest -q` -> {run.summary}")
        say("[agent]", f"{BOLD}\"Fixed. All tests pass.\"{RESET}")
        print()

        verdict = core.verify(
            repo=repo,
            baseline_sha=baseline,
            baseline_kind=baseline_kind,
            command="python3 -m pytest -q",
            reported=run,
            timeout=30,
        )
        say("[falsify]", f"{YELLOW}{STATUS_COPY[verdict.status][0]}{RESET} · {verdict.reason}")
        print()
        print(textwrap.indent(render_terminal_certificate(verdict), "  "))
        print()
        say("[falsify]", "The new test passes without the fix too. It proves nothing.")
        print()

        say("[agent]", "Fine: add a test that actually describes the missing cap.")
        write(
            repo / "tests" / "test_pricing.py",
            """
            from pricing import apply_discount

            def test_small_order():
                assert apply_discount(40) == 32.0

            def test_zero_percent():
                assert apply_discount(80, percent=0) == 80.0

            def test_discount_is_a_number():
                assert apply_discount(100) == 80.0

            def test_discount_is_capped_at_fifty():
                assert apply_discount(1000) == 950.0
            """,
        )
        run = pytest(repo)
        say("[agent]", f"ran `python3 -m pytest -q` -> {run.summary}")
        say("[agent]", f"{BOLD}\"Fixed. All tests pass.\"{RESET}")
        print()

        verdict = core.verify(
            repo=repo,
            baseline_sha=baseline,
            baseline_kind=baseline_kind,
            command="python3 -m pytest -q",
            reported=run,
            timeout=30,
        )
        say("[falsify]", f"{GREEN}{STATUS_COPY[verdict.status][0]}{RESET} · {verdict.reason}")
        print()
        print(textwrap.indent(render_terminal_certificate(verdict), "  "))
        print()

        certificate = Path(__file__).resolve().parent / "demo-certificate.html"
        certificate.write_text(render_certificate(verdict, diff_stat=""), encoding="utf-8")
        say("[falsify]", f"certificate: {certificate}")
        print()
        print(f"{BOLD}Verified: red without the fix ({verdict.before.summary}), green with it ({verdict.current.summary}).{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
