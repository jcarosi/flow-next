---
satisfies: [R1, R2, R3]
---
# fn-296-preserve-claude-review-failure.1 Port verified Claude result fix to stable 8.7.0

## Description
# Port the verified Claude result fix

### Scope

Replace fn-296's generic diagnostics expansion with the already verified
Claude result correction from the two assigned commits. Flow-Next 8.7.0 has
newer shared code, so port only the relevant Claude parser, dispatch, tests,
and documentation changes. Preserve the existing model-unavailable predicate
and review pipeline contracts.

The verified false-negative is in `run_claude_exec`: a valid successful result
can be rejected when unrelated stderr contains model-unavailable wording,
because the stderr marker is evaluated without first honoring the success
envelope. The parser also currently defaults or coerces `is_error` and accepts
a missing/non-string `result`, so malformed envelopes can be treated as
success-shaped output.

### Acceptance criteria

- **R1:** Claude stdout is accepted only as one JSON object with
  `type == "result"`, a boolean `is_error`, and a string `result`. A valid
  success envelope remains successful when stderr contains unrelated,
  non-secret text, including model-unavailable wording. Its result and session
  ID remain available to the normal review path.
- **R2:** Error envelopes, malformed or incomplete envelopes, and nonzero CLI
  exits never place reviewer text in the verdict output. Only the existing
  exact model-unavailable predicate may enter the unpinned fallback ladder;
  malformed payloads, unrelated failures, nonzero exits, and stderr attached
  to a valid success cannot trigger fallback. Explicit model pins continue to
  suppress fallback.
- **R3:** The packaged Claude review command preserves its official receipt,
  counter, refund, and diff-delivery behavior. Regression coverage exercises
  successful result plus unavailable wording on stderr, strict malformed
  envelopes, real supported unavailable fallback, nonzero/error rejection,
  and explicit-pin behavior.

### Focused validation

- Reproduce at least one success-plus-stderr regression against the unmodified
  target, then verify it passes after the port.
- Run `python3 -m unittest discover -s plugins/flow-next/tests -p 'test_claude_review_commands.py' -q`.
- Run `python3 -m unittest discover -s plugins/flow-next/tests -p 'test_model_resolution.py' -q`.
- Run `python3 scripts/gen_tracker_manifest.py` and `./scripts/sync-codex.sh`
  once, as required for `flowctl.py` changes; report generated paths.

### Boundaries

Port only the relevant changes from the two assigned commits. Do not copy the
older `flowctl.py`, add speculative diagnostics, change unrelated fallback
cache behavior, alter Flow state, or change review routing, receipts, counters,
refunds, or diff delivery.
## Acceptance
All R1-R3 in the parent spec are satisfied; preserve failing SHIP-tag rejection and explicit model pin no-fallback behavior.

## Done summary
Blocked:
verification failed: coordinator thread has native fileChange entries: /Users/julien/Dev/flow-next-claude-review-recovery/.flow/tmp/claude-result-diagnostics-plan.md
## Evidence
- Commits:
- Tests:
- PRs:
