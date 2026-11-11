"""Falsify: prove a fix with a negative control before Hermes can call it done."""

from __future__ import annotations

from pathlib import Path

try:
    from . import hooks, schemas, tools
except ImportError:  # pragma: no cover - direct import while testing
    import hooks  # type: ignore
    import schemas  # type: ignore
    import tools  # type: ignore


TOOLS = (
    ("falsify_check", schemas.FALSIFY_CHECK, tools.handle_check),
    ("falsify_status", schemas.FALSIFY_STATUS, tools.handle_status),
    ("falsify_certificate", schemas.FALSIFY_CERTIFICATE, tools.handle_certificate),
    ("falsify_history", schemas.FALSIFY_HISTORY, tools.handle_history),
    ("falsify_explain", schemas.FALSIFY_EXPLAIN, tools.handle_explain),
)

HOOKS = (
    ("pre_tool_call", hooks.on_pre_tool_call),
    ("post_tool_call", hooks.on_post_tool_call),
    ("pre_verify", hooks.on_pre_verify),
    ("transform_llm_output", hooks.on_transform_llm_output),
    ("on_session_end", hooks.on_session_end),
)


def _command(raw_args: str = "") -> str:
    """`/falsify` shows the latest proof; `/falsify explain` shows the rule."""
    text = (raw_args or "").strip().lower()
    if text in {"explain", "help", "?"}:
        return tools.EXPLAIN
    rows = tools.runtime.STORE.list_certificates(limit=5)
    if not rows:
        return "Falsify: no certificates yet. A verdict is written after the first fix."
    lines = ["Falsify · recent proofs"]
    for row in rows:
        status = str(row.get("status") or "?").upper()
        command = str(row.get("command") or "")[:60]
        lines.append(f"  {status:<12} {command}")
        lines.append(f"               {row.get('certificate')}")
    return "\n".join(lines)


def _setup_cli(parser) -> None:
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["status", "open", "explain"],
        help="status (default), open the latest certificate, or explain the rule",
    )


def _handle_cli(args) -> int:
    action = getattr(args, "action", "status")
    if action == "explain":
        print(tools.EXPLAIN)
        return 0
    if action == "open":
        latest = tools.runtime.STORE.latest_certificate()
        if latest is None:
            print("Falsify: no certificates yet.")
            return 1
        print(latest)
        tools._open_path(latest)
        return 0
    rows = tools.runtime.STORE.list_certificates(limit=20)
    if not rows:
        print("Falsify: no certificates yet.")
        return 0
    print(f"{'VERDICT':<14} {'COMMAND':<40} CERTIFICATE")
    for row in rows:
        print(
            f"{str(row.get('status') or '?').upper():<14} "
            f"{str(row.get('command') or '')[:38]:<40} {row.get('certificate')}"
        )
    return 0


def register(ctx) -> None:
    for name, schema, handler in TOOLS:
        ctx.register_tool(
            name=name,
            toolset="falsify",
            schema=schema,
            handler=handler,
            description=schema.get("description", ""),
        )

    for hook_name, callback in HOOKS:
        ctx.register_hook(hook_name, callback)

    ctx.register_command(
        "falsify",
        _command,
        description="Show the last Falsify proof; /falsify explain for the rule",
    )

    ctx.register_cli_command(
        "falsify",
        help="Inspect Falsify proof-of-fix certificates",
        setup_fn=_setup_cli,
        handler_fn=_handle_cli,
        description="List, open or explain the negative-control proofs Falsify minted.",
    )

    skill = Path(__file__).resolve().parent / "skills" / "negative-control" / "SKILL.md"
    if skill.exists():
        try:
            ctx.register_skill(
                "negative-control",
                skill,
                description="Reproduce a bug, make a test fail without the fix, then prove it.",
            )
        except Exception:  # noqa: BLE001, S110 - a skill is optional
            pass
