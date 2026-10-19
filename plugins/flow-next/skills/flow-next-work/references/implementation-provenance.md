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
`Implementation task: <canonical task id>` in its native parent history. If
the selected role has `require_reason: true`, include a concise `reason` in the
child request and emit the exact line `Escalation reason: <reason>` before the
child starts. If any role receives a reason, the same exact line must also
appear in its exposed spawn prompt. A required or supplied reason must be
evidence from the current task; never invent one to satisfy the policy.

Record the task's full base commit before the first implementation child is
dispatched. Keep the direct parent thread id and each implementation child's
native thread id from the host metadata. A child’s self-report is not evidence.
For each child, record the exact repo-relative application paths it was
assigned to change. Do not include arbitrary commands, broad coordination
exceptions, or executable content in the request.

When this policy is active, dispatch even a single owner task to a native
worker. Have the worker return the task as `in_progress` with its handover;
the conductor owns integration, review and the final done transition. For a
single task, use the isolated one-task handover path and read
[`wave-join.md`](wave-join.md) for integration. Rolling and wave runs already
use that handover shape.

## Before `flowctl done`

After integrating all implementation and review-fix commits, complete the
focused verification for the integrated candidate. Prepare a request with this
shape, using the canonical task id and full base commit:

```json
{
  "parent_thread": "<native coordinator thread id>",
  "children": [
    {
      "thread_id": "<native implementation child thread id>",
      "expected_files": ["<repo-relative application path>"]
    }
  ],
  "base_commit": "<full git commit sha>",
  "task": "<canonical task id>"
}
```

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
compatible and does not require a native request.

The request assigns each child a closed set of repository-relative files. The
adapter replays supported native text file changes against the base commit and
compares their bytes and executable mode with the current candidate. It also
checks the index, `HEAD`, and disk for unexplained intermediate states. Native
`fileChange` evidence must cover every source path in scope. A command that
generates a mirror, schema, help file, or other output does not attribute that
output by itself. If generated paths lack supported native `fileChange`
events, strict verification rejects them, even when the child generated them
legitimately. Binary or non-UTF-8 candidate content is unsupported and fails
closed. Git index states that hide worktree changes, including sparse,
`skip-worktree`, or `assume-unchanged` entries, may also be refused with a
diagnostic.

Flow coordinator metadata has a separate narrow classification for inert spec,
task, and base-marker files. This permits a recorded Flow operation such as
creating a spec alongside delegated source changes. It does not make arbitrary
project configuration or generated application output coordinator-owned.

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

Only changes visible in the checked Git candidate and supported native history
can be compared. Ignored files and paths outside the repository are outside the
candidate scan. Writes that are reverted before checking, identical overwrites,
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
launcher path. Keep the config, requests, role policy, and native IDs outside
the repository. Without the environment variable, all live integration cases
skip.
