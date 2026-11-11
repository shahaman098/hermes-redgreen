# RedGreen submission state, 11 Nov 2026

Deadline 5:00 PM EST = 22:00 GMT. **This folder (`hermes-redgreen`) is the only active project.** The old Falsify repo
is parked at `../hermes-falsify-parked`; nothing from it is submitted.

## What is merged from Falsify
- AST tamper guard (catches `assert True` rewrites), double-entry ledger in the certificate, 1200x630 proof card,
  and a tamper benchmark (`benchmarks/run_benchmarks.py`: AST 30/30, 0 false alarms; old text counter 20/30, 5 false alarms).
- 25 tests pass. The plugin loads and runs in the real Hermes plugin manager.
- New video: `~/Desktop/redgreen-demo.mp4` (88 s) and `redgreen-demo.srt`.

Platform list: `submission/PLATFORMS.md` (only **GitHub catalog PR + X + Typeform**; no Devpost).

## Still on you, in order
1. ~~Commit and push (pin `339fde5`)~~ done.
2. Catalog PR #153734: bump on fork branch `catalog-redgreen` (yaml + PR body from `submission/PR_BODY_UPDATE.md`) — agent pushes fork; you confirm CI.
3. ~~Post on X~~ done: https://x.com/KrisKumarS26166/status/2120597112388047027
4. ~~Typeform~~ **Submitted** 2026-11-11 (browser: Title RedGreen, email aman.k.sah@outlook.com, Discord shahaman098, X + PR #153734). If plugin description looked truncated on their side, paste the full text from `TYPEFORM.md` via `Again` or email Nous.
5. Rotate the ElevenLabs key (used again for this render).

Fallback: the old pin `c4b162c` is still a valid entry; it just lacks the guard, ledger and card shown in the video.
