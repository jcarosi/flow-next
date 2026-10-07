"""Fresh CLI re-reviews keep the review round while replacing its session."""

from __future__ import annotations

import json
import os
import contextlib
import subprocess
import unittest
from unittest import mock

from test_claude_review_commands import TASK_ID, _commit_change, _flow_repo, _run_cli
import test_review_fanout as fanout

import flowctl


@contextlib.contextmanager
def _fake_copilot(*, timeout=False):
    """Exercise the real Copilot adapter without calling an external model."""
    calls = []
    real_run = flowctl.subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd[0] != "/fake/copilot":
            return real_run(cmd, **kwargs)
        prompt = kwargs.get("input") if "-p" not in cmd else cmd[cmd.index("-p") + 1]
        calls.append({"argv": cmd, "prompt": prompt})
        if timeout:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(
            cmd, 0, "Reviewed frozen evidence.\n<verdict>NEEDS_WORK</verdict>\n", ""
        )

    with mock.patch.object(flowctl, "require_copilot", return_value="/fake/copilot"), \
            mock.patch.object(flowctl, "get_copilot_version", return_value="1.0.65"), \
            mock.patch.object(flowctl.subprocess, "run", side_effect=fake_run), \
            mock.patch.dict(os.environ, {"FLOW_REVIEW_EXEC_TIMEOUT": "37"}):
        yield calls


class FreshPolicyResolution(unittest.TestCase):
    def test_absent_policy_keeps_stock_resume(self):
        with _flow_repo(), mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(flowctl._resolve_re_review_session(None), "resume")

    def test_user_fresh_and_project_resume_precedence(self):
        with _flow_repo() as (repo, _base), mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            self.assertEqual(flowctl._resolve_re_review_session(None), "fresh")
            (repo / ".flow/config.json").write_text(
                json.dumps({"review": {"reReviewSession": "resume"}}), encoding="utf-8"
            )
            self.assertEqual(flowctl._resolve_re_review_session(None), "resume")
            self.assertEqual(flowctl._resolve_re_review_session("fresh"), "fresh")

    def test_config_get_effective_raw_and_init_unmaterialized(self):
        with _flow_repo() as (repo, _base), mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            self.assertNotIn("reReviewSession", flowctl._init_persisted_defaults()["review"])
            code, out, err = _run_cli("config", "get", "review.reReviewSession", "--json")
            self.assertEqual(code, 0, out + err)
            self.assertEqual(json.loads(out)["value"], "fresh")
            code, out, err = _run_cli(
                "config", "get", "review.reReviewSession", "--raw", "--json"
            )
            self.assertEqual(code, 0, out + err)
            self.assertIsNone(json.loads(out)["value"])
            (repo / ".flow/config.json").write_text(
                json.dumps({"review": {"reReviewSession": "resume"}}), encoding="utf-8"
            )
            code, out, err = _run_cli("config", "get", "review.reReviewSession", "--json")
            self.assertEqual(code, 0, out + err)
            self.assertEqual(json.loads(out)["value"], "resume")

    def test_invalid_explicit_or_project_policy_fails_closed(self):
        with _flow_repo() as (repo, _base):
            with self.assertRaises(ValueError):
                flowctl._resolve_re_review_session("reuse")
            (repo / ".flow/config.json").write_text(
                json.dumps({"review": {"reReviewSession": "reuse"}}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                flowctl._resolve_re_review_session(None)

    def test_invalid_user_policy_still_blocks_cli_dispatch(self):
        with _flow_repo() as (repo, base), mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "invalid"}
        ):
            receipt = repo / "receipt.json"
            code, out, err = _run_cli(
                "copilot", "impl-review", TASK_ID, "--base", base,
                "--receipt", str(receipt), "--spec", "copilot:qwen-l40s:medium", "--json",
            )
            self.assertEqual(code, 2)
            self.assertIn("FLOW_RE_REVIEW_SESSION", out + err)
            self.assertFalse(receipt.exists())

    def test_user_override_does_not_mask_invalid_review_object(self):
        with _flow_repo() as (repo, _base), mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            (repo / ".flow/config.json").write_text(
                '{"review": null}', encoding="utf-8"
            )
            snapshot = flowctl.load_config_snapshot()
            self.assertIsNone(snapshot.merged["review"])

    def test_config_set_on_new_file_preserves_user_policy_inheritance(self):
        with _flow_repo() as (repo, _base), mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            flowctl.set_config("review.backend", "copilot:qwen-l40s:medium")
            saved = json.loads((repo / ".flow/config.json").read_text())
            self.assertNotIn("reReviewSession", saved["review"])
            self.assertEqual(flowctl._resolve_re_review_session(None), "fresh")

    def test_legacy_codex_receipt_without_mode_remains_compatible(self):
        with _flow_repo() as (repo, _base):
            receipt = repo / "legacy-receipt.json"
            receipt.write_text(json.dumps({
                "verdict": "NEEDS_WORK", "session_id": "legacy-codex-session",
                "model": "gpt-5.6-sol", "effort": "high",
            }), encoding="utf-8")
            args = flowctl.argparse.Namespace(re_review_session="fresh", json=True)
            flowctl._require_fresh_receipt_backend(args, str(receipt), "codex")
            spec = flowctl.BackendSpec(
                backend="codex", model="gpt-5.6-sol", effort="high",
                model_explicit=True,
            )
            flowctl._require_fresh_re_review_route(
                str(receipt), "codex", spec, include_effort=True, use_json=True,
            )


