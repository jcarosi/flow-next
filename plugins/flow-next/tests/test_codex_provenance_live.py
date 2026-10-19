"""Opt-in end-to-end checks against existing Codex native thread history.

The default suite skips these tests. An external JSON config supplies disposable
Flow and standalone Git fixtures, their native requests, and the installed
candidate CLIs. No native history is fabricated and no model is invoked.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Iterator


LIVE_CONFIG_ENV = "FLOW_NEXT_CODEX_PROVENANCE_LIVE_CONFIG"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _required_file(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AssertionError(f"live config {label} must be a file path")
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file():
        raise AssertionError(f"live config {label} is not a file: {path}")
    return path


def _required_repo(value: object, label: str, fixture_root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise AssertionError(f"live config {label} must be a repository path")
    supplied = Path(value).expanduser()
    if supplied.is_symlink():
        raise AssertionError(f"live config {label} cannot be a symlink")
    path = supplied.resolve(strict=True)
    if not path.is_dir() or not _inside(path, fixture_root):
        raise AssertionError(
            f"live config {label} must be a directory below fixture_root: {path}"
        )
    if _inside(path, REPOSITORY_ROOT):
        raise AssertionError(f"live config {label} points inside this repository")
    if not (path / ".git").exists():
        raise AssertionError(f"live config {label} is not a disposable Git fixture")
    return path


def _snapshot(path: Path) -> tuple[str, bytes | str | None, int | None]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing", None, None
    if stat.S_ISLNK(info.st_mode):
        return "symlink", os.readlink(path), stat.S_IMODE(info.st_mode)
    if not stat.S_ISREG(info.st_mode):
        raise AssertionError(f"test fixture path is not a regular file: {path}")
    return "file", path.read_bytes(), stat.S_IMODE(info.st_mode)


def _restore(path: Path, snapshot: tuple[str, bytes | str | None, int | None]) -> None:
    kind, content, mode = snapshot
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    if kind == "file":
        path.parent.mkdir(parents=True, exist_ok=True)
        assert isinstance(content, bytes) and mode is not None
        path.write_bytes(content)
        path.chmod(mode)
    elif kind == "symlink":
        assert isinstance(content, str)
        path.symlink_to(content)


@contextlib.contextmanager
def _preserve_fixture_paths(
    root: Path, relative_paths: list[str]
) -> Iterator[None]:
    paths = [root / Path(value) for value in relative_paths]
    for path in paths:
        if not _inside(path.resolve(strict=False), root):
            raise AssertionError(f"fixture mutation escaped its repository: {path}")
    snapshots = {path: _snapshot(path) for path in paths}
    absent_directories: set[Path] = set()
    for path in paths:
        parent = path.parent
        while parent != root and _inside(parent, root):
            if not parent.exists():
                absent_directories.add(parent)
            parent = parent.parent
    try:
        yield
    finally:
        for path, snapshot in reversed(list(snapshots.items())):
            _restore(path, snapshot)
        for directory in sorted(
            absent_directories, key=lambda item: len(item.parts), reverse=True
        ):
            if directory.exists():
                shutil.rmtree(directory)


@unittest.skipUnless(
    os.environ.get(LIVE_CONFIG_ENV),
    f"live Codex provenance checks skipped; set {LIVE_CONFIG_ENV} to an external fixture config",
)
class CodexProvenanceLiveTests(unittest.TestCase):
    def setUp(self) -> None:
        config_path = _required_file(os.environ.get(LIVE_CONFIG_ENV), "config")
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.fail(f"cannot read live config {config_path}: {exc}")
        self.assertIsInstance(config, dict, "live config must be a JSON object")

        fixture_value = config.get("fixture_root")
        self.assertIsInstance(fixture_value, str, "live config needs fixture_root")
        fixture_root = Path(fixture_value).expanduser().resolve(strict=True)
        self.assertTrue(fixture_root.is_dir(), "fixture_root must be a directory")
        self.assertFalse(
            _inside(fixture_root, REPOSITORY_ROOT),
            "live fixtures must be outside the Flow-Next source repository",
        )
        codex_home = (Path.home() / ".codex").resolve(strict=False)
        self.assertFalse(
            _inside(fixture_root, codex_home),
            "live fixtures must be outside the active Codex home",
        )

        self.fixture_root = fixture_root
        self.flowctl = _required_file(config.get("flowctl"), "flowctl")
        self.flow = config.get("flow")
        self.standalone = config.get("standalone")
        self.worktree = config.get("worktree")
        self.assertIsInstance(self.flow, dict, "live config needs a flow object")
        self.assertIsInstance(
            self.standalone, dict, "live config needs a standalone object"
        )
        self.flow_repo = _required_repo(
            self.flow.get("repo_root"), "flow.repo_root", fixture_root
        )
        self.flow_request_path = _required_file(
            self.flow.get("request"), "flow.request"
        )
        self.created_spec_paths = self.flow.get("created_spec_paths")
        self.assertIsInstance(
            self.created_spec_paths,
            list,
            "flow.created_spec_paths must name the existing spec produced by flowctl",
        )
        self.assertTrue(self.created_spec_paths)

        self.standalone_repo = _required_repo(
            self.standalone.get("repo_root"), "standalone.repo_root", fixture_root
        )
        self.standalone_request_path = _required_file(
            self.standalone.get("request"), "standalone.request"
        )
        self.standalone_policy = _required_file(
            self.standalone.get("policy"), "standalone.policy"
        )
        self.standalone_launcher = _required_file(
            self.standalone.get("launcher"), "standalone.launcher"
        )

        self._temporary = tempfile.TemporaryDirectory(
            prefix="flow-codex-provenance-live-"
        )
        self.addCleanup(self._temporary.cleanup)
        self.temp_root = Path(self._temporary.name)
        self.flow_state_dir = self.temp_root / "flow-state"

    @staticmethod
    def _read_request(path: Path) -> dict:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise AssertionError(f"native request must be a JSON object: {path}")
        return value

    def _write_request(self, request: dict, label: str) -> Path:
        path = self.temp_root / f"{label}.json"
        path.write_text(
            json.dumps(request, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def _run_flowctl(
        self,
        args: list[str],
        repo: Path,
        *,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["FLOW_STATE_DIR"] = str(self.flow_state_dir)
        environment["PYTHON_BIN"] = sys.executable
        return subprocess.run(
            [str(self.flowctl), *args],
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )

    def _flow_check(
        self,
        repo: Path,
        request_path: Path,
        *,
        policy: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        args = [
            "provenance",
            "check",
            "--repo-root",
            str(repo),
            "--request",
            str(request_path),
            "--json",
        ]
        if policy is not None:
            args[6:6] = ["--policy", str(policy)]
        return self._run_flowctl(args, repo)

    def _standalone_check(
        self,
        repo: Path,
        request_path: Path,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.standalone_launcher),
                "--repo-root",
                str(repo),
                "--request",
                str(request_path),
                "--policy",
                str(self.standalone_policy),
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )

    def _assert_rejected(
        self,
        result: subprocess.CompletedProcess[str],
        expected_message: str | None = None,
    ) -> None:
        self.assertNotEqual(
            result.returncode,
            0,
            f"unexpected live verification success:\n{result.stdout}\n{result.stderr}",
        )
        output = result.stdout + result.stderr
        if expected_message is not None:
            self.assertIn(expected_message, output)

    def test_flow_check_and_done_accept_real_flowctl_spec_creation(self) -> None:
        request = self._read_request(self.flow_request_path)
        task_id = request.get("task")
        self.assertIsInstance(task_id, str)
        task_spec = self.flow_repo / ".flow" / "tasks" / f"{task_id}.md"
        with _preserve_fixture_paths(
            self.flow_repo, [task_spec.relative_to(self.flow_repo).as_posix()]
        ):
            check = self._flow_check(self.flow_repo, self.flow_request_path)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            payload = json.loads(check.stdout)
            self.assertTrue(payload.get("verified"), check.stdout)
            receipt = payload["receipt"]
            coordinator_paths = {
                row["path"] for row in receipt.get("coordinatorFiles", [])
            }
            for path in self.created_spec_paths:
                self.assertIsInstance(path, str)
                self.assertIn(path, coordinator_paths)

            start = self._run_flowctl(["start", task_id, "--json"], self.flow_repo)
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            evidence = {
                "commits": [],
                "tests": ["live Codex native provenance integration"],
                "prs": [],
                "native_provenance": request,
            }
            evidence_path = self.temp_root / "done-evidence.json"
            evidence_path.write_text(
                json.dumps(evidence, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            done = self._run_flowctl(
                ["done", task_id, "--evidence-json", str(evidence_path), "--json"],
                self.flow_repo,
            )
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn(
                "stage: native-provenance - verified",
                task_spec.read_text(encoding="utf-8"),
            )

    def test_real_linked_worktree_history_maps_to_integrated_repository(self) -> None:
        if self.worktree is None:
            self.skipTest("live config has no optional worktree fixture")
        self.assertIsInstance(self.worktree, dict, "worktree must be an object")
        repo = _required_repo(
            self.worktree.get("repo_root"), "worktree.repo_root", self.fixture_root
        )
        request_path = _required_file(self.worktree.get("request"), "worktree.request")
        request = self._read_request(request_path)
        children = request.get("children")
        self.assertIsInstance(children, list)
        self.assertTrue(children)
        self.assertTrue(
            any(isinstance(child, dict) and child.get("workspace") for child in children),
            "worktree request must bind at least one native child workspace",
        )

        result = self._flow_check(repo, request_path)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("verified"), result.stdout)
        receipt_children = payload["receipt"]["children"]
        self.assertTrue(
            any(child.get("workspace") != str(repo) for child in receipt_children),
            "receipt must retain the linked workspace used for native path mapping",
        )

    def test_staged_launcher_and_flowctl_share_the_standalone_native_api(self) -> None:
        request = self.standalone_request_path
        flowctl_result = self._flow_check(
            self.standalone_repo, request, policy=self.standalone_policy
        )
        self.assertEqual(
            flowctl_result.returncode,
            0,
            flowctl_result.stdout + flowctl_result.stderr,
        )
        flowctl_receipt = json.loads(flowctl_result.stdout)["receipt"]

        launcher_result = self._standalone_check(self.standalone_repo, request)
        self.assertEqual(
            launcher_result.returncode,
            0,
            launcher_result.stdout + launcher_result.stderr,
        )
        launcher_receipt = json.loads(launcher_result.stdout)
        self.assertEqual(
            launcher_receipt["receipt_sha256"], flowctl_receipt["receipt_sha256"]
        )

    def test_live_candidate_rejects_changed_source_bytes_and_mode(self) -> None:
        delegated = self.standalone_repo / "delegated.txt"
        with _preserve_fixture_paths(
            self.standalone_repo, ["delegated.txt"]
        ):
            snapshot = _snapshot(delegated)
            self.assertEqual(snapshot[0], "file")
            original_bytes = snapshot[1]
            original_mode = snapshot[2]
            self.assertIsInstance(original_bytes, bytes)
            self.assertIsInstance(original_mode, int)
            delegated.write_bytes(original_bytes + b"tampered\n")
            changed = self._flow_check(
                self.standalone_repo,
                self.standalone_request_path,
                policy=self.standalone_policy,
            )
            self._assert_rejected(changed, "differs from replayed native changes")

            delegated.write_bytes(original_bytes)
            delegated.chmod(original_mode ^ stat.S_IXUSR)
            changed_mode = self._flow_check(
                self.standalone_repo,
                self.standalone_request_path,
                policy=self.standalone_policy,
            )
            self._assert_rejected(changed_mode)

    def test_indirect_extra_source_and_mixed_metadata_are_rejected(self) -> None:
        extra_source = self.standalone_repo / "unexpected-generated.py"
        config_path = self.standalone_repo / ".flow" / "config.json"
        with _preserve_fixture_paths(
            self.standalone_repo,
            ["unexpected-generated.py", ".flow/config.json"],
        ):
            script = (
                "from pathlib import Path; "
                f"Path({str(extra_source)!r}).write_text('generated\\n', encoding='utf-8')"
            )
            indirect = subprocess.run(
                [sys.executable, "-c", script],
                cwd=self.standalone_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(indirect.returncode, 0, indirect.stdout + indirect.stderr)
            result = self._flow_check(
                self.standalone_repo,
                self.standalone_request_path,
                policy=self.standalone_policy,
            )
            self._assert_rejected(result, "unexplained tracked or untracked paths")
            extra_source.unlink()

            script = (
                "from pathlib import Path; "
                f"source = Path({str(extra_source)!r}); "
                "source.write_text('generated\\n', encoding='utf-8'); "
                f"metadata = Path({str(config_path)!r}); "
                "metadata.parent.mkdir(parents=True, exist_ok=True); "
                "metadata.write_text('{\\\"version\\\": 1}\\n', encoding='utf-8')"
            )
            mixed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=self.standalone_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(mixed.returncode, 0, mixed.stdout + mixed.stderr)
            result = self._standalone_check(
                self.standalone_repo, self.standalone_request_path
            )
            self._assert_rejected(result, "unexplained tracked or untracked paths")
            self.assertIn(extra_source.name, result.stdout + result.stderr)
            self.assertIn(".flow/config.json", result.stdout + result.stderr)

    def test_wrong_parent_child_and_task_ids_are_rejected(self) -> None:
        original = self._read_request(self.standalone_request_path)
        variants: list[tuple[str, dict]] = []

        wrong_parent = json.loads(json.dumps(original))
        wrong_parent["parent_thread"] += "-mismatch"
        variants.append(("wrong-parent", wrong_parent))

        wrong_child = json.loads(json.dumps(original))
        wrong_child["children"][0]["thread_id"] += "-mismatch"
        variants.append(("wrong-child", wrong_child))

        wrong_task = json.loads(json.dumps(original))
        wrong_task["task"] += "-mismatch"
        variants.append(("wrong-task", wrong_task))

        for label, request in variants:
            with self.subTest(identity=label):
                request_path = self._write_request(request, label)
                result = self._flow_check(
                    self.standalone_repo,
                    request_path,
                    policy=self.standalone_policy,
                )
                self._assert_rejected(result)

    def test_traversal_absolute_and_symlink_expected_paths_are_rejected(self) -> None:
        original = self._read_request(self.standalone_request_path)
        linked = self.standalone_repo / "linked.txt"
        with _preserve_fixture_paths(self.standalone_repo, ["linked.txt"]):
            linked.symlink_to(self.standalone_repo / "delegated.txt")
            for label, path in (
                ("traversal", "../outside.txt"),
                ("absolute", str(self.standalone_repo / "delegated.txt")),
                ("symlink", "linked.txt"),
            ):
                with self.subTest(path_kind=label):
                    request = json.loads(json.dumps(original))
                    request["children"][0]["expected_files"] = [path]
                    request_path = self._write_request(request, f"expected-{label}")
                    result = self._flow_check(
                        self.standalone_repo,
                        request_path,
                        policy=self.standalone_policy,
                    )
                    self._assert_rejected(result)


if __name__ == "__main__":
    unittest.main()
