# Catalog PR

Title: `feat(plugin-catalog): add redgreen`

Body:

## What it is

RedGreen proves a code fix with a negative control. It captures the pre-change tree at the first edit (clean `HEAD`,
or a throwaway commit that includes uncommitted and untracked work), re-runs the test command the agent already ran,
then runs the same command on the old tree with the new tests overlaid. Only red-before and green-after counts.

It catches:
- a green suite that was green before the change
- a new test that also passes without the fix
- deleted assertions, skipped tests or deleted test files
- a reported run that does not reproduce
- an agent that ignores the veto: `transform_llm_output` stamps the delivered reply UNPROVEN

Every verdict gets a self-contained HTML certificate with both runs, exit codes, output hashes, the baseline commit,
the diff stat and a SHA-256 attestation.

## Surfaces

- Tools: `redgreen_check`, `redgreen_status`, `redgreen_certificate`, `redgreen_history`, `redgreen_explain`
- Hooks: `pre_tool_call`, `post_tool_call`, `pre_verify`, `transform_llm_output`, `on_session_end`
- Slash command `/redgreen`, CLI `hermes redgreen`, one bundled skill (`redgreen:negative-control`)
- Stdlib only. No desktop half, no middleware, no core imports.

## Disclosure (rule 13)

- **Shell runs.** RedGreen runs the exact test command the agent already ran in this session. A simple command runs
  as an argv list, not through a shell; commands with pipes, redirection or inline env assignments fall back to the
  shell. No separate hidden command is registered.
- **Environment.** Test processes get a minimal environment (PATH, HOME, locale, TMPDIR, language toolchain
  variables). Provider keys and tokens are not inherited. There is a test that proves `OPENAI_API_KEY` does not
  reach the child.
- **Reads.** The plugin reads the git repository and the changed test files. It creates temporary worktrees under the
  system temp directory and removes them in a `finally` block.
- **Snapshot.** The pre-change tree is recorded as a throwaway commit through a temporary index. The real index,
  working tree and stash are never written. The objects are loose until `git gc`. `.env`, keys, `auth.json` and
  credential files are excluded from the snapshot and from signature hashing.
- **Storage.** JSON and HTML under `~/.hermes/plugin-data/redgreen/`.
- **Network.** None. **Credentials.** None. No background process, no telemetry.
- **Approvals.** The plugin does not introduce commands; it re-runs the command the user already let the agent run.
  It never disables or routes around Hermes's approval system.

## Why it is not a duplicate of `falsify` (#150860)

Independent implementation, no shared code. `falsify` asks the model to pre-register a claim and a check before it
changes anything, judges reverted copies, and never blocks completion. RedGreen captures the baseline itself, so no
pre-registration is needed; it blocks completion; and it proves the changed tests specifically by overlaying them on
the old tree. It also mints a certificate.

## Validation

- `python3 -m unittest discover -s tests` → 16 tests, OK
- `python3 demo.py` → red before, green after, certificate
- `python3 demo_plugin.py` with the Hermes plugin manager → veto, proof, badge
- `scripts/validate_plugin_catalog.py` on the entry → OK
- 60-second demo: [redgreen-demo.mp4](https://github.com/shahaman098/hermes-redgreen/blob/c4b162c72e9555ecc7930c2a367dab6ae0ccd60d/redgreen-demo.mp4)
