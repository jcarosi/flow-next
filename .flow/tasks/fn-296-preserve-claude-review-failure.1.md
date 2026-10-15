---
satisfies: [R1, R2, R3]
---
# fn-296-preserve-claude-review-failure.1 Preserve bounded Claude result failure diagnostics

## Description
Diagnose the official Claude error result without accepting verdict text from failures. Retain safe structured envelope fields in normal failure output. Run focused regression tests and generated-source checks.

## Acceptance
All R1-R3 in the parent spec are satisfied; preserve failing SHIP-tag rejection and explicit model pin no-fallback behavior.

## Done summary
Blocked:
verification failed: coordinator thread has native fileChange entries: /Users/julien/Dev/flow-next-claude-review-recovery/.flow/tmp/claude-result-diagnostics-plan.md
## Evidence
- Commits:
- Tests:
- PRs:
