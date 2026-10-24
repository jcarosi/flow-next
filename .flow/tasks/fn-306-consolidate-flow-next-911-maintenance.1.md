---
satisfies: [R1, R2, R3, R4, R5, R6, R7]
---
# fn-306-consolidate-flow-next-911-maintenance.1 Integrate qualified Flow 9.1.1 adaptations and validate safe release

## Description
### Goal

Finish the maintenance candidate on the named upstream-based branch. First consolidate the already-qualified upstream 9.1.1 source and guards, then adapt the still-needed strict Claude terminal/fallback-cache corrections from PR #546 and Copilot effort/attribution corrections from PR #567. Reuse the existing configurable Copilot file-diff writer from `50483d55`; do not add a second writer or import stale Flow bookkeeping from the PR branches.

Use offline disposable fixtures for `--auto` guard outcomes; a correct `NEEDS_HUMAN` refusal counts as success. Do not launch real OAP or Qwen workflows. Preserve upstream changes and all current Flow metadata outside this one new spec and task.

### Evidence and release gates

Keep focused test logs and the final full-suite, lint, generated-artifact and smoke logs in the private maintenance evidence directory. The exact effective independent reviewer route and completion review must cover the final candidate before it is described as validated or published. Prepare the supported host installation and rollback copy; defer activation while observed Codex processes may be using it. The required R6 maintenance reviews are release gates; the prohibition on Qwen campaigns excludes lab benchmarks and exploratory runs, not these reviews.

Publish only a validated, fast-forward update to the verified fork destination.
## Acceptance
- **R1:** The versioned candidate preserves the qualified upstream and fork behavior, guards, canonical generated mirrors, and focused regressions.
- **R2:** Claude failure/success/fallback-cache and Copilot effort plus exact configured-file-diff behavior have regression evidence; no duplicate writer is introduced.
- **R3:** Isolated clean/dirty, ready/unready, and blocker fixtures verify exact protective verdicts, no reviewer dispatch, and preserved durable state.
- **R4:** Supported installation staging, path/provenance/config preservation, rollback, and process-safety evidence are recorded; any unsafe activation is deferred.
- **R5:** Full repository tests, pinned lint, generation checks, affected regressions, and supported host smoke checks pass.
- **R6:** The effective configured independent implementation review and required completion review cover the final candidate with route evidence.
- **R7:** Only validated commits fast-forward to the confirmed fork destination, or the candidate stays local with a documented safety reason and rollback path.


## Done summary
# FN-306 implementation task completion

Integrated upstream Flow-Next 9.1.1 and retained the qualified fork behavior in commits `3ba43041` (upstream integration), `9984078c` (durable pilot admission regressions), and `08c782f6` (Claude/Copilot adapter corrections). FN-306 task/scope records were added at `f5749469`; the task-scoped Copilot/Opus authorization is recorded at `fe1bd4f1`. The configured Copilot diff-delivery key remains compatible and invalid values still fail closed. No unqualified Qwen laboratory prototype was imported, and no live OAP file or workflow was touched.

Validation passed on the resumed candidate: the full parallel suite completed at `fe1bd4f1` with 223 files, 4,164 tests, zero failures/errors, and 14 skips; Ruff passed; generated mirror, manifest, schema, documentation-link, and FN-306 validation checks passed. Eleven offline smoke suites and 18 staged command smokes passed. Staged source/install comparison recorded 443 byte matches with zero mismatches and 16/16 custom/config preservation checks. Disposable OAP safety fixtures covered six scenarios on seven targets, and the durable five-test guard module passed; these fixtures did not access OAP or start its workflow or a reviewer. The provenance run had 70 tests run and seven opt-in live cases skipped. Detailed non-secret logs and their SHA-256 manifest are in `.flow/tmp/maintenance-evidence/README.md`.

The official initial integrated implementation review finalized `SHIP` for `6236e0d6142ec0ceaefab8701d5c55bf8dc905ba..fe1bd4f176a59d5eb6faf7626b789fcdb2306d18` through `copilot:claude-opus-5.5:high`. Its native receipt records correctness, contracts, and integration as `SHIP`, with no failed draws. Correctness/contracts parser-format variants were handled through the documented legacy `--merged-file` finalizer; the native draw verdicts were preserved and the finalizer derived the worst-draw verdict. No verdict was fabricated. The initial Qwen panel remains a historical failed no-verdict attempt, superseded only for this task's continuation by the user's one-task Copilot/Opus authorization. The copied receipt, merged report, and finalizer decisions are available in `.flow/tmp/maintenance-evidence/`.

The separate specification-completion review is still required; this implementation-review result does not constitute an overall maintenance `SHIP`. Active installation remains deferred under R4 because process-safety conditions have not cleared. No fork publication or PR has occurred; R7 publication remains gated on the completion review and a fresh verified non-forced fork update. Review notes retain the fail-closed compatibility-key behavior; the pre-existing Copilot triage-effort mismatch/comment remains a disclosed non-blocking follow-up and was not changed by this maintenance.

stage: plan-sync - skipped(config: planSync.enabled != true)
## Evidence
- Commits: 3ba43041c54d3dbd5806256a127a73500aac5061, 9984078c96edaddb3ffbbfaa26a17661b0bc72ef, 08c782f65b65f4bdb3682ab2d409c53b7201b25a, f5749469c859cd2f84e9484e3b624f8b2387087e, fe1bd4f176a59d5eb6faf7626b789fcdb2306d18
- Tests: Full parallel suite on fe1bd4f1: 223 files, 4164 tests, 0 failures, 0 errors, 14 skipped, 229.39s, 4 jobs; .flow/tmp/maintenance-evidence/opus-resume-full-suite.log (exit 0), Ruff check passed; .flow/tmp/maintenance-evidence/opus-resume-ruff.log, Generated mirror/manifest, config schema, docs anchors, and FN-306 spec validation passed; .flow/tmp/maintenance-evidence/parent-static-generated.log and parent-mirror-check.log, 11 offline smoke suites passed; .flow/tmp/maintenance-evidence/smoke-summary.json, 18 staged command smoke cases passed; .flow/tmp/maintenance-evidence/staged-command-smokes.json, 443 source/install byte comparisons had zero mismatches and all 16 custom/config preservation checks passed; .flow/tmp/maintenance-evidence/staged-source-correspondence.json, Disposable pilot guard fixtures: six scenarios across seven targets; durable five-test guard module passed; .flow/tmp/maintenance-evidence/OAP-PILOT-RESULTS.md, Implementation-provenance suite: 70 run, 7 opt-in live cases skipped
- PRs: