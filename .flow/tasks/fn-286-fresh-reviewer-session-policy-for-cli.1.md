---
satisfies: [R1, R2, R3, R4, R5]
---
# fn-286-fresh-reviewer-session-policy-for-cli.1 Implement fresh CLI re-review policy with configuration, validation and docs

## Description
Implement the generic opt-in policy for all four CLI review backends, generate schema and mirrors, and verify focused and full gates. Preserve stock resume and existing review receipts.

## Acceptance
- [ ] Built-in resume, user fresh, project resume, invocation override and raw/effective reads pass tests.
- [ ] Fresh re-reviews on all four CLI backends use one distinct session and full prior findings; first-round panel remains unchanged.
- [ ] Model/effort, read-only transport, hash and round accounting, receipt lineage, and refund behavior pass focused tests.
- [ ] Generated schema, tracker manifest, Codex mirror, focused tests, full suite and lint are green with no new skips.
- [ ] Independent read-only review reaches SHIP before installation.
## Done summary
Added opt-in fresh CLI re-review sessions with invocation/project/user/default precedence. Software default remains resume. All four CLI adapters preserve full prior findings, provenance, round accounting and read-only controls. Independent Copilot/Opus panel and fresh corrective re-review returned SHIP.

Validation: 4014 tests, 0 failures/errors, 7 existing skips; 119 post-review focused tests; schema, manifest, mirror and Ruff passed.

stage: plan-sync - skipped(config: planSync.enabled != true)
## Evidence
- Commits: 950ccaa3cfb912ced40e151c4da63f6a48bc8238, e4a04c4f0273ca4bb076c29e0046fc9ed8d3c45b
- Tests: FLOW_RE_REVIEW_SESSION=fresh python3 scripts/run_tests_parallel.py --jobs 4, uvx ruff@0.16.0 check ., 119 focused tests after route fix
- PRs: