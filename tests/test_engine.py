"""Engine tests: every one builds a tiny real git repo, no mocks."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


class RepoFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="redgreen-test-")
        self.repo = Path(self._tmp.name) / "shop"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        write(
            self.repo / "pricing.py",
            """
            def apply_discount(subtotal, percent=20.0, cap=50.0):
                discount = subtotal * (percent / 100.0)
                return round(subtotal - discount, 2)
            """,
        )
        write(
            self.repo / "tests" / "test_pricing.py",
            """
            from pricing import apply_discount

            def test_small_order():
                assert apply_discount(40) == 32.0

            def test_zero_percent():
                assert apply_discount(80, percent=0) == 80.0
            """,
        )
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "baseline")
        self.baseline = git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fix(self, with_regression_test: bool = True) -> None:
        write(
            self.repo / "pricing.py",
            """
            def apply_discount(subtotal, percent=20.0, cap=50.0):
                discount = min(subtotal * (percent / 100.0), cap)
                return round(subtotal - discount, 2)
            """,
        )
        if with_regression_test:
            test_path = self.repo / "tests" / "test_pricing.py"
            test_path.write_text(
                test_path.read_text()
                + "\n\ndef test_discount_is_capped():\n    assert apply_discount(1000) == 950.0\n",
                encoding="utf-8",
            )


class VerifyTests(RepoFixture):
    def test_red_before_green_after_is_proven(self) -> None:
        self.fix(with_regression_test=True)
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=self.baseline,
            baseline_kind="head",
            command="python3 -m pytest -q",
            timeout=30,
        )
        self.assertEqual(verdict.status, "proven", verdict.reason)
        self.assertTrue(verdict.current and verdict.current.green)
        self.assertTrue(verdict.before and verdict.before.red)
        self.assertIn("tests/test_pricing.py", verdict.changed_test_files)
        self.assertTrue(verdict.certificate_id)

    def test_green_before_and_after_without_a_test_is_unproven(self) -> None:
        self.fix(with_regression_test=False)
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=self.baseline,
            baseline_kind="head",
            command="python3 -m pytest -q",
            timeout=30,
        )
        self.assertEqual(verdict.status, "unproven_no_test", verdict.reason)

    def test_test_that_passes_without_the_fix_is_weak(self) -> None:
        self.fix(with_regression_test=False)
        test_path = self.repo / "tests" / "test_pricing.py"
        test_path.write_text(
            test_path.read_text()
            + "\n\ndef test_discount_still_works():\n    assert apply_discount(100) < 100\n",
            encoding="utf-8",
        )
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=self.baseline,
            baseline_kind="head",
            command="python3 -m pytest -q",
            timeout=30,
        )
        self.assertEqual(verdict.status, "unproven_weak", verdict.reason)

    def test_failing_fix_is_not_done(self) -> None:
        write(
            self.repo / "pricing.py",
            """
            def apply_discount(subtotal, percent=20.0, cap=50.0):
                return "nope"
            """,
        )
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=self.baseline,
            baseline_kind="head",
            command="python3 -m pytest -q",
            timeout=30,
        )
        self.assertEqual(verdict.status, "failing_now", verdict.reason)

    def test_missing_command_is_not_proof(self) -> None:
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=self.baseline,
            baseline_kind="head",
            command="",
        )
        self.assertEqual(verdict.status, "no_command")

    def test_reported_green_but_actually_red_is_fabricated(self) -> None:
        write(
            self.repo / "pricing.py",
            """
            def apply_discount(subtotal, percent=20.0, cap=50.0):
                raise RuntimeError("boom")
            """,
        )
        reported = core.RunResult(
            command="python3 -m pytest -q",
            cwd=str(self.repo),
            exit_code=0,
            output="2 passed in 0.01s",
            duration_ms=10,
        )
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=self.baseline,
            baseline_kind="head",
            command="python3 -m pytest -q",
            reported=reported,
            timeout=30,
        )
        self.assertEqual(verdict.status, "fabricated", verdict.reason)

    def test_untracked_test_file_is_overlaid(self) -> None:
        self.fix(with_regression_test=False)
        write(
            self.repo / "tests" / "test_cap.py",
            """
            from pricing import apply_discount

            def test_cap():
                assert apply_discount(1000) == 950.0
            """,
        )
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=self.baseline,
            baseline_kind="head",
            command="python3 -m pytest -q",
            timeout=30,
        )
        self.assertEqual(verdict.status, "proven", verdict.reason)
        self.assertIn("tests/test_cap.py", verdict.changed_test_files)

    def test_deleted_assertion_is_tamper(self) -> None:
        self.fix(with_regression_test=False)
        test_path = self.repo / "tests" / "test_pricing.py"
        write(
            test_path,
            """
            from pricing import apply_discount

            def test_small_order():
                pass

            def test_zero_percent():
                assert apply_discount(80, percent=0) == 80.0
            """,
        )
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=self.baseline,
            baseline_kind="head",
            command="python3 -m pytest -q",
            timeout=30,
        )
        self.assertEqual(verdict.status, "unproven_tamper", verdict.reason)


class GitHelpersTests(RepoFixture):
    def test_clean_repo_baseline_is_head(self) -> None:
        sha, kind = core.capture_baseline(self.repo)
        self.assertEqual(sha, self.baseline)
        self.assertEqual(kind, "head")

    def test_dirty_repo_baseline_is_a_stash_commit(self) -> None:
        write(self.repo / "notes.txt", "uncommitted")
        sha, kind = core.capture_baseline(self.repo)
        self.assertEqual(kind, "snapshot")
        show = git(self.repo, "show", "--stat", "--oneline", sha)
        self.assertEqual(show.returncode, 0)

    def test_dirty_baseline_is_used_for_the_negative_control(self) -> None:
        # The user had uncommitted work before the session: a 10% default.
        write(
            self.repo / "pricing.py",
            """
            def apply_discount(subtotal, percent=10.0, cap=50.0):
                discount = subtotal * (percent / 100.0)
                return round(subtotal - discount, 2)
            """,
        )
        sha, kind = core.capture_baseline(self.repo)
        self.assertEqual(kind, "snapshot")
        # The agent fixes the default and adds the cap in the same edit.
        self.fix(with_regression_test=True)
        verdict = core.verify(
            repo=self.repo,
            baseline_sha=sha,
            baseline_kind=kind,
            command="python3 -m pytest -q",
            timeout=30,
        )
        self.assertEqual(verdict.status, "proven", verdict.reason)
        self.assertIn("test_discount_is_capped", " ".join(verdict.failed_before))

    def test_snapshot_excludes_secret_files(self) -> None:
        write(self.repo / ".env", "API_KEY=super-secret\n")
        write(self.repo / "server.pem", "not really a key\n")
        write(self.repo / "notes.txt", "keep me\n")
        sha, kind = core.capture_baseline(self.repo)
        self.assertEqual(kind, "snapshot")
        tree = git(self.repo, "ls-tree", "-r", "--name-only", sha).stdout
        self.assertIn("notes.txt", tree)
        self.assertNotIn(".env", tree)
        self.assertNotIn("server.pem", tree)

    def test_run_does_not_inherit_provider_keys(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-should-not-leak"
        try:
            run = core.run_command(
                "python3 -c \"import os; print(os.environ.get('OPENAI_API_KEY', 'missing'))\"",
                self.repo,
                timeout=15,
            )
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
        self.assertIn("missing", run.output)
        self.assertNotIn("sk-should-not-leak", run.output)

    def test_simple_commands_run_without_a_shell(self) -> None:
        self.assertEqual(core.argv_for("python3 -m pytest -q"), ["python3", "-m", "pytest", "-q"])
        self.assertIsNone(core.argv_for("pytest; rm -rf /tmp/nope"))
        self.assertIsNone(core.argv_for("FOO=1 pytest"))

    def test_test_command_detection(self) -> None:
        self.assertTrue(core.is_test_command("python3 -m pytest -q"))
        self.assertTrue(core.is_test_command("npm test"))
        self.assertTrue(core.is_test_command("cargo test --all"))
        self.assertFalse(core.is_test_command("git status"))

    def test_test_path_detection(self) -> None:
        self.assertTrue(core.is_test_path("tests/test_pricing.py"))
        self.assertTrue(core.is_test_path("src/app.test.tsx"))
        self.assertFalse(core.is_test_path("src/pricing.py"))


if __name__ == "__main__":
    unittest.main()
