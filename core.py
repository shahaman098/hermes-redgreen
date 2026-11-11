"""Falsify core: negative-control verification for agent fixes.

The rule is simple and old: a test only proves a fix when it fails without the
fix. Falsify takes the command the agent says it ran, re-runs it itself, then
runs the same command against the pre-change tree with the new tests overlaid.
Only red-before / green-after counts as proof.

No Hermes imports live here so the engine can be tested on its own.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# What counts as a test run
# ---------------------------------------------------------------------------

TEST_RUNNER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bpytest\b",
        r"\bpy\.test\b",
        r"\bpython3?\s+-m\s+(?:pytest|unittest)\b",
        r"\bpython3?\s+-m\s+pytest\b",
        r"\buv\s+run\s+(?:pytest|python\s+-m\s+pytest)\b",
        r"\bpoetry\s+run\s+pytest\b",
        r"\bcargo\s+test\b",
        r"\bnpm\s+(?:run\s+)?test\b",
        r"\bnpm\s+run\s+[\w:-]*test[\w:-]*\b",
        r"\bpnpm\s+(?:run\s+)?test\b",
        r"\byarn\s+(?:run\s+)?test\b",
        r"\bbun\s+test\b",
        r"\bnpx\s+(?:jest|vitest|mocha)\b",
        r"\bnode\s+--test\b",
        r"\bdeno\s+test\b",
        r"\bgo\s+test\b",
        r"\bmix\s+test\b",
        r"\bdotnet\s+test\b",
        r"\bmvnw?\s+(?:-\S+\s+)*test\b",
        r"\bgradlew?\s+(?:-\S+\s+)*test\b",
        r"\brspec\b",
        r"\bphpunit\b",
        r"\bswift\s+test\b",
        r"\bctest\b",
        r"\bpython3?\s+test_[\w-]+\.py\b",
        r"\bpytest\s+[^\n]*::[^\n]+",
        r"\bmake\s+(?:test|check)\b",
        r"\bjust\s+test\b",
        r"\bnox\b",
        r"\btox\b",
    )
)

FAILURE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bFAILED\b",
        r"\bFAILURES?\b",
        r"\bTraceback\s+\(most\s+recent\s+call\s+last\):",
        r"\bSyntaxError:",
        r"\bERRORS?:",
        r"\bcommand\s+failed\b",
        r"\btest\s+result:\s*FAILED\b",
        r"\bAssertionError\b",
        r"^\s*---\s+FAIL:",
    )
)

SUCCESS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b\d+\s+passed\b",
        r"\bRan\s+\d+\s+tests?\s+in\s+[\d.]+s\s+OK\b",
        r"\btest\s+result:\s*ok\b",
        r"\bTests?:\s+(?:\d+\s+failed,\s+)?\d+\s+passed\b",
        r"^\s*ok\s+\S+",
        r"\bHTTP/\d(?:\.\d)?\s+2\d\d\b",
    )
)

# Paths whose current version must be overlaid onto the pre-change tree for the
# negative control. Tests, fixtures and runner config only: overlaying source
# would erase the bug we are trying to prove.
TEST_PATH_RE = re.compile(
    r"(?:^|/)("
    r"tests?|__tests__|specs?|testdata|test_data|fixtures?|e2e|integration_tests?"
    r")(?:/|$)"
    r"|(?:^|/)test_[^/]*$"
    r"|(?:^|/)[^/]*_test\.py$"
    r"|\.(?:test|spec)\.[cm]?[jt]sx?$"
    r"|(?:^|/)conftest\.py$",
    re.IGNORECASE,
)

TEST_CONFIG_RE = re.compile(
    r"(?:^|/)("
    r"pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml|package\.json|"
    r"jest\.config\.[^/]+|vitest\.config\.[^/]+|\.mocharc\.[^/]+|"
    r"phpunit\.xml|Cargo\.toml|go\.mod|Makefile"
    r")$",
    re.IGNORECASE,
)

TAMPER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"@pytest\.mark\.(?:skip|skipif|xfail)",
        r"\bpytest\.(?:skip|xfail)\s*\(",
        r"\b(?:it|test|describe)\.(?:skip|todo)\s*\(",
        r"\bxit\s*\(",
        r"\bxdescribe\s*\(",
        r"\bunittest\.skip\s*\(",
        r"#\[ignore\]",
        r"\bt\.Skip(?:f)?\s*\(",
    )
)

TEST_DEFINITION_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+(test_\w+)|^\s*(?:it|test)\s*\(\s*['\"]([^'\"]+)",
    re.MULTILINE,
)

CLAIM_RE = re.compile(
    r"\b(?:done|complete(?:d)?|fixed|resolved|passing|passes|verified|shipped|works?)\b",
    re.IGNORECASE,
)

MAX_OUTPUT_CHARS = 200_000


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def short_hash(text: str, n: int = 12) -> str:
    return hash_text(text)[:n]


def is_test_command(command: str) -> bool:
    if not command:
        return False
    return any(pattern.search(command) for pattern in TEST_RUNNER_PATTERNS)


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH_RE.search(path or ""))


def is_test_config_path(path: str) -> bool:
    return bool(TEST_CONFIG_RE.search(path or ""))


CODE_SUFFIXES = frozenset(
    {
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rb",
        ".go", ".rs", ".java", ".kt", ".kts", ".php", ".cs", ".swift", ".c",
        ".h", ".cc", ".cpp", ".hpp", ".m", ".mm", ".sql", ".sh", ".bash",
        ".zsh", ".html", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
        ".astro", ".elm", ".ex", ".exs", ".erl", ".hs", ".lua", ".r", ".jl",
    }
)


def is_code_path(path: str) -> bool:
    return Path(path or "").suffix.lower() in CODE_SUFFIXES


def contains_completion_claim(text: str) -> bool:
    return bool(CLAIM_RE.search(text or ""))


def parse_failure(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in FAILURE_PATTERNS)


def parse_success(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in SUCCESS_PATTERNS)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """One execution of a test command."""

    command: str
    cwd: str
    exit_code: int | None
    output: str
    duration_ms: int
    source: str = "rerun"  # "reported" | "rerun" | "before"
    timed_out: bool = False

    @property
    def green(self) -> bool:
        if self.timed_out or self.exit_code is None:
            return False
        if self.exit_code != 0:
            return False
        return not parse_failure(self.output)

    @property
    def red(self) -> bool:
        return not self.green

    @property
    def output_digest(self) -> str:
        return hash_text(self.output)

    @property
    def summary(self) -> str:
        return summarize_output(self.output)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "output": self.output[-MAX_OUTPUT_CHARS:],
            "output_digest": self.output_digest,
            "duration_ms": self.duration_ms,
            "source": self.source,
            "timed_out": self.timed_out,
            "green": self.green,
        }


@dataclass
class Verdict:
    status: str
    reason: str
    command: str
    repo_root: str = ""
    baseline_sha: str = ""
    baseline_kind: str = ""
    current: RunResult | None = None
    before: RunResult | None = None
    reported: RunResult | None = None
    changed_test_files: list[str] = field(default_factory=list)
    failed_before: list[str] = field(default_factory=list)
    failed_now: list[str] = field(default_factory=list)
    tamper: list[str] = field(default_factory=list)
    certificate_id: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def proven(self) -> bool:
        return self.status == "proven"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["current"] = self.current.to_dict() if self.current else None
        data["before"] = self.before.to_dict() if self.before else None
        data["reported"] = self.reported.to_dict() if self.reported else None
        data["proven"] = self.proven
        return data

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "command": self.command,
            "repo_root": self.repo_root,
            "baseline_sha": self.baseline_sha,
            "baseline_kind": self.baseline_kind,
            "current_exit": self.current.exit_code if self.current else None,
            "current_digest": self.current.output_digest if self.current else None,
            "before_exit": self.before.exit_code if self.before else None,
            "before_digest": self.before.output_digest if self.before else None,
            "changed_test_files": self.changed_test_files,
            "failed_before": self.failed_before,
            "failed_now": self.failed_now,
            "created_at": round(self.created_at, 3),
        }

    def finalize(self) -> Verdict:
        if not self.certificate_id:
            self.certificate_id = hash_text(
                json.dumps(self.canonical_payload(), sort_keys=True)
            )
        return self


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

_PYTEST_COUNTS = re.compile(
    r"(?:(\d+)\s+failed[,\s]+)?(?:(\d+)\s+errors?[,\s]+)?(?:(\d+)\s+passed)"
    r"|(?:(\d+)\s+passed[,\s]+)?(?:(\d+)\s+failed)"
)
_JEST_COUNTS = re.compile(r"Tests:\s+(?:(\d+)\s+failed,\s+)?(?:(\d+)\s+skipped,\s+)?(\d+)\s+passed")
_CARGO_COUNTS = re.compile(r"test result: (\w+)\. (\d+) passed; (\d+) failed")
_GO_FAIL = re.compile(r"^--- FAIL: (\S+)", re.MULTILINE)
_GO_OK = re.compile(r"^ok\s+\S+", re.MULTILINE)
_UNITTEST = re.compile(r"Ran (\d+) tests? in [\d.]+s\s+(OK|FAILED)")


def summarize_output(output: str) -> str:
    """Return the most useful one-line summary the runner gave us."""
    if not output:
        return "no output"
    if _UNITTEST.search(output):
        match = _UNITTEST.search(output)
        return f"Ran {match.group(1)} tests, {match.group(2)}"
    cargo = _CARGO_COUNTS.search(output)
    if cargo:
        return f"{cargo.group(2)} passed, {cargo.group(3)} failed"
    jest = _JEST_COUNTS.search(output)
    if jest:
        failed = jest.group(1) or "0"
        passed = jest.group(3)
        return f"{passed} passed, {failed} failed"
    for match in _PYTEST_COUNTS.finditer(output):
        groups = [g for g in match.groups() if g is not None]
        if groups:
            failed = match.group(1) or match.group(5) or "0"
            passed = match.group(3) or match.group(4) or "0"
            return f"{passed} passed, {failed} failed"
    go_fail = _GO_FAIL.findall(output)
    if go_fail:
        return f"{len(go_fail)} failing test(s)"
    if _GO_OK.search(output):
        return "ok"
    failures = [line.strip() for line in output.splitlines() if line.strip()][-1:]
    return failures[0][:160] if failures else "no output"


def failed_test_ids(output: str) -> list[str]:
    ids: list[str] = []
    patterns = (
        re.compile(r"^FAILED\s+(\S+)", re.MULTILINE),
        re.compile(r"^--- FAIL: (\S+)", re.MULTILINE),
        re.compile(r"^test (\S+) \.\.\. FAILED", re.MULTILINE),
        re.compile(r"●\s+([^\n]+)"),
        re.compile(r"✕\s+([^\n]+)"),
        re.compile(r"^(\S+::\S+)\s+FAILED", re.MULTILINE),
    )
    for pattern in patterns:
        for match in pattern.finditer(output or ""):
            value = match.group(1).strip()
            if value and value not in ids:
                ids.append(value)
    return ids


def _looks_like_import_error(output: str) -> bool:
    return bool(
        re.search(
            r"ERROR collecting|ModuleNotFoundError|ImportError|No module named|"
            r"Cannot find module|error: could not compile",
            output or "",
            re.IGNORECASE,
        )
    )


def count_tamper(before_text: str, after_text: str) -> list[str]:
    """Cheap, transparent checks for tests that stopped testing anything."""
    findings: list[str] = []
    after_defs = len(TEST_DEFINITION_RE.findall(after_text or ""))
    before_defs = len(TEST_DEFINITION_RE.findall(before_text or ""))
    if before_defs and after_defs < before_defs:
        findings.append(
            f"{before_defs - after_defs} test definition(s) disappeared from this test file"
        )
    before_asserts = len(re.findall(r"\bassert\b|\bexpect\s*\(", before_text or ""))
    after_asserts = len(re.findall(r"\bassert\b|\bexpect\s*\(", after_text or ""))
    if before_asserts and after_asserts < before_asserts:
        findings.append(
            f"{before_asserts - after_asserts} assertion(s) disappeared from this test file"
        )
    for pattern in TAMPER_PATTERNS:
        added = len(pattern.findall(after_text or "")) - len(pattern.findall(before_text or ""))
        if added > 0:
            findings.append(f"{added} skip/xfail marker(s) added to this test file")
    return findings


# ---------------------------------------------------------------------------
# Git plumbing
# ---------------------------------------------------------------------------


def _git(
    repo: Path,
    *args: str,
    timeout: float = 30.0,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def find_repo_root(path: str | Path) -> Path | None:
    candidate = Path(path)
    if candidate.is_file():
        candidate = candidate.parent
    try:
        result = _git(candidate, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def capture_baseline(repo: Path) -> tuple[str, str]:
    """Return (commit, kind) for the pre-change tree.

    "head" means the tree was clean at the first mutation. "snapshot" means the
    user had uncommitted or untracked work, so Falsify records the whole working
    tree as a throwaway commit through a temporary index. The real index, working
    tree and stash list are never touched.
    """
    status = _git(repo, "status", "--porcelain", "-uall")
    if status.returncode != 0:
        return "", "none"
    if not status.stdout.strip():
        head = _git(repo, "rev-parse", "HEAD")
        return (head.stdout.strip(), "head") if head.returncode == 0 else ("", "none")

    head = _git(repo, "rev-parse", "HEAD")
    parent = head.stdout.strip() if head.returncode == 0 else ""

    with tempfile.TemporaryDirectory(prefix="falsify-index-") as tmp:
        index_path = str(Path(tmp) / "index")
        env = {"GIT_INDEX_FILE": index_path}
        if parent:
            _git(repo, "read-tree", parent, extra_env=env)
        added = _git(repo, "add", "-A", "--", ".", *SECRET_PATHSPECS, extra_env=env, timeout=120.0)
        if added.returncode != 0:
            return (parent, "head") if parent else ("", "none")
        tree = _git(repo, "write-tree", extra_env=env)
        if tree.returncode != 0 or not tree.stdout.strip():
            return (parent, "head") if parent else ("", "none")
        commit_args = ["-c", "user.name=Falsify", "-c", "user.email=falsify@localhost",
                       "commit-tree", tree.stdout.strip(), "-m", "falsify baseline snapshot"]
        if parent:
            commit_args.extend(["-p", parent])
        commit = _git(repo, *commit_args, extra_env=env)
        if commit.returncode == 0 and commit.stdout.strip():
            return commit.stdout.strip(), "snapshot"
    return (parent, "head") if parent else ("", "none")


def changed_paths(repo: Path, baseline: str) -> list[str]:
    paths: list[str] = []
    diff = _git(repo, "diff", "--name-only", baseline, "--")
    if diff.returncode == 0:
        paths.extend(line.strip() for line in diff.stdout.splitlines() if line.strip())
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
    if untracked.returncode == 0:
        paths.extend(line.strip() for line in untracked.stdout.splitlines() if line.strip())
    return list(dict.fromkeys(paths))


SECRET_PATHSPECS = (
    ":(exclude,glob)**/.env",
    ":(exclude,glob)**/.env.*",
    ":(exclude,glob)**/*.pem",
    ":(exclude,glob)**/*.key",
    ":(exclude,glob)**/*.p12",
    ":(exclude,glob)**/*.pfx",
    ":(exclude,glob)**/id_rsa*",
    ":(exclude,glob)**/id_ed25519*",
    ":(exclude,glob)**/.netrc",
    ":(exclude,glob)**/.npmrc",
    ":(exclude,glob)**/.pypirc",
    ":(exclude,glob)**/auth.json",
    ":(exclude,glob)**/credentials.json",
)

SECRET_NAME_RE = re.compile(
    r"(?:^|/)(?:\.env(?:\..*)?|.*\.(?:pem|key|p12|pfx)|id_rsa.*|id_ed25519.*|"
    r"\.netrc|\.npmrc|\.pypirc|auth\.json|credentials\.json)$"
)

_CACHE_DIR_RE = re.compile(
    r"(?:^|/)(?:__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|node_modules|"
    r"\.tox|\.venv|venv|target|dist|build|\.next|\.git)(?:/|$)"
)
_OVERLAY_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rb", ".go",
    ".rs", ".java", ".kt", ".kts", ".php", ".cs", ".swift", ".c", ".h", ".cpp",
    ".hpp", ".json", ".ini", ".toml", ".cfg", ".yaml", ".yml", ".xml", ".sh",
    ".sql", ".feature", ".snap", ".txt", ".md",
}


def is_overlay_path(path: str) -> bool:
    if not path:
        return False
    if _CACHE_DIR_RE.search(path):
        return False
    if Path(path).suffix.lower() not in _OVERLAY_SUFFIXES:
        return False
    return is_test_path(path) or is_test_config_path(path)


def test_files_to_overlay(repo: Path, baseline: str) -> list[str]:
    paths = changed_paths(repo, baseline)
    overlay = [p for p in paths if is_overlay_path(p)]
    # `git status` can miss a test file that is tracked but modified relative to
    # the baseline commit; changed_paths covers that. Keep only real files.
    return [p for p in overlay if (repo / p).is_file()]


def _worktree_add(repo: Path, sha: str, target: Path) -> subprocess.CompletedProcess[str]:
    return _git(repo, "worktree", "add", "--detach", "--force", str(target), sha, timeout=120.0)


def _worktree_remove(repo: Path, target: Path) -> None:
    try:
        _git(repo, "worktree", "remove", "--force", str(target), timeout=60.0)
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(target, ignore_errors=True)
    try:
        _git(repo, "worktree", "prune")
    except (OSError, subprocess.SubprocessError):
        pass  # best effort cleanup


def overlay_files(source_repo: Path, target_repo: Path, paths: Iterable[str]) -> list[str]:
    copied: list[str] = []
    for relative in paths:
        src = source_repo / relative
        if not src.is_file():
            continue
        dst = target_repo / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
            copied.append(relative)
        except OSError:
            continue
    return copied


# ---------------------------------------------------------------------------
# Running tests
# ---------------------------------------------------------------------------


def run_command(
    command: str,
    cwd: Path,
    *,
    timeout: float = 120.0,
    source: str = "rerun",
    extra_env: dict[str, str] | None = None,
) -> RunResult:
    started = time.monotonic()
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "CI": os.environ.get("CI", "1"),
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
    }
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            check=False,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return RunResult(
            command=command,
            cwd=str(cwd),
            exit_code=proc.returncode,
            output=output[-MAX_OUTPUT_CHARS:],
            duration_ms=int((time.monotonic() - started) * 1000),
            source=source,
        )
    except subprocess.TimeoutExpired as exc:
        partial = ""
        for stream in (exc.stdout, exc.stderr):
            if isinstance(stream, bytes):
                partial += stream.decode("utf-8", "replace")
            elif isinstance(stream, str):
                partial += stream
        return RunResult(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            output=(partial + f"\n[falsify] timed out after {timeout:.0f}s")[-MAX_OUTPUT_CHARS:],
            duration_ms=int((time.monotonic() - started) * 1000),
            source=source,
            timed_out=True,
        )
    except OSError as exc:
        return RunResult(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            output=f"[falsify] could not run command: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
            source=source,
        )


# ---------------------------------------------------------------------------
# The negative control
# ---------------------------------------------------------------------------


def verify(
    *,
    repo: Path,
    baseline_sha: str,
    baseline_kind: str,
    command: str,
    reported: RunResult | None = None,
    timeout: float = 120.0,
    mode: str = "fix",
) -> Verdict:
    """Run the current tree and the pre-change tree, then classify the claim."""
    if not command:
        return Verdict(
            status="no_command",
            reason="No test command was run in this session, so nothing can be reproduced.",
            command="",
            repo_root=str(repo),
            baseline_sha=baseline_sha,
            baseline_kind=baseline_kind,
        ).finalize()

    current = run_command(command, repo, timeout=timeout, source="rerun")
    verdict = Verdict(
        status="pending",
        reason="",
        command=command,
        repo_root=str(repo),
        baseline_sha=baseline_sha,
        baseline_kind=baseline_kind,
        current=current,
        reported=reported,
    )
    verdict.failed_now = failed_test_ids(current.output)

    if reported is not None:
        if reported.green and current.red:
            verdict.status = "fabricated"
            verdict.reason = (
                "The reported run was green, but Falsify's own re-run is red. "
                "The completion claim does not reproduce."
            )
            return verdict.finalize()
        if current.red and not current.timed_out:
            verdict.status = "failing_now"
            verdict.reason = (
                "The test command fails on the current tree (exit "
                f"{current.exit_code}). There is nothing to prove until it is green."
            )
            return verdict.finalize()
        if current.timed_out:
            verdict.status = "timeout"
            verdict.reason = (
                f"The test command did not finish within {timeout:.0f}s, so Falsify "
                "cannot reproduce the claim. Run the targeted test instead."
            )
            return verdict.finalize()
    elif current.red:
        verdict.status = "failing_now" if not current.timed_out else "timeout"
        verdict.reason = (
            "Falsify re-ran the test command and it is red on the current tree."
        )
        return verdict.finalize()

    # Green now. Build the pre-change tree and run the same command.
    overlay = test_files_to_overlay(repo, baseline_sha)
    verdict.changed_test_files = overlay
    for relative in changed_paths(repo, baseline_sha):
        if is_overlay_path(relative) and not (repo / relative).exists():
            verdict.tamper.append(f"{relative}: test file deleted")

    tmp_root = Path(tempfile.mkdtemp(prefix="falsify-"))
    before_tree = tmp_root / "tree"
    try:
        added = _worktree_add(repo, baseline_sha, before_tree)
        if added.returncode != 0:
            verdict.status = "no_baseline"
            verdict.reason = (
                "Could not materialize the pre-change tree "
                f"({added.stderr.strip()[:200] or 'git worktree failed'})."
            )
            return verdict.finalize()

        overlay_files(repo, before_tree, overlay)
        # The pre-change tree is a fresh checkout, so installed dependencies that
        # live outside git (node_modules, a project venv) would be missing. Link
        # them in rather than making the runner fail for an unrelated reason.
        for dependency_dir in ("node_modules", ".venv", "venv", "vendor", ".bundle"):
            source_dir = repo / dependency_dir
            target_dir = before_tree / dependency_dir
            if source_dir.exists() and not target_dir.exists():
                try:
                    os.symlink(source_dir, target_dir, target_is_directory=True)
                except OSError:
                    pass
        before = run_command(command, before_tree, timeout=timeout, source="before")
        verdict.before = before
        verdict.failed_before = failed_test_ids(before.output)

        # Tamper checks run against the test files that were changed.
        for relative in overlay:
            try:
                old = _git(repo, "show", f"{baseline_sha}:{relative}")
                new = (repo / relative).read_text(encoding="utf-8", errors="replace")
                old_text = old.stdout if old.returncode == 0 else ""
                findings = count_tamper(old_text, new)
                verdict.tamper.extend(f"{relative}: {finding}" for finding in findings)
            except OSError:
                continue

        if verdict.tamper and before.green and mode != "preserve":
            # Weakened tests are reported before a green-before verdict: the
            # interesting fact is that the proof was tampered with, not that a
            # hollow test also passes on the old tree.
            verdict.status = "unproven_tamper"
            verdict.reason = (
                "The negative control failed and the test file was weakened while "
                "it was being made to fail: " + "; ".join(verdict.tamper[:3])
            )
            return verdict.finalize()

        if mode == "preserve":
            verdict.status = "proven" if before.green else "unproven_behavior_changed"
            verdict.reason = (
                "Behavior is preserved: the command is green before and after."
                if before.green
                else "The command is green now but red before, so behavior changed."
            )
            return verdict.finalize()

        if before.timed_out:
            verdict.status = "timeout"
            verdict.reason = (
                f"The pre-change run did not finish within {timeout:.0f}s. "
                "Run the targeted test instead."
            )
            return verdict.finalize()

        if before.green:
            if not overlay:
                verdict.status = "unproven_no_test"
                verdict.reason = (
                    "The suite is green without your change too, and no test was added "
                    "or changed. A passing suite is not proof of a fix."
                )
            else:
                verdict.status = "unproven_weak"
                verdict.reason = (
                    "The negative control failed: the new/changed test also passes on "
                    "the pre-change tree. It cannot tell the bug from the fix."
                )
            return verdict.finalize()

        if not verdict.failed_before and _looks_like_import_error(before.output):
            verdict.status = "unproven_import_error"
            verdict.reason = (
                "The test cannot even load on the pre-change tree (import or collection "
                "error). That proves the code was absent, not that the behavior was "
                "broken. Write a test that runs against the old code and fails on an "
                "assertion."
            )
            return verdict.finalize()

        # Before is red. Is the failure in the tests we changed (or in an
        # existing test that the fix repairs)?
        if overlay:
            matches = [
                failure
                for failure in verdict.failed_before
                if any(Path(test.split("::")[0]).as_posix() in failure for test in overlay)
            ]
            if not matches:
                verdict.status = "before_unrelated_failure"
                verdict.reason = (
                    "The pre-change run fails, but not in a test added or changed by "
                    "this work, so it does not prove this fix. The failure is: "
                    + (", ".join(verdict.failed_before[:3]) or "unparsed")
                )
                return verdict.finalize()
        else:
            if not verdict.failed_before:
                verdict.status = "before_unrelated_failure"
                verdict.reason = (
                    "The pre-change run is red but no failing test could be identified, "
                    "so the negative control is not attributable to this fix."
                )
                return verdict.finalize()

        verdict.status = "proven"
        verdict.reason = (
            "Proof of fix: the command is red without the change and green with it"
            + (" (" + verdict.failed_before[0] + " fails before)" if verdict.failed_before else "")
            + "."
        )
        if verdict.tamper and mode != "preserve":
            verdict.status = "unproven_tamper"
            verdict.reason = (
                "The negative control passed, but the test file was weakened while it "
                "was being made to fail: " + "; ".join(verdict.tamper[:3])
            )
        return verdict.finalize()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        _worktree_remove(repo, before_tree)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class SessionRecord:
    session_id: str
    repo_root: str | None = None
    baseline_sha: str | None = None
    baseline_kind: str = "none"
    baseline_at: float = 0.0
    mutations: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    last_verdict: dict[str, Any] | None = None
    verified_at: float = 0.0
    tree_signature: str = ""
    created_at: float = field(default_factory=time.time)

    def mutation_paths(self) -> list[str]:
        return list(dict.fromkeys(str(m.get("path", "")) for m in self.mutations if m.get("path")))

    def last_test_command(self) -> str:
        for run in reversed(self.runs):
            if is_test_command(str(run.get("command", ""))):
                return str(run.get("command", ""))
        return ""

    def last_reported_run(self) -> RunResult | None:
        for run in reversed(self.runs):
            command = str(run.get("command", ""))
            if not is_test_command(command):
                continue
            return RunResult(
                command=command,
                cwd=str(run.get("cwd", "")),
                exit_code=run.get("exit_code"),
                output=str(run.get("output", "")),
                duration_ms=int(run.get("duration_ms", 0) or 0),
                source="reported",
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SessionStore:
    """Small JSON store under the Hermes home so a gateway restart keeps state."""

    def __init__(self, root: Path | None = None) -> None:
        home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        self.root = root or home / "plugin-data" / "falsify"
        self.sessions_dir = self.root / "sessions"
        self.certificates_dir = self.root / "certificates"
        self._cache: dict[str, SessionRecord] = {}

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "default")[:120]
        return self.sessions_dir / f"{safe}.json"

    def get(self, session_id: str) -> SessionRecord:
        if session_id in self._cache:
            return self._cache[session_id]
        path = self._path(session_id)
        record = SessionRecord(session_id=session_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                record = SessionRecord(**{**record.to_dict(), **data})
            except (OSError, json.JSONDecodeError, TypeError):
                record = SessionRecord(session_id=session_id)
        self._cache[session_id] = record
        return record

    def save(self, record: SessionRecord) -> None:
        self._cache[record.session_id] = record
        path = self._path(record.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    def save_certificate(self, verdict: Verdict, html: str) -> Path:
        self.certificates_dir.mkdir(parents=True, exist_ok=True)
        path = self.certificates_dir / f"{verdict.certificate_id[:16]}.html"
        path.write_text(html, encoding="utf-8")
        sidecar = path.with_suffix(".json")
        sidecar.write_text(json.dumps(verdict.to_dict(), indent=2), encoding="utf-8")
        return path

    def list_certificates(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.certificates_dir.exists():
            return []
        rows: list[dict[str, Any]] = []
        for sidecar in sorted(
            self.certificates_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows.append(
                {
                    "certificate": str(sidecar.with_suffix(".html")),
                    "status": data.get("status"),
                    "reason": data.get("reason"),
                    "command": data.get("command"),
                    "created_at": data.get("created_at"),
                    "certificate_id": data.get("certificate_id"),
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def latest_certificate(self) -> Path | None:
        if not self.certificates_dir.exists():
            return None
        files = sorted(self.certificates_dir.glob("*.html"), key=lambda p: p.stat().st_mtime)
        return files[-1] if files else None


def tree_signature(repo: Path) -> str:
    """Content signature of the current worktree, used to cache verdicts.

    `git diff` covers tracked edits (including assertion changes that keep the
    same line counts), and untracked files are hashed directly so editing a new
    test invalidates a cached verdict.
    """
    parts: list[str] = []
    try:
        diff = _git(repo, "diff")
        if diff.returncode == 0:
            parts.append(diff.stdout[:2_000_000])
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        status = _git(repo, "status", "--porcelain", "-uall")
        if status.returncode == 0:
            parts.append(status.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
        if untracked.returncode == 0:
            for relative in untracked.stdout.splitlines()[:200]:
                if _CACHE_DIR_RE.search(relative) or SECRET_NAME_RE.search(relative):
                    continue
                candidate = repo / relative
                try:
                    parts.append(relative + ":" + hash_text(candidate.read_text(encoding="utf-8", errors="replace")[:200_000]))
                except OSError:
                    continue
    except (OSError, subprocess.SubprocessError):
        pass
    return hash_text("\n".join(parts))
