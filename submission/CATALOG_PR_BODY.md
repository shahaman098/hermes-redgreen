## RedGreen

**What it does:** When an agent claims a bug is fixed, RedGreen does not trust the transcript. It re-runs the test command on the current worktree, reconstructs the pre-change tree (including uncommitted work via a throwaway index commit), overlays only new/changed test files, and runs the same command again. Only **red before + green after** counts as proof. Anything else is a precise veto (`UNPROVEN`, `FABRICATED`, `TAMPERED`, etc.). If the model ignores the veto, `transform_llm_output` stamps the delivered message **UNPROVEN**.

**Hermes surfaces used:** `pre_tool_call` / `post_tool_call` (mutation + test-run capture), `pre_verify` (completion gate), `transform_llm_output` (stamp), `on_session_end`, five tools, `/redgreen` command, bundled `redgreen:negative-control` skill, `hermes redgreen` CLI.

**Disclosure (rule 13):**
- **Git:** reads repo state; creates temporary `git worktree`s under the system temp directory; may write loose objects via a temporary index for dirty snapshots (never touches real index/stash).
- **Shell:** runs the same test-runner command the agent used (`pytest`, `npm test`, etc.) — argv-safe when possible; minimal env (PATH, locale, toolchain vars; provider keys stripped).
- **Local storage:** `~/.hermes/plugin-data/redgreen/` for verdict JSON and self-contained HTML certificates.
- **Network:** none. No telemetry. No API keys required.
- **Credentials:** does not read `.env`, `auth.json`, or external credential stores.

**Validation:** `hermes plugins validate` on pinned commit `c4b162c72e9555ecc7930c2a367dab6ae0ccd60d` (see PR CI).

**Demo:** https://github.com/shahaman098/hermes-redgreen/blob/main/redgreen-demo.mp4 (60s). Offline repro: `python3 demo.py`.
