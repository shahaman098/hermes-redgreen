# RedGreen submission state, 11 Nov 2026

Deadline 5:00 PM EST = 22:00 GMT. **This folder (`hermes-redgreen`) is the only active project.** The old Falsify repo
is parked at `../hermes-falsify-parked`; nothing from it is submitted.

## What is merged from Falsify
- AST tamper guard (catches `assert True` rewrites), double-entry ledger in the certificate, 1200x630 proof card,
  and a tamper benchmark (`benchmarks/run_benchmarks.py`: AST 30/30, 0 false alarms; old text counter 20/30, 5 false alarms).
- 25 tests pass. The plugin loads and runs in the real Hermes plugin manager.
- New video: `~/Desktop/redgreen-demo.mp4` (85 s) and `redgreen-demo.srt`.

## Still on you, in order
1. Commit and push in two commits so the pin stays code-only:
   - A: `core.py report.py runtime.py demo.py tests/ benchmarks/ BENCHMARKS.md video/ assets/ redgreen-demo.mp4 README.md`. Its SHA is the new pin.
   - B: the docs that carry the SHA (`submission/`).
2. Catalog PR #153734: bump `sha` and the two raw image URLs in `plugin-catalog/redgreen.yaml` on branch `catalog-redgreen`; paste `submission/PR_BODY_UPDATE.md` as the body (replace `<NEW_PIN_SHA>`).
3. Post on X with the video and the text in `submission/X_POST.md`.
4. Typeform https://form.typeform.com/to/FwJLvOln: title `RedGreen`, description from `submission/TYPEFORM.md`, PR link, X post URL, your email, Submit.
5. Rotate the ElevenLabs key (used again for this render).

Fallback: the old pin `c4b162c` is still a valid entry; it just lacks the guard, ledger and card shown in the video.
