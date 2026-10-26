## Goal & Context

Prepare an isolated, reviewable Flow-Next source candidate synchronized to the verified official stable release while preserving qualified fork behavior and protecting active shared installations.

## Architecture & Data Models

Preserve commit history through an ordinary merge. Keep source preparation isolated from the active central checkout and global host installations.

## API Contracts

No public API changes are required by this maintenance integration.

## Edge Cases & Constraints

The official source, release tag, candidate branch, and destination must resolve to the verified repositories and commits. Keep the worktree, remotes, pull request branches, active installations, application projects, service state, and all `.flow` configuration outside the mutation scope, except that the local central `main` ref and fork `main` may be advanced only under R6. Reuse existing valid preservation evidence. Stop publication on unresolved conflicts, failing validation, incomplete required reviews, or concurrent state changes.

## Acceptance Criteria

- **R1:** The candidate integrates the exact official stable source with preserved history in an isolated branch and records its source and destination.
- **R2:** Each fork-specific contribution is compared against upstream. Necessary Claude review reliability, Copilot reasoning and pinned diff delivery, and `--auto` guard coverage are preserved; upstream-integrated changes are not duplicated; redundant patches are removed only when their behavior and compatibility are established. Keep FN-305 opt-in and unchanged unless behavior and compatibility with a new architecture are demonstrated; do not adapt it automatically.
- **R3:** Relevant generated artifacts and repository validations pass, and all executed checks and remaining limitations are recorded.
- **R4:** Host installation preparation is tested only in isolated copies. Shared installation activation is deferred while active processes may use it.
- **R5:** The required implementation review and separate completion review run through the packaged Flow backend in independent fresh read-only reviewer contexts using the current-task override `codex:gpt-6.1-sol:xhigh`. Record effective model and effort, harness and reviewer session, and exact reviewed commit range from native evidence. Do not route to Qwen or fall back to another model or harness; if the requested route or evidence is unavailable, leave the gate blocked. No verdict or publication is claimed without complete evidence.
- **R6:** Preserve all existing history, concurrent work, pull request branch references, application projects and their configurations, active installations, services, and global settings. After R1-R5 pass, central `main` and `jcarosi/flow-next:main` may be advanced only by ordinary non-force fast-forward to the validated candidate, after verifying each destination and current ref immediately before the update and confirming no conflicting or concurrent work and no remote commit will be overwritten. Do not alter existing PR branch refs. If any safety or validation condition is not met, leave both main refs unchanged and retain the validated candidate on its isolated branch.

## Boundaries

No application project changes or workflows. No shared installation activation or `.flow` configuration changes. No PR creation, PR branch edits, force push, push to upstream, release, or tag. Central and fork `main` publication is allowed only under R1-R6's complete validation, review, destination verification, and non-destructive fast-forward conditions; otherwise retain the isolated candidate.

## Decision Context

The official 9.3.1 release is ahead of the verified central source. A separate candidate makes source integration inspectable without changing the active checkout or clients. Compatibility is checked against the known contribution matrix and current upstream state. The authorized Codex review route is temporary for this maintenance task, does not change global or repository defaults, and is not permission to substitute another reviewer if it is unavailable.

The retained host-neutral search guard has a documented unattended-trust purpose: Flow-Next 9.2.0 records that native hosts lacked Grep/Glob while scout instructions had forbidden read-only shell search, leaving verification unable to inspect source. The current canonical instructions pass the guard. A reviewer noted a possible false positive for hypothetical future valid prose; defer that nonblocking P2 because there is no current canonical counterexample, and removing the guard would weaken the existing verification control. Revisit only with a concrete valid canonical case and a replacement guard that preserves the unattended safety property (G4).

## Conversation Evidence

The user authorized this exceptional reviewer route in the current conversation: “tu peux utiliser codex/gpt 6.1 xhigh pour les reviews exceptionnnelement”. The per-run route is `codex:gpt-6.1-sol:xhigh`; do not use the ordinary configured Qwen route or silently fall back to another model or harness.

The original mission authorizes synchronizing `jcarosi/flow-next` only when the update is fully validated, safe against pre-existing work, non-destructive, and directed to the verified destination. This includes an ordinary fast-forward of central and fork `main` when all gates pass; it does not authorize force-push, upstream push, changes to PR branches, or creation of a new PR. Application projects, shared settings and installations, and services remain protected. [paraphrase]

## Requirement coverage

- R1 → isolated history-preserving integration and source identity
- R2 → contribution inventory and regression checks
- R3 → validation evidence
- R4 → installation rehearsal and activation decision
- R5 → independent review gates with current-task route override and verifiable evidence
- R6 → preservation controls and conditional non-destructive publication
