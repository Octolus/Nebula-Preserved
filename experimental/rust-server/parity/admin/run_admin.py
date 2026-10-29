"""Differential actual Management oracle, synthetic state, no listeners."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import urlencode
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import HERE, scratch, sha256, write_json
from run_parity import ProcessProbe, canonical, compare, normalized_state, public_observation
from normalize import Normalizer
from admin.cases import corpus


def run(args):
    admin_root = Path(__file__).resolve().parent
    fixture_path = HERE / "fixtures/configured-mutations-v1.json"
    game_fixture = json.loads(fixture_path.read_text())
    registry = json.loads((HERE / "fixtures/registry.json").read_text())
    if sha256(fixture_path) != registry["fixtures"][0]["sha256"]:
        raise ValueError("IMMUTABLE_GAME_FIXTURE_HASH_MISMATCH")
    admin_fixture_path = admin_root / "fixture.json"
    admin_registry = json.loads((admin_root / "registry.json").read_text())
    if sha256(admin_fixture_path) != admin_registry["sha256"]:
        raise ValueError("IMMUTABLE_ADMIN_FIXTURE_HASH_MISMATCH")
    admin_fixture = json.loads(admin_fixture_path.read_text())
    cases = corpus(args.unicode_version_edge)
    corpus_path = admin_root / ("unicode-edge-corpus.json" if args.unicode_version_edge else "corpus.json")
    write_json(corpus_path, cases)
    whitelist = json.loads((HERE / "fixtures/normalization.json").read_text())
    manifest = json.loads((HERE / "coverage-manifest.json").read_text())
    for entry in manifest["reference_sources"]:
        if sha256(args.reference / entry["source"]) != entry["sha256"]:
            raise ValueError("REFERENCE_HASH_MISMATCH")
    run_root = scratch(HERE / "runs" / args.name)
    if (run_root / "owned-run.json").exists():
        raise ValueError("RUN_DIRECTORY_ALREADY_USED")
    write_json(run_root / "owned-run.json", {"synthetic_disposable_state": True, "listeners": False})
    ref_command = [sys.executable, "-B", str(HERE / "reference_probe.py"), "--reference", str(args.reference)]
    candidate_sha = None
    if not args.self_control:
        pinned_binary = run_root / ("candidate-probe.exe" if sys.platform == "win32" else "candidate-probe")
        shutil.copy2(args.candidate, pinned_binary)
        candidate_sha = sha256(pinned_binary)
    commands = {"reference": ref_command, "candidate": ref_command if args.self_control else [str(pinned_binary), "probe"]}
    probes = {}
    norms = {label: Normalizer(whitelist) for label in commands}
    raw_states = {label: {} for label in commands}
    def initialize(label, fixture):
        probe = ProcessProbe(commands[label], label, run_root, args.timeout)
        init = {"id": "init", "op": "init", "state_dir": str(run_root / label),
                "reference_protocol_dir": str(args.reference / "protocol"), "core_test_profile": None}
        if fixture:
            init["fixture"] = game_fixture
        result = probe.request(init)
        if not result.get("ok"):
            raise ValueError(label.upper() + "_INIT_FAILED")
        result = probe.request({"id": "admin_init", "op": "admin_init", "token": admin_fixture["token"], "operators": admin_fixture["operators"]})
        if not result.get("ok"):
            raise ValueError(label.upper() + "_ADMIN_INIT_FAILED")
        return probe
    rows, observations = [], []
    harness_hashes = [{"source": path.relative_to(HERE).as_posix(), "sha256": sha256(path)} for path in [HERE / "reference_probe.py", HERE / "run_parity.py", HERE / "common.py", HERE / "fixture_support.py", *sorted(admin_root.glob("*.py"))]]
    started = time.monotonic()
    try:
        for label in commands:
            probes[label] = initialize(label, True)
        for case in cases:
            result = {}
            normalized = {}
            problems = {}
            request = {k: v for k, v in case.items() if k not in ("expected_status", "same_as")}
            if case["op"] == "admin":
                request["query"] = urlencode(request.get("query", {}))
            for label in commands:
                if case["op"] == "process_restart":
                    probes[label].close()
                    probes[label] = initialize(label, False)
                    result[label] = {"id": case["id"], "ok": True}
                else:
                    result[label] = probes[label].request(request)
                observed = result[label]
                try:
                    if not observed.get("ok"):
                        raise ValueError("PROBE_FAILED:" + observed.get("error", "unknown"))
                    norms[label].observe(case, observed)
                    if case["op"] == "admin":
                        normalized[label] = {"status": observed["status"], "body": norms[label].body(case, observed["body"])}
                    elif case["op"] == "snapshot":
                        normalized[label] = norms[label].state(observed["state"])
                        raw_states[label][case["id"]] = normalized_state(observed["state"], {"durable_state": []})
                        if case.get("same_as") and canonical(raw_states[label][case["id"]]) != canonical(raw_states[label][case["same_as"]]):
                            raise ValueError("RAW_STATE_CHANGED_AT_IDEMPOTENCE_OR_REOPEN_BOUNDARY")
                except (KeyError, TypeError, ValueError) as exc:
                    problems[label] = str(exc)
            differences = []
            status = "PASS"
            if "reference" in problems:
                status, differences = "REFERENCE_ERROR", [problems["reference"]]
            elif "candidate" in problems:
                status, differences = "FAIL", [problems["candidate"]]
            elif case["op"] in ("admin", "http") and result["reference"]["status"] != case["expected_status"]:
                status, differences = "REFERENCE_ERROR", ["Explicit reference status assertion failed"]
            elif case["op"] == "admin":
                differences = [key for key in ("status", "body") if canonical(normalized["reference"][key]) != canonical(normalized["candidate"][key])]
                if differences:
                    status = "FAIL"
            elif case["op"] == "snapshot":
                lt, rt = normalized["reference"]["tables"], normalized["candidate"]["tables"]
                differences = ["table:" + name for name in sorted(set(lt) | set(rt)) if canonical(lt.get(name)) != canonical(rt.get(name))]
                if differences:
                    status = "FAIL"
            elif case["op"] == "http":
                status, differences = compare(case, result["reference"], result["candidate"], whitelist)
            rows.append({"id": case["id"], "op": case["op"], "status": status, "differences": differences})
            observation = {"id": case["id"], "status": status}
            for label in commands:
                if case["op"] == "snapshot":
                    observation[label] = normalized.get(label, {"problem": problems.get(label)})
                else:
                    observation[label] = normalized.get(label, public_observation(result[label]))
            observations.append(observation)
            if status != "PASS":
                print(canonical(rows[-1]), flush=True)
    finally:
        for probe in probes.values():
            probe.close()
    summary = {"suite": "synthetic-management-v1", "status_counts": dict(Counter(row["status"] for row in rows)), "case_count": len(rows),
               "elapsed_seconds": round(time.monotonic() - started, 3), "self_control": args.self_control,
               "source_digest": manifest["reference_source_digest"], "fixture_sha256": sha256(admin_fixture_path),
               "game_fixture_sha256": sha256(fixture_path), "corpus_sha256": sha256(corpus_path),
               "candidate_sha256": candidate_sha, "harness_sources": harness_hashes, "cases": rows}
    write_json(run_root / "summary.json", summary)
    write_json(run_root / "observations.json", observations)
    print(canonical({k: v for k, v in summary.items() if k != "cases"}))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--self-control", action="store_true")
    parser.add_argument("--unicode-version-edge", action="store_true")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    if not args.self_control and args.candidate is None:
        parser.error("--candidate is required unless --self-control is selected")
    args.reference = args.reference.resolve()
    if args.candidate is not None:
        args.candidate = args.candidate.resolve()
    if not 0 < args.timeout <= 60:
        parser.error("timeout must be in (0,60]")
    summary = run(args)
    raise SystemExit(1 if any(key != "PASS" and count for key, count in summary["status_counts"].items()) else 0)
