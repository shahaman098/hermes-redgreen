"""Certificates: a self-contained HTML proof page and a terminal version."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

try:
    from . import core
except ImportError:  # pragma: no cover - direct import in tests
    import core  # type: ignore


STATUS_COPY = {
    "proven": ("PROVEN", "The test fails without the change and passes with it.", "#35d07f"),
    "unproven_no_test": ("UNPROVEN", "The suite is green on both sides and no test changed.", "#ff6b6b"),
    "unproven_weak": ("UNPROVEN", "The new test also passes without the fix.", "#ff6b6b"),
    "unproven_tamper": ("TAMPERED", "The test file was weakened while proving the fix.", "#ffb454"),
    "unproven_import_error": ("UNPROVEN", "The test could not load on the pre-change tree.", "#ffb454"),
    "failing_now": ("NOT DONE", "The test command is red on the current tree.", "#ff6b6b"),
    "fabricated": ("FABRICATED", "The reported result did not reproduce.", "#ff6b6b"),
    "no_command": ("UNPROVEN", "No test command was run.", "#ffb454"),
    "no_baseline": ("UNPROVEN", "No pre-change snapshot was captured.", "#ffb454"),
    "before_unrelated_failure": ("UNPROVEN", "The pre-change failure was not in the changed tests.", "#ffb454"),
    "timeout": ("INCONCLUSIVE", "The verification did not finish in time.", "#ffb454"),
    "unproven_behavior_changed": ("UNPROVEN", "Behavior changed when it was meant to be preserved.", "#ff6b6b"),
    "pending": ("PENDING", "Verification has not run yet.", "#8b95a5"),
}


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _short(value: str, n: int = 12) -> str:
    return (value or "")[:n]


def _panel(label: str, run: core.RunResult | None, tone: str) -> str:
    if run is None:
        state = "not run"
        exit_text = "n/a"
        output = ""
        summary = "No run recorded."
    else:
        state = "green" if run.green else "red"
        exit_text = "timeout" if run.timed_out else f"exit {run.exit_code}"
        output = run.output[-6000:]
        summary = run.summary
    output_html = _esc(output) if output else '<span class="muted">(no output)</span>'
    return f"""
      <section class="panel {tone}">
        <header>
          <div>
            <div class="eyebrow">{_esc(label)}</div>
            <div class="state">{_esc(state)}</div>
          </div>
          <div class="exit">{_esc(exit_text)}</div>
        </header>
        <div class="summary">{_esc(summary)}</div>
        <pre>{output_html}</pre>
      </section>
    """


HEADLINES = {
    "proven": "This fix is proven.",
    "unproven_no_test": "This claim is not proven.",
    "unproven_weak": "This test cannot prove the fix.",
    "unproven_tamper": "The proof was tampered with.",
    "unproven_import_error": "This test cannot prove a behavior change.",
    "failing_now": "This is not done.",
    "fabricated": "The reported result did not reproduce.",
    "no_command": "No test was run.",
    "no_baseline": "There is no pre-change snapshot.",
    "before_unrelated_failure": "The failure was not in the changed tests.",
    "timeout": "The check did not finish.",
    "unproven_behavior_changed": "Behavior changed when it was meant to be preserved.",
    "pending": "Verification has not run.",
}


def render_certificate(verdict: core.Verdict, *, diff_stat: str = "") -> str:
    label, _blurb, color = STATUS_COPY.get(verdict.status, (verdict.status.upper(), verdict.reason, "#8b95a5"))
    headline = HEADLINES.get(verdict.status, verdict.reason)
    changed = ", ".join(verdict.changed_test_files) or "none"
    tamper = ""
    if verdict.tamper:
        tamper = (
            '<div class="callout warn"><strong>Tamper checks</strong><ul>'
            + "".join(f"<li>{_esc(item)}</li>" for item in verdict.tamper)
            + "</ul></div>"
        )
    diff_block = f'<pre class="diff">{_esc(diff_stat)}</pre>' if diff_stat else ""
    created = core.time.strftime("%Y-%m-%d %H:%M:%S UTC", core.time.gmtime(verdict.created_at))
    before = _panel("without the change (new tests overlaid)", verdict.before, "bad")
    after = _panel("with the change", verdict.current, "good")
    fingerprint = verdict.certificate_id
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Falsify · {_esc(label)} · {_esc(_short(fingerprint, 8))}</title>
<style>
  :root {{
    --bg: #0b0e14; --panel: #121722; --line: #232b3b; --text: #e8edf7;
    --muted: #8b95a5; --good: #35d07f; --bad: #ff6b6b; --warn: #ffb454; --accent: {color};
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.55 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  .wrap {{ max-width: 1060px; margin: 0 auto; padding: 42px 24px 64px; }}
  .top {{ display: flex; align-items: center; gap: 14px; margin-bottom: 28px; }}
  .mark {{ width: 34px; height: 34px; }}
  .brand {{ letter-spacing: .22em; font-weight: 700; font-size: 13px; color: var(--muted); }}
  .brand b {{ color: var(--text); }}
  h1 {{ font-size: 34px; line-height: 1.1; margin: 0 0 8px; letter-spacing: -.02em; }}
  .verdict {{ display: inline-flex; align-items: center; gap: 10px; padding: 7px 13px;
    border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent); border-radius: 999px;
    color: var(--accent); font-weight: 700; font-size: 12px; letter-spacing: .14em; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 12px var(--accent); }}
  .blurb {{ color: var(--muted); margin: 12px 0 0; max-width: 720px; }}
  .meta {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px;
    background: var(--line); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; margin: 30px 0; }}
  @media (max-width: 760px) {{ .meta {{ grid-template-columns: 1fr 1fr; }} }}
  .meta div {{ background: var(--panel); padding: 13px 15px; }}
  .meta .k {{ font-size: 10px; letter-spacing: .14em; color: var(--muted); text-transform: uppercase; }}
  .meta .v {{ margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px;
    overflow-wrap: anywhere; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: start; }}
  @media (max-width: 820px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; min-width: 0; }}
  .panel.good {{ border-top: 2px solid var(--good); }}
  .panel.bad {{ border-top: 2px solid var(--bad); }}
  .panel header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }}
  .eyebrow {{ font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }}
  .state {{ font-size: 20px; font-weight: 700; text-transform: capitalize; }}
  .panel.good .state {{ color: var(--good); }}
  .panel.bad .state {{ color: var(--bad); }}
  .exit {{ font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); border: 1px solid var(--line);
    padding: 4px 8px; border-radius: 7px; white-space: nowrap; }}
  .summary {{ color: var(--muted); font-size: 13px; margin: 10px 0 12px; }}
  pre {{ margin: 0; background: #0a0d13; border: 1px solid var(--line); border-radius: 10px; padding: 12px;
    font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; color: #cdd6e6;
    max-height: 340px; overflow: auto; white-space: pre-wrap; word-break: break-word; }}
  .callout {{ border: 1px solid var(--line); border-left: 2px solid var(--warn); background: var(--panel);
    border-radius: 10px; padding: 12px 14px; margin: 18px 0; color: var(--muted); }}
  .callout ul {{ margin: 8px 0 0 18px; padding: 0; }}
  .rule {{ margin: 30px 0 14px; padding: 18px 20px; border: 1px solid var(--line); border-radius: 14px; background: #0e131d; }}
  .rule strong {{ color: var(--text); }}
  .rule p {{ margin: 6px 0 0; color: var(--muted); }}
  .diff {{ margin-top: 14px; max-height: 240px; }}
  footer {{ margin-top: 28px; color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; gap: 18px; flex-wrap: wrap; }}
  .muted {{ color: var(--muted); }}
  code {{ font-family: ui-monospace, monospace; color: #dbe4f5; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <svg class="mark" viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <circle cx="20" cy="20" r="16" stroke="#2b3447" stroke-width="2"/>
      <path d="M20 4a16 16 0 0 1 0 32V4Z" fill="{color}" opacity=".9"/>
      <circle cx="20" cy="20" r="4" fill="#0b0e14" stroke="#0b0e14"/>
    </svg>
    <div class="brand">FALSIFY · <b>PROOF OF FIX</b></div>
  </div>

  <div class="verdict"><span class="dot"></span>{_esc(label)}</div>
  <h1>{_esc(headline)}</h1>
  <p class="blurb">{_esc(verdict.reason)}</p>

  <div class="meta">
    <div><div class="k">Command</div><div class="v">{_esc(verdict.command or "none")}</div></div>
    <div><div class="k">Baseline</div><div class="v">{_esc(_short(verdict.baseline_sha, 12) or "none")} ({_esc(verdict.baseline_kind or "none")})</div></div>
    <div><div class="k">Changed tests</div><div class="v">{_esc(changed)}</div></div>
    <div><div class="k">Repository</div><div class="v">{_esc(verdict.repo_root or "unknown")}</div></div>
    <div><div class="k">Created</div><div class="v">{_esc(created)}</div></div>
    <div><div class="k">Certificate</div><div class="v">sha256:{_esc(_short(fingerprint, 24))}</div></div>
  </div>

  <div class="grid">
    {before}
    {after}
  </div>

  {tamper}

  <div class="rule">
    <strong>The rule</strong>
    <p>A test only proves a fix when it <em>fails without the fix</em>. Both runs above were
    executed by Falsify itself, from the same command, on the same machine.</p>
    {diff_block}
  </div>

  <footer>
    <span>Falsify verifies agent fixes with a negative control. Nothing here trusts the agent's transcript.</span>
    <span>sha256:{_esc(fingerprint)}</span>
  </footer>
</div>
</body>
</html>
"""


