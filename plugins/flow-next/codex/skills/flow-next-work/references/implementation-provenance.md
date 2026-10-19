# Native implementation provenance (opt-in)

Read this reference before dispatch and before task completion when
`.flow/config.json` sets `implementation.provenance` to `codex-native`. The
policy is off by default.

Contents: [Before dispatch](#before-dispatch) · [Before `flowctl done`](#before-flowctl-done) · [Component boundary and scope](#component-boundary-and-scope) · [Evidence limits](#evidence-limits) · [Live integration checks](#live-integration-checks)

## Before dispatch

Read the merged policy:

```bash
$FLOWCTL config get implementation --json
```

Use an available native Codex role whose exact name is configured under
`implementation.roles`. Its recorded model and effort must match that role's
configured policy. Do not implement inline or use a CLI bridge under this
policy: the verifier needs a native child thread and its app-server history.
If no configured role is available, or the host cannot provide supported
native history, stop before implementation and leave the task incomplete.

Before each native child is started, the coordinator must emit the exact line
`Implementation task: <task declaration>` in its native parent history. In a
Flow task, use that task's canonical id. The shared verifier also supports
standalone callers whose declaration is any exact, non-empty single line. If
the selected role has `require_reason: true`, include a concise `reason` in the
child request and emit the exact line `Escalation reason: <reason>` before the
child starts. If any role receives a reason, the same exact line must also
appear in its exposed spawn prompt. A required or supplied reason must be
evidence from the current task; never invent one to satisfy the policy.

Record the task's full base commit before the first implementation child is
dispatched. Keep the direct parent thread id and each implementation child's
native thread id from the host metadata. A child’s self-report is not evidence.
Record the complete set of native implementation children integrated since the
common immutable base, including children from each wave or rolling handover.
For each child, record its exact repo-relative application paths in the
integrated repository. Include a child-specific `task_declaration` when it was
assigned a different task; otherwise it defaults to the top-level `task`. The
parent must have emitted that exact task line before the child started, and the
complete request must include a verified child for the current task. A child may
also name its absolute linked-worktree root in `workspace`; keep that worktree
available and registered until verification finishes. Do not include arbitrary
commands, broad coordination exceptions, or executable content in the request.

When this policy is active, dispatch even a single owner task to a native
worker. Have the worker return the task as `in_progress` with its handover;
the conductor owns integration, review and the final done transition. For a
single task, use the isolated one-task handover path and read
[`wave-join.md`](wave-join.md) for integration. Rolling and wave runs already
use that handover shape.

## Before `flowctl done`

After integrating all implementation and review-fix commits, complete the
focused verification for the integrated candidate. Prepare a request with this
shape, using the current task declaration and full base commit:

```json
{
  "parent_thread": "<native coordinator thread id>",
  "children": [
    {
      "thread_id": "<native implementation child thread id>",
      "expected_files": ["<integrated-repository-relative application path>"],
      "task_declaration": "<optional exact child task declaration>",
      "workspace": "<optional absolute linked-worktree root>"
    }
  ],
  "base_commit": "<full git commit sha>",
  "task": "<current task declaration>"
}
```

`task_declaration` defaults to the top-level `task`; `workspace` defaults to the
integrated repository root. A supplied workspace must be a canonical, registered
linked worktree in the same Git repository. The verifier maps native absolute
paths from that workspace back to integrated-repository paths and rejects
symlinks, traversal, aliases, and unrelated clones. Keep each named workspace
until verification has completed so the native path evidence can be resolved.
Each child entry may also have a `reason` string. It is required when that
child's configured role has `require_reason: true`.

Keep the request and evidence JSON outside the repository so those temporary
inputs do not become part of the candidate being checked. Run the read-only
check against the integrated candidate, then pass that request as
`native_provenance` in the task's done evidence:

```bash
$FLOWCTL provenance check --request "$TMPDIR/<task-id>-native-provenance.json" --json
$FLOWCTL done <task-id> --evidence-json "$TMPDIR/<task-id>-evidence.json" --json
```

The done command repeats verification under the task lock immediately before
writing any receipt or status. It ignores any supplied old receipt and stores
the newly verified receipt in `evidence.native_provenance`; the tracked done
summary carries its `receipt_sha256`. `--force` does not skip this gate. On
failure, keep the task in progress and fix the request or return to the
conductor; do not edit Flow state to bypass the check.

## Component boundary and scope

Flow's `provenance check` reads the role policy from `.flow/config.json` and
`flowctl done` uses that same policy at the task transition. Outside a Flow
repository, `provenance check --policy <file>` accepts an explicit role policy.
The standalone checker accepts the same repository, request, and policy inputs.
Both call the shared `verify_native` adapter, which reads supported Codex
app-server history and checks the Git and disk candidate. The check command and
standalone checker do not write Flow state. Native verification is opt-in;
with the setting unset or disabled, existing task completion remains
compatible and does not require a native request. For coordinator PR
cognitive-aid artifacts, the standalone checker uses the canonical validator
from its sibling `flowctl.py` and fails closed if that validator is unavailable.

The request assigns every child a closed set of repository-relative files. The
adapter replays all included children against the common base in native activity
order and compares their bytes and executable mode with the current candidate.
Concurrent children with overlapping paths remain ambiguous and are rejected.
Native `fileChange` evidence must cover every source path in scope. A command
that generates a mirror, schema, help file, or other output does not attribute
that output by itself. If generated paths lack supported native `fileChange`
events, strict verification rejects them, even when a child generated them
legitimately. Binary or non-UTF-8 candidate content is unsupported and fails
closed. Git index states that hide worktree changes, including sparse,
`skip-worktree`, or `assume-unchanged` entries, may also be refused with a
diagnostic.

Flow coordinator metadata has a narrow classification for valid inert spec and
task files, memory entries and documents, run/task/review/QA evidence, JUnit
reports, observed or tracked PR cognitive-aid artifacts, and currently evidenced
base markers. These outputs must stay within their existing Flow path and
content contracts, be bounded UTF-8 data, and have no executable mode. Valid
intermediate Flow JSON in `HEAD` or the index can differ from both the common
base and final disk state;
application source still must reconcile to its base or fully replayed final
state. Ignored stale base-marker files are not read unless they have current
native or tracked evidence. This classification does not cover arbitrary
`.flow` paths: `.flow/config.json` is policy-bearing and has no inert exemption,
so configuration implementation must be assigned as delegated application
work and is rejected when written as unexplained coordinator output.

## Evidence limits

Native history and candidate comparison are detective checks. Codex permissions
and tool restrictions provide preventive controls; prompts and the Flow done
gate do not confine shell, MCP, or other filesystem access. The done gate covers
that supervised transition. It does not prevent later writes or establish an
operating-system boundary between processes running as the same user.

The caller supplies the role policy, so the verifier trusts its configured
role, model, effort, and any required reason. It matches those values to native
thread metadata; it does not prove provider identity. Receipt hashes bind the
serialized evidence against accidental changes. They are not signatures or an
authenticity claim.

When native provenance is unset or disabled, existing completion behavior
remains compatible: caller-supplied `native_provenance` data is preserved as
opaque evidence. This path adds no `UNVERIFIED` label or
`stage: native-provenance` marker, so treat that data as unverified. An absent
`.flow/config.json` or absent `implementation` setting resolves to `off`.
When native provenance is active, a fresh verified receipt replaces any
caller-supplied receipt. Unreadable or malformed configuration, or an unknown
or invalid implementation policy, fails closed.

Only changes visible in the checked Git candidate and supported native history
can be compared. Ignored files and paths outside the repository are outside the
candidate scan. PR cognitive-aid artifacts are intentionally ignored by Git, so
an untracked ignored artifact is not included unless native evidence names it;
Flow's artifact writer performs its own contract validation before use. Writes
that are reverted before checking, identical overwrites,
and external effects that leave no visible candidate change cannot be
attributed. An expected output that is ignored or absent from Git is rejected.
The standalone checker reports the candidate it observed and does not prevent
later changes.

## Live integration checks

The real-history integration test is skipped by default. It reads existing
native thread IDs and requests from an external JSON config, makes no model
calls, and uses only disposable Git fixtures named by that config. The test
restores any fixture file bytes and modes it changes, including task state
written by `flowctl done`.

Set `FLOW_NEXT_CODEX_PROVENANCE_LIVE_CONFIG` to an external config file and run:

```bash
FLOW_NEXT_CODEX_PROVENANCE_LIVE_CONFIG=/path/to/live-fixtures.json \
  python3 -m unittest discover \
  -s plugins/flow-next/tests \
  -p test_codex_provenance_live.py -v
```

The config supplies `fixture_root`, the installed candidate `flowctl`, a
`flow` object with `repo_root`, `request`, and `created_spec_paths`, plus a
`standalone` object with `repo_root`, `request`, `policy`, and the staged
launcher path. An optional top-level `worktree` object with `repo_root` and
`request` exercises real linked-worktree path mapping. Keep the config,
requests, role policy, and native IDs outside the repository. Without the
environment variable, all live integration cases skip.
