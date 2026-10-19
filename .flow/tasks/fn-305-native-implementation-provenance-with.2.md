---
satisfies: [R2, R5, R6, R7]
---
# fn-305-native-implementation-provenance-with.2 Resolve cross-platform provenance and review fixture regressions

## Description
Post-PR CI at a9455a73 reproduced the pre-existing Copilot main-branch fixture failure on Ubuntu and Windows and a new native-root validation incompatibility on Windows. Preserve prior successful implementation/completion receipts, repair only confirmed causes, keep all path/security assertions, rerun affected tests and independent scoped reviews before closing and updating the same PR.

## Acceptance
Copilot frozen-file tests pass with main/master/custom initial branches; valid supported repository roots reach semantic request validation on supported hosts, or unsupported native-platform scope is explicit and fail-closed with accurate tests; no broad alias/drive/ADS bypass; relevant suites and CI pass; packaged independent Opus/Copilot reviews verify corrections and final completion.

## Done summary
TBD

## Evidence
- Commits:
- Tests:
- PRs:
