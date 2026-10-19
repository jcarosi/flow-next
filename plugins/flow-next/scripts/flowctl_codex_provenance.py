"""Read-only Codex native-history and candidate-integrity verification.

The caller supplies all role/model/effort policy. Native history is detective
evidence, not an operating-system write boundary. Candidate checks use the
supplied worktree with Git environment overrides removed, reject index entries
that can hide edits, and ignore replacement objects and legacy grafts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from xml.etree import ElementTree

MAX_LINE_BYTES = 64 * 1024 * 1024
PAGE_SIZE = 100
MAX_PAGES = 10000
RPC_METHODS = frozenset({"thread/read", "thread/turns/list", "thread/items/list"})
ITEM_TYPES = frozenset(
    {
        "agentMessage", "collabAgentToolCall", "commandExecution", "contextCompaction",
        "dynamicToolCall", "enteredReviewMode", "exitedReviewMode", "fileChange",
        "functionCallOutput", "hookPrompt", "imageGeneration", "imageView", "mcpToolCall",
        "plan", "reasoning", "sleep", "subAgentActivity", "userMessage", "webSearch",
    }
)
TURN_STATUSES = frozenset({"completed", "interrupted", "failed", "inProgress"})
COLLAB_TOOLS = frozenset(
    {
        "spawnAgent", "sendInput", "resumeAgent", "wait", "closeAgent", "sendMessage",
        "followupTask", "interruptAgent", "listAgents",
    }
)
COLLAB_STATUSES = frozenset({"inProgress", "completed", "failed", "interrupted"})
ACTIVITY_KINDS = frozenset({"started", "interacted", "interrupted", "completed"})
FLOW_NATIVE_ID = re.compile(
    r"^fn-(\d+)(?:-[a-z0-9][a-z0-9-]*[a-z0-9]|-[a-z0-9]{1,3})?(?:\.(\d+))?$"
)
FLOW_TRACKER_ALIAS_ID = re.compile(r"^([a-z][a-z0-9]{0,9})-(\d+)(?:\.(\d+))?$")
FLOW_TRACKER_CANONICAL_ID = re.compile(
    r"^([a-z][a-z0-9]{0,9})-(\d+)-[a-z0-9][a-z0-9-]*[a-z0-9]?(?:\.(\d+))?$"
)
FLOW_MEMORY_CATEGORIES = {
    "bug": frozenset({
        "build-errors", "test-failures", "runtime-errors", "performance",
        "security", "integration", "data", "ui",
    }),
    "knowledge": frozenset({
        "architecture-patterns", "conventions", "tooling-decisions", "workflow",
        "best-practices", "decisions",
    }),
}
FLOW_EVIDENCE_RECEIPT_TYPES = frozenset(
    {"plan_review", "impl_review", "completion_review", "qa_verdict"}
)
MAX_INERT_FLOW_BYTES = 4 * 1024 * 1024
MAX_COGNITIVE_AID_BYTES = 512 * 1024
UNIFIED_HUNK = re.compile(
    rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:[^\r\n]*)?(?:\r?\n)?$"
)


class VerificationError(ValueError):
    """Native evidence or the observed candidate is incomplete or inconsistent."""


ProvenanceError = VerificationError


def _obj(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProvenanceError(f"{label} must be an object")
    return value


def _string(value: object, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        raise ProvenanceError(f"{label} must be a non-empty string")
    return value


def _digest_json(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RpcClient:
    """Bounded app-server client restricted to initialization and read RPCs."""

    def __init__(self, executable: str, timeout: float, cwd: Path) -> None:
        try:
            self.process = subprocess.Popen(
                [executable, "app-server", "--listen", "stdio://"],
                cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
            )
        except OSError as exc:
            raise ProvenanceError(f"could not start Codex app-server: {exc}") from exc
        if self.process.stdin is None or self.process.stdout is None:
            self.process.terminate()
            raise ProvenanceError("Codex app-server did not provide stdio pipes")
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.stdout_fd = self.stdout.fileno()
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.stdout_fd, selectors.EVENT_READ)
        self.timeout = timeout
        self.total_deadline = time.monotonic() + 300
        self.next_id = 1
        self.buffer = bytearray()

    def _write(self, message: dict[str, object]) -> None:
        try:
            self.stdin.write(
                json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
            )
            self.stdin.flush()
        except OSError as exc:
            raise ProvenanceError("Codex app-server closed its request pipe") from exc

    def _line(self, deadline: float) -> dict[str, Any]:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                try:
                    value = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProvenanceError("app-server emitted invalid JSON-RPC data") from exc
                if not isinstance(value, dict):
                    raise ProvenanceError("app-server JSON-RPC message was not an object")
                return value
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise ProvenanceError("Codex app-server request timed out")
            chunk = os.read(self.stdout_fd, 65536)
            if not chunk:
                raise ProvenanceError("Codex app-server closed stdout before responding")
            self.buffer.extend(chunk)
            if len(self.buffer) > MAX_LINE_BYTES:
                raise ProvenanceError("app-server response exceeded the 64 MiB line limit")

    def request(self, method: str, params: dict[str, object]) -> dict[str, Any]:
        if method != "initialize" and method not in RPC_METHODS:
            raise ProvenanceError(f"unsupported app-server method: {method}")
        request_id = self.next_id
        self.next_id += 1
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        deadline = min(time.monotonic() + self.timeout, self.total_deadline)
        while True:
            message = self._line(deadline)
            if "method" in message:
                if "id" in message:
                    raise ProvenanceError("unexpected server request during read-only verification")
                continue
            if message.get("id") != request_id:
                raise ProvenanceError("app-server returned an unexpected JSON-RPC response ID")
            if message.get("error") is not None:
                error = message["error"]
                code = error.get("code") if isinstance(error, dict) else None
                raise ProvenanceError(f"app-server {method} failed (JSON-RPC code {code})")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ProvenanceError(f"app-server {method} returned no object result")
            return result

    def initialize(self) -> None:
        result = self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "flow-next-native-provenance",
                    "title": "Flow-Next native implementation provenance",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        required = ("userAgent", "codexHome", "platformFamily", "platformOs")
        if any(not isinstance(result.get(key), str) or not result[key] for key in required):
            raise ProvenanceError(
                "unsupported initialize response; required app-server metadata is missing"
            )
        self._write({"method": "initialized"})

    def call(self, method: str, params: dict[str, object]) -> dict[str, Any]:
        if method not in RPC_METHODS:
            raise ProvenanceError(f"unsupported app-server method: {method}")
        return self.request(method, params)

    def close(self) -> None:
        self.selector.close()
        try:
            self.stdin.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        try:
            self.stdout.close()
        except OSError:
            pass


def _page_data(client: Any, method: str, params: dict[str, object]) -> list[object]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    values_all: list[object] = []
    for _ in range(MAX_PAGES):
        page_params = {
            **params, "cursor": cursor, "limit": PAGE_SIZE, "sortDirection": "asc"
        }
        result = _obj(client.call(method, page_params), f"{method} result")
        values = result.get("data")
        if not isinstance(values, list):
            raise ProvenanceError(f"{method} response schema/pagination is unsupported")
        values_all.extend(values)
        if "nextCursor" not in result or result["nextCursor"] is None:
            return values_all
        next_cursor = result["nextCursor"]
        if (
            not isinstance(next_cursor, str)
            or not next_cursor
            or next_cursor in seen_cursors
        ):
            raise ProvenanceError(f"{method} returned an invalid or repeated pagination cursor")
        if not values:
            raise ProvenanceError(f"{method} returned an empty page with a continuation cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise ProvenanceError(f"{method} exceeded the {MAX_PAGES}-page safety limit")


def _metadata(client: Any, thread_id: str) -> dict[str, Any]:
    result = _obj(
        client.call("thread/read", {"threadId": thread_id, "includeTurns": False}),
        "thread/read result",
    )
    thread = _obj(result.get("thread"), "thread/read thread")
    if thread.get("id") != thread_id:
        raise ProvenanceError("thread/read returned a different native thread ID")
    if thread.get("historyMode") not in {"legacy", "paginated"}:
        raise ProvenanceError("thread/read historyMode is missing or unsupported")
    cwd = _string(thread.get("cwd"), "thread cwd")
    if not Path(cwd).is_absolute():
        raise ProvenanceError("thread cwd is not absolute")
    status = _obj(thread.get("status"), "thread status").get("type")
    if status not in {"notLoaded", "idle", "systemError", "active"}:
        raise ProvenanceError("thread status is unknown to this verifier")
    return thread


def _turns(client: Any, thread: Mapping[str, Any]) -> list[object]:
    thread_id = _string(thread.get("id"), "thread ID")
    mode = thread.get("historyMode")
    if mode == "legacy":
        response = _obj(
            client.call("thread/read", {"threadId": thread_id, "includeTurns": True}),
            "thread/read includeTurns result",
        )
        hydrated = _obj(response.get("thread"), "thread/read includeTurns thread")
        if hydrated.get("id") != thread_id or hydrated.get("historyMode") != "legacy":
            raise ProvenanceError(
                "thread/read includeTurns changed thread identity or history mode"
            )
        turns = hydrated.get("turns")
        if not isinstance(turns, list):
            raise ProvenanceError("legacy thread/read includeTurns omitted turns")
        return turns
    if mode == "paginated":
        return _page_data(
            client, "thread/turns/list",
            {"threadId": thread_id, "itemsView": "full"},
        )
    raise ProvenanceError("thread historyMode is unsupported")


def _items(client: Any, thread_id: str, turn: Mapping[str, Any]) -> list[object]:
    view = turn.get("itemsView", "full")
    if view == "full":
        items = turn.get("items")
        if not isinstance(items, list):
            raise ProvenanceError("full turn omitted its items array")
        return items
    if view not in {"summary", "notLoaded"}:
        raise ProvenanceError("turn itemsView is unknown to this verifier")
    turn_id = _string(turn.get("id"), "turn ID")
    result: list[object] = []
    for entry_value in _page_data(
        client, "thread/items/list", {"threadId": thread_id, "turnId": turn_id}
    ):
        entry = _obj(entry_value, "thread/items/list entry")
        if entry.get("turnId") != turn_id:
            raise ProvenanceError("thread/items/list returned an item for a different turn")
        result.append(entry.get("item"))
    return result


@dataclass(frozen=True)
class FileOp:
    path: str
    kind: str
    diff: str
    move_path: str | None = None

    @property
    def touched_paths(self) -> tuple[str, ...]:
        return (self.path,) if self.move_path is None else (self.path, self.move_path)


@dataclass(frozen=True)
class FileChange:
    thread_id: str
    turn_id: str
    item_id: str
    order: int
    sha256: str
    operations: tuple[FileOp, ...]

    @property
    def touched_paths(self) -> frozenset[str]:
        return frozenset(path for op in self.operations for path in op.touched_paths)


def _raw_components(raw: str, label: str) -> None:
    if any(character in raw for character in "\x00\n\r\\:"):
        raise ProvenanceError(f"{label} has invalid or platform-ambiguous characters")
    if not raw or raw.startswith("//") or "//" in raw:
        raise ProvenanceError(f"{label} is ambiguous")
    parts = (raw[1:] if raw.startswith("/") else raw).split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ProvenanceError(f"{label} contains traversal or an ambiguous component")
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{n}" for n in range(1, 10)),
        *(f"LPT{n}" for n in range(1, 10)),
    }
    for part in parts:
        if part.endswith((".", " ")) or part.upper() in reserved:
            raise ProvenanceError(f"{label} has a platform-ambiguous component")


def _path_alias(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _canonical_directory(value: object, label: str) -> Path:
    raw = _string(value, label)
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        raise ProvenanceError(f"{label} must be an absolute canonical path")
    _raw_components(str(candidate), label)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ProvenanceError(f"{label} is unavailable: {exc}") from exc
    if str(candidate) != str(resolved):
        raise ProvenanceError(f"{label} must use its canonical path without aliases")
    if not resolved.is_dir():
        raise ProvenanceError(f"{label} must be a directory")
    cursor = Path(resolved.anchor)
    for component in resolved.parts[1:]:
        cursor = cursor / component
        try:
            info = cursor.lstat()
        except OSError as exc:
            raise ProvenanceError(f"cannot inspect {label} component {cursor}: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ProvenanceError(f"{label} cannot traverse a symlink: {cursor}")
        if not stat.S_ISDIR(info.st_mode):
            raise ProvenanceError(f"{label} contains a non-directory component: {cursor}")
    return resolved


def _assert_safe_path(root: Path, relative: PurePosixPath) -> Path:
    cursor = root
    for index, component in enumerate(relative.parts):
        if cursor.exists() and cursor.is_dir():
            try:
                names = [entry.name for entry in os.scandir(cursor)]
            except OSError as exc:
                raise ProvenanceError(f"cannot inspect path parent {cursor}: {exc}") from exc
            alias = _path_alias(component)
            if any(name != component and _path_alias(name) == alias for name in names):
                raise ProvenanceError(
                    f"case or Unicode path alias is ambiguous at {relative.as_posix()}"
                )
        cursor = cursor / component
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode):
            raise ProvenanceError(f"symlink path is unsupported: {relative.as_posix()}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ProvenanceError(f"non-directory path component: {relative.as_posix()}")
        if index == len(relative.parts) - 1:
            if not stat.S_ISREG(info.st_mode):
                raise ProvenanceError(f"non-regular candidate file: {relative.as_posix()}")
            if info.st_nlink != 1:
                raise ProvenanceError(f"hard-linked candidate file: {relative.as_posix()}")
    return root.joinpath(*relative.parts)


def _resolve_path(
    raw_value: object,
    root: Path,
    cwd: str,
    label: str,
    *,
    relative_to_root: bool = False,
) -> str:
    raw = _string(raw_value, label)
    _raw_components(raw, label)
    candidate = Path(raw)
    if candidate.is_absolute():
        relative: Path | None = None
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            # macOS reports native paths with either spelling of /tmp. Accept
            # that single filesystem alias at the repository root, then inspect
            # every component below the canonical root without resolving it.
            if root.parts[:3] == ("/", "private", "tmp"):
                alias_root = Path("/", "tmp", *root.parts[3:])
                try:
                    alias_matches = alias_root.resolve(strict=True) == root
                except OSError:
                    alias_matches = False
                if alias_matches:
                    try:
                        relative = candidate.relative_to(alias_root)
                    except ValueError:
                        pass
        if relative is None:
            raise ProvenanceError(
                f"{label} resolves outside the explicit repository root: {raw}"
            )
    else:
        base = root if relative_to_root else Path(cwd).resolve(strict=True)
        absolute = Path(os.path.abspath(base / candidate))
        try:
            relative = absolute.relative_to(root)
        except ValueError as exc:
            raise ProvenanceError(
                f"{label} resolves outside the explicit repository root: {raw}"
            ) from exc
    if not relative.parts:
        raise ProvenanceError(f"{label} resolves to the repository root")
    path = PurePosixPath(*relative.parts)
    _assert_safe_path(root, path)
    return path.as_posix()


def _flow_id_is_task(identifier: str) -> bool | None:
    native = FLOW_NATIVE_ID.fullmatch(identifier)
    if native:
        return native.group(2) is not None
    canonical = FLOW_TRACKER_CANONICAL_ID.fullmatch(identifier)
    if canonical and canonical.group(1) != "fn":
        return canonical.group(3) is not None
    alias = FLOW_TRACKER_ALIAS_ID.fullmatch(identifier)
    if alias and alias.group(1) != "fn":
        return alias.group(3) is not None
    return None


def _coordination_kind(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if len(parts) == 3 and parts[:2] == (".flow", "specs"):
        filename = parts[2]
        if filename.endswith((".md", ".json")):
            if _flow_id_is_task(filename.rsplit(".", 1)[0]) is False:
                return "spec"
        return None
    if len(parts) == 3 and parts[:2] == (".flow", "tasks"):
        filename = parts[2]
        if filename.endswith((".md", ".json")):
            if _flow_id_is_task(filename.rsplit(".", 1)[0]) is True:
                return "task"
        return None
    if len(parts) == 3 and parts[:2] == (".flow", "memory"):
        if parts[2] == "README.md" or parts[2] in {
            "pitfalls.md", "conventions.md", "decisions.md",
        }:
            return "memory_readme"
        return None
    if len(parts) == 5 and parts[:2] == (".flow", "memory"):
        track, category, filename = parts[2:]
        if track in FLOW_MEMORY_CATEGORIES and category in FLOW_MEMORY_CATEGORIES[track]:
            match = re.fullmatch(r"([a-z0-9]+(?:-[a-z0-9]+)*)-(\d{4}-\d{2}-\d{2})\.md", filename)
            if match:
                try:
                    date.fromisoformat(match.group(2))
                except ValueError:
                    return None
                return "memory_entry"
        if track in FLOW_MEMORY_CATEGORIES and filename == ".gitkeep":
            return "memory_gitkeep"
        return None
    if len(parts) >= 4 and parts[:2] == (".flow", "evidence"):
        spec_id = parts[2]
        if _flow_id_is_task(spec_id) is not False:
            return None
        tail = parts[3:]
        if tail == ("run.json",):
            return "evidence_run"
        if (
            len(tail) == 2
            and tail[0] == "tasks"
            and tail[1].endswith(".json")
            and _flow_id_is_task(tail[1][:-5]) is True
            and tail[1][:-5].rsplit(".", 1)[0] == spec_id
        ):
            return "evidence_task"
        if (
            len(tail) == 2
            and tail[0] == "reviews"
            and tail[1].endswith(".json")
        ):
            return "evidence_review"
        if (
            len(tail) == 3
            and tail[0] == "qa"
            and tail[2] == "receipt.json"
        ):
            return "evidence_qa"
        if (
            len(tail) == 3
            and tail[0] == "tests"
            and _flow_id_is_task(tail[1]) is True
            and tail[1].rsplit(".", 1)[0] == spec_id
            and tail[2].endswith(".xml")
            and len(tail[2]) > 4
        ):
            return "evidence_test"
        return None
    if (
        len(parts) == 5
        and parts[:2] == (".flow", "artifacts")
        and _flow_id_is_task(parts[2]) is False
        and parts[3] == "pr-cognitive-aid"
        and parts[4].endswith(".json")
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", parts[4][:-5])
    ):
        return "artifact"
    return {
        ".flow/tmp/base_commit": "base_commit",
        ".flow/tmp/spec_base": "spec_base",
    }.get(path)


def _flow_json(path: str, content: bytes, label: str) -> dict[str, Any]:
    if len(content) > MAX_INERT_FLOW_BYTES:
        raise ProvenanceError(f"{label} exceeds the inert Flow content limit: {path}")
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(document, dict):
        raise ProvenanceError(f"{label} must be a JSON object: {path}")
    return document


def _memory_frontmatter(path: str, content: bytes) -> tuple[str, dict[str, str]]:
    if len(content) > MAX_INERT_FLOW_BYTES:
        raise ProvenanceError(f"Flow memory entry exceeds the content limit: {path}")
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ProvenanceError(f"Flow memory entry is not UTF-8: {path}") from exc
    if not lines or lines[0] != "---":
        raise ProvenanceError(f"Flow memory entry has no frontmatter: {path}")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise ProvenanceError(f"Flow memory entry has incomplete frontmatter: {path}") from exc
    fields: dict[str, str] = {}
    required_identity = {"title", "date", "track", "category"}
    for line in lines[1:closing]:
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"(title|date|track|category):[ \t]*(.*)", line)
        if match is None:
            continue
        key, value = match.groups()
        if key in fields:
            raise ProvenanceError(f"Flow memory entry repeats identity frontmatter: {path}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    if required_identity - set(fields):
        raise ProvenanceError(f"Flow memory entry is missing required identity: {path}")
    return lines[closing + 1] if closing + 1 < len(lines) else "", fields


def _validate_cognitive_aid(path: str, document: dict[str, Any]) -> None:
    """Use Flow's canonical cognitive-aid validator instead of duplicating its schema."""
    module = sys.modules.get("__main__")
    validator = getattr(module, "validate_pr_cognitive_aid", None)
    if not callable(validator):
        module = sys.modules.get("flowctl")
        validator = getattr(module, "validate_pr_cognitive_aid", None)
    if not callable(validator):
        try:
            import flowctl as module
        except ImportError as exc:
            raise ProvenanceError(
                "Flow cognitive-aid validator is unavailable for coordinator artifact"
            ) from exc
        validator = getattr(module, "validate_pr_cognitive_aid", None)
    if not callable(validator):
        raise ProvenanceError(
            "Flow cognitive-aid validator is unavailable for coordinator artifact"
        )
    spec_id = PurePosixPath(path).parts[2]
    try:
        validator(document, expected_spec_id=spec_id)
    except ValueError as exc:
        raise ProvenanceError(
            f"Flow artifact does not satisfy its content contract: {path}: {exc}"
        ) from exc


