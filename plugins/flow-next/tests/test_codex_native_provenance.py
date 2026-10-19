"""Isolated tests for Codex native-history provenance and candidate integrity."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import flowctl_codex_provenance as native_provenance
from flowctl_codex_provenance import VerificationError, verify_native


PARENT_ID = "parent-thread"
CHILD_ID = "child-thread"
POLICY = {"implementer": {"model": "model-test", "effort": "high"}}


def _run(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _file_change(
    item_id: str,
    path: str,
    kind: str,
    diff: str,
    move_path: str | None = None,
) -> dict[str, Any]:
    kind_value: dict[str, str] = {"type": kind}
    if move_path is not None:
        kind_value["move_path"] = move_path
    return {
        "id": item_id,
        "type": "fileChange",
        "status": "completed",
        "changes": [{"path": path, "kind": kind_value, "diff": diff}],
    }


class FixtureClient:
    """Small native RPC fixture supporting legacy and paginated history."""

    def __init__(self, threads: dict[str, dict[str, Any]]) -> None:
        self.threads = threads
        self.turn_calls = 0
        self.item_calls = 0

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        thread_id = params["threadId"]
        data = self.threads[thread_id]
        thread = dict(data["thread"])
        if method == "thread/read":
            if params.get("includeTurns"):
                return {"thread": {**thread, "turns": data["turns"]}}
            return {"thread": thread}
        if method == "thread/turns/list":
            self.turn_calls += 1
            turns = data["turns"]
            cursor = params.get("cursor")
            if cursor is None:
                first = turns[:1]
                return {"data": first, "nextCursor": "turn-page" if len(turns) > 1 else None}
            if cursor == "turn-page":
                return {"data": turns[1:], "nextCursor": None}
            raise AssertionError(f"unexpected turns cursor {cursor!r}")
        if method == "thread/items/list":
            self.item_calls += 1
            turn_id = params["turnId"]
            turn = next(turn for turn in data["turns"] if turn["id"] == turn_id)
            items = turn.get("fixtureItems", turn.get("items", []))
            cursor = params.get("cursor")
            if cursor is None:
                first = items[:1]
                return {"data": [{"turnId": turn_id, "item": item} for item in first],
                        "nextCursor": "item-page" if len(items) > 1 else None}
            if cursor == "item-page":
                return {"data": [{"turnId": turn_id, "item": item} for item in items[1:]],
                        "nextCursor": None}
            raise AssertionError(f"unexpected items cursor {cursor!r}")
        raise AssertionError(f"unexpected native RPC method {method!r}")


@unittest.skipIf(os.name == "nt", "The adapter currently verifies POSIX-native Codex paths only.")
class NativeProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="native-provenance-")
        self.root = Path(self.temp.name).resolve()
        _run(self.root, "init", "-q")
        _run(self.root, "config", "user.name", "Provenance Test")
        _run(self.root, "config", "user.email", "provenance@example.invalid")
        (self.root / "delegated.txt").write_text("baseline\n", encoding="utf-8")
        _run(self.root, "add", "delegated.txt")
        _run(self.root, "commit", "-qm", "base")
        self.base = _run(self.root, "rev-parse", "HEAD")
        self.request = {
            "parent_thread": PARENT_ID,
            "children": [{"thread_id": CHILD_ID, "expected_files": ["delegated.txt"]}],
            "base_commit": self.base,
            "task": "fn-1-native-provenance.1",
        }
        self.change_items = [
            _file_change(
                "delete-event", str(self.root / "delegated.txt"), "delete", "baseline\n"
            ),
            _file_change(
                "add-event", str(self.root / "delegated.txt"), "add",
                "delegated implementation\n",
            ),
        ]
        self.client = self._client()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _thread(self, thread_id: str, **updates: Any) -> dict[str, Any]:
        thread = {
            "id": thread_id,
            "cwd": str(self.root),
            "historyMode": "legacy",
            "status": {"type": "active" if thread_id == PARENT_ID else "idle"},
        }
        thread.update(updates)
        return thread

    def _task_item(self, item_id: str = "task-declaration", text: str | None = None) -> dict[str, str]:
        return {
            "id": item_id,
            "type": "agentMessage",
            "text": text or f"Implementation task: {self.request['task']}",
        }

    def _client(
        self,
        *,
        parent_items: list[dict[str, Any]] | None = None,
        child_items: list[dict[str, Any]] | None = None,
        child_parent_id: str = PARENT_ID,
        child_id: str = CHILD_ID,
        parent_id: str = PARENT_ID,
    ) -> FixtureClient:
        if parent_items is None:
            parent_items = [
                self._task_item(),
                {
                    "id": "activity-start",
                    "type": "subAgentActivity",
                    "agentThreadId": child_id,
                    "agentPath": "implementer",
                    "kind": "started",
                },
                {
                    "id": "activity-complete",
                    "type": "subAgentActivity",
                    "agentThreadId": child_id,
                    "agentPath": "implementer",
                    "kind": "completed",
                },
            ]
        if child_items is None:
            child_items = [*self.change_items, {"id": "final-message", "type": "agentMessage", "text": "Done."}]
        parent_turn = {"id": "parent-turn", "status": "inProgress", "items": parent_items}
        child_turn = {"id": "child-turn", "status": "completed", "items": child_items}
        threads = {
            parent_id: {"thread": self._thread(parent_id), "turns": [parent_turn]},
            child_id: {
                "thread": self._thread(
                    child_id,
                    parentThreadId=child_parent_id,
                    agentRole="implementer",
                    model="model-test",
                    reasoningEffort="high",
                ),
                "turns": [child_turn],
            },
        }
        return FixtureClient(threads)

    def _verify(self, client: FixtureClient | None = None) -> dict[str, Any]:
        return verify_native(self.root, self.request, POLICY, client or self.client)

    def _add_tracked_baseline(self, path: str, content: str = "original\n") -> None:
        (self.root / path).write_text(content, encoding="utf-8")
        _run(self.root, "add", path)
        _run(self.root, "commit", "-qm", f"add {path}")
        self.base = _run(self.root, "rev-parse", "HEAD")
        self.request["base_commit"] = self.base

    def test_delete_then_add_replays_in_native_order_and_binds_receipt(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        receipt = self._verify()
        self.assertEqual(receipt["children"][0]["nativeEvidence"]["fileChanges"][0]["id"], "delete-event")
        self.assertEqual(receipt["candidateFiles"][0]["sha256"], receipt["children"][0]["finalFiles"][0]["sha256"])
        digest = receipt["receipt_sha256"]
        self.assertEqual(self._verify()["receipt_sha256"], digest)

    def test_flow_owned_spec_task_and_hash_markers_are_allowed(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        spec_id = "fn-1-native-provenance"
        task_id = spec_id + ".1"
        flow = self.root / ".flow"
        (flow / "specs").mkdir(parents=True)
        (flow / "tasks").mkdir(parents=True)
        (flow / "tmp").mkdir(parents=True)
        (flow / "specs" / f"{spec_id}.md").write_text(
            "",
            encoding="utf-8",
        )
        (flow / "specs" / f"{spec_id}.json").write_text(
            json.dumps({"id": spec_id, "status": "open"}) + "\n", encoding="utf-8"
        )
        (flow / "tasks" / f"{task_id}.md").write_text(
            "<!-- Project-specific task scaffold. -->\n",
            encoding="utf-8",
        )
        (flow / "tasks" / f"{task_id}.json").write_text(
            json.dumps({"id": task_id, "spec": spec_id}) + "\n", encoding="utf-8"
        )
        (flow / "tmp" / "base_commit").write_text(self.base + "\n", encoding="ascii")
        (flow / "tmp" / "spec_base").write_text(self.base + "\n", encoding="ascii")
        receipt = self._verify()
        coordinator_paths = {item["path"] for item in receipt["coordinatorFiles"]}
        self.assertIn(f".flow/specs/{spec_id}.md", coordinator_paths)
        self.assertIn(f".flow/tasks/{task_id}.json", coordinator_paths)
        self.assertIn(".flow/tmp/base_commit", coordinator_paths)

    def test_real_flowctl_spec_scaffold_is_accepted_as_coordinator_candidate(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        flowctl = SCRIPT_DIR / "flowctl"
        init = subprocess.run(
            [str(flowctl), "init", "--json"],
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
        _run(self.root, "add", ".flow")
        _run(self.root, "commit", "-qm", "Flow baseline")
        self.base = _run(self.root, "rev-parse", "HEAD")
        self.request["base_commit"] = self.base

        create = subprocess.run(
            [
                str(flowctl), "spec", "create", "--title",
                "Legitimate coordination event after baseline", "--json",
            ],
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(create.returncode, 0, create.stdout + create.stderr)
        spec_id = json.loads(create.stdout)["id"]
        spec_path = self.root / ".flow" / "specs" / f"{spec_id}.md"
        json_path = self.root / ".flow" / "specs" / f"{spec_id}.json"
        spec_content = spec_path.read_text(encoding="utf-8")
        json_content = json_path.read_text(encoding="utf-8")
        parent_items = [
            self._task_item(),
            {
                "id": "activity-start", "type": "subAgentActivity",
                "agentThreadId": CHILD_ID, "agentPath": "implementer",
                "kind": "started",
            },
            _file_change("coordination-markdown", str(spec_path), "add", spec_content),
            _file_change("coordination-json", str(json_path), "add", json_content),
            {
                "id": "activity-complete", "type": "subAgentActivity",
                "agentThreadId": CHILD_ID, "agentPath": "implementer",
                "kind": "completed",
            },
        ]

        receipt = self._verify(self._client(parent_items=parent_items))
        self.assertTrue(spec_content.startswith("<!--"))
        self.assertEqual(
            {item["path"] for item in receipt["coordinatorFiles"]},
            {f".flow/specs/{spec_id}.md", f".flow/specs/{spec_id}.json"},
        )
        self.assertEqual(
            {item["path"] for item in receipt["candidateFiles"]},
            {"delegated.txt", f".flow/specs/{spec_id}.md", f".flow/specs/{spec_id}.json"},
        )

    def test_executable_coordinator_markdown_is_rejected(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        spec_path = self.root / ".flow" / "specs" / "fn-1-native-provenance.md"
        spec_path.parent.mkdir(parents=True)
        spec_path.write_text("<!-- Valid UTF-8 Markdown. -->\n", encoding="utf-8")
        spec_path.chmod(0o755)

        with self.assertRaisesRegex(VerificationError, "coordinator file is executable"):
            self._verify()

    def test_binary_coordinator_markdown_is_rejected(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        spec_path = self.root / ".flow" / "specs" / "fn-1-native-provenance.md"
        spec_path.parent.mkdir(parents=True)
        spec_path.write_bytes(b"valid prefix\x00binary suffix\n")

        with self.assertRaisesRegex(VerificationError, "coordinator Flow file is binary"):
            self._verify()

    def test_native_parent_coordination_event_can_bind_flowctl_final_file(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        flow = self.root / ".flow" / "specs"
        flow.mkdir(parents=True)
        spec_path = flow / "fn-1-native-provenance.md"
        spec_content = "# Native provenance\n\n## Goal & Context\nfixture\n"
        spec_path.write_text(spec_content, encoding="utf-8")
        parent_items = [
            self._task_item(),
            {"id": "activity-start", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
             "agentPath": "implementer", "kind": "started"},
            _file_change("coordination-event", str(spec_path), "add", spec_content),
            {"id": "activity-complete", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
             "agentPath": "implementer", "kind": "completed"},
        ]
        receipt = self._verify(self._client(parent_items=parent_items))
        self.assertEqual(receipt["coordinatorFiles"][0]["path"], ".flow/specs/fn-1-native-provenance.md")

    def test_parent_application_or_mixed_native_file_change_is_rejected(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        app_path = self.root / "unexpected.py"
        app_path.write_text("print('not coordination')\n", encoding="utf-8")
        parent_items = [
            self._task_item(),
            {"id": "activity-start", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
             "agentPath": "implementer", "kind": "started"},
            _file_change("parent-app-event", str(app_path), "add", app_path.read_text()),
            {"id": "activity-complete", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
             "agentPath": "implementer", "kind": "completed"},
        ]
        with self.assertRaisesRegex(VerificationError, "non-inert Flow path"):
            self._verify(self._client(parent_items=parent_items))
        spec_path = self.root / ".flow" / "specs" / "fn-1-native-provenance.md"
        spec_path.parent.mkdir(parents=True)
        spec_path.write_text("# Native provenance\n", encoding="utf-8")
        mixed_items = [
            self._task_item(),
            {"id": "activity-start", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
             "agentPath": "implementer", "kind": "started"},
            _file_change("parent-coordination", str(spec_path), "add", "# Native provenance\n"),
            _file_change("parent-application", str(app_path), "add", app_path.read_text()),
            {"id": "activity-complete", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
             "agentPath": "implementer", "kind": "completed"},
        ]
        with self.assertRaisesRegex(VerificationError, "non-inert Flow path"):
            self._verify(self._client(parent_items=mixed_items))

    def test_missing_or_forged_parent_child_relation_is_rejected(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(VerificationError, "native parent-child relation"):
            self._verify(self._client(parent_items=[]))
        with self.assertRaisesRegex(VerificationError, "parentThreadId"):
            self._verify(self._client(child_parent_id="forged-parent"))

    def test_exact_parent_task_declaration_must_precede_each_child_start(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        start = {
            "id": "activity-start", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
            "agentPath": "implementer", "kind": "started",
        }
        complete = {
            "id": "activity-complete", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
            "agentPath": "implementer", "kind": "completed",
        }
        for items in (
            [start, complete],
            [self._task_item(text="Implementation task: fn-2-wrong.1"), start, complete],
            [start, self._task_item(), complete],
        ):
            with self.subTest(items=items):
                with self.assertRaisesRegex(VerificationError, "exact Implementation task line"):
                    self._verify(self._client(parent_items=items))

    def test_optional_reason_policy_requires_matching_parent_line(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        policy = {"implementer": {"model": "model-test", "effort": "high", "require_reason": True}}
        missing_reason = {**self.request, "children": [{
            "thread_id": CHILD_ID, "expected_files": ["delegated.txt"]
        }]}
        with self.assertRaisesRegex(VerificationError, "requires a caller-supplied escalation reason"):
            verify_native(self.root, missing_reason, policy, self.client)
        reason = "review found unsupported native coverage"
        request = {**self.request, "children": [{
            "thread_id": CHILD_ID, "expected_files": ["delegated.txt"], "reason": reason
        }]}
        parent_items = [
            self._task_item(),
            {"id": "reason-declaration", "type": "agentMessage",
             "text": f"Escalation reason: {reason}"},
            {"id": "activity-start", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
             "agentPath": "implementer", "kind": "started"},
            {"id": "activity-complete", "type": "subAgentActivity", "agentThreadId": CHILD_ID,
             "agentPath": "implementer", "kind": "completed"},
        ]
        receipt = verify_native(
            self.root, request, policy, self._client(parent_items=parent_items)
        )
        evidence = receipt["children"][0]["preDispatch"]
        self.assertTrue(evidence["reasonRequired"])
        self.assertEqual(evidence["reasonEvidence"]["itemId"], "reason-declaration")
        self.assertIsNone(evidence["reasonInLegacyPrompt"])
        wrong_items = [self._task_item(), {
            "id": "wrong-reason", "type": "agentMessage", "text": "Escalation reason: another reason"
        }, *parent_items[2:]]
        with self.assertRaisesRegex(VerificationError, "exact Escalation reason line"):
            verify_native(self.root, request, policy, self._client(parent_items=wrong_items))
        late_items = [
            self._task_item(),
            parent_items[2],
            parent_items[1],
            parent_items[3],
        ]
        with self.assertRaisesRegex(VerificationError, "exact Escalation reason line"):
            verify_native(self.root, request, policy, self._client(parent_items=late_items))

    def test_legacy_spawn_prompt_must_match_any_supplied_reason(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        reason = "specialist escalation"
        request = {**self.request, "children": [{
            "thread_id": CHILD_ID, "expected_files": ["delegated.txt"], "reason": reason
        }]}
        spawn = {
            "id": "spawn-event", "type": "collabAgentToolCall", "tool": "spawnAgent",
            "status": "completed", "senderThreadId": PARENT_ID,
            "receiverThreadIds": [CHILD_ID], "model": "model-test", "reasoningEffort": "high",
            "prompt": f"Implementation task: {request['task']}\nEscalation reason: {reason}",
        }
        parent_items = [
            self._task_item(),
            {"id": "reason-declaration", "type": "agentMessage",
             "text": f"Escalation reason: {reason}"},
            spawn,
        ]
        receipt = verify_native(
            self.root, request, POLICY, self._client(parent_items=parent_items)
        )
        self.assertTrue(receipt["children"][0]["preDispatch"]["taskInLegacyPrompt"])
        self.assertTrue(receipt["children"][0]["preDispatch"]["reasonInLegacyPrompt"])
        spawn["prompt"] = f"Implementation task: {request['task']}\nEscalation reason: wrong"
        with self.assertRaisesRegex(VerificationError, "legacy spawn prompt lacks exact escalation reason"):
            verify_native(self.root, request, POLICY, self._client(parent_items=parent_items))

    def test_child_role_and_expected_path_are_bound_to_native_events(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        wrong_policy = {"implementer": {"model": "model-other", "effort": "high"}}
        with self.assertRaisesRegex(VerificationError, "caller policy"):
            verify_native(self.root, self.request, wrong_policy, self.client)
        child_items = [
            _file_change("extra-event", str(self.root / "extra.txt"), "add", "extra\n"),
            {"id": "final-message", "type": "agentMessage", "text": "Done."},
        ]
        with self.assertRaisesRegex(VerificationError, "unexpected native fileChange paths"):
            self._verify(self._client(child_items=child_items))

    def test_editing_child_must_finish_its_file_change_turn(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        client = self._client()
        client.threads[CHILD_ID]["thread"]["status"] = {"type": "active"}
        client.threads[CHILD_ID]["turns"][0]["status"] = "inProgress"
        with self.assertRaisesRegex(VerificationError, "thread status is active"):
            self._verify(client)

    def test_altered_native_diff_and_replayed_item_id_are_rejected(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        altered = [dict(item) for item in self.change_items]
        altered[1] = _file_change(
            "add-event", str(self.root / "delegated.txt"), "add", "altered output\n"
        )
        with self.assertRaisesRegex(VerificationError, "replayed native|diff"):
            self._verify(self._client(child_items=[*altered, {"id": "final-message", "type": "agentMessage", "text": "Done."}]))
        replay = [dict(item) for item in self.change_items]
        replay[1] = _file_change(
            "delete-event", str(self.root / "delegated.txt"), "add", "delegated implementation\n"
        )
        with self.assertRaisesRegex(VerificationError, "repeats an item ID"):
            self._verify(self._client(child_items=[*replay, {"id": "final-message", "type": "agentMessage", "text": "Done."}]))

    def test_rerun_after_candidate_mutation_does_not_trust_old_receipt(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        original = self._verify()
        (self.root / "delegated.txt").write_text("changed later\n", encoding="utf-8")
        with self.assertRaisesRegex(VerificationError, "differs from replayed native changes"):
            self._verify()
        self.assertTrue(original["receipt_sha256"])

    def test_assume_unchanged_edit_cannot_hide_an_unexplained_tracked_path(self) -> None:
        self._add_tracked_baseline("other.py")
        _run(self.root, "update-index", "--assume-unchanged", "other.py")
        (self.root / "other.py").write_text("unexplained edit\n", encoding="utf-8")
        self.assertEqual(_run(self.root, "diff", "--name-only", self.base), "")
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(VerificationError, "assume-unchanged entry"):
            self._verify()

    def test_skip_worktree_edit_cannot_hide_an_unexplained_tracked_path(self) -> None:
        self._add_tracked_baseline("other.py")
        _run(self.root, "update-index", "--skip-worktree", "other.py")
        (self.root / "other.py").write_text("unexplained edit\n", encoding="utf-8")
        self.assertEqual(_run(self.root, "diff", "--name-only", self.base), "")
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(VerificationError, "skip-worktree entry"):
            self._verify()

    def test_final_candidate_check_rejects_skip_worktree_added_mid_verification(self) -> None:
        self._add_tracked_baseline("other.py")
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        original_validate = native_provenance._validate_candidate
        validation_calls = 0

        def validate_then_hide_unexplained_edit(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            nonlocal validation_calls
            validation_calls += 1
            result = original_validate(*args, **kwargs)
            if validation_calls == 1:
                (self.root / "other.py").write_text("unexplained edit\n", encoding="utf-8")
                _run(self.root, "update-index", "--skip-worktree", "other.py")
            return result

        with patch.object(
            native_provenance,
            "_validate_candidate",
            side_effect=validate_then_hide_unexplained_edit,
        ):
            with self.assertRaisesRegex(VerificationError, "skip-worktree entry"):
                self._verify()
        self.assertEqual(validation_calls, 2)

    def test_core_filemode_false_cannot_hide_unexplained_mode_change(self) -> None:
        self._add_tracked_baseline("other.py")
        _run(self.root, "config", "core.fileMode", "false")
        (self.root / "other.py").chmod(0o755)
        self.assertEqual(_run(self.root, "diff", "--name-only", self.base), "")
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(VerificationError, "unexplained tracked or untracked paths: other.py"):
            self._verify()

    def test_replace_refs_do_not_redefine_the_requested_base(self) -> None:
        (self.root / "delegated.txt").write_text(
            "replacement baseline\n", encoding="utf-8"
        )
        _run(self.root, "commit", "-qam", "replacement commit")
        replacement = _run(self.root, "rev-parse", "HEAD")
        _run(self.root, "reset", "--hard", self.base)
        _run(self.root, "replace", self.base, replacement)
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )

        receipt = self._verify()
        self.assertEqual(
            receipt["candidateFiles"][0]["sha256"],
            hashlib.sha256(b"delegated implementation\n").hexdigest(),
        )

    def test_nonempty_legacy_grafts_are_rejected(self) -> None:
        grafts = self.root / _run(self.root, "rev-parse", "--git-path", "info/grafts")
        grafts.parent.mkdir(parents=True, exist_ok=True)
        grafts.write_text(self.base + "\n", encoding="ascii")
        with self.assertRaisesRegex(VerificationError, "non-empty legacy Git grafts"):
            self._verify()

    def test_git_environment_overrides_cannot_redirect_candidate_checks(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        with tempfile.TemporaryDirectory(prefix="native-provenance-foreign-") as foreign_dir:
            foreign = Path(foreign_dir)
            _run(foreign, "init", "-q")
            _run(foreign, "config", "user.name", "Foreign Repository")
            _run(foreign, "config", "user.email", "foreign@example.invalid")
            (foreign / "delegated.txt").write_text("foreign baseline\n", encoding="utf-8")
            _run(foreign, "add", "delegated.txt")
            _run(foreign, "commit", "-qm", "foreign base")
            overrides = {
                "GIT_DIR": str(foreign / ".git"),
                "GIT_WORK_TREE": str(foreign),
                "GIT_INDEX_FILE": str(foreign / "alternate-index"),
                "GIT_OBJECT_DIRECTORY": str(foreign / ".git" / "objects"),
                "GIT_COMMON_DIR": str(foreign / ".git"),
                "GIT_REPLACE_REF_BASE": "refs/alternate/replace/",
            }
            with patch.dict(os.environ, overrides):
                receipt = self._verify()
        self.assertEqual(
            receipt["candidateFiles"][0]["path"], "delegated.txt"
        )

    def test_git_candidate_reads_do_not_run_configured_fsmonitor(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        hook = self.root / ".git" / "fsmonitor-probe"
        hook.write_text(
            "#!/bin/sh\nprintf invoked > \"$0.invoked\"\n", encoding="utf-8"
        )
        hook.chmod(0o755)
        marker = Path(str(hook) + ".invoked")
        _run(self.root, "config", "core.fsmonitor", str(hook))

        receipt = self._verify()

        self.assertEqual(receipt["candidateFiles"][0]["path"], "delegated.txt")
        self.assertFalse(marker.exists(), "Git invoked the configured fsmonitor hook")

    def test_linked_git_worktree_remains_supported(self) -> None:
        original_root = self.root
        with tempfile.TemporaryDirectory(prefix="native-provenance-worktree-") as path:
            worktree = Path(path) / "checkout"
            _run(original_root, "worktree", "add", "--detach", str(worktree), self.base)
            self.root = worktree.resolve()
            self.change_items = [
                _file_change(
                    "delete-event", str(self.root / "delegated.txt"), "delete", "baseline\n"
                ),
                _file_change(
                    "add-event", str(self.root / "delegated.txt"), "add",
                    "delegated implementation\n",
                ),
            ]
            self.client = self._client()
            (self.root / "delegated.txt").write_text(
                "delegated implementation\n", encoding="utf-8"
            )
            receipt = self._verify()
        self.root = original_root
        self.assertEqual(receipt["candidateFiles"][0]["path"], "delegated.txt")

    def test_unexplained_shell_or_observable_mcp_effect_is_rejected(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        (self.root / "shell-effect.txt").write_text("unexplained\n", encoding="utf-8")
        command = {
            "id": "command-event", "type": "commandExecution", "command": "touch shell-effect.txt",
            "status": "completed",
        }
        with self.assertRaisesRegex(VerificationError, "unexplained tracked or untracked"):
            self._verify(self._client(child_items=[*self.change_items, command, {"id": "final-message", "type": "agentMessage", "text": "Done."}]))
        (self.root / "shell-effect.txt").unlink()
        (self.root / "mcp-effect.txt").write_text("observable\n", encoding="utf-8")
        mcp = {"id": "mcp-event", "type": "mcpToolCall", "server": "fixture"}
        with self.assertRaisesRegex(VerificationError, "unexplained tracked or untracked"):
            self._verify(self._client(child_items=[*self.change_items, mcp, {"id": "final-message", "type": "agentMessage", "text": "Done."}]))

    def test_opaque_mcp_events_are_reported_when_no_effect_is_observed(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        mcp = {"id": "mcp-event", "type": "mcpToolCall", "server": "fixture"}
        receipt = self._verify(
            self._client(child_items=[*self.change_items, mcp, {"id": "final-message", "type": "agentMessage", "text": "Done."}])
        )
        events = receipt["coverage"]["opaqueToolEvents"]
        self.assertEqual([event["itemId"] for event in events], ["mcp-event"])
        self.assertTrue(events[0]["sha256"])

    def test_traversal_symlink_and_hardlink_paths_fail_closed(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        traversal = {
            **self.request,
            "children": [{"thread_id": CHILD_ID, "expected_files": ["../escape"]}],
        }
        with self.assertRaisesRegex(VerificationError, "traversal"):
            verify_native(self.root, traversal, POLICY, self.client)
        outside = self.root.parent / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        symlink = self.root / "linked.txt"
        symlink.symlink_to(outside)
        with self.assertRaisesRegex(VerificationError, "symlink"):
            verify_native(
                self.root,
                {**self.request, "children": [{"thread_id": CHILD_ID, "expected_files": ["linked.txt"]}]},
                POLICY,
                self.client,
            )
        symlink.unlink()
        hardlink = self.root / "linked.txt"
        os.link(outside, hardlink)
        with self.assertRaisesRegex(VerificationError, "hard-linked"):
            verify_native(
                self.root,
                {**self.request, "children": [{"thread_id": CHILD_ID, "expected_files": ["linked.txt"]}]},
                POLICY,
                self.client,
            )

    def test_move_requires_source_and_destination_in_expected_set(self) -> None:
        (self.root / "delegated.txt").write_text("delegated implementation\n", encoding="utf-8")
        (self.root / "source.txt").write_text("old\n", encoding="utf-8")
        _run(self.root, "add", "source.txt")
        _run(self.root, "commit", "-qm", "add source")
        self.base = _run(self.root, "rev-parse", "HEAD")
        self.request["base_commit"] = self.base
        self.request["children"][0]["expected_files"] = ["delegated.txt", "source.txt", "destination.txt"]
        (self.root / "delegated.txt").write_text("delegated implementation\n", encoding="utf-8")
        (self.root / "source.txt").unlink()
        (self.root / "destination.txt").write_text("new\n", encoding="utf-8")
        move = _file_change(
            "move-event", str(self.root / "source.txt"), "update", "@@ -1 +1 @@\n-old\n+new\n",
            str(self.root / "destination.txt"),
        )
        child_items = [*self.change_items, move, {"id": "final-message", "type": "agentMessage", "text": "Done."}]
        # The child fixture emits the delegated replacement before the move.
        self.client = self._client(child_items=child_items)
        receipt = self._verify()
        final = {item["path"]: item["exists"] for item in receipt["candidateFiles"]}
        self.assertFalse(final["source.txt"])
        self.assertTrue(final["destination.txt"])
        self.request["children"][0]["expected_files"] = ["delegated.txt", "destination.txt"]
        with self.assertRaisesRegex(VerificationError, "unexpected native fileChange paths"):
            self._verify()

    def test_update_hunks_replay_and_bad_context_is_rejected(self) -> None:
        (self.root / "delegated.txt").write_text("updated line\n", encoding="utf-8")
        update = _file_change(
            "update-event", str(self.root / "delegated.txt"), "update",
            "@@ -1 +1 @@\n-baseline\n+updated line\n",
        )
        client = self._client(
            child_items=[update, {"id": "final-message", "type": "agentMessage", "text": "Done."}]
        )
        self.assertTrue(self._verify(client)["receipt_sha256"])
        bad_update = _file_change(
            "update-event", str(self.root / "delegated.txt"), "update",
            "@@ -1 +1 @@\n-wrong context\n+updated line\n",
        )
        with self.assertRaisesRegex(VerificationError, "context does not match"):
            self._verify(
                self._client(
                    child_items=[bad_update, {"id": "final-message", "type": "agentMessage", "text": "Done."}]
                )
            )

    def test_paginated_turns_and_items_are_exhausted(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        client = self._client()
        for value in client.threads.values():
            value["turns"].insert(
                0,
                {
                    "id": value["thread"]["id"] + "-prior-turn",
                    "status": "completed",
                    "items": [
                        {
                            "id": value["thread"]["id"] + "-prior-message",
                            "type": "agentMessage",
                            "text": "Earlier completed turn.",
                        }
                    ],
                },
            )
            value["thread"]["historyMode"] = "paginated"
            for turn in value["turns"]:
                turn["itemsView"] = "summary"
                turn["fixtureItems"] = turn["items"]
                turn.pop("items")
        receipt = self._verify(client)
        self.assertTrue(receipt["receipt_sha256"])
        self.assertGreater(client.turn_calls, 0)
        self.assertGreater(client.item_calls, 0)

    def test_macos_tmp_root_alias_is_accepted_without_resolving_inside_paths(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("the /tmp to /private/tmp alias is macOS-specific")
        with tempfile.TemporaryDirectory(prefix="native-provenance-alias-", dir="/tmp") as path:
            self.root = Path(path).resolve()
            _run(self.root, "init", "-q")
            _run(self.root, "config", "user.name", "Provenance Test")
            _run(self.root, "config", "user.email", "provenance@example.invalid")
            (self.root / "delegated.txt").write_text("baseline\n", encoding="utf-8")
            _run(self.root, "add", "delegated.txt")
            _run(self.root, "commit", "-qm", "base")
            self.base = _run(self.root, "rev-parse", "HEAD")
            self.request["base_commit"] = self.base
            alias_root = Path("/", "tmp", *self.root.parts[3:])
            for item in self.change_items:
                item["changes"][0]["path"] = str(alias_root / "delegated.txt")
            (self.root / "delegated.txt").write_text(
                "delegated implementation\n", encoding="utf-8"
            )
            receipt = self._verify()
            self.assertEqual(receipt["candidateFiles"][0]["path"], "delegated.txt")

    def test_bad_pagination_schema_fails_closed(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )

        class BrokenClient(FixtureClient):
            def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
                if method == "thread/turns/list":
                    return {"data": [], "nextCursor": "same"}
                return super().call(method, params)

        client = self._client()
        for value in client.threads.values():
            value["thread"]["historyMode"] = "paginated"
        with self.assertRaisesRegex(VerificationError, "empty page"):
            self._verify(BrokenClient(client.threads))

    def test_repeated_cursor_and_unknown_native_item_fail_closed(self) -> None:
        (self.root / "delegated.txt").write_text(
            "delegated implementation\n", encoding="utf-8"
        )
        unknown = {"id": "unknown-event", "type": "newNativeItemType"}
        with self.assertRaisesRegex(VerificationError, "unknown thread item type"):
            self._verify(
                self._client(
                    child_items=[*self.change_items, unknown,
                                 {"id": "final-message", "type": "agentMessage", "text": "Done."}]
                )
            )

        class RepeatedCursorClient(FixtureClient):
            def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
                if method == "thread/turns/list":
                    data = self.threads[params["threadId"]]["turns"]
                    return {"data": data, "nextCursor": "repeat"}
                return super().call(method, params)

        client = self._client()
        for value in client.threads.values():
            value["thread"]["historyMode"] = "paginated"
        with self.assertRaisesRegex(VerificationError, "repeated pagination cursor"):
            self._verify(RepeatedCursorClient(client.threads))

    def test_sequential_overlapping_children_replay_in_native_activity_order(self) -> None:
        first_id, second_id = "child-first", "child-second"
        path = str(self.root / "delegated.txt")
        first_event = _file_change(
            "first-update", path, "update", "@@ -1 +1 @@\n-baseline\n+first\n"
        )
        second_event = _file_change(
            "second-update", path, "update", "@@ -1 +1 @@\n-first\n+second\n"
        )
        parent_items = [self._task_item()]
        for event_id, child_id, kind in (
            ("first-start", first_id, "started"),
            ("first-complete", first_id, "completed"),
            ("second-start", second_id, "started"),
            ("second-complete", second_id, "completed"),
        ):
            parent_items.append({
                "id": event_id, "type": "subAgentActivity", "agentThreadId": child_id,
                "agentPath": "implementer", "kind": kind,
            })

        def child(thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
            return {
                "thread": {
                    "id": thread_id, "cwd": str(self.root), "historyMode": "legacy",
                    "status": {"type": "idle"}, "parentThreadId": PARENT_ID,
                    "agentRole": "implementer", "model": "model-test", "reasoningEffort": "high",
                },
                "turns": [{
                    "id": thread_id + "-turn", "status": "completed",
                    "items": [event, {"id": thread_id + "-message", "type": "agentMessage", "text": "Done."}],
                }],
            }

        client = FixtureClient({
            PARENT_ID: {
                "thread": self._thread(PARENT_ID),
                "turns": [{"id": "parent-turn", "status": "inProgress", "items": parent_items}],
            },
            first_id: child(first_id, first_event),
            second_id: child(second_id, second_event),
        })
        self.request["children"] = [
            {"thread_id": second_id, "expected_files": ["delegated.txt"]},
            {"thread_id": first_id, "expected_files": ["delegated.txt"]},
        ]
        (self.root / "delegated.txt").write_text("second\n", encoding="utf-8")
        receipt = self._verify(client)
        self.assertEqual(receipt["candidateFiles"][0]["sha256"],
                         hashlib.sha256(b"second\n").hexdigest())

    def test_concurrent_overlapping_children_are_ambiguous(self) -> None:
        first_id, second_id = "child-first", "child-second"
        path = str(self.root / "delegated.txt")
        first_event = _file_change(
            "first-update", path, "update", "@@ -1 +1 @@\n-baseline\n+first\n"
        )
        second_event = _file_change(
            "second-update", path, "update", "@@ -1 +1 @@\n-first\n+second\n"
        )
        parent_items = [self._task_item()]
        for event_id, child_id, kind in (
            ("first-start", first_id, "started"),
            ("second-start", second_id, "started"),
            ("first-complete", first_id, "completed"),
            ("second-complete", second_id, "completed"),
        ):
            parent_items.append({
                "id": event_id, "type": "subAgentActivity", "agentThreadId": child_id,
                "agentPath": "implementer", "kind": kind,
            })
        threads = {PARENT_ID: {
            "thread": self._thread(PARENT_ID),
            "turns": [{"id": "parent-turn", "status": "inProgress", "items": parent_items}],
        }}
        for thread_id, event in ((first_id, first_event), (second_id, second_event)):
            threads[thread_id] = {
                "thread": {
                    "id": thread_id, "cwd": str(self.root), "historyMode": "legacy",
                    "status": {"type": "idle"}, "parentThreadId": PARENT_ID,
                    "agentRole": "implementer", "model": "model-test", "reasoningEffort": "high",
                },
                "turns": [{
                    "id": thread_id + "-turn", "status": "completed",
                    "items": [event, {"id": thread_id + "-message", "type": "agentMessage", "text": "Done."}],
                }],
            }
        self.request["children"] = [
            {"thread_id": first_id, "expected_files": ["delegated.txt"]},
            {"thread_id": second_id, "expected_files": ["delegated.txt"]},
        ]
        (self.root / "delegated.txt").write_text("second\n", encoding="utf-8")
        with self.assertRaisesRegex(VerificationError, "concurrent native children overlap"):
            self._verify(FixtureClient(threads))


if __name__ == "__main__":
    unittest.main()
