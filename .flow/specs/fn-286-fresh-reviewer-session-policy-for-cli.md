# Fresh reviewer session policy for CLI re-reviews

## Goal

Allow a user or project to opt into one new independent CLI reviewer session after each NEEDS_WORK fix pass. Keep the built-in default at resume and preserve prior finding, receipt, and round lineage.

## Acceptance Criteria

- **R1:** A missing policy uses resume. An explicit invocation overrides project configuration, which overrides the user environment, which overrides the built-in default. Newly initialized projects do not materialize the policy key.
- **R2:** Fresh mode starts one new session for each re-review on Codex, Copilot, Cursor and Claude. The first-round panel and host review are unchanged.
- **R3:** The fresh reviewer receives every prior finding and ordinal, uses the same backend/model/effort, and remains read-only. A changed or unknown route fails before reserving a round.
- **R4:** Fresh reviews preserve receipt lineage, artifact/hash guards, round accounting and transport/refund semantics. The new receipt truthfully identifies previous and current sessions.
- **R5:** Generated schema, tracker manifest and Codex mirror are current; focused and full tests, lint and static checks pass without new skips.

## Decision Context

Keep this a generic Flow feature. The software default remains resume; a user may select fresh through the existing FLOW_* environment pattern. Do not change first-round scheduling or Copilot evidence delivery defaults.
