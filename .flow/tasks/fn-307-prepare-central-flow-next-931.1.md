---
satisfies: [R1, R2, R3, R4, R5, R6]
---
# fn-307-prepare-central-flow-next-931.1 Integrate and validate isolated 9.3.1 candidate

## Description
TBD

## Acceptance
All parent acceptance criteria R1-R6 are satisfied and independently reviewed; report any gate that remains incomplete.

## Done summary
Integrated official Flow-Next 9.3.1 with preserved fork behavior and isolated host staging. Qualified initial and correction implementation reviews returned SHIP; two renderer regressions are fixed. Full suite: 4163 tests, zero failures/errors, 14 skipped; final affected tests and Ruff pass. The unchanged search guard has one documented nonblocking possible false positive. Shared installations and applications remain untouched. Separate completion review and publication checks remain pending.

stage: plan-sync - skipped(config: planSync.enabled != true)
## Evidence
- Commits: 32e2f06bcab477c46087f05beb3ca5710e7cb94f, 6a836d17ddb29d2b8590378416908f1f32d7ad97, 3d350523c3c2e0402ba33da4523c06750cd636c4, 4dd27eaa0dff33c442c6b7eb37c18dcf8e14af54
- Tests: python3 scripts/run_tests_parallel.py:223files4163tests0fail0error14skip, python3 -m unittest test_pr_cognitive_aid_briefing:23passed after fixture-onlysentinelrefinement, uvx ruff@0.16.0 check .:passed, tracker manifest:49files verified; Codexmirrorfresh, make-pr/impl-review/ci functional smokes passed on source integration; renderer-focused73tests passed aftercorrection, isolated Codex/OpenCode installs and Claudepackage correspondence/launcherspassed
- PRs: