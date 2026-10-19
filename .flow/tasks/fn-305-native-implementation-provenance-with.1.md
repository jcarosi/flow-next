---
satisfies: [R1, R2, R3, R4, R5, R6, R7]
---
# fn-305-native-implementation-provenance-with.1 Integrate native provenance and validate scoped coordination

## Description
Implement generic opt-in native Codex provenance at the existing task transition, a reusable native-history adapter and final candidate integrity checks; validate audit scenarios A–P in isolation, preserve default-off compatibility and review/installation contracts.

## Acceptance
R1–R7; focused native-history, candidate integrity, CLI and compatibility suites plus repository final tests and independent implementation/completion reviews.

## Done summary
Implemented the generic opt-in Codex native provenance gate and shared verifier at the existing done boundary. Native parent/child identity, configured roles, exact predispatch declarations, supported file-change replay, full Git/index/disk candidate checks and registered linked worktrees now bind integrated delegations. Per-child task declarations support rolling and wave unions; inert Flow coordination is checked by existing content contracts without per-event exceptions. Fixed all eight initial Copilot findings and two factual documentation notes. Full suite 4125 tests, zero failures/errors, 14 expected skips; Ruff and generated mirror/manifest checks pass. Seven real native-history CLI checks pass, plus real linked-worktree done and two-task rolling union/done; omitting the first delegation is refused. Initial review f97a93ec1d764299962cfe3127301550 NEEDS_WORK, followed by packaged Copilot claude-opus-5.5 medium SHIP reviews at64a7716e and745c1150. Actual native reads close the residual global scope gaps; .flow/tmp/provenance-review-context/copilot-final-scope-native-provenance.json records verified coverage. Read-only shell/write restrictions retained; previous wrong-harness401 remains interrupted without verdict. Standing reviewer unchanged. R1/R5 architecture and A-P evidence are available to the completion reviewer under .flow/tmp/provenance-review-context/architecture-decision.md, 2026-10-19-provenance-architecture.md (historical draft, old auth/status superseded), correction-validation.json, rolling-native-results.json, native-sandbox-probe.json, and global-candidate.diff plus candidate-global actual files. Outside-Flow staged launcher delegates to the SAME shared core; manifest says prepared_only_uninstalled. User explicitly defers historical global verifier replacement and shared installation until later integration/install/E2E verification. Active485 baseline files unchanged, active8.7.0 source50483d5 unchanged. Official isolated candidate installation matches current source hashes; backup/rollback prepared and tested. Codex role instructions are procedural, unsigned receipts detective; ignored/outside/transient or identical effects and unavailable real MCP transport remain documented limits. No real app writes or protection changes; concurrent LetzLearn/Xposed work belongs to separate sessions and is preserved. Independent completion review is still pending; push/PR only after its satisfactory verdict, never merge.

stage: plan-sync - skipped(config: planSync.enabled != true)
## Evidence
- Commits: 62dcb6588b201b412459a0c2286aa3c148429617, 149c172bdc7644bf104bbf30d52191a8bdc08406, 1e2b3b5e71d37800cdc2fa190fc8055c922392fd, 4cc52a61fd6deb757a968bdcf2016531f56b0028, 64a7716e8d35a7d2b32783d160ecd7010be3334c, 745c115087ab3da0341f6da3551b4cd48c5c6c47
- Tests: python3 scripts/run_tests_parallel.py --jobs 10, uvx ruff@0.16.0 check .
- PRs: