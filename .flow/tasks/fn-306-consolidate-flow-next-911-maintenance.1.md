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
Initial implementation-review attempt — blocked, no verdict:

The official integrated panel for `6236e0d6142ec0ceaefab8701d5c55bf8dc905ba..f5749469c859cd2f84e9484e3b624f8b2387087e` was dispatched through `claude:qwen-l40s:medium` and exited with code 2. All three native reviewer contexts ended with API 400 `ContextWindowExceededError`; the panel produced no verdict. The reserved review round was refunded and zero implementation-review rounds were consumed. Provider token usage was not aggregated, so this is not evidence of zero token use. No `SHIP` was produced.

Source validations and local safety gates do not satisfy R6. At this block, the implementation review had no valid verdict and the required specification-completion review had not run. The candidate was unpublished; active installation remained deferred, and the candidate pin remained provisional.

Evidence is in `.git/maintenance/20261024/maintenance-review-dispatch.log`, `.git/maintenance/20261024/review-runtime-evidence.json`, and the three native reviewer profiles under `.git/maintenance/20261024/reviewer-claude/projects/-Users-julien-Worktrees-flow-next-maintenance-20261024/` (`bc0b0629-ec20-43b8-bf26-fe1ba804be9f.jsonl`, `d50f9504-ca68-42f8-8831-744563baef08.jsonl`, and `0ffff298-c520-4256-8f55-0d26fca59fc7.jsonl`).

This review infrastructure failure does not implicate OAP or its FN-60 protective stop. OAP was not changed or used for this review. Qwen analytical fixes and benchmark work remain outside this maintenance scope.

Current authorized resumption — R6 still pending:

> user: "je tautorise exceptionnellement copilot/opus 5.5 pour aller au bout"

For FN-306 only, the user authorizes the exact per-run route `copilot:claude-opus-5.5:high` for the required implementation and separate specification-completion reviews. This exception preserves the review gates and requires native evidence of the effective route, effort, harness/session provenance, and reviewed commit range; it does not change reviewer defaults, global configuration, permissions, or policy. Keep the initial Qwen failure as a failed no-verdict attempt; do not convert it into `SHIP` or reset review counters. No new review verdict is recorded here. The exception does not authorize an OAP/FN-60 workflow or review, Qwen lab work, or a new pull request.
## Evidence
- Commits:
- Tests:
- PRs:
