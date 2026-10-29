"""Run synthetic JSONL probes; reports never promote unexercised contracts."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid

from common import HERE, environment, scratch, sha256, write_json
from fixture_support import validate_fixture


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


class ProcessProbe:
    def __init__(self, command, label, run_root, timeout):
        self.label, self.timeout = label, timeout
        self.log = (run_root / (label + "-stderr.log")).open("a", encoding="utf-8")
        self.process = subprocess.Popen(command, cwd=HERE, env=environment(run_root / (label + "-temp")),
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                        text=True, encoding="utf-8", bufsize=1)
        self.lines = queue.Queue()
        def read():
            try:
                for line in self.process.stdout:
                    self.lines.put(line)
            finally:
                self.lines.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def request(self, request):
        if self.process.poll() is not None:
            return {"id": request["id"], "ok": False, "error": "PROBE_EXITED"}
        try:
            self.process.stdin.write(canonical(request) + "\n")
            self.process.stdin.flush()
            line = self.lines.get(timeout=self.timeout)
            if line is None:
                return {"id": request["id"], "ok": False, "error": "PROBE_EOF"}
            result = json.loads(line)
            if result.get("id") != request["id"]:
                return {"id": request["id"], "ok": False, "error": "PROBE_ID_MISMATCH"}
            return result
        except queue.Empty:
            self.process.kill()
            return {"id": request["id"], "ok": False, "error": "PROBE_TIMEOUT"}
        except (OSError, ValueError):
            return {"id": request["id"], "ok": False, "error": "PROBE_INVALID_JSONL"}

    def close(self):
        if self.process.poll() is None:
            self.request({"id": "close", "op": "close"})
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.log.close()


def normalized_state(state, whitelist):
    result = json.loads(canonical(state))
    if not isinstance(result, dict) or set(result) != {"tables"} or not isinstance(result["tables"], dict):
        raise ValueError("invalid durable state shape")
    allowed = {(row["table"], row["column"]): row for row in whitelist["durable_state"]}
    for table, value in result["tables"].items():
        if set(value) != {"columns", "rows"}:
            raise ValueError("invalid table state shape")
        column_names = [col["name"] for col in value["columns"]]
        if len(column_names) != len(set(column_names)):
            raise ValueError("duplicate column")
        for row in value["rows"]:
            if set(row) != set(column_names):
                raise ValueError("partial durable row")
            for column, cell in row.items():
                if (table, column) not in allowed or cell is None or cell == 0:
                    continue
                if type(cell) not in (float, int) or not math.isfinite(cell) or cell < 0:
                    raise ValueError("whitelisted clock is not a finite positive number")
                # Preserve the SQLite/JSON numeric storage type in the sentinel.
                row[column] = {"normalized_clock": "real" if type(cell) is float else "integer"}
        value["rows"].sort(key=canonical)
    return result


def public_observation(result):
    # Reports contain generated test identities only; never include probe errors,
    # arbitrary stderr text or caller-supplied paths in exportable JSON.
    keys = ("status", "body", "plaintext", "content_type")
    return {key: result.get(key) for key in keys}


def compare(case, reference, candidate, whitelist):
    if not reference.get("ok"):
        return "REFERENCE_ERROR", ["Reference operation did not produce an observation"]
    if case["op"] == "http":
        if case.get("expected_status") != reference.get("status"):
            return "REFERENCE_ERROR", ["Explicit reference status assertion failed"]
        if "expected_plaintext" in case and case["expected_plaintext"] != reference.get("plaintext"):
            return "REFERENCE_ERROR", ["Explicit reference plaintext assertion failed"]
    if candidate is None:
        return "REFERENCE_ONLY", []
    if not candidate.get("ok"):
        if candidate.get("error") == "NOT_IMPLEMENTED":
            return "NOT_PROVEN", ["Candidate operation not implemented"]
        return "FAIL", ["Candidate probe failed"]
    if case["op"] == "http":
        required = {"status", "body", "plaintext", "content_type"}
        if not required.issubset(candidate):
            return "FAIL", ["Candidate omitted required HTTP observation"]
        mismatches = [key for key in sorted(required) if canonical(reference[key]) != canonical(candidate[key])]
        return ("FAIL", mismatches) if mismatches else ("PASS", [])
    if case["op"] == "snapshot":
        try:
            left = normalized_state(reference["state"], whitelist)
            right = normalized_state(candidate["state"], whitelist)
        except (KeyError, TypeError, ValueError):
            return "FAIL", ["Invalid or partial typed durable snapshot"]
        if canonical(left) == canonical(right):
            return "PASS", []
        names = sorted(set(left["tables"]) | set(right["tables"]))
        return "FAIL", ["table:" + name for name in names if canonical(left["tables"].get(name)) != canonical(right["tables"].get(name))]
    return "PASS", []


def run(args):
    manifest_path = HERE / "coverage-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["reference_sources"]:
        path = args.reference / entry["source"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise ValueError("REFERENCE_HASH_MISMATCH: regenerate and review the coverage manifest")
    fixture_payload, fixture_identity = None, None
    cases_path = HERE / "case-corpus.json"
    normalization_path = HERE / "normalization.json"
    if args.fixture:
        registry = json.loads((HERE / "fixtures/registry.json").read_text())
        entry = next(row for row in registry["fixtures"] if row["fixture_id"] == args.fixture)
        fixture_path = HERE / "fixtures" / entry["file"]
        if fixture_path.parent != HERE / "fixtures" or sha256(fixture_path) != entry["sha256"]:
            raise ValueError("IMMUTABLE_FIXTURE_HASH_MISMATCH")
        fixture_payload = validate_fixture(json.loads(fixture_path.read_text()))
        fixture_identity = {"fixture_id": args.fixture, "sha256": entry["sha256"], "provenance": fixture_payload["provenance"]}
        cases_path = HERE / "fixtures/configured-corpus.json"
        normalization_path = HERE / "fixtures/normalization.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if args.only:
        # Dependencies remain in order: --only selects reported cases while all
        # prior cases still execute. Never skip the login/setup state sequence.
        selected = {row["id"] for row in cases if args.only in row["id"]}
    else:
        selected = {row["id"] for row in cases}
    whitelist = json.loads(normalization_path.read_text(encoding="utf-8"))
    run_root = scratch(HERE / "runs" / (args.name or ("run-" + uuid.uuid4().hex[:12])))
    marker = run_root / "owned-run.json"
    if marker.exists() or (run_root / "reference").exists() or (run_root / "candidate").exists():
        raise ValueError("RUN_DIRECTORY_ALREADY_USED: use a fresh --name")
    write_json(marker, {"format_version": 1, "synthetic_disposable_state": True, "listeners": False})
    reference_command = [sys.executable, "-B", str(HERE / "reference_probe.py"), "--reference", str(args.reference)]
    candidate_command = [args.candidate, *args.candidate_arg] if args.candidate else None
    reference = ProcessProbe(reference_command, "reference", run_root, args.timeout)
    candidate = ProcessProbe(candidate_command, "candidate", run_root, args.timeout) if candidate_command else None
    candidate_path = Path(shutil.which(args.candidate) or args.candidate) if args.candidate else None
    candidate_identity = {"name": candidate_path.name, "sha256": sha256(candidate_path)} if candidate_path and candidate_path.is_file() else None
    rows, observations = [], []
    reference_snapshots = {}
    reference_raw_snapshots, candidate_raw_snapshots = {}, {}
    started = time.monotonic()
    try:
        for probe in [reference] + ([candidate] if candidate else []):
            initial = {"id": "init", "op": "init", "state_dir": str(run_root / probe.label),
                       "reference_protocol_dir": str(args.reference / "protocol"), "core_test_profile": None}
            if fixture_payload:
                initial["fixture"] = fixture_payload
            result = probe.request(initial)
            if not result.get("ok"):
                raise ValueError(probe.label.upper() + "_INIT_FAILED")
        for case in cases:
            request = {key: value for key, value in case.items() if key not in {"category", "expected_status", "expected_plaintext", "reference_same_state_as"}}
            if case["op"] == "process_restart":
                reference.close()
                reference = ProcessProbe(reference_command, "reference", run_root, args.timeout)
                ref = reference.request({"id": case["id"], "op": "init", "state_dir": str(run_root / "reference"),
                                         "reference_protocol_dir": str(args.reference / "protocol"), "core_test_profile": None})
                if candidate:
                    candidate.close()
                    candidate = ProcessProbe(candidate_command, "candidate", run_root, args.timeout)
                    cand = candidate.request({"id": case["id"], "op": "init", "state_dir": str(run_root / "candidate"),
                                               "reference_protocol_dir": str(args.reference / "protocol"), "core_test_profile": None})
                else:
                    cand = None
            else:
                ref = reference.request(request)
                cand = candidate.request(request) if candidate else None
            status, differences = compare(case, ref, cand, whitelist)
            extra = []
            if case["op"] == "snapshot" and ref.get("ok"):
                try:
                    normalized = normalized_state(ref["state"], whitelist)
                    reference_snapshots[case["id"]] = normalized
                    reference_raw_snapshots[case["id"]] = normalized_state(ref["state"], {"durable_state": []})
                    if cand and cand.get("ok"):
                        candidate_raw_snapshots[case["id"]] = normalized_state(cand["state"], {"durable_state": []})
                    if case["id"] == "state-after-restart" and canonical(normalized) != canonical(reference_snapshots["state-before-restart"]):
                        status, differences = "REFERENCE_ERROR", ["Reference typed durable state changed on reopen"]
                    if case["id"] == "state-after-process-restart" and canonical(normalized) != canonical(reference_snapshots["state-after-restart"]):
                        status, differences = "REFERENCE_ERROR", ["Reference typed durable state changed on process reopen"]
                    if case.get("reference_same_state_as") and canonical(normalized) != canonical(reference_snapshots[case["reference_same_state_as"]]):
                        status, differences = "REFERENCE_ERROR", ["Reference atomicity/idempotence state assertion failed"]
                    if case.get("reference_same_state_as"):
                        prior = case["reference_same_state_as"]
                        if canonical(reference_raw_snapshots[case["id"]]) != canonical(reference_raw_snapshots[prior]):
                            status, differences = "REFERENCE_ERROR", ["Reference raw durable state changed across asserted atomicity/idempotence boundary"]
                        elif cand and cand.get("ok") and prior in candidate_raw_snapshots and canonical(candidate_raw_snapshots[case["id"]]) != canonical(candidate_raw_snapshots[prior]):
                            status, differences = "FAIL", ["Candidate raw durable state changed across asserted atomicity/idempotence boundary"]
                    extra = ["reference_state_sha256=" + hashlib.sha256(canonical(normalized).encode()).hexdigest(),
                             "reference_table_count=" + str(len(normalized["tables"]))]
                except (KeyError, TypeError, ValueError):
                    status, differences = "REFERENCE_ERROR", ["Reference snapshot normalization invalid"]
            if case["id"] not in selected:
                continue
            row = {"id": case["id"], "op": case["op"], "category": case["category"], "status": status,
                   "differences": differences, "notes": extra}
            if "route" in case:
                row["route"] = case["route"]
            rows.append(row)
            if case["op"] == "http":
                observations.append({"id": case["id"], "reference": public_observation(ref),
                                     "candidate": public_observation(cand) if cand else None})
    finally:
        reference.close()
        if candidate:
            candidate.close()
    counts = dict(Counter(row["status"] for row in rows))
    by_route = []
    for route in manifest["http_routes"]:
        matched = [row for row in rows if row.get("route") == route["route"]]
        by_route.append({"id": route["id"], "parity_status": "NOT_PROVEN",
                         "case_counts": dict(Counter(row["status"] for row in matched)),
                         "happy_cases_passed": sum(row["status"] == "PASS" and row["category"] == "happy" for row in matched),
                         "reason": "Case-level evidence only; required dimensions and original-client acceptance remain incomplete"})
    summary = {"format_version": 1, "comparison_target": "AUTHORED_PRESERVATION_REFERENCE",
               "reference_source_digest": manifest["reference_source_digest"],
               "manifest_sha256": sha256(manifest_path), "normalization_sha256": sha256(normalization_path),
               "case_corpus_sha256": sha256(cases_path), "fixture": fixture_identity,
               "candidate_binary": candidate_identity,
               "harness_sources": [{"source": path.name, "sha256": sha256(path)} for path in sorted(HERE.glob("*.py"))],
               "candidate_supplied": bool(candidate), "elapsed_seconds": round(time.monotonic() - started, 3),
               "counts": counts, "cases": rows, "route_coverage": by_route,
               "unexercised_contracts": {key: [{"id": row["id"], "status": "NOT_PROVEN"} for row in manifest[key]]
                                        for key in ["mirror_inbound", "mirror_commands", "application_opcodes", "behavior_requirements"]},
               "original_server_parity": "NOT_PROVEN", "one_to_one_parity": "NOT_PROVEN",
               "limits": ["No game, Unity scene server, original native runtime, remote endpoint or listener was run",
                          "Store reopen and graceful process reopen are tested; crash recovery, concurrent requests and wire socket behavior are not",
                          "Malformed framing across every route does not establish valid branch behavior",
                          ("Configured gathering, fresh part0 staging, part1-before-part0 concurrent waiting, notification creation, consumable issuance UUIDs and resource selection IPC are not tested" if fixture_payload else "No full housing commit, configured shop/reward/gathering success, grants or resource selection IPC tested"),
                          "Private default backend mode only; public credentials, TLS and management remain untested"]}
    write_json(run_root / "summary.json", summary)
    write_json(run_root / "observations.json", observations)
    print(canonical({"report": (run_root / "summary.json").relative_to(HERE).as_posix(), "counts": counts,
                     "one_to_one_parity": "NOT_PROVEN"}))
    return 1 if counts.get("FAIL", 0) or counts.get("REFERENCE_ERROR", 0) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", help="JSONL probe executable")
    parser.add_argument("--candidate-arg", action="append", default=[])
    parser.add_argument("--fixture", choices=["configured-mutations-v1"], help="audited immutable synthetic state; uses separate configured corpus")
    parser.add_argument("--name", help="new relative run directory name")
    parser.add_argument("--only", help="report matching case IDs; retain execution dependencies")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    args.reference = args.reference.resolve()
    if args.timeout <= 0 or args.timeout > 60:
        parser.error("timeout must be in (0,60]")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
