"""Portable, file-only client for the reviewed NAC1 automation protocol.

This module does not launch a game, inject input, open a socket, or discover a
process.  The caller must supply a session directory belonging to an already
running, independently owned native test session.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable

MAX_RESULT_BYTES = 64 * 1024
MAX_TIMEOUT_MS = 120_000
NONCE_RE = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")

NO_ARGUMENT_ACTIONS = frozenset({
    "query", "background-on", "login.start", "wardrobe.open", "frame.capture",
    "editor.remove_female_hat", "shop.open_clothing",
    "shop.select_test_female_torso", "shop.buy_selected_local_crystals",
    "shop.open", "shop.select_wardrobe_fixture", "shop.select_companion_fixture",
    "shop.select_locomotion_fixture", "shop.buy_selected_crystals", "shop.buy_selected_np",
    "social.friend_request", "social.friend_accept", "social.favorite_on",
    "social.favorite_off", "social.block_on", "social.block_off", "social.silence_on",
    "social.silence_off", "social.invite", "social.invite_accept", "social.talk",
    "social.chat_send", "social.open", "social.show_friends",
    "social.show_space_users", "social.show_silenced", "social.show_blocked",
    "social.select_peer", "social.show_notifications", "chat.show_public",
    "chat.send_public_test", "movement.forward", "movement.reverse", "settings.open",
    "settings.toggle_notification", "settings.toggle_platform",
    "resource.companion.select", "resource.companion.remove",
    "resource.locomotion.select", "resource.locomotion.remove",
    "resource.companion.prepare_select", "resource.companion.prepare_remove",
    "resource.locomotion.prepare_select", "resource.locomotion.prepare_remove",
})
NAMED_ARGUMENT_ACTIONS = frozenset({"editor.load_named", "editor.save_named"})
HOUSING_ACTION = "housing.command"
HOUSING_FIXED = frozenset({
    "open", "organize", "menu", "menu.left", "menu.right", "menu.up", "menu.down",
    "cancel", "place", "save", "move.left", "move.right", "move.up", "move.down",
    "look.left", "look.right", "look.up", "look.down", "raise", "lower",
    "rotate.left", "rotate.right", "personal.menu", "interact",
    "interaction.left", "interaction.right",
})
ACTIONS = NO_ARGUMENT_ACTIONS | NAMED_ARGUMENT_ACTIONS | {HOUSING_ACTION}

MUTATING_ACTIONS = frozenset({
    "editor.remove_female_hat", "editor.save_named", "shop.buy_selected_local_crystals",
    "shop.buy_selected_crystals", "shop.buy_selected_np", "social.friend_request",
    "social.friend_accept", "social.favorite_on", "social.favorite_off", "social.block_on",
    "social.block_off", "social.silence_on", "social.silence_off", "social.invite",
    "social.invite_accept", "social.talk", "social.chat_send", "chat.send_public_test",
    "movement.forward", "movement.reverse", "settings.toggle_notification",
    "settings.toggle_platform", "resource.companion.select", "resource.companion.remove",
    "resource.locomotion.select", "resource.locomotion.remove", HOUSING_ACTION,
})


class ProtocolError(RuntimeError):
    """A command, result, or local session contract is invalid."""


def _has_reparse_point(path: Path) -> bool:
    attrs = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attrs & getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def require_plain_directory(path: Path) -> Path:
    path = path.expanduser().resolve(strict=True)
    if not path.is_dir() or path.is_symlink() or _has_reparse_point(path):
        raise ProtocolError("session must be an existing, direct directory (not a link/reparse point)")
    return path


def _validate_housing(argument: str) -> None:
    if not 1 <= len(argument) <= 64 or any(not 33 <= ord(ch) <= 126 for ch in argument):
        raise ValueError("housing argument must be 1..64 printable ASCII characters without spaces")
    parts = argument.split("|")
    valid = argument in HOUSING_FIXED
    if len(parts) == 2 and parts[0] == "travel":
        valid = bool(IDENTIFIER_RE.fullmatch(parts[1]))
    if len(parts) == 3 and parts[0] in {"activate", "replace", "remove"}:
        valid = bool(IDENTIFIER_RE.fullmatch(parts[1]) and IDENTIFIER_RE.fullmatch(parts[2]))
    if not valid:
        raise ValueError("housing subcommand is not allowlisted")


def encode_command(
    nonce: str,
    sequence: int,
    action: str,
    argument: str | None,
    now_ms: int,
    timeout_ms: int,
) -> bytes:
    if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce):
        raise ValueError("nonce must be exactly 64 lowercase hexadecimal characters")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 1 <= sequence <= 256:
        raise ValueError("sequence must be an integer from 1 through 256")
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms < 0:
        raise ValueError("now_ms must be a non-negative integer")
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1 <= timeout_ms <= MAX_TIMEOUT_MS:
        raise ValueError("timeout_ms must be an integer from 1 through 120000")
    if action not in ACTIONS:
        raise ValueError("action is not allowlisted")
    if action in NO_ARGUMENT_ACTIONS:
        if argument is not None:
            raise ValueError("fixed action takes no argument")
        arguments: list[str] = []
    elif action in NAMED_ARGUMENT_ACTIONS:
        if not isinstance(argument, str) or not IDENTIFIER_RE.fullmatch(argument):
            raise ValueError("named action requires one 1..64 character identifier")
        arguments = [argument]
    else:
        if not isinstance(argument, str):
            raise ValueError("housing.command requires one argument")
        _validate_housing(argument)
        arguments = [argument]
    if action in {"movement.forward", "movement.reverse"}:
        timeout_ms = min(timeout_ms, 3_000)
    lines = ["NAC1", nonce, str(sequence), str(now_ms + timeout_ms), action, *arguments]
    return ("\n".join(lines) + "\n").encode("ascii")


def checked_result(raw: bytes, nonce: str, sequence: int, action: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_RESULT_BYTES:
        raise ProtocolError("result size is outside the accepted range")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("result is not one UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ProtocolError("result must be a JSON object")
    if value.get("nonce") != nonce or value.get("sequence") != sequence or value.get("action") != action:
        raise ProtocolError("result identity does not match the submitted command")
    if value.get("status") not in {"ok", "started", "rejected", "error"}:
        raise ProtocolError("result status is not recognized")
    return value


def read_result(path: Path, nonce: str, sequence: int, action: str) -> dict[str, Any]:
    if path.is_symlink() or _has_reparse_point(path):
        raise ProtocolError("result file must not be a link/reparse point")
    before = path.stat()
    if not 1 <= before.st_size <= MAX_RESULT_BYTES:
        raise ProtocolError("result size is outside the accepted range")
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise ProtocolError("result changed while it was being read")
    return checked_result(raw, nonce, sequence, action)


class Session:
    """Publish NAC1 commands to one already-owned native session directory."""

    def __init__(self, directory: Path, nonce: str, *, clock: Callable[[], float] = time.monotonic):
        self.directory = require_plain_directory(Path(directory))
        if not NONCE_RE.fullmatch(nonce):
            raise ValueError("nonce must be exactly 64 lowercase hexadecimal characters")
        self.nonce = nonce
        self.clock = clock

    def publish(self, sequence: int, action: str, argument: str | None, timeout_ms: int) -> None:
        command = self.directory / "command.txt"
        pending = self.directory / "command.pending"
        claimed = self.directory / "command.claimed"
        result = self.directory / f"result-{sequence}.json"
        if any(path.exists() for path in (command, pending, claimed, result)):
            raise ProtocolError("command/result slot is not empty; refusing to overwrite")
        payload = encode_command(self.nonce, sequence, action, argument, int(self.clock() * 1000), timeout_ms)
        try:
            descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, command)
        except Exception:
            try:
                pending.unlink()
            except FileNotFoundError:
                pass
            raise

    def wait(
        self,
        sequence: int,
        action: str,
        timeout_ms: int,
        *,
        poll_seconds: float = 0.05,
        alive: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        deadline = self.clock() + timeout_ms / 1000.0
        path = self.directory / f"result-{sequence}.json"
        while self.clock() < deadline:
            if path.exists():
                try:
                    return read_result(path, self.nonce, sequence, action)
                except PermissionError as exc:
                    if getattr(exc, "winerror", None) not in {32, 33}:
                        raise
            if alive is not None and not alive():
                raise ProtocolError("independent owner reports that the native process ended")
            time.sleep(poll_seconds)
        raise TimeoutError(f"timed out waiting for result-{sequence}.json")

    def submit(
        self,
        sequence: int,
        action: str,
        argument: str | None = None,
        *,
        timeout_ms: int = 30_000,
        alive: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        self.publish(sequence, action, argument, timeout_ms)
        return self.wait(sequence, action, timeout_ms, alive=alive)


def dotted_get(value: Any, path: str) -> Any:
    current = value
    if not isinstance(path, str) or not path or any(not part for part in path.split(".")):
        raise ProtocolError("assertion path must be a non-empty dotted path")
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ProtocolError(f"result has no value at {path!r}")
        current = current[part]
    return current


def require_values(value: Any, expected: dict[str, Any]) -> None:
    if not isinstance(expected, dict):
        raise ProtocolError("require must be an object of dotted paths to exact values")
    for path, wanted in expected.items():
        actual = dotted_get(value, path)
        if actual != wanted or type(actual) is not type(wanted):
            raise ProtocolError(f"assertion failed at {path!r}: expected {wanted!r}, got {actual!r}")


def plan_actions(steps: Iterable[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            raise ProtocolError("each plan step must be an object")
        if "action" in step:
            actions.append(step["action"])
        elif "poll" in step and isinstance(step["poll"], dict):
            actions.append(step["poll"].get("action"))
        else:
            raise ProtocolError("each plan step must contain action or poll")
    return actions