class CopilotFreshRereview(unittest.TestCase):
    def test_each_rereview_uses_one_new_session_with_prior_findings(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls, mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            (repo / ".flow/config.json").write_text(json.dumps({"review": {
                "backend": "copilot:qwen-l40s:medium",
            }}), encoding="utf-8")
            receipt = repo / "receipt.json"
            sessions = []
            for turn in range(3):
                if turn:
                    _commit_change(repo, f"def a(x):\n    return x + {turn + 1}\n", "fix")
                code, out, err = _run_cli(
                    "copilot", "impl-review", TASK_ID, "--base", base,
                    "--receipt", str(receipt), "--json",
                )
                self.assertEqual(code, 0, out + err)
                self.assertEqual(len(calls), turn + 1)
                args = calls[-1]["argv"]
                self.assertFalse(any(arg.startswith("--resume=") for arg in args))
                session_args = [arg for arg in args if arg.startswith("--session-id=")]
                self.assertEqual(len(session_args), 1)
                sessions.append(session_args[0].split("=", 1)[1])
                self.assertEqual(args[args.index("--model") + 1], "qwen-l40s")
                self.assertEqual(args[args.index("--effort") + 1], "medium")
                self.assertIn("--deny-tool", args)
                self.assertEqual(json.loads(receipt.read_text())["session_id"], sessions[-1])
                if turn:
                    self.assertIn("<prior_findings>", calls[-1]["prompt"])
                    self.assertIn("Prior finding", calls[-1]["prompt"])
            self.assertEqual(len(set(sessions)), 3)
            self.assertEqual(len(calls), 3)

    def test_explicit_resume_override_retains_old_session(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls, mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            receipt = repo / "receipt.json"
            common = (
                "copilot", "impl-review", TASK_ID, "--base", base,
                "--receipt", str(receipt), "--spec", "copilot:qwen-l40s:medium", "--json",
            )
            code, out, err = _run_cli(*common)
            self.assertEqual(code, 0, out + err)
            _commit_change(repo, "def a(x):\n    return x + 2\n", "fix")
            code, out, err = _run_cli(*common, "--re-review-session", "resume")
            self.assertEqual(code, 0, out + err)
            self.assertEqual(len(calls), 2)
            self.assertIn(f"--resume={json.loads(receipt.read_text())['session_id']}", calls[1]["argv"])

    def test_route_drift_refused_before_round_reservation(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls, mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            receipt = repo / "receipt.json"
            common = (
                "copilot", "impl-review", TASK_ID, "--base", base,
                "--receipt", str(receipt), "--json",
            )
            (repo / ".flow/config.json").write_text(json.dumps({"review": {
                "backend": "copilot:qwen-l40s:medium",
            }}), encoding="utf-8")
            code, out, err = _run_cli(*common)
            self.assertEqual(code, 0, out + err)
            before = receipt.read_bytes()
            _commit_change(repo, "def a(x):\n    return x + 2\n", "fix")
            (repo / ".flow/config.json").write_text(json.dumps({"review": {
                "backend": "copilot:other-model:medium",
            }}), encoding="utf-8")
            code, out, err = _run_cli(*common)
            self.assertEqual(code, 2)
            self.assertIn("differs from the previous receipt", out + err)
            self.assertEqual(len(calls), 1)
            self.assertEqual(receipt.read_bytes(), before)
            spec = json.loads((repo / ".flow/specs" / f"{TASK_ID.rsplit('.', 1)[0]}.json").read_text())
            self.assertFalse(spec.get("review_pending_rounds"))

    def test_foreign_backend_receipt_is_not_treated_as_first_round(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls, mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            receipt = repo / "receipt.json"
            code, out, err = _run_cli(
                "copilot", "impl-review", TASK_ID, "--base", base,
                "--receipt", str(receipt), "--spec", "copilot:qwen-l40s:medium", "--json",
            )
            self.assertEqual(code, 0, out + err)
            before = receipt.read_bytes()
            _commit_change(repo, "def a(x):\n    return x + 2\n", "fix")
            code, out, err = _run_cli(
                "codex", "impl-review", TASK_ID, "--base", base,
                "--receipt", str(receipt), "--spec", "codex:gpt-5.6-sol:high", "--json",
            )
            self.assertEqual(code, 2)
            self.assertIn("same backend", out + err)
            self.assertEqual(receipt.read_bytes(), before)
            self.assertEqual(len(calls), 1)

    def test_unchanged_artifact_refused_before_fresh_dispatch(self):
        with _flow_repo() as (repo, base), _fake_copilot() as calls, mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            receipt = repo / "receipt.json"
            common = (
                "copilot", "impl-review", TASK_ID, "--base", base,
                "--receipt", str(receipt), "--spec", "copilot:qwen-l40s:medium", "--json",
            )
            code, out, err = _run_cli(*common)
            self.assertEqual(code, 0, out + err)
            prior = receipt.read_bytes()
            code, out, err = _run_cli(*common)
            self.assertNotEqual(code, 0)
            self.assertIn("unchanged", (out + err).lower())
            self.assertEqual(len(calls), 1)
            self.assertEqual(receipt.read_bytes(), prior)

    def test_fresh_transport_failure_refunds_one_round(self):
        with _flow_repo() as (repo, base), mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            receipt = repo / "receipt.json"
            common = (
                "copilot", "impl-review", TASK_ID, "--base", base,
                "--receipt", str(receipt), "--spec", "copilot:qwen-l40s:medium", "--json",
            )
            with _fake_copilot():
                code, out, err = _run_cli(*common)
            self.assertEqual(code, 0, out + err)
            original = receipt.read_bytes()
            _commit_change(repo, "def a(x):\n    return x + 2\n", "fix")
            with _fake_copilot(timeout=True) as calls:
                code, out, err = _run_cli(*common)
            self.assertNotEqual(code, 0)
            self.assertEqual(len(calls), 1)
            self.assertTrue(any(arg.startswith("--session-id=") for arg in calls[0]["argv"]))
            self.assertFalse(any(arg.startswith("--resume=") for arg in calls[0]["argv"]))
            spec = json.loads((repo / ".flow/specs" / f"{TASK_ID.rsplit('.', 1)[0]}.json").read_text())
            self.assertEqual(spec["impl_review_rounds"][TASK_ID], 1)
            self.assertEqual(spec.get("review_pending_rounds", {}).get(f"impl:{TASK_ID}", 0), 0)
            self.assertEqual(spec["review_attempts"][-1]["outcome"], "transport_failure")
            self.assertEqual(receipt.read_bytes(), original)

    def test_same_session_id_is_refunded_even_with_a_verdict(self):
        with _flow_repo() as (repo, base), mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        ):
            receipt = repo / "receipt.json"
            common = (
                "codex", "impl-review", TASK_ID, "--base", base,
                "--receipt", str(receipt), "--spec", "codex:gpt-5.6-sol:high", "--json",
            )
            calls = []

            def fake(prompt, *, session_id, repo_root, spec, resolution_out,
                     args, resume_only=False):
                calls.append(session_id)
                return "<verdict>NEEDS_WORK</verdict>", "same-session", 0, ""

            flowctl._wire_backend_review_hooks()
            with mock.patch.dict(flowctl.BACKEND_REGISTRY["codex"], {"run_exec": fake}):
                code, out, err = _run_cli(*common)
                self.assertEqual(code, 0, out + err)
                original = receipt.read_bytes()
                _commit_change(repo, "def a(x):\n    return x + 2\n", "fix")
                code, out, err = _run_cli(*common)
            self.assertNotEqual(code, 0)
            self.assertEqual(calls, [None, None])
            self.assertEqual(receipt.read_bytes(), original)
            spec = json.loads((repo / ".flow/specs" / f"{TASK_ID.rsplit('.', 1)[0]}.json").read_text())
            self.assertEqual(spec["impl_review_rounds"][TASK_ID], 1)
            self.assertEqual(spec.get("review_pending_rounds", {}).get(f"impl:{TASK_ID}", 0), 0)


class BackendFreshRereview(unittest.TestCase):
    def test_codex_cursor_claude_start_new_sessions(self):
        routes = {
            "codex": "codex:gpt-5.6-sol:high",
            "cursor": "cursor:test-model",
            "claude": "claude:claude-opus-5:high",
        }
        flowctl._wire_backend_review_hooks()
        for backend, spec in routes.items():
            with self.subTest(backend=backend), _flow_repo() as (repo, base), \
                    mock.patch.dict(os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}):
                receipt = repo / "receipt.json"
                calls = []

                def fake(prompt, *, session_id, repo_root, spec, resolution_out,
                         args, resume_only=False, calls=calls):
                    calls.append((session_id, prompt, str(spec)))
                    sid = "first-session" if len(calls) == 1 else "second-session"
                    return "<verdict>NEEDS_WORK</verdict>", sid, 0, ""

                with mock.patch.dict(flowctl.BACKEND_REGISTRY[backend], {"run_exec": fake}):
                    code, out, err = _run_cli(
                        backend, "impl-review", TASK_ID, "--base", base,
                        "--receipt", str(receipt), "--spec", spec, "--json",
                    )
                    self.assertEqual(code, 0, out + err)
                    _commit_change(repo, "def a(x):\n    return x + 2\n", "fix")
                    code, out, err = _run_cli(
                        backend, "impl-review", TASK_ID, "--base", base,
                        "--receipt", str(receipt), "--spec", spec, "--json",
                    )
                self.assertEqual(code, 0, out + err)
                self.assertEqual(len(calls), 2)
                self.assertIsNone(calls[1][0])
                self.assertIn("<prior_findings>", calls[1][1])
                data = json.loads(receipt.read_text())
                self.assertEqual(data["session_id"], "second-session")
                self.assertEqual(data["previous_session_id"], "first-session")
                self.assertEqual(data["re_review_session"], "fresh")


class PanelFreshRereview(unittest.TestCase):
    """A finalized three-axis round feeds one independent reviewer per fix."""

    _git = fanout.TestReviewFanout._git
    _run = fanout.TestReviewFanout._run
    _payload = fanout.TestReviewFanout._payload
    _spec_data = fanout.TestReviewFanout._spec_data
    _pending = fanout.TestReviewFanout._pending
    _rounds = fanout.TestReviewFanout._rounds

    def setUp(self):
        fanout.TestReviewFanout.setUp(self)
        self._user_policy = mock.patch.dict(
            os.environ, {"FLOW_RE_REVIEW_SESSION": "fresh"}
        )
        self._user_policy.start()
        self.addCleanup(self._user_policy.stop)
        (self.root / ".flow/config.json").write_text(json.dumps({"review": {
            "backend": "copilot:qwen-l40s:medium",
        }}), encoding="utf-8")

    def test_panel_three_needs_work_then_two_single_fresh_rounds(self):
        receipt = self.root / "panel-receipt.json"
        base = flowctl._resolve_review_sha("HEAD~1")
        self.assertIsNotNone(base)
        axes = []

        def panel(prompt, *, session_id, repo_root, spec, resolution_out, args,
                  resume_only=False):
            axis = fanout._axis_of(prompt)
            axes.append(axis)
            if axis == "integration":
                review = fanout._merged_review("First issue", "Second issue")
            else:
                review = fanout._empty_merged_review()
            return review, session_id, 0, ""

        code, out, err = self._run(
            "copilot", "impl-review-fanout", self.task_id,
            "--base", "HEAD~1", "--receipt", str(receipt), "--json",
            fake=panel, backend="copilot",
        )
        self.assertEqual(code, 0, out + err)
        self.assertCountEqual(axes, ["correctness", "contracts", "integration"])
        rid = self._payload(out)["rid"]
        merge_plan = self.root / "merge-plan.json"
        merge_plan.write_text(json.dumps({
            "keep": ["integration:1", "integration:2"], "collapse": {},
        }), encoding="utf-8")
        code, out, err = self._run(
            "copilot", "impl-review-fanout-finalize", "--rid", rid,
            "--merge-plan", str(merge_plan), "--needs-work-survivors", "2",
            "--json", backend="copilot",
        )
        self.assertEqual(code, 0, out + err)
        prior = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(prior["verdict"], "NEEDS_WORK")
        self.assertEqual([item["ordinal"] for item in prior["findings"]["items"]], [1, 2])
        self.assertEqual(self._rounds(), 1)
        self.assertEqual(self._pending(), 0)

        seen = []

        def single(prompt, *, session_id, repo_root, spec, resolution_out, args,
                   resume_only=False):
            seen.append({"prompt": prompt, "session_id": session_id, "spec": str(spec)})
            review = (
                "Prior finding #1: not-fixed\nPrior finding #2: fixed\n"
                "<verdict>NEEDS_WORK</verdict>"
                if len(seen) == 1 else
                "Prior findings: all fixed\n<verdict>SHIP</verdict>"
            )
            return review, session_id, 0, ""

        for turn in range(2):
            (self.root / "app.py").write_text(f"x = {turn + 3}\n", encoding="utf-8")
            self._git("add", "app.py")
            self._git("commit", "-qm", f"fix-{turn}")
            code, out, err = self._run(
                "copilot", "impl-review", self.task_id, "--base", base,
                "--receipt", str(receipt), "--json", fake=single,
                backend="copilot",
            )
            self.assertEqual(code, 0, out + err)
            self.assertEqual(len(seen), turn + 1)
            self.assertNotEqual(seen[-1]["session_id"], prior["session_id"])
            self.assertEqual(seen[-1]["spec"], "copilot:qwen-l40s:medium")
            self.assertIn("<prior_findings>", seen[-1]["prompt"])
            self.assertIn("First issue", seen[-1]["prompt"])
            self.assertIn("Second issue", seen[-1]["prompt"])
            self.assertIn("firstSeenReceiptId", seen[-1]["prompt"])
            for axis_line in flowctl.REVIEW_FANOUT_AXIS_LINES.values():
                self.assertNotIn(axis_line, seen[-1]["prompt"])
            self.assertEqual(self._pending(), 0)
            prior = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertNotEqual(seen[0]["session_id"], seen[1]["session_id"])
        self.assertEqual(self._rounds(), 0)
        self.assertEqual(prior["verdict"], "SHIP")


if __name__ == "__main__":
    unittest.main()
