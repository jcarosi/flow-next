---
satisfies: [R2, R5, R6, R7]
---
# fn-305-native-implementation-provenance-with.2 Resolve cross-platform provenance and review fixture regressions

## Description
Post-PR CI at a9455a73 reproduced the pre-existing Copilot main-branch fixture failure on Ubuntu and Windows and a new native-root validation incompatibility on Windows. Preserve prior successful implementation/completion receipts, repair only confirmed causes, keep all path/security assertions, rerun affected tests and independent scoped reviews before closing and updating the same PR.

## Acceptance
Copilot frozen-file tests pass with main/master/custom initial branches; valid supported repository roots reach semantic request validation on supported hosts, or unsupported native-platform scope is explicit and fail-closed with accurate tests; no broad alias/drive/ADS bypass; relevant suites and CI pass; packaged independent Opus/Copilot reviews verify corrections and final completion.

## Done summary
Resolved the three confirmed causes from first CI39296460878 (failed on a9455a73, preserved as failure). The pre-existing Copilot completion fixture now detaches the candidate and pins main to base without changing exact frozen-diff, route, denial or resume assertions; 8 tests pass for main/master/custom initial branches. The native adapter already accepted POSIX paths only; it now explicitly rejects non-POSIX before repository/Git/RPC/client access, with a no-read regression and accurate Windows unsupported/macOS live/Linux fixture documentation. Default-off and strict path rules are unchanged. The standalone no-write fixture disables only its local Git automatic gc/maintenance before commit, preventing maintenance.lock races while retaining full filesystem/no-state assertions. Full suite4126 tests222files0fail0errors14skips in140.06s under init.defaultBranch=main, full Ruff/schema/manifest/mirror checks pass. Updated official isolated installer matches runtime source; 7 actual native-history CLI tests pass in15.090s on macOS with the final two-child union fixture. Three independent packaged Copilot claude-opus-5.5 medium draws f1e5f394-e701-4ac4-8e73-76dcad0b6d1b,17220045-9ca5-4a23-9b51-20629802ae60,53050a78-8a5a-4dca-994f-a115feb24298 all returned SHIP on a9455a73..a828d910; each actually read all210 frozen diff lines, shell/write denied, no test execution by reviewers. Formal finalizationRID1d1cffe8b2fe439891095a001f77eb9b SHIP, no blocking findings. Native proof and CI causes/logs are in .flow/tmp/provenance-review-context/ci-repair-validation.json and /tmp/flow-provenance-20261019/copilot-ci-repair-native-provenance.json (copy inside review context follows). Renewed independent completion review and second exact-head CI are pending, so PR1 remains draft. Historical global verifier/shared installation still untouched; user explicitly defers replacement until integration/install/E2E. No native Windows or Linux transport E2E guarantee is claimed. No application edits or default reviewer changes.

stage: plan-sync - skipped(config: planSync.enabled != true)
## Evidence
- Commits: a828d9107e57787f42fa2b245f52f29650e78192
- Tests: env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=init.defaultBranch GIT_CONFIG_VALUE_0=main python3 scripts/run_tests_parallel.py --jobs 10, uvx ruff@0.16.0 check .
- PRs: