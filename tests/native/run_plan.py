#!/usr/bin/env python3
"""Run a declarative NAC1 plan against an already-running native session."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from nac1 import (
    ACTIONS,
    MUTATING_ACTIONS,
    ProtocolError,
    Session,
    plan_actions,
    require_values,
)


def load_plan(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("format_version") != 1:
        raise ProtocolError("plan must be a format_version 1 JSON object")
    if not isinstance(value.get("name"), str) or not value["name"]:
        raise ProtocolError("plan requires a non-empty name")
    if type(value.get("mutating")) is not bool:
        raise ProtocolError("plan requires an explicit boolean mutating field")
    if not isinstance(value.get("steps"), list) or not value["steps"]:
        raise ProtocolError("plan requires at least one step")
    actions = plan_actions(value["steps"])
    if any(action not in ACTIONS for action in actions):
        raise ProtocolError("plan contains an action not supported by this harness")
    inferred = any(action in MUTATING_ACTIONS for action in actions)
    if inferred and not value["mutating"]:
        raise ProtocolError("plan uses a mutating action but declares mutating=false")
    return value


def _expected_statuses(step: dict[str, Any]) -> list[str]:
    statuses = step.get("expect_status", ["ok", "started"])
    if not isinstance(statuses, list) or not statuses or any(
        status not in {"ok", "started", "rejected", "error"} for status in statuses
    ):
        raise ProtocolError("expect_status must be a non-empty list of result statuses")
    return statuses


def _run_action(session: Session, sequence: int, step: dict[str, Any]) -> dict[str, Any]:
    action = step.get("action")
    argument = step.get("argument")
    timeout_ms = step.get("timeout_ms", 30_000)
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
        raise ProtocolError("timeout_ms must be an integer")
    result = session.submit(sequence, action, argument, timeout_ms=timeout_ms)
    if result["status"] not in _expected_statuses(step):
        raise ProtocolError(f"{action} returned unexpected status {result['status']!r}")
    require_values(result, step.get("require", {}))
    return result


def execute_plan(session: Session, plan: dict[str, Any], start_sequence: int) -> list[dict[str, Any]]:
    sequence = start_sequence
    records: list[dict[str, Any]] = []
    for raw_step in plan["steps"]:
        if "action" in raw_step:
            result = _run_action(session, sequence, raw_step)
            records.append({"sequence": sequence, "kind": "action", "result": result})
            sequence += 1
            continue
        poll = raw_step["poll"]
        if not isinstance(poll, dict) or poll.get("action") != "query":
            raise ProtocolError("poll steps may issue only the read-only query action")
        max_seconds = poll.get("max_seconds", 10)
        interval_ms = poll.get("interval_ms", 100)
        if not isinstance(max_seconds, (int, float)) or isinstance(max_seconds, bool) or not 0 < max_seconds <= 120:
            raise ProtocolError("poll max_seconds must be in (0, 120]")
        if not isinstance(interval_ms, int) or isinstance(interval_ms, bool) or not 10 <= interval_ms <= 5_000:
            raise ProtocolError("poll interval_ms must be in [10, 5000]")
        deadline = time.monotonic() + max_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            result = _run_action(session, sequence, {
                "action": "query",
                "timeout_ms": poll.get("timeout_ms", 10_000),
                "expect_status": poll.get("expect_status", ["ok"]),
            })
            records.append({"sequence": sequence, "kind": "poll", "result": result})
            sequence += 1
            try:
                require_values(result, poll.get("until", {}))
                last_error = None
                break
            except ProtocolError as exc:
                last_error = exc
                time.sleep(interval_ms / 1000.0)
        if last_error is not None:
            raise TimeoutError(f"poll condition was not reached: {last_error}")
    return records


def _write_new_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    pending = path.with_name(path.name + ".pending")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    except Exception:
        try:
            pending.unlink()
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--start-sequence", type=int, default=1)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-mutation", action="store_true")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    if plan["mutating"] and not args.allow_mutation:
        raise ProtocolError("mutating plan requires the explicit --allow-mutation flag")
    records = execute_plan(Session(args.session, args.nonce), plan, args.start_sequence)
    _write_new_json(args.output, {
        "format_version": 1,
        "plan": plan["name"],
        "mutating": plan["mutating"],
        "records": records,
        "note": "started means callback dispatch only; see docs/TESTING.md",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