def _validate_inert_flow_content(
    kind: str, path: str, content: bytes, mode: int
) -> None:
    if mode & 0o111:
        raise ProvenanceError(f"coordinator file is executable: {path}")
    if len(content) > MAX_INERT_FLOW_BYTES and kind != "artifact":
        raise ProvenanceError(f"coordinator file exceeds the inert Flow content limit: {path}")
    if b"\x00" in content:
        raise ProvenanceError(f"coordinator Flow file is binary: {path}")
    if kind == "memory_gitkeep":
        if content:
            raise ProvenanceError(f"Flow memory .gitkeep must be empty: {path}")
        return
    if kind in {"memory_readme"}:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProvenanceError(f"Flow memory document is not UTF-8: {path}") from exc
        return
    if kind == "memory_entry":
        _, fields = _memory_frontmatter(path, content)
        parts = PurePosixPath(path).parts
        match = re.fullmatch(r".+-(\d{4}-\d{2}-\d{2})\.md", parts[4])
        required = {"title", "date", "track", "category"}
        if (
            match is None
            or required - set(fields)
            or not fields["title"]
            or fields["date"] != match.group(1)
            or fields["track"] != parts[2]
            or fields["category"] != parts[3]
        ):
            raise ProvenanceError(f"Flow memory entry does not match its path contract: {path}")
        try:
            date.fromisoformat(fields["date"])
        except ValueError as exc:
            raise ProvenanceError(f"Flow memory entry has an invalid date: {path}") from exc
        return
    if kind in {"evidence_test"}:
        if len(content) > MAX_INERT_FLOW_BYTES:
            raise ProvenanceError(f"Flow test report exceeds the content limit: {path}")
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise ProvenanceError(f"Flow test report is invalid XML: {path}") from exc
        if root.tag.rsplit("}", 1)[-1] not in {"testsuite", "testsuites"}:
            raise ProvenanceError(f"Flow test report has an unsupported XML root: {path}")
        return
    if kind in {"evidence_run", "evidence_task", "evidence_review", "evidence_qa"}:
        document = _flow_json(path, content, "Flow evidence")
        parts = PurePosixPath(path).parts
        if kind == "evidence_task" and document.get("id") != parts[4][:-5]:
            raise ProvenanceError(f"Flow task evidence ID does not match its path: {path}")
        if kind in {"evidence_review", "evidence_qa"}:
            receipt_id = document.get("id")
            receipt_type = document.get("type")
            if (
                not isinstance(receipt_id, str)
                or _flow_id_is_task(receipt_id) is None
                or not isinstance(receipt_type, str)
                or receipt_type not in FLOW_EVIDENCE_RECEIPT_TYPES
                or not isinstance(document.get("verdict"), str)
            ):
                raise ProvenanceError(f"Flow receipt has an invalid content contract: {path}")
            if kind == "evidence_qa" and receipt_type != "qa_verdict":
                raise ProvenanceError(f"Flow QA evidence must contain a qa_verdict: {path}")
            if kind == "evidence_review":
                expected_suffix = f"-{receipt_type}-{receipt_id}.json"
                if not PurePosixPath(path).name.endswith(expected_suffix):
                    raise ProvenanceError(f"Flow review evidence ID does not match its path: {path}")
        return
    if kind == "artifact":
        if len(content) > MAX_COGNITIVE_AID_BYTES:
            raise ProvenanceError(f"Flow artifact exceeds the content limit: {path}")
        document = _flow_json(path, content, "Flow artifact")
        _validate_cognitive_aid(path, document)
        return


def _parse_file_change(
    item: Mapping[str, Any],
    thread_id: str,
    turn_id: str,
    order: int,
    cwd: str,
    root: Path,
) -> FileChange:
    item_id = _string(item.get("id"), "fileChange ID")
    if item.get("status") != "completed":
        raise ProvenanceError(f"fileChange {item_id} is not completed")
    values = item.get("changes")
    if not isinstance(values, list) or not values:
        raise ProvenanceError(f"fileChange {item_id} has no changes")
    operations: list[FileOp] = []
    touched_in_item: set[str] = set()
    for value in values:
        change = _obj(value, "fileChange entry")
        path = _resolve_path(change.get("path"), root, cwd, "changed path")
        kind = _obj(change.get("kind"), "fileChange kind")
        change_type = _string(kind.get("type"), "fileChange kind type")
        if change_type not in {"add", "delete", "update"}:
            raise ProvenanceError(f"fileChange {item_id} kind is unsupported")
        allowed_kind_fields = {"type", "move_path"} if change_type == "update" else {"type"}
        if set(kind) - allowed_kind_fields:
            raise ProvenanceError(f"fileChange {item_id} kind has unsupported fields")
        raw_move = kind.get("move_path") if change_type == "update" else None
        move_path = (
            None
            if raw_move is None
            else _resolve_path(raw_move, root, cwd, "move destination")
        )
        if move_path == path:
            raise ProvenanceError(f"fileChange {item_id} has a self move")
        diff = _string(change.get("diff"), "fileChange diff", empty=True)
        if "\x00" in diff:
            raise ProvenanceError(f"fileChange {item_id} contains binary content")
        paths = (path,) if move_path is None else (path, move_path)
        if any(value in touched_in_item for value in paths):
            raise ProvenanceError(f"fileChange {item_id} has overlapping path entries")
        touched_in_item.update(paths)
        operations.append(FileOp(path, change_type, diff, move_path))
    return FileChange(
        thread_id=thread_id,
        turn_id=turn_id,
        item_id=item_id,
        order=order,
        sha256=_digest_json(dict(item)),
        operations=tuple(operations),
    )


def _summarize_collab_call(
    item: Mapping[str, Any], item_id: str, digest: str, order: int
) -> dict[str, Any]:
    tool = _string(item.get("tool"), "collab tool")
    status = _string(item.get("status"), "collab tool status")
    sender = _string(item.get("senderThreadId"), "collab sender ID")
    receivers = item.get("receiverThreadIds")
    if tool not in COLLAB_TOOLS or status not in COLLAB_STATUSES:
        raise ProvenanceError(f"collab tool metadata is unknown for call {item_id}")
    if not isinstance(receivers, list) or not all(
        isinstance(value, str) and value for value in receivers
    ):
        raise ProvenanceError(f"collab receivers are invalid for call {item_id}")
    if len(receivers) != len(set(receivers)):
        raise ProvenanceError(f"collab call {item_id} repeats a receiver thread ID")
    model, effort, prompt = (
        item.get("model"), item.get("reasoningEffort"), item.get("prompt")
    )
    if model is not None and not isinstance(model, str):
        raise ProvenanceError(f"collab model is invalid for call {item_id}")
    if effort is not None and not isinstance(effort, str):
        raise ProvenanceError(f"collab effort is invalid for call {item_id}")
    if prompt is not None and not isinstance(prompt, str):
        raise ProvenanceError(f"collab prompt is invalid for call {item_id}")
    return {
        "id": item_id, "sha256": digest, "tool": tool, "status": status,
        "sender": sender, "receivers": list(receivers), "model": model,
        "effort": effort, "prompt": prompt, "order": order,
    }


