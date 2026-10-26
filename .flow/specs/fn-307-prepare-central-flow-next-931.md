## Goal & Context

Prepare an isolated, reviewable Flow-Next source candidate synchronized to the verified official stable release while preserving qualified fork behavior and protecting active shared installations.

## Architecture & Data Models

Preserve commit history through an ordinary merge. Keep source preparation isolated from the active central checkout and global host installations.

## API Contracts

No public API changes are required by this maintenance integration.

## Edge Cases & Constraints

The official source, release tag, candidate branch, and destination must resolve to the verified repositories and commits. Keep the worktree, remotes, pull request branches, active installations, application projects, service state, and all .flow configuration outside the mutation scope. Reuse existing valid preservation evidence. Stop publication on unresolved conflicts, failing validation, incomplete required reviews, or concurrent state changes.

## Acceptance Criteria

- **R1:** The candidate integrates the exact official stable source with preserved history in an isolated branch and records its source and destination.
- **R2:** Each fork-specific contribution is compared against upstream. Necessary Claude review reliability, Copilot reasoning and pinned diff delivery, --auto guard coverage, and FN-305 behavior are preserved; upstream-integrated changes are not duplicated; redundant patches are removed only when their behavior and compatibility are established.
- **R3:** Relevant generated artifacts and repository validations pass, and all executed checks and remaining limitations are recorded.
- **R4:** Host installation preparation is tested only in isolated copies. Shared installation activation is deferred while active processes may use it.
- **R5:** Required independent implementation and completion review gates remain authoritative. No verdict or publication is claimed without the configured route and complete evidence.
- **R6:** Existing central state, fork and PR references, application projects, global settings, active services, and concurrent work remain unchanged.

## Boundaries

No application project changes or workflows. No shared install activation, .flow config changes, PR creation, PR branch edits, force push, upstream push, main publication, release, or tag without the required evidence and a safe live-state check.

## Decision Context

The official 9.3.1 release is ahead of the verified central source. A separate candidate makes source integration inspectable without changing the active checkout or clients. Compatibility is checked against the known contribution matrix and current upstream state.

## Conversation Evidence

The user requested fact-first verification and conditional synchronization, preservation of useful fork changes, no application intervention, no shared installation replacement while agents may be active, and no operation when it is unnecessary. [paraphrase]

## Requirement coverage

- R1 → isolated history-preserving integration and source identity
- R2 → contribution inventory and regression checks
- R3 → validation evidence
- R4 → installation rehearsal and activation decision
- R5 → independent review gates
- R6 → preservation and isolation controls
