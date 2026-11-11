# Typeform answers

Form: https://form.typeform.com/to/FwJLvOln  
Deadline: 5PM EST, 11 Nov 2026 (22:00 GMT).

## Copy-paste (last step)

| Field | Value |
| --- | --- |
| Plugin title | `RedGreen` |
| Catalog PR | https://github.com/NousResearch/hermes-agent/pull/153734 |
| Demo on X | https://x.com/KrisKumarS26166/status/2120597112388047027 |
| Repo | https://github.com/shahaman098/hermes-redgreen |

The form starts with:

1. **Plugin Title** → `RedGreen`
2. **Plugin Description** → see below
3. **Email Address** → your email

Later steps ask for the links; have these ready:

- Catalog PR: https://github.com/NousResearch/hermes-agent/pull/153734
- Demo video on X: https://x.com/KrisKumarS26166/status/2120597112388047027

## Plugin Description

RedGreen proves a fix with a negative control. It captures the pre-change tree at the first edit, re-runs the
agent's test command itself, then runs the same command on the old tree with the new tests overlaid. Only red without
the fix and green with it counts. It catches tests that pass either way, deleted assertions, assertions weakened to `assert True` (detected from the Python AST, so the assertion count never gives it away), skipped cases, and test
results that never reproduced, and it stamps the final reply UNPROVEN when the model tries to finish anyway. Every
proof is a signed HTML certificate with both runs, exit codes, output hashes and a SHA-256 attestation. It also keeps a double-entry ledger (changed files are debits, a proven negative control is the credit) and exports a 1200x630 proof card. On 50 synthetic scenarios the AST guard caught 30/30 tampering attempts with 0 false alarms; the earlier text counter caught 20/30 with 5 false alarms (benchmarks/run_benchmarks.py). Zero
dependencies, local, no API key.
