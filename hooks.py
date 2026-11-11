"""Hermes lifecycle hooks: baseline capture, run capture, interlock, stamp."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from . import core, runtime
except ImportError:  # pragma: no cover - direct import while testing
    import core  # type: ignore
    import runtime  # type: ignore


WRITE_COMMAND_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:sed\s+-i|perl\s+-i|tee\b|truncate\b|rm\b|mv\b|cp\b|"
    r"patch\b|git\s+(?:apply|checkout|restore|reset)\b|cat\s*>|"
    r"python[0-9.]*\s+-c\b[^\n]*\bopen\()",
    re.IGNORECASE,
)


def _sid(kwargs: dict[str, Any]) -> str:
    return runtime.session_id_from(**kwargs)


def _ensure_baseline(record: core.SessionRecord, hint_path: str = "", hint_cwd: str = "") -> None:
    if record.baseline_sha and record.repo_root:
        return
    repo = runtime.infer_repo(hint_path, hint_cwd)
    if repo is None:
        return
    sha, kind = core.capture_baseline(repo)
    if not sha:
        return
    record.repo_root = str(repo)
    record.baseline_sha = sha
    record.baseline_kind = kind
    record.baseline_at = core.time.time()


def on_pre_tool_call(tool_name: str, args: dict | None = None, **kwargs: Any) -> None:
    """Snapshot the pre-change tree before the first mutation lands."""
    if tool_name in runtime.TOOL_NAMES:
        return
    args = args or {}
    record = runtime.STORE.get(_sid(kwargs))

    if tool_name in runtime.MUTATION_TOOLS:
        hint = runtime.path_from_args(args)
        if hint:
            _ensure_baseline(record, hint)
            if record.baseline_sha:
                runtime.STORE.save(record)
        return

    command = str(args.get("command") or args.get("cmd") or "")
    if command and WRITE_COMMAND_RE.search(command):
        _ensure_baseline(record, str(args.get("cwd") or args.get("working_dir") or ""))
        if record.baseline_sha:
            runtime.STORE.save(record)
    return


def on_post_tool_call(tool_name: str, args: dict | None = None, result: Any = "", **kwargs: Any) -> None:
    """Record mutations and any real test run the agent performed."""
    if tool_name in runtime.TOOL_NAMES:
        return
    args = args or {}
    record = runtime.STORE.get(_sid(kwargs))

    if tool_name in runtime.MUTATION_TOOLS:
        path = runtime.path_from_args(args)
        if path:
            record.mutations.append(
                {
                    "path": path,
                    "tool": tool_name,
                    "at": core.time.time(),
                }
            )
            _ensure_baseline(record, path)
            runtime.STORE.save(record)
        return

    if tool_name not in {"terminal", "shell_exec", "execute_code"}:
        return

    command = str(args.get("command") or args.get("cmd") or "").strip()
    if not command or not core.is_test_command(command):
        return

    exit_code, output = runtime.parse_tool_result(result)
    cwd = str(args.get("cwd") or args.get("working_dir") or record.repo_root or "")
    runtime.record_test_run(record, command, cwd, exit_code, output)
    runtime.STORE.save(record)
    return


def on_pre_verify(
    session_id: str = "",
    changed_paths: list[str] | None = None,
    attempt: int = 0,
    final_response: str = "",
    coding: bool = True,
    **kwargs: Any,
) -> dict[str, str] | None:
    """Refuse completion until the negative control is green."""
    sid = runtime.session_id_from(session_id=session_id, **kwargs)
    record = runtime.STORE.get(sid)

    for path in changed_paths or []:
        if not any(str(m.get("path")) == str(path) for m in record.mutations):
            record.mutations.append({"path": str(path), "tool": "turn_edit", "at": core.time.time()})

    if not record.mutations:
        return None
    if not any(core.is_code_path(str(m.get("path", ""))) for m in record.mutations):
        # Documentation, images and data files are outside the negative control.
        return None
    if not (record.baseline_sha and record.repo_root):
        # Nothing to compare against. Do not trap sessions outside git; the final
        # message still gets an honest stamp if it claims completion.
        runtime.STORE.save(record)
        return None

    repo = Path(record.repo_root)
    if not repo.exists():
        return None

    command = record.last_test_command() or runtime.command_from_message(final_response)
    settings = runtime.settings()
    signature = core.tree_signature(repo)

    cached = record.last_verdict
    if cached and record.tree_signature == signature:
        verdict = core.Verdict(
            status=str(cached.get("status", "")),
            reason=str(cached.get("reason", "")),
            command=str(cached.get("command", "")),
            repo_root=str(cached.get("repo_root", "")),
            baseline_sha=str(cached.get("baseline_sha", "")),
            baseline_kind=str(cached.get("baseline_kind", "")),
            certificate_id=str(cached.get("certificate_id", "")),
            changed_test_files=list(cached.get("changed_test_files") or []),
            tamper=list(cached.get("tamper") or []),
        )
        # Re-hydrate the two runs for the message.
        for field_name, source in (("current", "current"), ("before", "before")):
            raw = cached.get(source)
            if isinstance(raw, dict):
                setattr(
                    verdict,
                    field_name,
                    core.RunResult(
                        command=raw.get("command", ""),
                        cwd=raw.get("cwd", ""),
                        exit_code=raw.get("exit_code"),
                        output=raw.get("output", ""),
                        duration_ms=int(raw.get("duration_ms", 0) or 0),
                        source=raw.get("source", "rerun"),
                    ),
                )
    else:
        verdict = runtime.prove(
            record,
            command=command,
            timeout=settings["timeout"],
            mode=str(settings["mode"]),
        )
        record.last_verdict = verdict.to_dict()
        runtime.STORE.save(record)

    certificate = None
    if verdict.status != "no_command":
        try:
            certificate = runtime.certificate_for(record, verdict)
        except Exception:  # noqa: BLE001 - a certificate is nice, never required
            certificate = None
    runtime.STORE.save(record)

    if verdict.proven:
        return None

    message = runtime.veto_message(verdict, certificate)
    if attempt >= 2:
        message += (
            "\n\nThis is the third check. If you finish anyway, Falsify will stamp the "
            "final reply UNPROVEN."
        )
    return {"action": "continue", "message": message}


def on_transform_llm_output(response_text: str = "", session_id: str = "", **kwargs: Any) -> str:
    """Make the delivered message tell the truth even if the model ignores the gate."""
    sid = runtime.session_id_from(session_id=session_id, **kwargs)
    record = runtime.STORE.get(sid)
    if not record.mutations or not record.baseline_sha:
        return response_text
    if not any(core.is_code_path(str(m.get("path", ""))) for m in record.mutations):
        return response_text
    settings = runtime.settings()
    if not settings["stamp"]:
        return response_text

    verdict = None
    repo = Path(record.repo_root) if record.repo_root else None
    signature = core.tree_signature(repo) if repo and repo.exists() else ""
    cached = record.last_verdict
    if cached and signature and record.tree_signature == signature:
        verdict = core.Verdict(
            status=str(cached.get("status", "")),
            reason=str(cached.get("reason", "")),
            command=str(cached.get("command", "")),
            repo_root=str(cached.get("repo_root", "")),
            baseline_sha=str(cached.get("baseline_sha", "")),
            baseline_kind=str(cached.get("baseline_kind", "")),
            certificate_id=str(cached.get("certificate_id", "")),
        )
        for field_name in ("current", "before"):
            raw = cached.get(field_name)
            if isinstance(raw, dict):
                setattr(
                    verdict,
                    field_name,
                    core.RunResult(
                        command=raw.get("command", ""),
                        cwd=raw.get("cwd", ""),
                        exit_code=raw.get("exit_code"),
                        output=raw.get("output", ""),
                        duration_ms=int(raw.get("duration_ms", 0) or 0),
                        source=raw.get("source", "rerun"),
                    ),
                )

    if verdict is None:
        command = record.last_test_command() or runtime.command_from_message(response_text)
        verdict = runtime.prove(
            record,
            command=command,
            timeout=min(float(settings["timeout"]), 90.0),
            mode=str(settings["mode"]),
        )
        runtime.STORE.save(record)

    if verdict.proven:
        if runtime.mention_claims(response_text) and "Falsify" not in response_text[:400]:
            certificate = runtime.certificate_path_for(verdict)
            return response_text.rstrip() + "\n\n" + runtime.proof_badge(verdict, certificate)
        return response_text

    if not runtime.mention_claims(response_text):
        return response_text

    certificate = runtime.certificate_path_for(verdict)
    return runtime.stamp_unproven(response_text, verdict, certificate)


def on_session_end(session_id: str = "", **kwargs: Any) -> None:
    sid = runtime.session_id_from(session_id=session_id, **kwargs)
    runtime.STORE.save(runtime.STORE.get(sid))
