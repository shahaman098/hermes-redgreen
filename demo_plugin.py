#!/usr/bin/env python3
"""Drive the real Hermes plugin manager through a scripted session.

This is the demo behind the video. It needs a Hermes checkout with its Python
environment (the interpreter that can import ``hermes_cli``):

    ~/.hermes/hermes-agent-jobos/venv/bin/python demo_plugin.py

No model is called. The scripted "agent" performs the same writes and test runs
a model would, and every RedGreen decision comes from the plugin's real hooks.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
BOLD, DIM, RED, GREEN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"


def pause(seconds: float) -> None:
    if os.environ.get("REDGREEN_DEMO_SLOW"):
        time.sleep(seconds)


def say(prefix: str, text: str, color: str = "") -> None:
    print(f"{color}{prefix}{RESET} {text}")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def pytest(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        "python3 -m pytest -q", shell=True, check=False, cwd=repo, capture_output=True, text=True
    )


def main() -> int:
    hermes_home = Path(tempfile.mkdtemp(prefix="redgreen-home-"))
    repo = Path(tempfile.mkdtemp(prefix="redgreen-plugin-demo-")) / "shopcart"
    repo.mkdir()
    plugins = hermes_home / "plugins"
    plugins.mkdir()
    shutil.copytree(REPO, plugins / "redgreen", ignore=shutil.ignore_patterns(".git", "__pycache__", "demo"))

    os.environ["HERMES_HOME"] = str(hermes_home)
    os.environ["REDGREEN_TIMEOUT"] = "30"

    sys.path.insert(0, os.environ.get("HERMES_CHECKOUT", str(Path.home() / ".hermes/hermes-agent-jobos")))
    import yaml

    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump({"plugins": {"enabled": ["redgreen"]}}), encoding="utf-8"
    )
    from hermes_cli.plugins import PluginManager  # type: ignore

    manager = PluginManager()
    manager.discover_and_load()
    if "redgreen" not in getattr(manager, "_plugins", {}):
        print("RedGreen did not load. Run this with the Hermes Python environment.")
        return 1

    session = {"session_id": "redgreen-demo"}

    def fire(name: str, **payload):
        return manager.invoke_hook(name, **session, **payload)

    print()
    print(f"{BOLD}REDGREEN{RESET} {DIM}real Hermes plugin hooks, scripted agent{RESET}")
    print()

    git(repo, "init", "-q")
    git(repo, "config", "user.email", "demo@redgreen.local")
    git(repo, "config", "user.name", "RedGreen Demo")
    write(
        repo / "pricing.py",
        """
        def apply_discount(subtotal, percent=20.0, cap=50.0):
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

    say("[hermes]", "agent writes pricing.py")
    fire("pre_tool_call", tool_name="write_file", args={"path": str(repo / "pricing.py")})
    write(
        repo / "pricing.py",
        """
        def apply_discount(subtotal, percent=20.0, cap=50.0):
            discount = min(subtotal * (percent / 100.0), cap)
            return round(subtotal - discount, 2)
        """,
    )
    fire(
        "post_tool_call",
        tool_name="write_file",
        args={"path": str(repo / "pricing.py")},
        result='{"output": "ok", "exit_code": 0}',
    )

    say("[hermes]", "agent writes a test and runs it")
    path = repo / "tests" / "test_pricing.py"
    path.write_text(
        path.read_text()
        + "\n\ndef test_discount_is_a_number():\n    assert apply_discount(100) == 80.0\n",
        encoding="utf-8",
    )
    fire(
        "post_tool_call",
        tool_name="write_file",
        args={"path": str(path)},
        result='{"output": "ok", "exit_code": 0}',
    )
    run = pytest(repo)
    fire(
        "post_tool_call",
        tool_name="terminal",
        args={"command": "python3 -m pytest -q", "cwd": str(repo)},
        result=json.dumps({"output": run.stdout, "exit_code": run.returncode}),
    )
    say("[agent]", f"{run.stdout.strip().splitlines()[-1]}")
    say("[agent]", f'{BOLD}"Fixed. All tests pass."{RESET}')
    pause(2.0)

    vetoes = fire(
        "pre_verify",
        changed_paths=[str(repo / "pricing.py"), str(path)],
        attempt=0,
        final_response="Fixed. All tests pass.",
        coding=True,
    )
    message = vetoes[0]["message"] if vetoes else "no veto"
    print()
    for line in message.splitlines():
        print(f"  {RED}{line}{RESET}" if line.startswith("⛔") else f"  {line}")
    print()
    pause(4.0)

    say("[agent]", "agent adds a regression test that asserts the cap")
    path.write_text(
        path.read_text()
        + "\n\ndef test_discount_is_capped_at_fifty():\n    assert apply_discount(1000) == 950.0\n",
        encoding="utf-8",
    )
    fire(
        "post_tool_call",
        tool_name="write_file",
        args={"path": str(path)},
        result='{"output": "ok", "exit_code": 0}',
    )
    run = pytest(repo)
    fire(
        "post_tool_call",
        tool_name="terminal",
        args={"command": "python3 -m pytest -q", "cwd": str(repo)},
        result=json.dumps({"output": run.stdout, "exit_code": run.returncode}),
    )
    say("[agent]", f"{run.stdout.strip().splitlines()[-1]}")
    say("[agent]", f'{BOLD}"Fixed. All tests pass."{RESET}')
    pause(2.0)

    vetoes = fire(
        "pre_verify",
        changed_paths=[str(repo / "pricing.py"), str(path)],
        attempt=1,
        final_response="Fixed. All tests pass.",
        coding=True,
    )
    print()
    if vetoes:
        print(f"  {YELLOW}still blocked: {vetoes[0]['message'].splitlines()[0]}{RESET}")
        return 1
    say("[redgreen]", f"{GREEN}PROVEN{RESET} red without the change, green with it")

    final = fire("transform_llm_output", response_text="Fixed. All tests pass.")
    print()
    print(f"  {final[0] if final else ''}")
    print()
    pause(5.0)
    say("[redgreen]", f"state: {hermes_home / 'plugin-data' / 'redgreen'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
