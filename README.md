# Falsify

**A test only proves a fix when it fails without the fix.**

Falsify is a Hermes Agent plugin that refuses to let an agent call a bug fixed until the test it ran is a real
negative control: red on the pre-change tree, green on the current one. It does not read the transcript and
trust it. It re-runs the command itself, twice.

[![Tests](https://img.shields.io/badge/tests-12_passing-success.svg)]()
[![Dependencies](https://img.shields.io/badge/dependencies-zero_(stdlib)-brightgreen.svg)]()
[![Hermes](https://img.shields.io/badge/Hermes_Agent-plugin_v1.0-blue.svg)]()

![Falsify certificate](assets/certificate.png)

## The problem: a passing suite is not proof

An agent edits `pricing.py`, runs `pytest`, sees `3 passed`, and says:

> Fixed. All tests pass.

It is telling the truth about the suite and lying about the fix. The suite was green before the change too.
No test in it can tell the buggy code from the fixed code, so the run proves nothing. The same failure shows up
as a test that asserts nothing, a test that was skipped, or a reported result that never happened.

Hermes already has verify-on-stop: it nudges an agent that edited code without running checks. That catches
"did you run anything?". Falsify answers the next question: **could the test have failed?**

## The rule

> A test only proves a fix when it is red without the fix and green with it.

That second run is the **negative control**. It is the oldest idea in experimental science and the missing half
of most agent verification.

## How it works

```
                  first code edit
                        │
                        ▼
        snapshot the pre-change tree
        (clean HEAD, or a throwaway commit that
         includes the user's uncommitted work)
                        │
   agent runs pytest ───┤  the run is recorded
                        │
   agent says "done" ───┤
                        ▼
        ┌─────────────────────────────────────────┐
        │ 1. re-run the command on the worktree   │  green
        │ 2. build the pre-change tree            │
        │ 3. overlay the new/changed test files   │
        │ 4. run the same command there           │  red
        └─────────────────────────────────────────┘
                        │
          red before + green after = PROVEN
          anything else = a precise veto
```

1. **Snapshot.** On the first mutation in a git repository, Falsify records the pre-change tree. A clean tree
   is pinned at `HEAD`. Uncommitted work is captured as a throwaway commit through a temporary index, so the real
   index, working tree and stash list are never touched. It also covers untracked files.
2. **Re-run.** When the agent claims completion, Falsify runs the test command itself. The transcript is not
   evidence. If the reported result does not reproduce, the claim is marked **FABRICATED**.
3. **Negative control.** It creates a temporary `git worktree` at the baseline, overlays the tests and test
   config that changed (never the source), links installed dependencies, and runs the same command.
4. **Classify.** Red before and green after is proof. Green on both sides means the test cannot discriminate.
   A failure that is not in the changed tests does not count. A test that was weakened on the way does not count.
5. **Certificate.** A signed, self-contained HTML proof page with both runs, exit codes, output hashes, the diff
   and a SHA-256 attestation.

If the model ignores the veto and finishes anyway, `transform_llm_output` stamps the delivered reply **UNPROVEN**
with the reason. The user never receives the lie.

## Demo

No model, no API key, no network:

```bash
python3 demo.py
```

The demo builds a real git repository with a real bug, plays a scripted agent that "fixes" it with a test that
cannot fail, and then runs the same engine the plugin uses.

```text
[falsify] UNPROVEN · The negative control failed: the new/changed test also
          passes on the pre-change tree. It cannot tell the bug from the fix.

  FALSIFY · UNPROVEN
  ────────────────────────────────────────────────────────────────────
  without change GREEN  exit 0    3 passed, 0 failed
  with change    GREEN  exit 0    3 passed, 0 failed
  ────────────────────────────────────────────────────────────────────
  command  python3 -m pytest -q

[agent]   Fine: add a test that actually describes the missing cap.
[agent]   ran `python3 -m pytest -q` -> 4 passed, 0 failed

[falsify] PROVEN · Proof of fix: the command is red without the change and
          green with it (test_discount_is_capped_at_fifty fails before).

  FALSIFY · PROVEN
  ────────────────────────────────────────────────────────────────────
  without change RED    exit 1    3 passed, 1 failed
  with change    GREEN  exit 0    4 passed, 0 failed
  ────────────────────────────────────────────────────────────────────
  sha256   0c7a77c500c37b2ab30c8521274936d5c2252c64
```

It ends by writing `demo-certificate.html`.

## Install

From the catalog (once listed):

```bash
hermes plugins install falsify
hermes plugins enable falsify
```

From the repository:

```bash
hermes plugins install shahaman098/hermes-falsify --enable
```

Local development:

```bash
cp -R . ~/.hermes/plugins/falsify
hermes plugins enable falsify
```

Restart Hermes. The plugin is opt-in like every general plugin.

## Using it

Nothing to configure. Edit code, run a test command, finish. Falsify checks the run.

The agent also gets five tools:

| Tool | What it does |
| --- | --- |
| `falsify_check` | Run the negative control now. Returns PROVEN or the exact reason it is not. |
| `falsify_status` | Baseline, changed files, runs seen, last verdict. |
| `falsify_certificate` | Write or open the HTML proof page. |
| `falsify_history` | Recent proofs. |
| `falsify_explain` | The rule and the workflow. |

And a slash command:

```text
/falsify            latest proofs
/falsify explain    the rule
```

A bundled skill, `falsify:negative-control`, teaches the agent the workflow: reproduce, watch it fail, fix,
watch it pass.

## What counts as proof

| Verdict | Meaning |
| --- | --- |
| **PROVEN** | The command is red without the change and green with it. |
| UNPROVEN (no test) | The suite is green on both sides and no test changed. A passing suite is not proof. |
| UNPROVEN (weak) | The new test also passes without the fix. It cannot discriminate. |
| TAMPERED | A test file lost assertions, test cases or was skipped/deleted while proving the fix. |
| UNPROVEN (import) | The test cannot load on the old tree. That proves absence, not a behavior change. |
| NOT DONE | The command is red now. |
| FABRICATED | The reported run was green, but Falsify's own run is red. |
| UNPROVEN (no command) | No test command was run. |
| INCONCLUSIVE | The command timed out. Run the targeted test. |
| UNPROVEN (unrelated) | The pre-change failure was not in a test this change touched. |

Refactors use `mode: preserve`, where the command must be green on both sides.

## Tamper checks

Before a green-before verdict or a proven one, Falsify compares the changed test files with their baseline
version and reports:

- test definitions that disappeared
- assertions that disappeared
- added `skip`, `xfail`, `todo` or `ignore` markers
- test files that were deleted

None of these can rescue a claim.

## Configuration

Environment variables, all optional:

| Variable | Default | Meaning |
| --- | --- | --- |
| `FALSIFY_TIMEOUT` | `120` | Seconds for each run, current and before. |
| `FALSIFY_MODE` | `fix` | `fix` requires red-before/green-after. `preserve` requires green on both. |
| `FALSIFY_STAMP` | `1` | Stamp an unproven final message with the reason. |

Full suites are run twice. On a large repository, run the targeted test (`pytest tests/test_pricing.py`) and
Falsify only re-runs that.

## Safety and disclosure

Falsify reads your git repository, creates temporary worktrees under the system temp directory, runs the test
command the agent already ran, and writes JSON and HTML under `~/.hermes/plugin-data/falsify/`.

- No network calls, no API keys, no credentials, no telemetry.
- Test commands are executed through the user's shell, like Hermes's terminal tool. Only commands matching a
  test-runner pattern are accepted, and `falsify_check` refuses anything else.
- The temporary worktree is removed in a `finally` block, and stale worktrees are pruned.
- The plugin never overwrites the real working tree, index or stash.
- Installed dependency directories (`node_modules`, `.venv`, `venv`, `vendor`) are symlinked into the temporary
  tree so the old side does not fail for a missing dependency.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 demo.py
```

The 12 engine tests build real git repositories. No mocks. They cover clean and dirty baselines, untracked test
files, weak tests, failing fixes, fabricated results, deleted assertions and command detection.

## Limitations

- **Needs git.** Outside a repository there is no pre-change tree, so Falsify does not gate. It degrades quietly.
- **Flaky tests** produce flaky proofs. The certificate records both exit codes and output hashes so the evidence
  is inspectable.
- **Generated or deleted source** can make the old tree fail to collect. That is reported as an import error, not
  a proof.
- **Behavior changes without a test** cannot be proven. That is the point.
- **Very slow suites** need the targeted test command or a larger timeout.

## Why this is not a prompt

A prompt can ask an agent to reproduce a bug. It cannot:

- reconstruct the exact pre-change tree, including uncommitted and untracked work
- run the command itself and compare the agent's report with reality
- overlay only the new tests, so the source keeps the bug
- detect that a test was weakened
- mint a deterministic certificate over both runs
- stamp the delivered message when the model ignores all of it

## License

MIT.