SHORT_REASONS = {
    "proven": "red without the change, green with it",
    "unproven_no_test": "the suite was green before the change too",
    "unproven_weak": "the new test also passes without the fix",
    "unproven_tamper": "a test file was weakened while proving the fix",
    "unproven_import_error": "the test cannot load on the old tree",
    "failing_now": "the command is red now",
    "fabricated": "the reported result did not reproduce",
    "no_command": "no test command was run",
    "no_baseline": "no pre-change snapshot",
    "before_unrelated_failure": "the old failure was not in the changed tests",
    "timeout": "the command timed out",
    "unproven_behavior_changed": "behavior changed but should not have",
}


def render_terminal_certificate(verdict: core.Verdict) -> str:
    label, _, _ = STATUS_COPY.get(verdict.status, (verdict.status.upper(), "", ""))
    before = verdict.before
    current = verdict.current

    def row(name: str, run: core.RunResult | None) -> str:
        if run is None:
            return f"│ {name:<14} not run"
        state = "GREEN" if run.green else "RED  "
        exit_text = "timeout" if run.timed_out else f"exit {run.exit_code}"
        return f"│ {name:<14} {state:<6} {exit_text:<9} {run.summary[:30]}"

    rule = "─" * 68
    lines = [
        f"FALSIFY · {label}",
        rule,
        row("without change", before).replace("│ ", ""),
        row("with change", current).replace("│ ", ""),
        rule,
        f"command  {verdict.command}",
        f"baseline {_short(verdict.baseline_sha, 16) or 'none'}",
        f"verdict  {SHORT_REASONS.get(verdict.status, verdict.reason)}",
        f"sha256   {_short(verdict.certificate_id, 40)}",
    ]
    return "\n".join(lines)


def render_json(verdict: core.Verdict, certificate: Path | None = None) -> str:
    payload = verdict.to_dict()
    payload["certificate"] = str(certificate) if certificate else ""
    return json.dumps(payload, indent=2)
