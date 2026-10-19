"""Copilot's opt-in frozen diff delivery through the registered adapter."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from test_claude_review_commands import (
    EPIC_ID,
    TASK_ID,
    _assert_fixed_read_only_argv,
    _commit_change,
    _fake_claude,
    _flow_repo,
    _git,
    _git_raw,
    _impl_review,
    _run_cli,
)

import flowctl

SID = "11111111-2222-3333-4444-555555555555"
REVIEW = "Reviewed frozen evidence.\n<verdict>NEEDS_WORK</verdict>\n"
FAKE_COPILOT = "/fake/bin/copilot"


@contextlib.contextmanager
def _fake_copilot(*, timeout: bool = False):
    calls: list[dict] = []
    real_run = flowctl.subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd[0] != FAKE_COPILOT:
            return real_run(cmd, **kwargs)
        prompt = kwargs.get("input") if "-p" not in cmd else cmd[cmd.index("-p") + 1]
        scratch = Path(kwargs["cwd"]) / ".flow/tmp/claude-review"
        files = sorted(scratch.glob("*.diff")) if scratch.exists() else []
        calls.append({
            "argv": cmd,
            "prompt": prompt,
            "files": files,
            "timeout": kwargs["timeout"],
        })
        if timeout:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 0, REVIEW, "")

    with mock.patch.object(flowctl, "require_copilot", return_value=FAKE_COPILOT), \
            mock.patch.object(flowctl, "get_copilot_version", return_value="1.0.65"), \
            mock.patch.object(flowctl.subprocess, "run", side_effect=fake_run), \
            mock.patch.dict(os.environ, {"FLOW_REVIEW_EXEC_TIMEOUT": "37"}):
        yield calls


def _policy(repo: Path, value: object) -> None:
    (repo / ".flow/config.json").write_text(
        json.dumps({"review": {"copilotDiffDelivery": value}}), encoding="utf-8",
    )


def _primary(base: str, receipt: Path):
    return _run_cli(
        "copilot", "impl-review", TASK_ID, "--base", base,
        "--receipt", str(receipt), "--spec", "copilot:qwen-l40s:medium", "--json",
    )


class CopilotDiffDelivery(unittest.TestCase):
    def _adapter(self, repo: Path, base: str, head: str, *, receipt_id: str = "receipt"):
        args = argparse.Namespace(claude_range=(base, head, receipt_id))
        spec = flowctl.BackendSpec.parse("copilot:qwen-l40s:medium").resolve()
        return flowctl._copilot_run_exec(
            "Inspect the frozen range.", session_id=SID, repo_root=repo, spec=spec,
            resolution_out={}, args=args,
        )

    def test_default_native_and_config_writes(self) -> None:
        self.assertEqual(flowctl.get_default_config()["review"]["copilotDiffDelivery"], "native")
        for invalid in ("typo", "File", "true", "null", "1"):
            with _flow_repo():
                code, out, err = _run_cli(
                    "config", "set", "review.copilotDiffDelivery", invalid, "--json",
                )
                self.assertNotEqual(code, 0, out + err)
        for value in flowctl.COPILOT_DIFF_DELIVERY_VALUES:
            with _flow_repo() as (repo, _base):
                code, out, err = _run_cli(
                    "config", "set", "review.copilotDiffDelivery", value, "--json",
                )
                self.assertEqual(code, 0, out + err)
                self.assertEqual(json.loads(out)["value"], value)
                self.assertEqual(json.loads((repo / ".flow/config.json").read_text())["review"]["copilotDiffDelivery"], value)

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
                argv = calls[0]["argv"]
                denied_tools = [
                    argv[index + 1]
                    for index, value in enumerate(argv[:-1])
                    if value == "--deny-tool"
                ]
                self.assertEqual(denied_tools, ["write", "shell"])
                self.assertEqual(argv[argv.index("--model") + 1], "qwen-l40s")
                self.assertEqual(argv[argv.index("--effort") + 1], "medium")

    def test_primary_rereview_and_completion_routes_use_exact_pinned_files(self) -> None:
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            _policy(repo, "file")
            receipt = repo / "receipt.json"
            heads = []
            for iteration in range(2):
                if iteration:
                    _commit_change(repo, "def a(x):\n    return x + 2\n", "fix")
                head = _git(repo, "rev-parse", "HEAD")
                heads.append(head)
                code, out, err = _primary(base, receipt)
                self.assertEqual(code, 0, out + err)
                call = calls[-1]
                path = repo / ".flow/tmp/claude-review" / f"receipt-{base[:7]}-{head[:7]}.diff"
                self.assertIn(path, call["files"])
                self.assertIn(str(path), call["prompt"])
                self.assertIn("file tools", call["prompt"])
                self.assertIn("do not delegate", call["prompt"])
                self.assertNotIn("diff --git", call["prompt"])
                self.assertEqual(path.read_text(encoding="utf-8"), _git_raw(repo, "diff", f"{base}..{head}"))
                self.assertEqual(call["timeout"], 37)
            self.assertTrue(any(arg.startswith("--session-id=") for arg in calls[0]["argv"]))
            self.assertTrue(any(arg.startswith("--resume=") for arg in calls[1]["argv"]))
            self.assertEqual(len(calls[1]["files"]), 2)
            attempts = json.loads((repo / ".flow/specs" / f"{EPIC_ID}.json").read_text())["review_attempts"]
            self.assertEqual([(row["base_sha"], row["head_sha"]) for row in attempts[-2:]], [(base, head) for head in heads])

        for kind in ("plan", "completion"):
            with self.subTest(kind=kind), _flow_repo() as (repo, base), _fake_copilot() as calls:
                _policy(repo, "file")
                head = _git(repo, "rev-parse", "HEAD")
                if kind == "completion":
                    _git(repo, "branch", "main", base)
                argv = [
                    "copilot", f"{kind}-review", EPIC_ID, "--receipt", str(repo / f"{kind}.json"),
                    "--spec", "copilot:qwen-l40s:medium", "--json",
                ]
                if kind == "plan":
                    argv.extend(["--base", base])
                code, out, err = _run_cli(*argv)
                self.assertEqual(code, 0, out + err)
                self.assertEqual(len(calls), 1)
                (path,) = calls[0]["files"]
                self.assertIn(head[:7], path.name)
                self.assertIn(str(path), calls[0]["prompt"])
                self.assertEqual(path.read_text(encoding="utf-8"), _git_raw(repo, "diff", f"{base}..{head}"))

    def test_file_delivery_uses_copilot_stdin_transport_on_windows(self) -> None:
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            _policy(repo, "file")
            head = _git(repo, "rev-parse", "HEAD")
            with mock.patch.object(flowctl.sys, "platform", "win32"):
                code, out, err = _primary(base, repo / "receipt.json")
            self.assertEqual(code, 0, out + err)
            self.assertEqual(len(calls), 1)
            call = calls[0]
            self.assertNotIn("-p", call["argv"])
            self.assertIn("## Diff delivery (copilot backend)", call["prompt"])
            (path,) = call["files"]
            self.assertIn(str(path), call["prompt"])
            self.assertIn(f"{base}..{head}", call["prompt"])
            self.assertEqual(path.read_text(encoding="utf-8"), _git_raw(repo, "diff", f"{base}..{head}"))

    def test_sequential_fanout_uses_distinct_frozen_file_per_axis(self) -> None:
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            (repo / ".flow/config.json").write_text(json.dumps({"review": {
                "copilotDiffDelivery": "file", "fanoutExecution": "sequential",
            }}), encoding="utf-8")
            head = _git(repo, "rev-parse", "HEAD")
            code, out, err = _run_cli(
                "copilot", "impl-review-fanout", TASK_ID, "--base", base,
                "--spec", "copilot:qwen-l40s:medium", "--receipt", str(repo / "panel.json"), "--json",
            )
            self.assertEqual(code, 0, out + err)
            panel = json.loads(out)
            self.assertEqual(len(calls), 3)
            self.assertFalse(panel["failed_draws"])
            expected = _git_raw(repo, "diff", f"{base}..{head}")
            session_ids = []
            for axis, call in zip(flowctl.REVIEW_FANOUT_AXES, calls, strict=True):
                path = repo / ".flow/tmp/claude-review" / f"{panel['rid']}-{axis}-{base[:7]}-{head[:7]}.diff"
                self.assertIn(path, call["files"])
                self.assertIn(str(path), call["prompt"])
                self.assertEqual(path.read_text(encoding="utf-8"), expected)
                self.assertNotIn("diff --git", call["prompt"])
                session_ids.extend(arg for arg in call["argv"] if arg.startswith("--session-id="))
            self.assertEqual(len(set(session_ids)), 3)

    def test_adapter_uses_frozen_head_and_skips_policy_for_unranged_pass(self) -> None:
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            _policy(repo, "file")
            frozen = _git(repo, "rev-parse", "HEAD")
            _commit_change(repo, "def a(x):\n    return x + 99\n", "later")
            result = self._adapter(repo, base, frozen)
            self.assertEqual(result[2], 0)
            path = calls[0]["files"][0]
            frozen_diff = path.read_text(encoding="utf-8")
            self.assertEqual(frozen_diff, _git_raw(repo, "diff", f"{base}..{frozen}"))
            self.assertNotIn("+ 99", frozen_diff)

            _policy(repo, "invalid-hand-edited-value")
            with mock.patch.object(flowctl, "_review_config_enum", side_effect=AssertionError("unranged pass read policy")) as policy, \
                    mock.patch.object(flowctl, "_claude_materialise_review_diff") as materialise, \
                    mock.patch.object(flowctl, "_managed_review_exec", return_value=(REVIEW, SID, 0, "")), \
                    mock.patch.object(flowctl, "run_copilot_exec") as cli:
                args = argparse.Namespace()
                result = flowctl._copilot_run_exec(
                    "Continue the existing review.", session_id=SID, repo_root=repo,
                    spec=flowctl.BackendSpec.parse("copilot:qwen-l40s:medium").resolve(),
                    resolution_out={}, args=args,
                )
                self.assertEqual(result[2], 0)
                policy.assert_not_called()
                materialise.assert_not_called()
                cli.assert_not_called()

    def test_invalid_policy_and_materialisation_fail_before_both_dispatch_paths(self) -> None:
        with _flow_repo() as (repo, base), _fake_copilot() as calls:
            _policy(repo, "invalid-hand-edited-value")
            code, out, err = _primary(base, repo / "receipt.json")
            self.assertNotEqual(code, 0, out + err)
            self.assertIn("review.copilotDiffDelivery", out + err)
            self.assertFalse(calls)

            head = _git(repo, "rev-parse", "HEAD")
            with mock.patch.object(flowctl, "_managed_review_exec") as managed, \
                    mock.patch.object(flowctl, "run_copilot_exec") as cli:
                result = self._adapter(repo, base, head)
                self.assertEqual(result[2], 2)
                managed.assert_not_called()
                cli.assert_not_called()

        with _flow_repo() as (repo, base):
            _policy(repo, "file")
            head = _git(repo, "rev-parse", "HEAD")
            for receipt_id in ("../escape", "a/b", "a\\b", "..", ""):
                with self.subTest(receipt_id=receipt_id), \
                        mock.patch.object(flowctl, "_managed_review_exec") as managed, \
                        mock.patch.object(flowctl, "run_copilot_exec") as cli:
                    result = self._adapter(repo, base, head, receipt_id=receipt_id)
                    self.assertEqual(result[2], 2)
                    managed.assert_not_called()
                    cli.assert_not_called()

            scratch = repo / ".flow/tmp/claude-review"
            scratch.parent.mkdir(parents=True, exist_ok=True)
            outside = repo / "outside"
            outside.mkdir()
            try:
                scratch.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with mock.patch.object(flowctl, "_managed_review_exec") as managed, \
                    mock.patch.object(flowctl, "run_copilot_exec") as cli:
                self.assertEqual(self._adapter(repo, base, head)[2], 2)
                managed.assert_not_called()
                cli.assert_not_called()
            scratch.unlink()
            scratch.mkdir()
            leaf = scratch / f"receipt-{base[:7]}-{head[:7]}.diff"
            target = outside / "sentinel"
            target.write_text("keep", encoding="utf-8")
            leaf.symlink_to(target)
            with mock.patch.object(flowctl, "_managed_review_exec") as managed, \
                    mock.patch.object(flowctl, "run_copilot_exec") as cli:
                self.assertEqual(self._adapter(repo, base, head)[2], 2)
                managed.assert_not_called()
                cli.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_file_materialises_before_managed_execution(self) -> None:
        with _flow_repo() as (repo, base):
            _policy(repo, "file")
            head = _git(repo, "rev-parse", "HEAD")
            with mock.patch.object(flowctl, "_managed_review_exec", return_value=(REVIEW, SID, 0, "")) as managed, \
                    mock.patch.object(flowctl, "run_copilot_exec") as cli:
                result = self._adapter(repo, base, head)
                self.assertEqual(result[2], 0)
                prompt = managed.call_args.args[0]
                self.assertIn(str(repo / ".flow/tmp/claude-review"), prompt)
                self.assertNotIn("diff --git", prompt)
                cli.assert_not_called()

    def test_claude_qwen_medium_terminal_result_survives_copilot_file_config(self) -> None:
        with _flow_repo() as (repo, base):
            _policy(repo, "file")
            receipt = repo / "claude.json"
            head = _git(repo, "rev-parse", "HEAD")
            with _fake_claude() as calls:
                code, out, err = _impl_review(
                    repo, base, receipt, "--spec", "claude:qwen-l40s:medium",
                )
            self.assertEqual(code, 0, out + err)
            self.assertEqual(len(calls), 1)
            response = json.loads(out)
            stored = json.loads(receipt.read_text(encoding="utf-8"))
            for row in (response, stored):
                self.assertEqual(row["mode"], "claude")
                self.assertEqual(row["model"], "qwen-l40s")
                self.assertEqual(row["effort"], "medium")
                self.assertEqual(row["verdict"], "NEEDS_WORK")
            argv = calls[0]["argv"]
            _assert_fixed_read_only_argv(self, argv)
            self.assertEqual(argv[argv.index("--model") + 1], "qwen-l40s")
            self.assertEqual(argv[argv.index("--effort") + 1], "medium")
            diff_path = repo / ".flow/tmp/claude-review" / f"claude-{base[:7]}-{head[:7]}.diff"
            self.assertIn(str(diff_path), calls[0]["stdin"])
            self.assertEqual(diff_path.read_text(encoding="utf-8"), _git_raw(repo, "diff", f"{base}..{head}"))


if __name__ == "__main__":
    unittest.main()
