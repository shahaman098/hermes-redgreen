## RedGreen

**What it does:** When an agent claims a bug is fixed, RedGreen does not trust the transcript. It re-runs the test command on the current worktree, reconstructs the pre-change tree (including uncommitted work via a throwaway index commit), overlays only new/changed test files, and runs the same command again. Only **red before + green after** counts as proof. Anything else is a precise veto (`UNPROVEN`, `FABRICATED`, `TAMPERED`, etc.). Python test files are also checked on their AST, so an assertion rewritten to `assert True` (same assertion count) is caught as `TAMPERED`. Each certificate also lists a double-entry ledger (changed files are debits, a proven negative control is the credit) and writes a 1200x630 proof card. Benchmark (`benchmarks/run_benchmarks.py`, 50 synthetic scenarios): AST guard 30/30 tampering caught, 0/20 false alarms; the earlier text counter 20/30 and 5/20. If the model ignores the veto, `transform_llm_output` stamps the delivered message **UNPROVEN**.

**Hermes surfaces used:** `pre_tool_call` / `post_tool_call` (mutation + test-run capture), `pre_verify` (completion gate), `transform_llm_output` (stamp), `on_session_end`, five tools, `/redgreen` command, bundled `redgreen:negative-control` skill, `hermes redgreen` CLI.

**Disclosure (rule 13):**
- **Git:** reads repo state; creates temporary `git worktree`s under the system temp directory; may write loose objects via a temporary index for dirty snapshots (never touches real index/stash).
- **Shell:** runs the same test-runner command the agent used (`pytest`, `npm test`, etc.) — argv-safe when possible; minimal env (PATH, locale, toolchain vars; provider keys stripped).
- **Local storage:** `~/.hermes/plugin-data/redgreen/` for verdict JSON and self-contained HTML certificates.
- **Network:** none. No telemetry. No API keys required.
- **Credentials:** does not read `.env`, `auth.json`, or external credential stores.

**Validation:** 25 unit tests, `python3 demo.py` and the plugin-manager demo run at the pinned `<NEW_PIN_SHA>`. `hermes plugins validate` was run on `6bff19441bd64e6337a6cb7f955f62a3aea46ecb`; the delta to the pin is one veto-message string and the re-cut video. Catalog CI validates the pin itself.

**Demo:** https://github.com/shahaman098/hermes-redgreen/blob/<NEW_PIN_SHA>/redgreen-demo.mp4 (~85s). Offline repro: `python3 demo.py`.