def _summarize_activity(
    item: Mapping[str, Any], item_id: str, digest: str, order: int
) -> dict[str, Any]:
    kind = _string(item.get("kind"), "subAgentActivity kind")
    if kind not in ACTIVITY_KINDS:
        raise ProvenanceError(f"subAgentActivity kind is unknown for {item_id}")
    return {
        "id": item_id,
        "sha256": digest,
        "childThreadId": _string(item.get("agentThreadId"), "activity child ID"),
        "agentPath": _string(item.get("agentPath"), "activity agent path"),
        "kind": kind,
        "order": order,
    }


def _summarize_thread(
    client: Any, thread: Mapping[str, Any], path_root: Path
) -> dict[str, Any]:
    thread_id = _string(thread.get("id"), "thread ID")
    cwd_raw = _string(thread.get("cwd"), "thread cwd")
    try:
        cwd_path = Path(cwd_raw).resolve(strict=True)
    except OSError as exc:
        raise ProvenanceError(f"thread cwd is unavailable: {cwd_raw}") from exc
    if not cwd_path.is_dir():
        raise ProvenanceError(f"thread cwd is not a directory: {cwd_raw}")
    cwd = str(cwd_path)
    seen_turns: set[str] = set()
    items: list[dict[str, Any]] = []
    file_changes: list[FileChange] = []
    commands: list[dict[str, str]] = []
    opaque_tools: list[dict[str, str]] = []
    activities: list[dict[str, Any]] = []
    spawn_calls: list[dict[str, Any]] = []
    file_change_turns: list[dict[str, Any]] = []
    turns = _turns(client, thread)
    last_turn: dict[str, Any] | None = None
    order = 0
    for turn_value in turns:
        turn = _obj(turn_value, "turn")
        turn_id = _string(turn.get("id"), "turn ID")
        if turn_id in seen_turns:
            raise ProvenanceError(f"thread {thread_id} history repeated a turn ID")
        seen_turns.add(turn_id)
        turn_status = _string(turn.get("status"), "turn status")
        if turn_status not in TURN_STATUSES:
            raise ProvenanceError(f"unsupported turn status: {turn_status}")
        has_message = False
        changes_in_turn: list[FileChange] = []
        for item_value in _items(client, thread_id, turn):
            item = _obj(item_value, "thread item")
            item_type = _string(item.get("type"), "thread item type")
            if item_type not in ITEM_TYPES:
                raise ProvenanceError(f"unknown thread item type: {item_type}")
            item_id = _string(item.get("id"), f"{item_type} item ID")
            digest = _digest_json(item)
            order += 1
            items.append(
                {
                    "id": item_id, "type": item_type, "turn_id": turn_id,
                    "order": order, "sha256": digest, "raw": item,
                }
            )
            if item_type == "agentMessage":
                text = item.get("text")
                if not isinstance(text, str):
                    raise ProvenanceError("agentMessage text has an unsupported type")
                has_message = has_message or bool(text)
            elif item_type == "fileChange":
                change = _parse_file_change(
                    item, thread_id, turn_id, order, cwd, path_root
                )
                file_changes.append(change)
                changes_in_turn.append(change)
            elif item_type == "commandExecution":
                _string(item.get("command"), "commandExecution command", empty=True)
                status = _string(item.get("status"), "commandExecution status")
                if status not in {"inProgress", "completed", "failed", "declined"}:
                    raise ProvenanceError("commandExecution status is unknown")
                commands.append(
                    {
                        "threadId": thread_id, "turnId": turn_id,
                        "itemId": item_id, "sha256": digest,
                    }
                )
            elif item_type in {"mcpToolCall", "dynamicToolCall"}:
                opaque_tools.append(
                    {
                        "threadId": thread_id, "turnId": turn_id,
                        "itemId": item_id, "type": item_type, "sha256": digest,
                    }
                )
            elif item_type == "collabAgentToolCall":
                spawn_calls.append(_summarize_collab_call(item, item_id, digest, order))
            elif item_type == "subAgentActivity":
                activities.append(_summarize_activity(item, item_id, digest, order))
        if changes_in_turn:
            file_change_turns.append(
                {
                    "id": turn_id, "status": turn_status,
                    "hasAgentMessage": has_message,
                }
            )
        last_turn = {
            "id": turn_id, "status": turn_status, "hasAgentMessage": has_message
        }
    if last_turn is None:
        raise ProvenanceError(f"thread {thread_id} history contained no turns")
    return {
        "thread": dict(thread), "thread_id": thread_id, "cwd": cwd,
        "workspace": str(path_root),
        "items": items, "file_changes": file_changes, "commands": commands,
        "opaque_tools": opaque_tools, "activities": activities,
        "spawn_calls": spawn_calls, "file_change_turns": file_change_turns,
        "last_turn": last_turn,
    }


def _validate_inputs(
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    root: Path,
    common_dir: Path,
) -> tuple[str, str, list[dict[str, Any]], dict[str, dict[str, str]]]:
    if set(request) != {"parent_thread", "children", "base_commit", "task"}:
        raise ProvenanceError(
            "request must contain parent_thread, children, base_commit, and task"
        )
    parent_id = _string(request.get("parent_thread"), "parent_thread")
    task = _string(request.get("task"), "task")
    if task != task.strip() or "\n" in task or "\r" in task:
        raise ProvenanceError("task must be a single exact native declaration line")
    base_commit = _string(request.get("base_commit"), "base_commit")
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", base_commit):
        raise ProvenanceError("base_commit must be a full lowercase Git commit hash")
    child_values = request.get("children")
    if not isinstance(child_values, list) or not child_values:
        raise ProvenanceError("request must include at least one child")
    children: list[dict[str, Any]] = []
    child_ids: set[str] = set()
    expected_aliases: dict[str, str] = {}
    validated_workspaces: dict[str, Path] = {str(root): root}
    for child_value in child_values:
        child = _obj(child_value, "child request")
        if set(child) - {
            "thread_id", "expected_files", "reason", "workspace", "task_declaration"
        } or not {
            "thread_id", "expected_files"
        }.issubset(child):
            raise ProvenanceError(
                "each child must contain thread_id and expected_files, with optional "
                "reason, workspace, and task_declaration"
            )
        child_id = _string(child.get("thread_id"), "child thread_id")
        if child_id == parent_id or child_id in child_ids:
            raise ProvenanceError("parent and child thread IDs must be unique")
        child_ids.add(child_id)
        values = child.get("expected_files")
        if not isinstance(values, list) or not values:
            raise ProvenanceError(f"child {child_id} must include expected_files")
        paths = []
        for value in values:
            path_value = _string(value, "expected file")
            if Path(path_value).is_absolute():
                raise ProvenanceError("expected files must be repository-relative paths")
            paths.append(
                _resolve_path(
                    path_value, root, str(root), "expected file", relative_to_root=True
                )
            )
        if len(paths) != len(set(paths)):
            raise ProvenanceError(f"child {child_id} repeats an expected file")
        for path in paths:
            alias = _path_alias(path)
            previous = expected_aliases.get(alias)
            if previous is not None and previous != path:
                raise ProvenanceError(
                    f"expected paths have a case or Unicode alias: {previous} and {path}"
                )
            expected_aliases[alias] = path
        normalized_child = {"thread_id": child_id, "expected_files": sorted(paths)}
        task_declaration = _string(
            child.get("task_declaration", task),
            f"task_declaration for child {child_id}",
        )
        if (
            task_declaration != task_declaration.strip()
            or "\n" in task_declaration
            or "\r" in task_declaration
        ):
            raise ProvenanceError(
                f"task_declaration for child {child_id} must be a single exact native declaration line"
            )
        normalized_child["task_declaration"] = task_declaration
        workspace_value = child.get("workspace")
        if "workspace" not in child:
            workspace = root
        else:
            raw_workspace = _string(workspace_value, f"workspace for child {child_id}")
            if raw_workspace not in validated_workspaces:
                validated_workspaces[raw_workspace] = _validate_workspace(
                    raw_workspace, root, common_dir
                )
            workspace = validated_workspaces[raw_workspace]
        normalized_child["workspace"] = str(workspace)
        if "reason" in child:
            reason = _string(child["reason"], f"reason for child {child_id}")
            if "\n" in reason or "\r" in reason:
                raise ProvenanceError(
                    f"reason for child {child_id} must fit on one exact native line"
                )
            normalized_child["reason"] = reason
        children.append(normalized_child)
    if not any(child["task_declaration"] == task for child in children):
        raise ProvenanceError(
            "the complete child set must include a verified child for the current task"
        )
    roles: dict[str, dict[str, str]] = {}
    for role_value, policy_value in policy.items():
        role = _string(role_value, "policy role")
        role_policy = _obj(policy_value, f"policy for {role}")
        if set(role_policy) - {"model", "effort", "require_reason"} or not {
            "model", "effort"
        }.issubset(role_policy):
            raise ProvenanceError(
                f"policy for {role} must contain model and effort, with optional require_reason"
            )
        require_reason = role_policy.get("require_reason", False)
        if not isinstance(require_reason, bool):
            raise ProvenanceError(f"policy require_reason for {role} must be boolean")
        roles[role] = {
            "model": _string(role_policy.get("model"), f"policy model for {role}"),
            "effort": _string(role_policy.get("effort"), f"policy effort for {role}"),
            "require_reason": require_reason,
        }
    if not roles:
        raise ProvenanceError("policy must configure at least one role")
    return parent_id, task, children, roles


