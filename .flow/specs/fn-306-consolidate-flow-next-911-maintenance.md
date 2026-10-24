# Consolidate Flow-Next 9.1.1 maintenance safely

## Conversation Evidence

> user: "Aucune mise à jour ne doit interrompre ou modifier un projet actif."
>
> user: "Ne relâche pas globalement le garde de l'arbre Git modifié."
>
> user: "Conduis cette maintenance de bout en bout, sans intervention humaine inutile, avec une installation reproductible et des preuves de non-régression."

## Goal & Context

Bring the local Flow-Next fork and its user installation to a recent, traceable release while retaining useful fork behavior, removing duplicate patches, and protecting active projects. The selected candidate is the stable 9.1.1 release plus the current upstream main documentation commit. [inferred]

<!-- Source: 90% [paraphrase] / 10% [inferred] -->

## Architecture & Data Models

Use an upstream-based maintenance branch, with fork-specific behavior isolated in reviewed commits. Keep canonical plugin sources and generated host mirrors in sync. Prepare installation changes through the existing supported host installers and retain private rollback copies. [paraphrase]

## API Contracts

No new public commands, configuration keys, reviewer routes, or file formats are required. Preserve existing command and configuration behavior, including explicit Copilot file-diff delivery. [paraphrase]

## Edge Cases & Constraints

- A changed working tree or an unready selected spec must stop the unattended pilot before review dispatch. Report the exact guard reason and preserve task/spec/ledger state; the pilot snapshot may remain as the documented pre-dispatch diagnostic artifact. [paraphrase]
- An unexpected mismatch between the validated candidate and the staged install blocks activation. If active processes require the old installation to remain in place, document activation as intentionally deferred; that old active version alone does not block publication of an otherwise validated source candidate. [paraphrase]
- Do not modify OAP, its open FN-60 capsule or five changed files, the Qwen review laboratory, global policies, or other active project state. Do not run the OAP workflow, a Qwen campaign, or create a pull request. [paraphrase]

## Acceptance Criteria

- **R1:** The maintenance candidate is based on upstream Flow-Next 9.1.1 and preserves the fork's qualified native delegation, implementation-provenance, candidate-integrity, permission, review, and completion guards, with their canonical generated mirrors and tests. Keep added always-loaded agent prose justified under G1 and test behavior under G2. Conflicts that cannot be resolved without dropping behavior remain unresolved. Errors: uncertain behavior or a failing guard regression blocks integration. [paraphrase]
- **R2:** Claude terminal parsing accepts valid successful output despite non-fatal stderr warnings, rejects malformed or nonzero terminal results, and fallback caches only successful dispatches. Copilot forwards the selected reasoning effort with truthful attribution and preserves `review.copilotDiffDelivery=file` by delivering the exact frozen diff before dispatch. Existing configurable file-delivery code is reused without a duplicate writer. Errors: failed or missing diff materialization prevents reviewer dispatch; terminal failures publish no verdict and are not cached. [paraphrase]
- **R3:** Disposable offline fixtures cover clean/dirty repositories crossed with ready/unready specs and non-empty blocker lists. They assert the documented `NEEDS_HUMAN` verdict and reason, no reviewer launch on a guard stop, and preserved workflow files and state apart from the pre-dispatch diagnostic snapshot. Tests follow G2. A correct refusal passes. Errors: no fixture touches OAP or invokes a real reviewer. [paraphrase]
- **R4:** The supported install path is staged and its source, installed files, configuration preservation, rollback copy, and smoke checks are recorded. Activation occurs only when no observed active process could use the replaced files; otherwise the validated activation remains deferred. Errors: path, symlink, ownership, backup, or provenance mismatch blocks installation. [paraphrase]
- **R5:** The final candidate passes the repository's full test suite, pinned Ruff check, generated-artifact checks, affected offline regressions, and host installation smoke checks; complete output is retained as evidence. Any failure remains visible and blocks a clean maintenance verdict. [paraphrase]
- **R6:** The effective configured `claude:qwen-l40s:medium` implementation review and required specification-completion review cover the final candidate in separate reviewer contexts with verifiable route evidence. No real reviewer result is inferred from mocks. Errors: unavailable or unverifiable configured review leaves the candidate unvalidated and unpublished. [paraphrase]
- **R7:** Fork publication targets only the verified `jcarosi/flow-next` branch, is a non-forced fast-forward from its observed remote head, includes only validated maintenance commits, and is verified by the resulting SHA and CI state. A failed safety check leaves changes local and records the rollback path. [paraphrase]

## Boundaries

- Leave OAP and FN-60 unchanged; do not execute their workflow or direct review.
- Do not change global Codex, Chezmoi, reviewer, permissions, updater, or policy files.
- Do not import unqualified Qwen laboratory prototypes, alter reviewer model defaults, run benchmark/lab Qwen campaigns, or create a pull request. The configured maintenance reviews in R6 remain required release gates.
- Do not weaken dirty-tree, readiness, provenance, reviewer permission, coverage, or completion guards.

## Decision Context

- Treat the OAP pilot stop as a protective outcome when the implemented preconditions are unmet; the test succeeds when the guard refuses before a reviewer starts.
- Retain validated behavior rather than old implementation lines. An upstream or PR change replaces a local patch only when tests demonstrate equivalent or stronger behavior.
- This is one cohesive maintenance task on `maintenance/flow-next-9.1.1-20261024`; execution is direct/no-plan.
- The ban on Qwen campaigns excludes benchmarks and exploratory lab runs; the independently configured implementation and completion reviews remain the requested maintenance gates.
- Respect G4: no new pre-action structure is introduced beyond the user's requested existing maintenance and release gates.
