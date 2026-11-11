"""Shared runtime: settings, session helpers and the human-facing verdict text."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

try:  # Hermes loads plugins as a namespace package.
    from . import core
    from .report import render_certificate
except ImportError:  # Direct import while testing.
    import core  # type: ignore
    from report import render_certificate  # type: ignore


MUTATION_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "patch",
        "str_replace_editor",
        "apply_patch",
        "delete_file",
    }
)

TOOL_NAMES = frozenset(
    {
        "redgreen_check",
        "redgreen_status",
        "redgreen_certificate",
        "redgreen_history",
        "redgreen_explain",
    }
)

STORE = core.SessionStore()


def session_id_from(**kwargs: Any) -> str:
    for key in ("session_id", "conversation_id", "task_id"):
        value = kwargs.get(key)
        if value:
            return str(value)
    return "default"


def settings() -> dict[str, Any]:
    def number(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except (TypeError, ValueError):
            return default

    return {
        "timeout": max(5.0, number("REDGREEN_TIMEOUT", 120.0)),
        "mode": os.environ.get("REDGREEN_MODE", "fix").strip().lower() or "fix",
        "stamp": os.environ.get("REDGREEN_STAMP", "1").strip() not in {"0", "false", "no"},
    }


def resolve_path(value: str) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def path_from_args(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "filename", "destination", "target", "file"):
        value = args.get(key)
        if value:
            return str(value)
    # V4A multi-file patches carry their paths inside the patch text.
    patch_text = args.get("patch")
    if isinstance(patch_text, str):
        match = re.search(
            r"^\*\*\*\s+(?:Update|Add|Delete)\s+File:\s*(.+)$",
            patch_text,
            re.MULTILINE,
        )
        if match:
            return match.group(1).strip()
    return ""


def infer_repo(*candidates: str) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        root = core.find_repo_root(resolve_path(candidate))
        if root:
            return root
    return core.find_repo_root(Path.cwd())


def parse_tool_result(result: Any) -> tuple[int | None, str]:
    """Return (exit_code, output) from Hermes's terminal result payload."""
    text = result if isinstance(result, str) else json.dumps(result)
    exit_code: int | None = None
    output = text
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        for key in ("exit_code", "returncode", "code"):
            value = payload.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                exit_code = int(value)
                break
            if isinstance(value, str) and value.strip().lstrip("-").isdigit():
                exit_code = int(value.strip())
                break
        for key in ("output", "stdout", "result", "text"):
            value = payload.get(key)
            if isinstance(value, str):
                output = value
                break
        stderr = payload.get("stderr")
        if isinstance(stderr, str) and stderr.strip():
            output = output + "\n" + stderr
    if exit_code is None:
        match = re.search(r"exit\s*code[:\s]+(-?\d+)", text, re.IGNORECASE)
        if match:
            exit_code = int(match.group(1))
    return exit_code, output


def record_test_run(record: core.SessionRecord, command: str, cwd: str, exit_code: int | None, output: str) -> None:
    record.runs.append(
        {
            "command": command,
            "cwd": cwd,
            "exit_code": exit_code,
            "output": output[-core.MAX_OUTPUT_CHARS:],
            "output_digest": core.hash_text(output),
            "duration_ms": 0,
            "ran_at": time.time(),
        }
    )
    # Keep the JSON bounded; the last 50 runs are enough to reconstruct a turn.
    record.runs = record.runs[-50:]


def command_from_message(message: str) -> str:
    """Find a test command the agent mentioned but may not have run."""
    for block in re.findall(r"`([^`\n]+)`", message or ""):
        if core.is_test_command(block):
            return block.strip()
    for line in (message or "").splitlines():
        if core.is_test_command(line) and len(line) < 300:
            return line.strip().strip("`")
    return ""


def prove(
    record: core.SessionRecord,
    *,
    command: str,
    timeout: float,
    mode: str,
) -> core.Verdict:
    repo = Path(record.repo_root) if record.repo_root else None
    if repo is None or not record.baseline_sha:
        return core.Verdict(
            status="no_baseline",
            reason=(
                "RedGreen has no pre-change snapshot for this session. The plugin can "
                "only prove a fix when it saw the change happen inside a git repository."
            ),
            command=command,
            repo_root=record.repo_root or "",
            baseline_sha=record.baseline_sha or "",
            baseline_kind=record.baseline_kind,
        ).finalize()

    verdict = core.verify(
        repo=repo,
        baseline_sha=record.baseline_sha,
        baseline_kind=record.baseline_kind,
        command=command,
        reported=record.last_reported_run(),
        timeout=timeout,
        mode=mode,
    )
    record.last_verdict = verdict.to_dict()
    record.verified_at = time.time()
    record.tree_signature = core.tree_signature(repo)
    return verdict


def certificate_path_for(verdict: core.Verdict) -> Path | None:
    if not verdict.certificate_id:
        return None
    path = STORE.certificates_dir / f"{verdict.certificate_id[:16]}.html"
    return path if path.exists() else None


def certificate_for(record: core.SessionRecord, verdict: core.Verdict) -> Path:
    report_repo = verdict.repo_root or record.repo_root or ""
    diff_stat = ""
    if report_repo and verdict.baseline_sha:
        try:
            result = core._git(
                Path(report_repo), "diff", "--stat", verdict.baseline_sha, "--"
            )
            diff_stat = result.stdout.strip() if result.returncode == 0 else ""
        except Exception:  # noqa: BLE001 - report generation is best effort
            diff_stat = ""
    html = render_certificate(verdict, diff_stat=diff_stat)
    path = STORE.save_certificate(verdict, html)
    record.last_verdict = verdict.to_dict()
    return path


def display_certificate(certificate: Path | None) -> str:
    if certificate is None:
        return ""
    return f"certificates/{certificate.name}"


def verdict_headline(verdict: core.Verdict) -> str:
    labels = {
        "proven": "PROVEN",
        "unproven_no_test": "UNPROVEN",
        "unproven_weak": "UNPROVEN",
        "unproven_tamper": "TAMPERED",
        "unproven_import_error": "UNPROVEN",
        "failing_now": "NOT DONE",
        "fabricated": "FABRICATED",
        "no_command": "UNPROVEN",
        "no_baseline": "UNPROVEN",
        "before_unrelated_failure": "UNPROVEN",
        "timeout": "INCONCLUSIVE",
        "unproven_behavior_changed": "UNPROVEN",
        "pending": "PENDING",
    }
    return labels.get(verdict.status, verdict.status.upper())


def _run_line(label: str, run: core.RunResult | None) -> str:
    if run is None:
        return f"  {label:<11} (not run)"
    state = "green" if run.green else "red"
    exit_text = "timeout" if run.timed_out else f"exit {run.exit_code}"
    return f"  {label:<11} {state:<5}  {exit_text:<9}  {run.summary}"


def veto_message(verdict: core.Verdict, certificate: Path | None = None) -> str:
    """The message the model reads when it is not allowed to finish."""
    before = verdict.before
    current = verdict.current
    lines = [f"⛔ RedGreen: {verdict_headline(verdict)}. You may not call this done yet.", ""]
    lines.append(f"Negative control: `{verdict.command or 'no command'}`")
    if current is not None:
        lines.append(_run_line("with change", current))
    if before is not None:
        lines.append(_run_line("without", before))
    if verdict.failed_before:
        lines.append(f"  fails before: {', '.join(verdict.failed_before[:3])}")
    lines.append("")
    lines.append(verdict.reason)
    lines.append("")

    if verdict.status in {"unproven_no_test", "unproven_weak"}:
        lines.append(
            "Write a test that fails without the fix and passes with it, then run it. "
            "RedGreen re-runs both sides."
        )
    elif verdict.status == "unproven_tamper":
        lines.append(
            "Restore the assertions, skipped tests or deleted cases you changed. A "
            "weakened test cannot prove anything, even if it goes red."
        )
    elif verdict.status == "unproven_import_error":
        lines.append(
            "Write a test that imports the code that exists before your change and "
            "fails on an assertion about the old behavior. An import error only proves "
            "the code was absent."
        )
    elif verdict.status == "failing_now":
        lines.append("Fix the failure, then run the command again.")
    elif verdict.status == "fabricated":
        lines.append(
            "Run the command for real. RedGreen only accepts a result it reproduced "
            "itself."
        )
    elif verdict.status == "no_command":
        lines.append(
            "Run a real test command (pytest, npm test, cargo test, go test, ...) that "
            "targets the changed behavior, then finish."
        )
    elif verdict.status == "timeout":
        lines.append(
            "Run the targeted test instead of the full suite, or set REDGREEN_TIMEOUT "
            "to a larger value."
        )
    elif verdict.status == "no_baseline":
        lines.append(
            "Make the change inside a git repository so RedGreen can reconstruct the "
            "pre-change tree, or call redgreen_check with a command after committing "
            "the baseline."
        )
    if certificate is not None:
        lines.append("")
        lines.append(f"Certificate: {display_certificate(certificate)}")
    return "\n".join(lines)


def proof_badge(verdict: core.Verdict, certificate: Path | None) -> str:
    location = f" · {display_certificate(certificate)}" if certificate else ""
    return (
        f"🧪 RedGreen: proof of fix. `{verdict.command}` fails without the change and "
        f"passes with it{location}"
    )


def stamp_unproven(text: str, verdict: core.Verdict, certificate: Path | None) -> str:
    if "RedGreen" in (text or "")[:400]:
        return text
    reason = verdict.reason.strip()
    detail = (
        f"⛔ UNPROVEN (RedGreen)\n{reason}\n"
        f"Evidence: `{verdict.command or 'no test command'}` · "
        f"before: {(verdict.before.summary if verdict.before else 'not run')} · "
        f"after: {(verdict.current.summary if verdict.current else 'not run')}"
    )
    if certificate is not None:
        detail += f"\nCertificate: {display_certificate(certificate)}"
    return detail + "\n\n---\n\n" + (text or "")


def mention_claims(text: str) -> bool:
    return core.contains_completion_claim(text)


def changed_test_files(record: core.SessionRecord) -> list[str]:
    repo = Path(record.repo_root) if record.repo_root else None
    if repo is None or not record.baseline_sha:
        return []
    try:
        return core.test_files_to_overlay(repo, record.baseline_sha)
    except Exception:  # noqa: BLE001
        return []
