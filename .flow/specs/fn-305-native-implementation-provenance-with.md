# Native implementation provenance with scoped coordination and candidate integrity

## Conversation Evidence

> User: "Privilégier l'intégration des contrôles pertinents directement dans Flow-Next et l'utilisation des mécanismes natifs de Codex"
> User: "ne supprime aucune garantie de sécurité sans avoir démontré qu'elle est effectivement préservée."
> User: "Ne considère pas Flow-Next comme une frontière de sécurité universelle."

## Goal & Context

Replace event-specific coordination exceptions with deterministic, scoped provenance validation, using existing audit evidence. Flow owns its transitions and candidate verification; Codex owns actual capability restrictions. A standalone outside-Flow control survives only for demonstrated residual value. [paraphrase]

## Architecture & Data Models

Opt-in native Codex provenance at the existing done boundary; unchanged default behavior for other consumers. A reusable host adapter reads supported native app-server history, verifies native parent/child and configured role metadata, classifies inert Flow coordination paths and binds delegated text edits to a Git base and final candidate. No provider-identity claim. Final verification rereads evidence and disk instead of trusting an old receipt. [inferred]

## API Contracts

Native evidence references identify a parent, bounded children, allowed role/model/effort policy, immutable base/head and expected paths. Deterministic failures precede state changes. Existing review input hashing and independent review mechanisms remain authoritative for reviews. Public policy is generic and default off. [inferred]

## Edge Cases & Constraints

Applications outside this repository remain read-only. No new reviewer authorization, no permanent routing changes, no unsafe live bypass experiments. Fail closed on unknown protocol, ambiguous paths, symlinks, missing history or unsupported content. Native history and hashes are detective evidence, not an unforgeable OS boundary. Stage global changes only after isolated tests, backup and exact rollback. [paraphrase]

## Acceptance Criteria

- **R1:** Document current/target owners, duplicates, preventive versus detective guarantees, invocation/bypass/test gaps and alternatives. Missing capabilities remain explicit. [paraphrase]
- **R2:** Generic opt-in Flow provenance rejects missing/forged relationships, role mismatches, extra files, substituted/replayed or altered evidence, direct or mixed coordinator application edits, ambiguous/moved/symlink paths and candidate divergence; unconfigured workflows retain existing behavior. Errors are actionable and leave tasks incomplete. [paraphrase]
- **R3:** Valid new Flow specs/state/coordination events and delegated edits complete without event-specific exceptions. Paths cannot disguise application writes as planning. [paraphrase]
- **R4:** Reconcile observed native text edits and final Git/disk candidate, including mutations through shell or MCP when their effects are observable; document identical overwrite, invisible external effects and other coverage limits. Reject unsupported evidence rather than claim coverage. [paraphrase]
- **R5:** Reproducible isolated positive/negative tests cover A through P from the mandate, reuse audit regressions and exercise real CLI and native-history routes. No real application protections are disabled. [paraphrase]
- **R6:** Independent packaged claude:qwen-l40s:medium full pertinent diff review and completion review have truthful runtime/commit provenance; diagnose timeouts without repeating identical attempts. Unavailable mandatory review blocks acceptance and installation. [paraphrase]
- **R7:** Preserve application trees and preexisting local changes; coherent local commits and only a dedicated jcarosi/flow-next branch/PR, with official candidate installation verification, backups and rollback before shared replacement. Global/Chezmoi changes stay local and maintain coherence. [paraphrase]

## Boundaries

No universal security framework, no personal paths/models in Flow defaults, no change to permanent reviewer or Qwen server, no application edits, no direct main push, force-push or merge. [paraphrase]

## Decision Context

One cohesive engineering outcome; direct execution with bounded implementation children, independent full review and independent completion review. Prefer the existing done/evidence boundary over another workflow framework. Reject native instructions as filesystem isolation, broad .flow exemptions, per-event exception registries and trusting self-reported model labels or stale receipts. Standing criteria G1/G2/G4 apply. [inferred]
