"""Flow transition gate for opt-in Codex-native implementation provenance."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import flowctl  # noqa: E402

FLOWCTL_PY = SCRIPTS / "flowctl.py"
SPEC_ID = "fn-1-native-provenance"
TASK_ID = f"{SPEC_ID}.1"
RECEIPT_SHA256 = "a" * 64


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.state = self.root / "runtime-state"
        self.env = {**os.environ, "FLOW_STATE_DIR": str(self.state)}
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.run_ok("init")
        self.run_ok("spec", "create", "--title", "Native provenance")
        self.run_ok("task", "create", "--spec", SPEC_ID, "--title", "Implement")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fixture")
        self.base_commit = self.git("rev-parse", "HEAD").strip()
        self.run_ok("start", TASK_ID)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True,
            check=True,
        )
        return result.stdout

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(FLOWCTL_PY), *args],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )

    def run_ok(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def enable_native(self) -> None:
        self.run_ok(
            "config", "set", "implementation.roles",
            '{"coding":{"model":"example-model","effort":"medium"}}',
        )
        self.run_ok("config", "set", "implementation.provenance", "codex-native")

    def set_raw_config(self, update) -> None:
        path = self.root / ".flow" / "config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        update(config)
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    def set_raw_config_text(self, contents: str) -> None:
        (self.root / ".flow" / "config.json").write_text(contents, encoding="utf-8")

    def request(self, **overrides) -> dict:
        request = {
            "parent_thread": "native-parent-thread",
            "children": [
                {"thread_id": "native-child-thread", "expected_files": ["src/example.py"]}
            ],
            "base_commit": self.base_commit,
            "task": TASK_ID,
        }
        request.update(overrides)
        return request

    def evidence(self, request: dict | None = None) -> dict:
        evidence = {"commits": [], "tests": [], "prs": []}
        if request is not None:
            evidence["native_provenance"] = request
        return evidence

    def done_cli(
        self, evidence: dict, *, force: bool = False
    ) -> subprocess.CompletedProcess[str]:
        args = [
            "done", TASK_ID, "--summary", "- implemented",
            "--evidence", json.dumps(evidence),
        ]
        if force:
            args.append("--force")
        args.append("--json")
        return self.run_cli(*args)

    def _verifier_module(self, verify_native) -> types.ModuleType:
        module = types.ModuleType("flowctl_codex_provenance")

        class VerificationError(Exception):
            pass

        module.VerificationError = VerificationError
        module.verify_native = verify_native
        return module

    def done_in_process_result(
        self, evidence: dict, module: types.ModuleType
    ) -> tuple[int, str]:
        runtime = json.loads(
            (self.state / "tasks" / f"{TASK_ID}.state.json").read_text(
                encoding="utf-8"
            )
        )
        args = argparse.Namespace(
            id=TASK_ID,
            summary="- implemented",
            summary_file=None,
            evidence=json.dumps(evidence),
            evidence_json=None,
            range=None,
            test=None,
            force=False,
            json=True,
        )
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.env),
            mock.patch.object(flowctl, "get_repo_root", return_value=self.root),
            mock.patch.object(
                flowctl, "get_actor", return_value=runtime.get("assignee")
            ),
            mock.patch.dict(sys.modules, {"flowctl_codex_provenance": module}),
            contextlib.redirect_stdout(output),
        ):
            try:
                flowctl.cmd_done(args)
            except SystemExit as exc:
                return int(exc.code), output.getvalue()
        return 0, output.getvalue()

    def done_in_process(self, evidence: dict, module: types.ModuleType) -> str:
        code, output = self.done_in_process_result(evidence, module)
        self.assertEqual(code, 0, output)
        return output

    def status(self) -> str:
        return json.loads(self.run_ok("show", TASK_ID, "--json").stdout)["status"]


class NativeProvenanceGateTest(_Repo):
    def test_off_mode_keeps_existing_done_behavior_and_recognizes_the_key(self) -> None:
        self.set_raw_config(
            lambda config: config.update(
                implementation={"provenance": "off", "roles": {}}
            )
        )
        marker = {
            "caller_note": "opaque while disabled",
            "receipt": {"receipt_sha256": "f" * 64},
        }
        result = self.done_cli(self.evidence(marker))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("unknown evidence key", result.stderr)
        self.assertEqual(self.status(), "done")
        self.assertNotIn("stage: native-provenance", (self.root / ".flow/tasks" / f"{TASK_ID}.md").read_text(encoding="utf-8"))
        runtime = json.loads(
            (self.state / "tasks" / f"{TASK_ID}.state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(runtime["evidence"]["native_provenance"], marker)

    def test_absent_implementation_policy_preserves_done_compatibility(self) -> None:
        self.set_raw_config(lambda config: config.pop("implementation", None))
        result = self.done_cli(self.evidence())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.status(), "done")

    def test_malformed_config_fails_closed_before_transition(self) -> None:
        self.set_raw_config_text("{\n")
        result = self.done_cli(self.evidence())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot read implementation provenance policy", result.stdout)
        self.assertEqual(self.status(), "in_progress")

    def test_unreadable_config_fails_closed_before_transition(self) -> None:
        config_path = self.root / ".flow" / "config.json"
        config_path.unlink()
        config_path.mkdir()
        result = self.done_cli(self.evidence())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot read implementation provenance policy", result.stdout)
        self.assertEqual(self.status(), "in_progress")

    def test_unknown_implementation_policy_fails_closed_before_transition(self) -> None:
        self.set_raw_config(
            lambda config: config["implementation"].update(unknown_policy=True)
        )
        result = self.done_cli(self.evidence())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown implementation setting(s): unknown_policy", result.stdout)
        self.assertEqual(self.status(), "in_progress")

    def test_missing_request_and_force_leave_task_in_progress(self) -> None:
        self.enable_native()
        for force in (False, True):
            with self.subTest(force=force):
                result = self.done_cli(self.evidence(), force=force)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("native_provenance request", result.stdout)
                self.assertEqual(self.status(), "in_progress")

    def test_invalid_hand_edited_policy_fails_closed(self) -> None:
        self.set_raw_config(
            lambda config: config["implementation"].update(provenance="codex-native")
        )
        result = self.done_cli(self.evidence(self.request()))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("implementation.roles is empty", result.stdout)
        self.assertEqual(self.status(), "in_progress")

    def test_invalid_mode_and_invalid_role_fail_before_transition(self) -> None:
        invalid_modes = ("codex", None)
        for invalid_mode in invalid_modes:
            with self.subTest(mode=invalid_mode):
                self.set_raw_config(
                    lambda config, mode=invalid_mode: config["implementation"].update(
                        provenance=mode
                    )
                )
                result = self.done_cli(self.evidence())
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid implementation.provenance", result.stdout)
                self.assertEqual(self.status(), "in_progress")
        self.set_raw_config(
            lambda config: config["implementation"].update(
                provenance="codex-native",
                roles={"coding": {"model": "example-model"}},
            )
        )
        result = self.done_cli(self.evidence(self.request()))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must contain model and effort", result.stdout)
        self.assertEqual(self.status(), "in_progress")
        self.set_raw_config(
            lambda config: config["implementation"].update(
                provenance="codex-native",
                roles={
                    "coding": {
                        "model": "example-model",
                        "effort": "medium",
                        "require_reason": "true",
                    }
                },
            )
        )
        result = self.done_cli(self.evidence(self.request()))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("require_reason must be a boolean", result.stdout)
        self.assertEqual(self.status(), "in_progress")

    def test_standalone_check_uses_explicit_repo_root_and_writes_no_state(self) -> None:
        outside_flow = self.root / "outside-flow"
        outside_flow.mkdir()
        subprocess.run(["git", "init", "-q", str(outside_flow)], check=True)
        subprocess.run(
            ["git", "-C", str(outside_flow), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(outside_flow), "config", "user.name", "Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(outside_flow), "config", "gc.auto", "0"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(outside_flow), "config", "maintenance.auto", "false"],
            check=True,
        )
        (outside_flow / "tracked.txt").write_text("fixture\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(outside_flow), "add", "tracked.txt"], check=True
        )
        subprocess.run(
            ["git", "-C", str(outside_flow), "commit", "-q", "-m", "fixture"],
            check=True,
        )
        request_path = self.root / "invalid-request.json"
        request_path.write_text("{}\n", encoding="utf-8")
        policy_path = self.root / "roles.json"
        policy_path.write_text(
            '{"coding":{"model":"example-model","effort":"medium"}}\n',
            encoding="utf-8",
        )
        before = sorted(path.relative_to(outside_flow) for path in outside_flow.rglob("*"))

        result = self.run_cli(
            "provenance", "check", "--request", str(request_path),
            "--repo-root", str(outside_flow), "--policy", str(policy_path), "--json",
        )

        self.assertNotEqual(result.returncode, 0)
        expected_refusal = (
            "request must contain parent_thread"
            if os.name == "posix"
            else "POSIX platforms only"
        )
        self.assertIn(expected_refusal, result.stdout)
        self.assertFalse((outside_flow / ".flow").exists())
        self.assertEqual(
            before,
            sorted(path.relative_to(outside_flow) for path in outside_flow.rglob("*")),
        )

    def test_task_mismatch_refuses_before_calling_verifier(self) -> None:
        self.enable_native()
        verifier = mock.Mock()
        module = self._verifier_module(verifier)
        code, output = self.done_in_process_result(
            self.evidence(self.request(task="fn-2-other.1")), module
        )
        self.assertNotEqual(code, 0)
        self.assertIn("must exactly match", output)
        self.assertEqual(self.status(), "in_progress")
        verifier.assert_not_called()

    def test_top_level_reason_is_rejected_before_calling_verifier(self) -> None:
        self.enable_native()
        verifier = mock.Mock()
        module = self._verifier_module(verifier)
        code, output = self.done_in_process_result(
            self.evidence(self.request(reason="reason belongs to a child")), module
        )
        self.assertNotEqual(code, 0)
        self.assertIn("Invalid native_provenance request field(s): reason", output)
        self.assertEqual(self.status(), "in_progress")
        verifier.assert_not_called()

    def test_parent_and_base_failures_are_left_to_native_verifier(self) -> None:
        self.enable_native()

        def verifier_for(field: str, wrong: str) -> types.ModuleType:
            module = self._verifier_module(None)

            def reject(_root, passed_request, _policy):
                if passed_request[field] != wrong:
                    self.fail(f"{field} was not passed to the verifier")
                raise module.VerificationError(f"{field} mismatch")

            module.verify_native = reject
            return module

        for field, wrong in (
            ("parent_thread", "wrong-parent"),
            ("base_commit", "0" * 40),
        ):
            with self.subTest(field=field):
                request = self.request(**{field: wrong})
                module = verifier_for(field, wrong)
                code, output = self.done_in_process_result(
                    self.evidence(request), module
                )
                self.assertNotEqual(code, 0)
                self.assertIn(f"{field} mismatch", output)
                self.assertEqual(self.status(), "in_progress")

    def test_stale_receipt_is_discarded_and_live_verifier_result_is_saved(self) -> None:
        self.enable_native()
        self.run_ok(
            "config", "set", "implementation.roles",
            '{"coding":{"model":"example-model","effort":"medium","require_reason":true}}',
        )
        request = self.request(
            receipt={"receipt_sha256": "f" * 64},
            children=[
                {
                    "thread_id": "native-child-thread",
                    "expected_files": ["src/example.py"],
                    "reason": "task needs a native-only implementation pass",
                }
            ],
        )
        calls = []
        receipt = {"receipt_sha256": RECEIPT_SHA256, "verified": True}

        def verify_native(repo_root, passed_request, policy):
            calls.append((repo_root, passed_request, policy))
            return receipt

        module = self._verifier_module(verify_native)
        output = self.done_in_process(self.evidence(request), module)
        self.assertTrue(json.loads(output)["success"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], self.root)
        self.assertNotIn("receipt", calls[0][1])
        self.assertEqual(calls[0][1]["task"], TASK_ID)
        self.assertNotIn("reason", calls[0][1])
        self.assertEqual(
            calls[0][1]["children"][0]["reason"],
            "task needs a native-only implementation pass",
        )
        self.assertEqual(
            calls[0][2],
            {
                "coding": {
                    "model": "example-model",
                    "effort": "medium",
                    "require_reason": True,
                }
            },
        )
        task_summary = (self.root / ".flow" / "tasks" / f"{TASK_ID}.md").read_text(encoding="utf-8")
        self.assertIn(f"receipt_sha256={RECEIPT_SHA256}", task_summary)
        runtime = json.loads((self.state / "tasks" / f"{TASK_ID}.state.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime["evidence"]["native_provenance"]["receipt"], receipt)

    def test_optional_reason_schema_is_a_boolean(self) -> None:
        schema_path = SCRIPTS.parent / "schema" / "flow-config.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        reason = schema["properties"]["implementation"]["properties"]["roles"][
            "additionalProperties"
        ]["properties"]["require_reason"]
        self.assertEqual(reason, {"type": "boolean", "default": False})


if __name__ == "__main__":
    unittest.main()
