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
Blocked:
The required independent review gate R6 is unmet. The official initial integrated panel for `6236e0d6142ec0ceaefab8701d5c55bf8dc905ba..f5749469c859cd2f84e9484e3b624f8b2387087e` was dispatched through `claude:qwen-l40s:medium` and exited with code 2. All three native reviewer contexts ended with API 400 `ContextWindowExceededError`; the panel produced no verdict. The reserved round was refunded and consumed zero tokens. No context reset, retry, model or harness fallback, or alternate review route was used.

Source validations and local safety gates are green, but they do not satisfy R6. The independent implementation review has no valid verdict, and the required independent specification-completion review is therefore not complete. Keep the source unpublished and defer active installation until the required reviews succeed against the final candidate SHA. The candidate pin remains provisional.

Evidence is in `.git/maintenance/20261024/maintenance-review-dispatch.log`, `.git/maintenance/20261024/review-runtime-evidence.json`, and the three native reviewer profiles under `.git/maintenance/20261024/reviewer-claude/projects/-Users-julien-Worktrees-flow-next-maintenance-20261024/` (`bc0b0629-ec20-43b8-bf26-fe1ba804be9f.jsonl`, `d50f9504-ca68-42f8-8831-744563baef08.jsonl`, and `0ffff298-c520-4256-8f55-0d26fca59fc7.jsonl`).

This review infrastructure failure does not implicate OAP or its FN-60 protective stop. OAP was not changed or used for this review. Qwen analytical fixes and benchmark work remain outside this maintenance scope.

Blocked:
The required independent review gate R6 is unmet. The official initial integrated panel for `6236e0d6142ec0ceaefab8701d5c55bf8dc905ba..f5749469c859cd2f84e9484e3b624f8b2387087e` was dispatched through `claude:qwen-l40s:medium` and exited with code 2. All three native reviewer contexts ended with API 400 `ContextWindowExceededError`; the panel produced no verdict. The reserved review round was refunded; the task has zero consumed implementation-review rounds. Native provider token usage was not aggregated for this maintenance report. No context reset, retry, model or harness fallback, or alternate review route was used.

Source validations and local safety gates are green, but they do not satisfy R6. The independent implementation review has no valid verdict, and the required independent specification-completion review is therefore not complete. Keep the source unpublished and defer active installation until the required reviews succeed against the final candidate SHA. The candidate pin remains provisional.

Evidence is in `.git/maintenance/20261024/maintenance-review-dispatch.log`, `.git/maintenance/20261024/review-runtime-evidence.json`, and the three native reviewer profiles under `.git/maintenance/20261024/reviewer-claude/projects/-Users-julien-Worktrees-flow-next-maintenance-20261024/` (`bc0b0629-ec20-43b8-bf26-fe1ba804be9f.jsonl`, `d50f9504-ca68-42f8-8831-744563baef08.jsonl`, and `0ffff298-c520-4256-8f55-0d26fca59fc7.jsonl`).

This review infrastructure failure does not implicate OAP or its FN-60 protective stop. OAP was not changed or used for this review. Qwen analytical fixes and benchmark work remain outside this maintenance scope.
## Evidence
- Commits:
- Tests:
- PRs:
