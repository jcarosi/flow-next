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
TBD

## Evidence
- Commits:
- Tests:
- PRs:
