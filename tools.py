"""Model-facing tools. Every one is deterministic and local."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

try:
    from . import core, runtime
except ImportError:  # pragma: no cover - direct import while testing
    import core  # type: ignore
    import runtime  # type: ignore


EXPLAIN = """Falsify proves a fix with a negative control.

A test only proves a fix when it fails without the fix. Falsify re-runs the test
command itself, then runs the same command on the pre-change tree with the new
tests overlaid. Only red-before / green-after counts.

Workflow:
1. Reproduce: write a test that fails on the current (unfixed) code.
2. Run it and show the failure.
3. Fix the code.
4. Run the test again; it must pass.
5. Finish. Falsify re-runs both sides and mints a certificate.

Weak evidence Falsify rejects:
- a green suite that was green before the change
- a new test that also passes without the fix
- a reported run that does not reproduce
- deleted assertions, skipped tests, or removed cases
"""


def _session(handler_kwargs: dict[str, Any]) -> str:
    return runtime.session_id_from(**handler_kwargs)


def _summary(record: core.SessionRecord) -> dict[str, Any]:
    verdict = record.last_verdict or {}
    return {
        "session": record.session_id,
        "repo": record.repo_root,
        "baseline": (record.baseline_sha or "")[:12],
        "baseline_kind": record.baseline_kind,
        "mutations": len(record.mutations),
        "test_runs": len(record.runs),
        "last_command": record.last_test_command(),
        "last_verdict": {
            "status": verdict.get("status"),
            "reason": verdict.get("reason"),
            "certificate": verdict.get("certificate_id"),
        }
        if verdict
        else None,
    }


def handle_check(params: dict[str, Any], **kwargs: Any) -> str:
    record = runtime.STORE.get(_session(kwargs))
    settings = runtime.settings()
    command = str(params.get("command") or "").strip() or record.last_test_command()
    if not command:
        return json.dumps(
            {
                "ok": False,
                "status": "no_command",
                "message": (
                    "No test command is known for this session. Run a test command "
                    "(pytest, npm test, cargo test, go test, ...) first, or pass one."
                ),
            }
        )
    if not core.is_test_command(command):
        return json.dumps(
            {
                "ok": False,
                "status": "not_a_test",
                "message": (
                    "Falsify only re-runs test commands, not arbitrary shell commands. "
                    "Pass a pytest/npm test/cargo test/go test command."
                ),
            }
        )
    verdict = runtime.prove(
        record,
        command=command,
        timeout=settings["timeout"],
        mode=str(params.get("mode") or settings["mode"]),
    )
    certificate = None
    if verdict.status != "no_command":
        try:
            certificate = runtime.certificate_for(record, verdict)
        except Exception:  # noqa: BLE001
            certificate = None
    runtime.STORE.save(record)
    message = (
        runtime.proof_badge(verdict, certificate)
        if verdict.proven
        else runtime.veto_message(verdict, certificate)
    )
    return json.dumps(
        {
            "ok": verdict.proven,
            "status": verdict.status,
            "message": message,
            "command": verdict.command,
            "before": verdict.before.to_dict() if verdict.before else None,
            "after": verdict.current.to_dict() if verdict.current else None,
            "certificate": str(certificate) if certificate else "",
        }
    )


def handle_status(params: dict[str, Any], **kwargs: Any) -> str:
    record = runtime.STORE.get(_session(kwargs))
    return json.dumps(_summary(record), indent=2)


def handle_certificate(params: dict[str, Any], **kwargs: Any) -> str:
    record = runtime.STORE.get(_session(kwargs))
    verdict_data = record.last_verdict
    if not verdict_data:
        return json.dumps(
            {"ok": False, "message": "No verdict yet. Call falsify_check first."}
        )
    certificate = runtime.STORE.latest_certificate()
    if certificate is None or certificate.stem != str(verdict_data.get("certificate_id", ""))[:16]:
        verdict = core.Verdict(
            status=str(verdict_data.get("status", "")),
            reason=str(verdict_data.get("reason", "")),
            command=str(verdict_data.get("command", "")),
            repo_root=str(verdict_data.get("repo_root", "")),
            baseline_sha=str(verdict_data.get("baseline_sha", "")),
            baseline_kind=str(verdict_data.get("baseline_kind", "")),
            certificate_id=str(verdict_data.get("certificate_id", "")),
        )
        certificate = runtime.certificate_for(record, verdict)
    opened = False
    if bool(params.get("open")):
        opened = _open_path(certificate)
    return json.dumps(
        {
            "ok": True,
            "certificate": str(certificate),
            "opened": opened,
            "status": verdict_data.get("status"),
            "certificate_id": verdict_data.get("certificate_id"),
        }
    )


def handle_history(params: dict[str, Any], **kwargs: Any) -> str:
    limit = int(params.get("limit") or 20)
    rows = runtime.STORE.list_certificates(limit=max(1, min(limit, 100)))
    return json.dumps({"ok": True, "certificates": rows}, indent=2)


def handle_explain(params: dict[str, Any], **kwargs: Any) -> str:
    return EXPLAIN


def _open_path(path: Path) -> bool:
    system = platform.system().lower()
    commands = {
        "darwin": ["open", str(path)],
        "windows": ["cmd", "/c", "start", "", str(path)],
    }
    command = commands.get(system, ["xdg-open", str(path)])
    try:
        subprocess.run(
            command,
            check=False,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=dict(os.environ),
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


TOOL_HANDLERS = {
    "falsify_check": handle_check,
    "falsify_status": handle_status,
    "falsify_certificate": handle_certificate,
    "falsify_history": handle_history,
    "falsify_explain": handle_explain,
}
