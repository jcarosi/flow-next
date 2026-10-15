---
satisfies: [R1, R2, R3]
---
# fn-296-preserve-claude-review-failure.1 Port verified Claude result fix to stable 8.7.0

## Description
# Port the verified Claude result fix

### Scope

Replace fn-296's generic diagnostics expansion with the already verified
Claude result correction from the two assigned commits. Flow-Next 8.7.0 has
newer shared code, so port only the relevant Claude parser, dispatch, tests,
and documentation changes. Preserve the existing model-unavailable predicate
and review pipeline contracts.

The verified false-negative is in `run_claude_exec`: a valid successful result
can be rejected when unrelated stderr contains model-unavailable wording,
because the stderr marker is evaluated without first honoring the success
envelope. The parser also currently defaults or coerces `is_error` and accepts
a missing/non-string `result`, so malformed envelopes can be treated as
success-shaped output.

### Acceptance criteria

- **R1:** Claude stdout is accepted only as one JSON object with
  `type == "result"`, a boolean `is_error`, and a string `result`. A valid
  success envelope remains successful when stderr contains unrelated,
  non-secret text, including model-unavailable wording. Its result and session
  ID remain available to the normal review path.
- **R2:** Error envelopes, malformed or incomplete envelopes, and nonzero CLI
  exits never place reviewer text in the verdict output. Only the existing
  exact model-unavailable predicate may enter the unpinned fallback ladder;
  malformed payloads, unrelated failures, nonzero exits, and stderr attached
  to a valid success cannot trigger fallback. Explicit model pins continue to
  suppress fallback.
- **R3:** The packaged Claude review command preserves its official receipt,
  counter, refund, and diff-delivery behavior. Regression coverage exercises
  successful result plus unavailable wording on stderr, strict malformed
  envelopes, real supported unavailable fallback, nonzero/error rejection,
  and explicit-pin behavior.

### Focused validation

- Reproduce at least one success-plus-stderr regression against the unmodified
  target, then verify it passes after the port.
- Run `python3 -m unittest discover -s plugins/flow-next/tests -p 'test_claude_review_commands.py' -q`.
- Run `python3 -m unittest discover -s plugins/flow-next/tests -p 'test_model_resolution.py' -q`.
- Run `python3 scripts/gen_tracker_manifest.py` and `./scripts/sync-codex.sh`
  once, as required for `flowctl.py` changes; report generated paths.

### Boundaries

Port only the relevant changes from the two assigned commits. Do not copy the
older `flowctl.py`, add speculative diagnostics, change unrelated fallback
cache behavior, alter Flow state, or change review routing, receipts, counters,
refunds, or diff delivery.
## Acceptance
All R1-R3 in the parent spec are satisfied; preserve failing SHIP-tag rejection and explicit model pin no-fallback behavior.

## Done summary
# fn-296 completion summary

Installed the reviewed Flow-Next 8.7.0 runtime from source commit `1950d9a24f49803146dd6dffcaf0b9ddb06042bc` using the official Codex installer. The installed Claude review adapter strictly validates the result envelope, preserves successful custom-model output when stderr has diagnostics, suppresses verdict-shaped output after process failure, and falls back only for a genuine model-unavailable result. The installed `flowctl.py` matches reviewed source byte for byte.

The official Qwen/L40S correctness review finalized SHIP with no findings after reading the complete frozen diff and parent spec R1–R3. Review reservation: `8e525610475743449c23652351422b0b`; session: `ec4e9702-3078-447a-80a0-8f5cf8b9e6cb`.

The coordinator-provided full-suite result was 4,047 tests across 218 files, zero failures, and seven conditional skips. The suite was not rerun, as instructed. Local verification passed the official installer preflight, the official installation, post-install tracker manifest validation (49 files), `flowctl usage`, `flowctl --help`, source/install fingerprint comparison, configuration preservation checks, and standalone role/verifier byte comparisons. `flowctl --version` is unsupported by this CLI and exits 2 because it requires a subcommand; source and installed plugin metadata both report version 8.7.0.

The installation did not publish upstream, commit changes, or modify task/spec state.

stage: plan-sync - skipped(config: planSync.enabled != true)
## Evidence
- Commits: 1950d9a24f49803146dd6dffcaf0b9ddb06042bc
- Tests: Coordinator-provided full-suite result (not rerun): 4047 tests, 218 files, 0 failures, 7 conditional skips; log /tmp/flow-next-stable-port-full-tests.log., python3 scripts/merge_codex_config.py /Users/julien/.codex/config.toml plugins/flow-next/codex/agents --max-threads 12 --check (exit 0)., CODEX_HOME=/Users/julien/.codex /bin/bash scripts/install-codex.sh (exit 0; 29 skills, 21 agents, 26 prompts)., python3 plugins/flow-next/scripts/lib/verify_tracker_manifest.py /Users/julien/.codex/scripts (exit 0; 49 files verified)., /Users/julien/.codex/scripts/flowctl usage (exit 0)., /Users/julien/.codex/scripts/flowctl --help (exit 0)., Source/install flowctl.py byte comparison (exit 0; SHA-256 0beff1946a255673b7eafb37cd5c547050e465ee20385b86e7d7f3f115ad4ef4)., Configuration and custom role/verifier preservation comparison (exit 0; multi_agent_v2=true, implementer gpt-6-luna/max)., /Users/julien/.codex/scripts/flowctl --version (exit 2; unsupported because this CLI requires a subcommand).
- PRs: