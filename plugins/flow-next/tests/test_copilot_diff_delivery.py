"""Opt-in Copilot primary diff transport, using real git and the CLI adapter."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from test_claude_review_commands import (
    EPIC_ID, TASK_ID, _commit_change, _flow_repo, _git, _git_raw, _run_cli,
)

import flowctl


def setUpModule():
    # Delivery tests exercise native/file transport with stock session resume.
    global _stock_session_policy
    _stock_session_policy = mock.patch.dict(os.environ, {"FLOW_RE_REVIEW_SESSION": "resume"})
    _stock_session_policy.start()


def tearDownModule():
    _stock_session_policy.stop()

SID = "11111111-2222-3333-4444-555555555555"
REVIEW = "Reviewed frozen evidence.\n<verdict>NEEDS_WORK</verdict>\n"


@contextlib.contextmanager
def _fake_copilot(*, timeout=False):
    calls = []
    real_run = flowctl.subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd[0] != "/fake/copilot":
            return real_run(cmd, **kwargs)
        prompt = kwargs.get("input") if "-p" not in cmd else cmd[cmd.index("-p") + 1]
        files = sorted((Path(kwargs["cwd"]) / ".flow/tmp/claude-review").glob("*.diff"))
        calls.append({"argv": cmd, "prompt": prompt, "files": files, "timeout": kwargs["timeout"]})
        if timeout:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 0, REVIEW, "")

    with mock.patch.object(flowctl, "require_copilot", return_value="/fake/copilot"), \
            mock.patch.object(flowctl, "get_copilot_version", return_value="1.0.65"), \
            mock.patch.object(flowctl.subprocess, "run", side_effect=fake_run), \
            mock.patch.dict("os.environ", {"FLOW_REVIEW_EXEC_TIMEOUT": "37"}):
        yield calls


def _policy(repo, value):
    (repo / ".flow/config.json").write_text(
        json.dumps({"review": {"copilotDiffDelivery": value}}), encoding="utf-8",
    )


def _primary(base, receipt):
    return _run_cli(
        "copilot", "impl-review", TASK_ID, "--base", base, "--receipt", str(receipt),
        "--spec", "copilot:test-model:high", "--json",
    )


class CopilotDiffDelivery(unittest.TestCase):
    def test_default_and_explicit_native_keep_prompt_and_evidence_contract(self):
        for policy in (None, "native"):
            with self.subTest(policy=policy), _flow_repo() as (repo, base), _fake_copilot() as calls:
                if policy:
                    _policy(repo, policy)
                code, out, err = _primary(base, repo / "receipt.json")
                self.assertEqual(code, 0, out + err)
                self.assertEqual(len(calls), 1)
                self.assertFalse(calls[0]["files"])
                self.assertNotIn("## Diff delivery", calls[0]["prompt"])
                self.assertIn("git diff", calls[0]["prompt"])

    def test_primary_and_resumed_review_deliver_exact_ranges_without_embedding(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            _policy(repo, "file")
            receipt = repo / "receipt.json"
            heads = []
            source = repo / "src/mod.py"
            for iteration in range(2):
                if iteration:
                    _commit_change(repo, "def a(x):\n    return x + 2\n", "fix")
                heads.append(_git(repo, "rev-parse", "HEAD"))
                source_fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()
                code, out, err = _primary(base, receipt)
                self.assertEqual(code, 0, out + err)
                call = calls[-1]
                path = repo / ".flow/tmp/claude-review" / f"receipt-{base[:7]}-{heads[-1][:7]}.diff"
                self.assertIn(path, call["files"])
                self.assertIn(str(path), call["prompt"])
                expected = _git_raw(repo, "diff", f"{base}..{heads[-1]}")
                self.assertEqual(path.read_text(encoding="utf-8"), expected)
                self.assertNotIn("diff --git", call["prompt"])
                self.assertIn("file tools", call["prompt"])
                self.assertIn("do not delegate", call["prompt"])
                self.assertEqual(call["timeout"], 37)
                self.assertEqual(source_fingerprint, hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertIn("shell", call["argv"])
                self.assertIn("write", call["argv"])
                data = json.loads(receipt.read_text(encoding="utf-8"))
                attempts = json.loads((repo / ".flow/specs" / f"{TASK_ID.rsplit('.', 1)[0]}.json").read_text(encoding="utf-8"))["review_attempts"]
                self.assertEqual(attempts[-1]["head_sha"], heads[-1])
                self.assertEqual(attempts[-1]["base_sha"], base)
                self.assertEqual(data["mode"], "copilot")
            self.assertTrue(any(a.startswith("--session-id=") for a in calls[0]["argv"]))
            self.assertTrue(any(a.startswith("--resume=") for a in calls[1]["argv"]))
            self.assertEqual(len(calls[1]["files"]), 2)

    def test_plan_and_completion_primary_dispatches_use_file_delivery(self):
        for kind in ("plan", "completion"):
            with self.subTest(kind=kind), _flow_repo() as (repo, base), _fake_copilot() as calls:
                _policy(repo, "file")
                head = _git(repo, "rev-parse", "HEAD")
                receipt = repo / f"{kind}.json"
                argv = ["copilot", f"{kind}-review", EPIC_ID, "--receipt", str(receipt),
                        "--spec", "copilot:test-model:high", "--json"]
                if kind == "plan":
                    argv.extend(["--base", base])
                elif not _git(repo, "branch", "--list", "main"):
                    _git(repo, "branch", "main", base)
                code, out, err = _run_cli(*argv)
                self.assertEqual(code, 0, out + err)
                self.assertEqual(len(calls), 1)
                (path,) = calls[0]["files"]
                self.assertIn(str(path), calls[0]["prompt"])
                self.assertIn(head[:7], path.name)
                self.assertNotIn("diff --git", calls[0]["prompt"])
                self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["mode"], "copilot")

    def test_sequential_fanout_delivers_separate_frozen_file_per_axis(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            (repo / ".flow/config.json").write_text(json.dumps({"review": {
                "copilotDiffDelivery": "file", "fanoutExecution": "sequential",
            }}), encoding="utf-8")
            head = _git(repo, "rev-parse", "HEAD")
            code, out, err = _run_cli(
                "copilot", "impl-review-fanout", TASK_ID, "--base", base,
                "--spec", "copilot:test-model:high", "--receipt", str(repo / "panel.json"), "--json",
            )
            self.assertEqual(code, 0, out + err)
            panel = json.loads(out)
            self.assertEqual(len(calls), 3)
            self.assertFalse(panel["failed_draws"])
            expected = _git_raw(repo, "diff", f"{base}..{head}")
            sessions = []
            for axis, call in zip(flowctl.REVIEW_FANOUT_AXES, calls, strict=True):
                path = repo / ".flow/tmp/claude-review" / f"{panel['rid']}-{axis}-{base[:7]}-{head[:7]}.diff"
                self.assertIn(path, call["files"])
                self.assertIn(str(path), call["prompt"])
                self.assertIn(flowctl.REVIEW_FANOUT_AXIS_LINES[axis], call["prompt"])
                self.assertEqual(path.read_text(encoding="utf-8"), expected)
                self.assertNotIn("diff --git", call["prompt"])
                sessions.extend(arg for arg in call["argv"] if arg.startswith("--session-id="))
            self.assertEqual(len(set(sessions)), 3)

    def _adapter(self, repo, base, head, *, receipt_id="receipt", ranged=True):
        args = argparse.Namespace(copilot_diff_delivery="file")
        if ranged:
            args.claude_range = (base, head, receipt_id)
        return flowctl._copilot_run_exec(
            "Inspect the frozen range.", session_id=SID, repo_root=repo,
            spec=flowctl.BackendSpec.parse("copilot:test-model:high").resolve(),
            resolution_out={}, args=args,
        )

    def test_adapter_uses_frozen_head_after_branch_moves(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            frozen = _git(repo, "rev-parse", "HEAD")
            _commit_change(repo, "def a(x):\n    return x + 99\n", "later")
            result = self._adapter(repo, base, frozen)
            self.assertEqual(result[2], 0)
            path = calls[0]["files"][0]
            self.assertEqual(path.read_text(encoding="utf-8"), _git_raw(repo, "diff", f"{base}..{frozen}"))
            self.assertNotIn("+ 99", path.read_text(encoding="utf-8"))

    def test_optional_pass_retains_primary_file_and_timeout_keeps_marker_contract(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            head = _git(repo, "rev-parse", "HEAD")
            self.assertEqual(self._adapter(repo, base, head)[2], 0)
            path = calls[0]["files"][0]
            fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
            with mock.patch.object(flowctl, "_claude_materialise_review_diff") as materialise:
                self.assertEqual(self._adapter(repo, base, head, ranged=False)[2], 0)
                materialise.assert_not_called()
            self.assertNotIn("## Diff delivery", calls[-1]["prompt"])
            self.assertEqual(fingerprint, hashlib.sha256(path.read_bytes()).hexdigest())
        with _flow_repo() as (repo, base), _fake_copilot(timeout=True) as calls:
            result = self._adapter(repo, base, _git(repo, "rev-parse", "HEAD"))
            self.assertEqual(result[2], 2)
            self.assertIn("37s", result[3])
            self.assertEqual(len(calls), 1)
            self.assertFalse(flowctl._copilot_session_marker(repo, SID).exists())

    def test_no_range_session_pass_never_reads_delivery_policy(self):
        with _flow_repo() as (repo, base):
            _policy(repo, "invalid-hand-edited-value")
            prompt = "Continue reviewing the prior session evidence."
            expected = (REVIEW, SID, 0, "")
            resolution = {}
            args = argparse.Namespace()
            spec = flowctl.BackendSpec.parse("copilot:test-model:high").resolve()
            with mock.patch.object(flowctl, "_review_config_enum", side_effect=AssertionError("irrelevant policy read")) as policy,                     mock.patch.object(flowctl, "_claude_materialise_review_diff") as materialise,                     mock.patch.object(flowctl, "_managed_review_exec", return_value=None) as managed,                     mock.patch.object(flowctl, "run_copilot_exec", return_value=expected) as cli:
                result = flowctl._copilot_run_exec(
                    prompt, session_id=SID, repo_root=repo, spec=spec,
                    resolution_out=resolution, args=args,
                )
                self.assertEqual(result, expected)
                policy.assert_not_called()
                materialise.assert_not_called()
                self.assertEqual(managed.call_args.args[0], prompt)
                cli.assert_called_once_with(
                    prompt, session_id=SID, repo_root=repo, spec=spec, resolution_out=resolution,
                )

    def test_materialisation_failure_never_launches_cli_or_managed_execution(self):
        with _flow_repo() as (repo, base):
            head = _git(repo, "rev-parse", "HEAD")
            for receipt_id in ("../escape", "a/b", "a\\b", "..", ""):
                with self.subTest(receipt_id=receipt_id), \
                        mock.patch.object(flowctl, "_managed_review_exec") as managed, \
                        mock.patch.object(flowctl, "run_copilot_exec") as cli:
                    result = self._adapter(repo, base, head, receipt_id=receipt_id)
                    self.assertEqual(result[2], 2)
                    managed.assert_not_called()
                    cli.assert_not_called()
            with mock.patch.object(flowctl, "_claude_review_diff_text", side_effect=flowctl.ClaudeReviewDiffError("git failed")), \
                    mock.patch.object(flowctl, "run_copilot_exec") as cli:
                result = self._adapter(repo, base, head)
                self.assertIn("git failed", result[3])
                cli.assert_not_called()

    def test_symlinked_scratch_or_leaf_fail_before_dispatch(self):
        with _flow_repo() as (repo, base):
            head = _git(repo, "rev-parse", "HEAD")
            scratch = repo / ".flow/tmp/claude-review"
            scratch.parent.mkdir(parents=True)
            outside = repo / "outside"
            outside.mkdir()
            scratch.symlink_to(outside, target_is_directory=True)
            with mock.patch.object(flowctl, "run_copilot_exec") as cli:
                self.assertEqual(self._adapter(repo, base, head)[2], 2)
                cli.assert_not_called()
            scratch.unlink()
            scratch.mkdir()
            leaf = scratch / f"receipt-{base[:7]}-{head[:7]}.diff"
            target = outside / "sentinel"
            target.write_text("keep", encoding="utf-8")
            leaf.symlink_to(target)
            with mock.patch.object(flowctl, "run_copilot_exec") as cli:
                self.assertEqual(self._adapter(repo, base, head)[2], 2)
                cli.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_file_delivery_precedes_managed_dispatch_without_local_cli(self):
        with _flow_repo() as (repo, base):
            head = _git(repo, "rev-parse", "HEAD")
            with mock.patch.object(flowctl, "_managed_review_exec", return_value=(REVIEW, SID, 0, "")) as managed, \
                    mock.patch.object(flowctl, "run_copilot_exec") as cli:
                self.assertEqual(self._adapter(repo, base, head)[2], 0)
                self.assertIn(str(repo / ".flow/tmp/claude-review"), managed.call_args.args[0])
                self.assertNotIn("diff --git", managed.call_args.args[0])
                cli.assert_not_called()
