---
name: negative-control
description: "Prove a fix: reproduce the bug, make the test fail without the fix, then make it pass."
version: 1.0.0
author: shahaman098
license: MIT
metadata:
  hermes:
    tags: [testing, debugging, verification, tdd]
---

# The negative control

A green test only proves a fix when the same test is red without the fix. That
second run is the negative control. Falsify runs it for you.

## Workflow

1. **Reproduce before changing code.** Write the smallest test that expresses
   the reported behavior and run it. It should fail. If it passes, the test does
   not describe the bug yet.
2. **Show the failure.** Keep the command and the failing assertion.
3. **Fix the code.** Change only what the failure requires.
4. **Run the same command again.** It must pass.
5. **Finish.** Falsify re-runs the command on the current tree and on the
   pre-change tree with your test overlaid. Red before, green after is proof.

## What is not proof

- A full suite that was already green before the change.
- A new test that also passes without the fix.
- A test that was made to fail by deleting assertions or skipping cases.
- A reported test result that does not reproduce when Falsify runs it.

## Useful commands

- `pytest -q path/to/test_file.py` for the narrowest Python check.
- `npm test -- path/to/file.test.ts` or `npx vitest run path/to/file.test.ts`.
- `cargo test name_of_test`, `go test ./pkg -run Name`.
- `falsify_check` to ask for proof before claiming completion.
- `falsify_certificate` to write or open the proof page.

## Writing the regression test

Name the behavior, not the implementation. Assert the exact user-visible value:
`assert apply_discount(1000) == 950.0`, not `assert apply_discount(1000) != 800`.

If the fix is a refactor and behavior must not change, say so and use
`falsify_check` with `mode: preserve`; Falsify then requires green on both
sides.