def _git_environment() -> dict[str, str]:
    # Git environment variables can redirect repository, index, object, config,
    # or ref lookup. The verifier always operates on the supplied worktree.
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git_result(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    command = [
        "git", "--no-replace-objects", "-c", "core.fileMode=true",
        "-c", "core.fsmonitor=false",
        "-C", str(root), *arguments,
    ]
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_environment(),
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProvenanceError(f"git {' '.join(arguments[:2])} failed: {exc}") from exc


def _git(root: Path, *arguments: str) -> bytes:
    result = _git_result(root, *arguments)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ProvenanceError(
            f"git {' '.join(arguments[:2])} failed" + (f": {detail}" if detail else "")
        )
    return result.stdout


def _validate_index_flags(root: Path) -> None:
    output = _git(root, "ls-files", "-v", "-z")
    for entry in output.split(b"\x00"):
        if not entry:
            continue
        if len(entry) < 2 or entry[1:2] != b" ":
            raise ProvenanceError("Git returned a malformed index flag listing")
        tag = entry[:1]
        path = entry[2:].decode("utf-8", errors="replace")
        if tag in {b"S", b"s"}:
            raise ProvenanceError(
                "Git index has a skip-worktree entry that can hide candidate edits "
                f"({path!r}); clear it with `git update-index --no-skip-worktree -- <path>`"
            )
        if tag.islower():
            raise ProvenanceError(
                "Git index has an assume-unchanged entry that can hide candidate edits "
                f"({path!r}); clear it with `git update-index --no-assume-unchanged -- <path>`"
            )


def _validate_legacy_grafts(root: Path) -> None:
    raw_path = _git(root, "rev-parse", "--git-path", "info/grafts")
    try:
        path = Path(raw_path.decode("utf-8").strip())
    except UnicodeDecodeError as exc:
        raise ProvenanceError("Git returned a non-UTF-8 legacy graft path") from exc
    if not path.is_absolute():
        path = root / path
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ProvenanceError(f"cannot inspect legacy Git grafts: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ProvenanceError("legacy Git graft metadata must be a regular file")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ProvenanceError(f"cannot read legacy Git grafts: {exc}") from exc
    if content:
        raise ProvenanceError(
            "non-empty legacy Git grafts are unsupported because they redefine commit ancestry; "
            "remove the entries from info/grafts"
        )


def _repository_common_dir(root: Path) -> Path:
    raw = _git(root, "rev-parse", "--git-common-dir").decode("utf-8").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        common_dir = path.resolve(strict=True)
    except OSError as exc:
        raise ProvenanceError(f"Git common directory is unavailable: {exc}") from exc
    if not common_dir.is_dir():
        raise ProvenanceError("Git common directory is not a directory")
    return common_dir


def _registered_worktrees(root: Path) -> set[str]:
    output = _git(root, "worktree", "list", "--porcelain", "-z")
    try:
        fields = output.decode("utf-8").split("\x00")
    except UnicodeDecodeError as exc:
        raise ProvenanceError("Git returned a non-UTF-8 linked worktree path") from exc
    paths = {
        field.removeprefix("worktree ")
        for field in fields
        if field.startswith("worktree ")
    }
    if not paths:
        raise ProvenanceError("Git did not report any registered worktrees")
    return paths


def _validate_workspace(value: object, root: Path, common_dir: Path) -> Path:
    workspace = _canonical_directory(value, "child workspace")
    top_level_raw = _git(workspace, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    if Path(top_level_raw) != workspace:
        raise ProvenanceError("child workspace must be the canonical Git worktree root")
    if _repository_common_dir(workspace) != common_dir:
        raise ProvenanceError("child workspace belongs to a different Git repository")
    registered = _registered_worktrees(root)
    if str(workspace) not in registered:
        raise ProvenanceError("child workspace is not a registered linked worktree")
    return workspace


def _prepare_repository(
    repo_root: str | os.PathLike[str],
) -> tuple[Path, str, str]:
    try:
        supplied = Path(os.path.expanduser(os.fspath(repo_root)))
        if not supplied.is_absolute():
            supplied = Path.cwd() / supplied
        root = _canonical_directory(str(supplied), "repo_root")
    except (OSError, TypeError) as exc:
        raise ProvenanceError(f"repo_root is unavailable: {exc}") from exc
    top_level = _git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    if Path(top_level) != root:
        raise ProvenanceError("repo_root must be the Git worktree root")
    _validate_index_flags(root)
    _validate_legacy_grafts(root)
    object_format = (
        _git(root, "rev-parse", "--show-object-format").decode("ascii").strip()
    )
    if object_format not in {"sha1", "sha256"}:
        raise ProvenanceError(f"unsupported Git object format: {object_format}")
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head):
        raise ProvenanceError("Git returned an invalid HEAD commit ID")
    return root, str(root), head


def _resolve_commit(root: Path, commit: str) -> str:
    resolved = _git(
        root, "rev-parse", "--verify", "--end-of-options", f"{commit}^{{commit}}"
    ).decode("ascii").strip()
    if resolved != commit:
        raise ProvenanceError("base_commit does not resolve to the exact immutable commit")
    if _git(root, "cat-file", "-t", commit).decode("ascii").strip() != "commit":
        raise ProvenanceError("base_commit is not a commit object")
    ancestor = _git_result(root, "merge-base", "--is-ancestor", commit, "HEAD")
    if ancestor.returncode != 0:
        raise ProvenanceError("base_commit is not an ancestor of the current HEAD")
    return resolved


def _git_tree_entry(
    root: Path, tree: str, path: str
) -> tuple[bytes, int] | None:
    output = _git(root, "ls-tree", "-z", tree, "--", f":(literal){path}")
    entries = [entry for entry in output.split(b"\x00") if entry]
    if not entries:
        return None
    if len(entries) != 1:
        raise ProvenanceError(f"Git tree has ambiguous entries for {path}")
    metadata, separator, returned_path = entries[0].partition(b"\t")
    if not separator or returned_path.decode("utf-8", errors="strict") != path:
        raise ProvenanceError(f"Git tree path lookup was ambiguous for {path}")
    fields = metadata.decode("ascii").split()
    if len(fields) != 3 or fields[1] != "blob":
        raise ProvenanceError(f"unsupported Git tree entry for {path}")
    mode_text, _, object_id = fields
    if mode_text not in {"100644", "100755"}:
        raise ProvenanceError(f"unsupported Git mode for {path}: {mode_text}")
    return _git(root, "cat-file", "blob", object_id), int(mode_text, 8)


def _git_index_entry(root: Path, path: str) -> tuple[bytes, int] | None:
    output = _git(
        root, "ls-files", "--stage", "-z", "--", f":(literal){path}"
    )
    entries = [entry for entry in output.split(b"\x00") if entry]
    if not entries:
        return None
    parsed: list[tuple[bytes, int]] = []
    for entry in entries:
        metadata, separator, returned_path = entry.partition(b"\t")
        if not separator or returned_path.decode("utf-8", errors="strict") != path:
            raise ProvenanceError(f"Git index path lookup was ambiguous for {path}")
        fields = metadata.decode("ascii").split()
        if len(fields) != 3 or fields[2] != "0":
            raise ProvenanceError(f"Git index has unresolved stages for {path}")
        mode_text, object_id, _stage = fields
        if mode_text not in {"100644", "100755"}:
            raise ProvenanceError(f"unsupported Git index mode for {path}: {mode_text}")
        parsed.append((_git(root, "cat-file", "blob", object_id), int(mode_text, 8)))
    if len(parsed) != 1:
        raise ProvenanceError(f"Git index has ambiguous entries for {path}")
    return parsed[0]


def _read_disk_state(
    root: Path, path: str, *, max_bytes: int | None = None
) -> tuple[bytes, int] | None:
    target = _assert_safe_path(root, PurePosixPath(path))
    try:
        info = target.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProvenanceError(f"candidate path is not a regular file: {path}")
    if info.st_nlink != 1:
        raise ProvenanceError(f"candidate file is hard-linked: {path}")
    if max_bytes is not None and info.st_size > max_bytes:
        raise ProvenanceError(f"candidate file exceeds its content limit: {path}")
    try:
        content = target.read_bytes()
    except OSError as exc:
        raise ProvenanceError(f"cannot read candidate file {path}: {exc}") from exc
    if max_bytes is not None and len(content) > max_bytes:
        raise ProvenanceError(f"candidate file exceeds its content limit: {path}")
    mode = 0o100755 if info.st_mode & 0o111 else 0o100644
    return content, mode


def _patch_update(original: bytes, patch_text: str, path: str) -> bytes:
    try:
        patch = patch_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProvenanceError(f"update diff for {path} is not UTF-8") from exc
    if b"\x00" in patch:
        raise ProvenanceError(f"binary update diff is unsupported for {path}")
    patch_lines = patch.splitlines(keepends=True)
    source = original.splitlines(keepends=True)
    output: list[bytes] = []
    source_cursor = 0
    patch_index = 0
    hunk_count = 0
    while patch_index < len(patch_lines):
        header = patch_lines[patch_index]
        match = UNIFIED_HUNK.fullmatch(header)
        if match is None:
            if hunk_count == 0 and header.startswith((b"--- ", b"+++ ")):
                patch_index += 1
                continue
            if not header.strip():
                patch_index += 1
                continue
            raise ProvenanceError(f"unsupported unified diff syntax for {path}")
        old_start = int(match.group(1))
        old_count = int(match.group(2) or b"1")
        new_count = int(match.group(4) or b"1")
        old_index = old_start if old_count == 0 else old_start - 1
        if old_index < source_cursor or old_index > len(source):
            raise ProvenanceError(f"overlapping or out-of-range diff hunk for {path}")
        output.extend(source[source_cursor:old_index])
        source_cursor = old_index
        patch_index += 1
        consumed_old = 0
        produced_new = 0
        while patch_index < len(patch_lines) and not patch_lines[patch_index].startswith(b"@@ "):
            line = patch_lines[patch_index]
            if line.startswith(b"\\ No newline at end of file"):
                raise ProvenanceError(f"orphan no-newline marker in diff for {path}")
            if not line or line[:1] not in {b" ", b"+", b"-"}:
                raise ProvenanceError(f"unsupported diff line for {path}")
            prefix, body = line[:1], line[1:]
            no_newline = (
                patch_index + 1 < len(patch_lines)
                and patch_lines[patch_index + 1].startswith(
                    b"\\ No newline at end of file"
                )
            )
            if no_newline:
                if body.endswith(b"\r\n"):
                    body = body[:-2]
                elif body.endswith((b"\n", b"\r")):
                    body = body[:-1]
            if prefix in {b" ", b"-"}:
                if source_cursor >= len(source) or source[source_cursor] != body:
                    raise ProvenanceError(
                        f"update diff context does not match base content for {path}"
                    )
                source_cursor += 1
                consumed_old += 1
            if prefix in {b" ", b"+"}:
                output.append(body)
                produced_new += 1
            patch_index += 1
            if no_newline:
                patch_index += 1
        if consumed_old != old_count or produced_new != new_count:
            raise ProvenanceError(f"unified diff hunk counts are invalid for {path}")
        hunk_count += 1
    if hunk_count == 0:
        raise ProvenanceError(f"update diff has no unified hunks for {path}")
    output.extend(source[source_cursor:])
    return b"".join(output)


def _delete_matches(current: bytes, diff_text: str, path: str) -> bool:
    try:
        diff = diff_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProvenanceError(f"delete diff for {path} is not UTF-8") from exc
    if diff == current:
        return True
    if diff.startswith(b"@@ "):
        try:
            return _patch_update(current, diff_text, path) == b""
        except ProvenanceError:
            return False
    return False


def _apply_op(
    state: dict[str, tuple[bytes, int] | None], operation: FileOp
) -> None:
    path = operation.path
    current = state.get(path)
    if operation.kind == "add":
        if current is not None or operation.move_path is not None:
            raise ProvenanceError(f"native add does not match candidate state for {path}")
        try:
            content = operation.diff.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ProvenanceError(f"add diff for {path} is not UTF-8") from exc
        if b"\x00" in content:
            raise ProvenanceError(f"binary add is unsupported for {path}")
        state[path] = (content, 0o100644)
        return
    if current is None:
        raise ProvenanceError(f"native {operation.kind} has no source file: {path}")
    content, mode = current
    if operation.kind == "delete":
        if operation.move_path is not None or not _delete_matches(
            content, operation.diff, path
        ):
            raise ProvenanceError(f"delete diff does not match candidate content for {path}")
        state[path] = None
        return
    if operation.kind != "update":
        raise ProvenanceError(f"unsupported native file operation: {operation.kind}")
    updated = _patch_update(content, operation.diff, path)
    if operation.move_path is None:
        state[path] = (updated, mode)
        return
    destination = operation.move_path
    if state.get(destination) is not None:
        raise ProvenanceError(f"native move destination already exists: {destination}")
    state[path] = None
    state[destination] = (updated, mode)


def _base_state(
    root: Path,
    base: str,
    path: str,
    cache: dict[str, tuple[bytes, int] | None],
) -> tuple[bytes, int] | None:
    if path not in cache:
        cache[path] = _git_tree_entry(root, base, path)
    return cache[path]


def _coordination_changes(
    parent: Mapping[str, Any], root: Path, base: str
) -> tuple[list[FileChange], dict[str, tuple[bytes, int] | None]]:
    changes: list[FileChange] = parent["file_changes"]
    state: dict[str, tuple[bytes, int] | None] = {}
    base_cache: dict[str, tuple[bytes, int] | None] = {}
    marker_counts: dict[str, int] = {}
    for file_change in changes:
        for operation in file_change.operations:
            if operation.move_path is not None:
                raise ProvenanceError(
                    "coordinator move events are unsupported for inert Flow paths"
                )
            kind = _coordination_kind(operation.path)
            if kind is None:
                raise ProvenanceError(
                    f"coordinator fileChange touches a non-inert Flow path: {operation.path}"
                )
            if kind in {"base_commit", "spec_base"}:
                marker_counts[kind] = marker_counts.get(kind, 0) + 1
                if marker_counts[kind] != 1:
                    raise ProvenanceError(f"coordinator repeats the {kind} marker")
                if operation.kind not in {"add", "update"}:
                    raise ProvenanceError(f"coordinator cannot delete {kind}")
            if operation.path not in state:
                state[operation.path] = _base_state(
                    root, base, operation.path, base_cache
                )
            _apply_op(state, operation)
    return changes, state


def _validate_coordinator_file(
    root: Path, base: str, path: str, state: tuple[bytes, int] | None
) -> None:
    kind = _coordination_kind(path)
    if kind is None:
        raise ProvenanceError(f"coordinator path is not inert Flow state: {path}")
    if state is None:
        if kind in {"base_commit", "spec_base"}:
            raise ProvenanceError(f"coordinator marker is missing: {path}")
        return
    content = state[0]
    if state[1] & 0o111:
        raise ProvenanceError(f"coordinator file is executable: {path}")
    if b"\x00" in content:
        raise ProvenanceError(f"coordinator Flow file is binary: {path}")
    if kind in {"base_commit", "spec_base"}:
        try:
            marker = content.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProvenanceError(f"coordinator marker is not ASCII: {path}") from exc
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\n?", marker):
            raise ProvenanceError(f"coordinator marker is not an exact Git hash: {path}")
        commit = marker.removesuffix("\n")
        _resolve_commit(root, commit)
        if kind == "base_commit" and commit != base:
            raise ProvenanceError(
                "coordinator base_commit marker differs from requested base"
            )
        return
    if kind not in {"spec", "task"}:
        _validate_inert_flow_content(kind, path, content, state[1])
        return
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProvenanceError(f"coordinator Flow file is not UTF-8: {path}") from exc
    stem = PurePosixPath(path).stem
    if kind in {"spec", "task"} and path.endswith(".json"):
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProvenanceError(f"coordinator Flow JSON is invalid: {path}") from exc
        if not isinstance(document, dict) or document.get("id") != stem:
            raise ProvenanceError(f"coordinator Flow JSON ID does not match its path: {path}")
        return
    # Flow owns Markdown structure and prose semantics. Provenance only binds
    # the file to its path and requires safe, non-binary UTF-8 text.


def _candidate_coordinator_state(
    root: Path,
    base: str,
    changed: set[str],
    native_state: Mapping[str, tuple[bytes, int] | None],
) -> dict[str, tuple[bytes, int] | None]:
    paths = {path for path in changed if _coordination_kind(path) is not None}
    paths.update(native_state)
    state = {
        path: _read_disk_state(
            root,
            path,
            max_bytes=MAX_COGNITIVE_AID_BYTES
            if _coordination_kind(path) == "artifact"
            else None,
        )
        for path in sorted(paths)
    }
    for path, value in state.items():
        _validate_coordinator_file(root, base, path, value)
    return state


def _changed_paths(root: Path, base: str) -> set[str]:
    commands = (
        (
            "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
            "--name-only", "-z", base, "--",
        ),
        (
            "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
            "--name-only", "-z", base, "HEAD", "--",
        ),
        (
            "diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames",
            "--name-only", "-z", base, "--",
        ),
    )
    paths: set[str] = set()
    for arguments in commands:
        output = _git(root, *arguments)
        for raw in output.split(b"\x00"):
            if raw:
                try:
                    paths.add(raw.decode("utf-8"))
                except UnicodeDecodeError as exc:
                    raise ProvenanceError("Git candidate contains a non-UTF-8 path") from exc
    output = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    for raw in output.split(b"\x00"):
        if raw:
            try:
                paths.add(raw.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise ProvenanceError(
                    "untracked candidate contains a non-UTF-8 path"
                ) from exc
    return paths


def _validate_git_path_aliases(root: Path, base: str, changed: set[str]) -> None:
    output = _git(root, "ls-tree", "-r", "-z", "--full-tree", base)
    aliases: dict[str, str] = {}
    changed_aliases = {_path_alias(path) for path in changed}
    for entry in output.split(b"\x00"):
        if not entry:
            continue
        _metadata, separator, raw_path = entry.partition(b"\t")
        if not separator:
            raise ProvenanceError("Git tree returned a malformed path entry")
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProvenanceError("base Git tree contains a non-UTF-8 path") from exc
        alias = _path_alias(path)
        if alias not in changed_aliases:
            continue
        previous = aliases.get(alias)
        if previous is not None and previous != path:
            raise ProvenanceError(
                f"base Git tree has case or Unicode path aliases: {previous} and {path}"
            )
        aliases[alias] = path
    for path in changed:
        previous = aliases.get(_path_alias(path))
        if previous is not None and previous != path:
            raise ProvenanceError(f"candidate path aliases a base path: {path} and {previous}")


def _state_equal(
    left: tuple[bytes, int] | None, right: tuple[bytes, int] | None
) -> bool:
    return left == right


def _state_record(path: str, state: tuple[bytes, int] | None) -> dict[str, Any]:
    if state is None:
        return {"path": path, "exists": False, "sha256": None, "mode": None}
    content, mode = state
    return {
        "path": path,
        "exists": True,
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": f"{mode:06o}",
    }


def _validate_candidate(
    root: Path,
    base: str,
    final_state: dict[str, tuple[bytes, int] | None],
    delegated_paths: set[str],
    coordinator_paths: set[str],
) -> list[dict[str, Any]]:
    _validate_index_flags(root)
    _validate_legacy_grafts(root)
    changed = _changed_paths(root, base)
    _validate_git_path_aliases(root, base, changed)
    allowed = delegated_paths | coordinator_paths
    extra = sorted(changed - allowed)
    if extra:
        raise ProvenanceError(
            "Git candidate has unexplained tracked or untracked paths: "
            + ", ".join(extra)
        )
    for path, expected in sorted(final_state.items()):
        base_state = _git_tree_entry(root, base, path)
        head_state = _git_tree_entry(root, "HEAD", path)
        index_state = _git_index_entry(root, path)
        disk_state = _read_disk_state(root, path)
        if not _state_equal(disk_state, expected):
            raise ProvenanceError(
                f"disk candidate differs from replayed native changes: {path}"
            )
        if path in coordinator_paths:
            for candidate in (head_state, index_state):
                if candidate is not None:
                    _validate_coordinator_file(root, base, path, candidate)
        else:
            for label, candidate in (("HEAD", head_state), ("index", index_state)):
                if not (
                    _state_equal(candidate, base_state)
                    or _state_equal(candidate, expected)
                ):
                    raise ProvenanceError(
                        f"{label} candidate has an unexplained intermediate state: {path}"
                    )
        if (
            path in delegated_paths
            and not _state_equal(expected, base_state)
            and path not in changed
        ):
            raise ProvenanceError(
                f"delegated output is ignored or absent from the Git candidate: {path}"
            )
        if path in delegated_paths and _state_equal(expected, base_state):
            raise ProvenanceError(
                f"native child changes have no final effect relative to base: {path}"
            )
    return [
        _state_record(path, final_state[path])
        for path in sorted(final_state)
    ]


def _validate_unique_native_ids(summaries: list[Mapping[str, Any]]) -> None:
    seen: set[str] = set()
    for summary in summaries:
        for item in summary["items"]:
            item_id = item["id"]
            if item_id in seen:
                raise ProvenanceError(f"native history repeats an item ID: {item_id}")
            seen.add(item_id)


def _child_relation(
    parent: Mapping[str, Any], child_thread: Mapping[str, Any], child_id: str
) -> dict[str, Any]:
    parent_id = parent["thread_id"]
    if child_thread.get("parentThreadId") != parent_id:
        raise ProvenanceError(
            f"child {child_id} parentThreadId does not match requested parent"
        )
    activities = [
        item for item in parent["activities"] if item["childThreadId"] == child_id
    ]
    spawns = [
        item
        for item in parent["spawn_calls"]
        if item["tool"] == "spawnAgent"
        and item["sender"] == parent_id
        and child_id in item["receivers"]
    ]
    if activities and spawns:
        raise ProvenanceError(
            f"child {child_id} has duplicate native activity and spawn relations"
        )
    if len(spawns) > 1:
        raise ProvenanceError(f"child {child_id} has multiple native spawn relations")
    if activities:
        starts = [item for item in activities if item["kind"] == "started"]
        completes = [item for item in activities if item["kind"] == "completed"]
        if (
            len(starts) != 1
            or len(completes) != 1
            or any(item["kind"] == "interrupted" for item in activities)
        ):
            raise ProvenanceError(
                f"child {child_id} lacks one completed native activity link"
            )
        paths = {item["agentPath"] for item in activities}
        start_order, complete_order = starts[0]["order"], completes[0]["order"]
        if len(paths) != 1 or start_order >= complete_order:
            raise ProvenanceError(
                f"child {child_id} native activity path or ordering is inconsistent"
            )
        if any(
            item["kind"] == "interacted"
            and not start_order < item["order"] < complete_order
            for item in activities
        ):
            raise ProvenanceError(
                f"child {child_id} has activity outside its native start/completion interval"
            )
        return {
            "kind": "subAgentActivity",
            "start": start_order,
            "complete": complete_order,
            "events": sorted(activities, key=lambda item: item["order"]),
        }
    if len(spawns) == 1:
        spawn = spawns[0]
        if spawn["status"] != "completed" or spawn["receivers"] != [child_id]:
            raise ProvenanceError(
                f"child {child_id} native spawn did not complete as a unique relation"
            )
        return {
            "kind": "spawnAgent",
            "start": spawn["order"],
            "complete": None,
            "events": [spawn],
            "requestedModel": spawn["model"],
            "requestedEffort": spawn["effort"],
        }
    raise ProvenanceError(
        f"no supported native parent-child relation links {parent_id} to {child_id}"
    )


def _order_children(
    children: list[dict[str, Any]], relations: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    child_ids = [child["thread_id"] for child in children]
    expected = {
        child["thread_id"]: set(child["expected_files"]) for child in children
    }
    edges = {child_id: set() for child_id in child_ids}
    indegree = dict.fromkeys(child_ids, 0)
    for index, left_id in enumerate(child_ids):
        for right_id in child_ids[index + 1 :]:
            if not expected[left_id].intersection(expected[right_id]):
                continue
            left, right = relations[left_id], relations[right_id]
            if left["complete"] is None or right["complete"] is None:
                raise ProvenanceError(
                    "overlapping child paths require native start/completion activity ordering"
                )
            if left["complete"] < right["start"]:
                before, after = left_id, right_id
            elif right["complete"] < left["start"]:
                before, after = right_id, left_id
            else:
                raise ProvenanceError(
                    "concurrent native children overlap expected paths; candidate order is ambiguous"
                )
            if after not in edges[before]:
                edges[before].add(after)
                indegree[after] += 1
    native_start = {child_id: relations[child_id]["start"] for child_id in child_ids}
    ready = sorted(
        (child_id for child_id in child_ids if indegree[child_id] == 0),
        key=lambda child_id: (native_start[child_id], child_id),
    )
    order: list[str] = []
    while ready:
        child_id = ready.pop(0)
        order.append(child_id)
        for after in sorted(edges[child_id]):
            indegree[after] -= 1
            if indegree[after] == 0:
                ready.append(after)
                ready.sort(key=lambda value: (native_start[value], value))
    if len(order) != len(child_ids):
        raise ProvenanceError("native child activity ordering contains a cycle")
    return order


def _parent_line_evidence(
    parent: Mapping[str, Any], before_order: int, required_line: str, label: str
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for item in parent["items"]:
        if item["type"] != "agentMessage" or item["order"] >= before_order:
            continue
        text = item["raw"].get("text")
        if isinstance(text, str) and required_line in text.splitlines():
            matches.append(item)
    if not matches:
        raise ProvenanceError(
            f"parent thread lacks exact {label} line before native child start"
        )
    item = matches[-1]
    return {
        "itemId": item["id"],
        "turnId": item["turn_id"],
        "sha256": item["sha256"],
        "order": item["order"],
    }


def _verify_child(
    request_child: Mapping[str, Any],
    summary: Mapping[str, Any],
    parent_summary: Mapping[str, Any],
    roles: Mapping[str, Mapping[str, str]],
    task: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    child_id = request_child["thread_id"]
    thread = summary["thread"]
    if thread.get("id") != child_id:
        raise ProvenanceError("thread/read returned a child ID different from the request")
    if thread.get("parentThreadId") != parent_summary["thread_id"]:
        raise ProvenanceError(
            f"child {child_id} parentThreadId does not match requested parent"
        )
    status = _obj(thread.get("status"), "child status").get("type")
    if status in {"active", "systemError"}:
        raise ProvenanceError(f"implementation child thread status is {status}")
    last_turn = summary["last_turn"]
    if last_turn["status"] != "completed" or not last_turn["hasAgentMessage"]:
        raise ProvenanceError(
            f"implementation child {child_id} has no completed final response"
        )
    change_turns = summary["file_change_turns"]
    if len(change_turns) != 1:
        raise ProvenanceError(
            f"implementation child {child_id} must have exactly one fileChange-bearing turn"
        )
    edit_turn = change_turns[0]
    if edit_turn["status"] != "completed" or not edit_turn["hasAgentMessage"]:
        raise ProvenanceError(
            f"child {child_id} fileChange turn is not completed with a final response"
        )
    if not summary["file_changes"]:
        raise ProvenanceError(f"child {child_id} has no native fileChange evidence")
    role = _string(thread.get("agentRole"), "child configured role")
    configured = roles.get(role)
    if configured is None:
        raise ProvenanceError(f"child {child_id} role is absent from caller policy: {role}")
    model = _string(thread.get("model"), "child configured model")
    effort = _string(thread.get("reasoningEffort"), "child configured effort")
    if model != configured["model"] or effort != configured["effort"]:
        raise ProvenanceError(
            f"child {child_id} configured metadata does not match caller policy for {role}"
        )
    relation = _child_relation(parent_summary, thread, child_id)
    requested_model = relation.get("requestedModel")
    requested_effort = relation.get("requestedEffort")
    if requested_model is not None and requested_model != model:
        raise ProvenanceError(f"native spawn requested a different model for child {child_id}")
    if requested_effort is not None and requested_effort != effort:
        raise ProvenanceError(f"native spawn requested a different effort for child {child_id}")
    task_line = _parent_line_evidence(
        parent_summary,
        relation["start"],
        f"Implementation task: {task}",
        "Implementation task",
    )
    reason = request_child.get("reason")
    reason_required = configured["require_reason"]
    if reason_required and reason is None:
        raise ProvenanceError(
            f"child {child_id} requires a caller-supplied escalation reason"
        )
    reason_line = None
    if reason is not None:
        reason_line = _parent_line_evidence(
            parent_summary,
            relation["start"],
            f"Escalation reason: {reason}",
            "Escalation reason",
        )
    prompt = (
        relation["events"][0].get("prompt")
        if relation["kind"] == "spawnAgent"
        else None
    )
    prompt_task_line = (
        isinstance(prompt, str)
        and f"Implementation task: {task}" in prompt.splitlines()
    )
    prompt_reason_line = None
    if reason is not None and isinstance(prompt, str):
        prompt_reason_line = f"Escalation reason: {reason}" in prompt.splitlines()
        if not prompt_reason_line:
            raise ProvenanceError(
                f"legacy spawn prompt lacks exact escalation reason for child {child_id}"
            )
    native_paths = {
        path
        for change in summary["file_changes"]
        for path in change.touched_paths
    }
    expected = set(request_child["expected_files"])
    if native_paths != expected:
        missing, extra = sorted(expected - native_paths), sorted(native_paths - expected)
        details = []
        if missing:
            details.append("missing native fileChange paths: " + ", ".join(missing))
        if extra:
            details.append("unexpected native fileChange paths: " + ", ".join(extra))
        raise ProvenanceError(
            f"child {child_id} " + ("; ".join(details) or "has no file changes")
        )
    result = {
        "threadId": child_id,
        "taskDeclaration": request_child["task_declaration"],
        "workspace": summary["workspace"],
        "nativeCwd": summary["cwd"],
        "role": role,
        "configured": {
            "model": model,
            "effort": effort,
            "require_reason": configured["require_reason"],
        },
        "requested": {"model": requested_model, "effort": requested_effort},
        "preDispatch": {
            "taskEvidence": task_line,
            "taskInLegacyPrompt": prompt_task_line if isinstance(prompt, str) else None,
            "reasonRequired": reason_required,
            "reasonEvidence": reason_line,
            "reasonInLegacyPrompt": prompt_reason_line,
        },
        "expectedFiles": sorted(expected),
        "relation": {
            "kind": relation["kind"],
            "events": [
                {
                    "id": event["id"],
                    "sha256": event["sha256"],
                    "kind": event.get("kind", event.get("tool")),
                }
                for event in relation["events"]
            ],
        },
        "nativeEvidence": {
            "completedTurn": last_turn["id"],
            "fileChangeTurns": [record["id"] for record in change_turns],
            "fileChanges": [
                {
                    "id": change.item_id,
                    "turnId": change.turn_id,
                    "sha256": change.sha256,
                    "paths": sorted(change.touched_paths),
                }
                for change in summary["file_changes"]
            ],
        },
    }
    return result, relation


def verify_native(
    repo_root: str | os.PathLike[str],
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    client: Any | None = None,
) -> dict[str, Any]:
    """Return a deterministic receipt after rereading native history and candidate state.

    An injected client exposes a read-only call(method, params) operation.
    Otherwise this initializes Codex app-server and uses only thread read RPCs.
    """
    if os.name != "posix":
        platform_detail = (
            "Windows native verification is unsupported"
            if os.name == "nt"
            else f"native verification is unsupported on {os.name!r} hosts"
        )
        raise ProvenanceError(f"POSIX platforms only; {platform_detail}")
    if not isinstance(request, Mapping) or not isinstance(policy, Mapping):
        raise ProvenanceError("request and policy must be mappings")
    root, root_text, head = _prepare_repository(repo_root)
    common_dir = _repository_common_dir(root)
    parent_id, task, children, roles = _validate_inputs(
        request, policy, root, common_dir
    )
    base = _resolve_commit(root, request["base_commit"])
    owned_client = client is None
    if owned_client:
        executable = shutil.which("codex")
        if executable is None:
            raise ProvenanceError("Codex CLI is unavailable for native app-server history")
        active_client = RpcClient(executable, 10, root)
        try:
            active_client.initialize()
        except Exception:
            active_client.close()
            raise
    else:
        active_client = client
        if not callable(getattr(active_client, "call", None)):
            raise ProvenanceError("injected native client must expose call(method, params)")
    try:
        parent_thread = _metadata(active_client, parent_id)
        parent_summary = _summarize_thread(active_client, parent_thread, root)
        child_threads: dict[str, dict[str, Any]] = {}
        child_summaries: dict[str, dict[str, Any]] = {}
        for child in children:
            child_id = child["thread_id"]
            child_thread = _metadata(active_client, child_id)
            child_threads[child_id] = child_thread
            child_summaries[child_id] = _summarize_thread(
                active_client, child_thread, Path(child["workspace"])
            )
        summaries = [parent_summary, *child_summaries.values()]
        _validate_unique_native_ids(summaries)

        verified_children: dict[str, dict[str, Any]] = {}
        relations: dict[str, dict[str, Any]] = {}
        for child in children:
            child_id = child["thread_id"]
            result, relation = _verify_child(
                child,
                child_summaries[child_id],
                parent_summary,
                roles,
                child["task_declaration"],
            )
            verified_children[child_id] = result
            relations[child_id] = relation
        replay_order = _order_children(children, relations)

        delegated_paths = {
            path for child in children for path in child["expected_files"]
        }
        parent_changes, native_coordinator_state = _coordination_changes(
            parent_summary, root, base
        )
        for path, state in native_coordinator_state.items():
            _validate_coordinator_file(root, base, path, state)
        coordinator_state = _candidate_coordinator_state(
            root, base, _changed_paths(root, base), native_coordinator_state
        )
        coordinator_paths = set(coordinator_state)
        if delegated_paths.intersection(coordinator_paths):
            raise ProvenanceError(
                "coordinator and delegated child events overlap on a candidate path"
            )

        child_state: dict[str, tuple[bytes, int] | None] = {}
        base_cache: dict[str, tuple[bytes, int] | None] = {}
        for child_id in replay_order:
            for change in child_summaries[child_id]["file_changes"]:
                for operation in change.operations:
                    for path in operation.touched_paths:
                        if path not in child_state:
                            child_state[path] = _base_state(root, base, path, base_cache)
                    _apply_op(child_state, operation)
        if set(child_state) != delegated_paths:
            raise ProvenanceError(
                "delegated native path coverage differs from reconstructed candidate paths"
            )
        final_state = {**child_state, **coordinator_state}
        for path, state in final_state.items():
            if state is None:
                continue
            try:
                state[0].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProvenanceError(
                    f"binary or non-UTF-8 candidate content is unsupported: {path}"
                ) from exc
        candidate_files = _validate_candidate(
            root, base, final_state, delegated_paths, coordinator_paths
        )

        command_events = [
            *parent_summary["commands"],
            *(
                event
                for summary in child_summaries.values()
                for event in summary["commands"]
            ),
        ]
        opaque_events = [
            *parent_summary["opaque_tools"],
            *(
                event
                for summary in child_summaries.values()
                for event in summary["opaque_tools"]
            ),
        ]
        payload: dict[str, Any] = {
            "schema": "flow-next/codex-native-provenance/v1",
            "task": task,
            "repository": {
                "root": root_text,
                "commonDir": str(common_dir),
                "head": head,
            },
            "baseCommit": base,
            "parentThreadId": parent_id,
            "parentNativeEvidence": {
                "fileChanges": [
                    {
                        "id": change.item_id,
                        "turnId": change.turn_id,
                        "sha256": change.sha256,
                        "paths": sorted(change.touched_paths),
                    }
                    for change in parent_changes
                ],
                "childActivities": [
                    {
                        "id": event["id"],
                        "childThreadId": event["childThreadId"],
                        "kind": event["kind"],
                        "sha256": event["sha256"],
                    }
                    for event in parent_summary["activities"]
                    if event["childThreadId"] in verified_children
                ],
            },
            "children": [
                {
                    **verified_children[child_id],
                    "finalFiles": [
                        _state_record(path, final_state[path])
                        for path in sorted(
                            verified_children[child_id]["expectedFiles"]
                        )
                    ],
                }
                for child_id in sorted(verified_children)
            ],
            "coordinatorFiles": [
                _state_record(path, coordinator_state[path])
                for path in sorted(coordinator_state)
            ],
            "candidateFiles": candidate_files,
            "coverage": {
                "parentAndChildCommands": sorted(
                    command_events,
                    key=lambda event: (
                        event["threadId"], event["turnId"], event["itemId"]
                    ),
                ),
                "opaqueToolEvents": sorted(
                    opaque_events,
                    key=lambda event: (
                        event["threadId"], event["turnId"], event["itemId"]
                    ),
                ),
                "limitations": [
                    "Native v2 history can omit the original child brief; task association is caller-supplied and not independently established by native history.",
                    "CommandExecution, MCP, and dynamic-tool events are bound by native IDs and hashes only; payloads and effects are not semantically interpreted.",
                    "Matching final state does not rule out identical overwrites, transient writes, or unobservable external effects.",
                    "Native fileChange history is detective evidence and does not prevent shell, MCP, or other writes.",
                ],
            },
        }
        payload["receipt_sha256"] = _digest_json(payload)
        if _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip() != head:
            raise ProvenanceError("HEAD changed during native provenance verification")
        if _validate_candidate(
            root, base, final_state, delegated_paths, coordinator_paths
        ) != candidate_files:
            raise ProvenanceError("candidate changed during native provenance verification")
        return payload
    finally:
        if owned_client:
            active_client.close()


__all__ = ["VerificationError", "RpcClient", "verify_native"]
