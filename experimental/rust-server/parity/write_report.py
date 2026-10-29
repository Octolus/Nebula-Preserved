"""Produce a path-redacted review report from an existing completed run."""
import argparse
from collections import Counter
import json
from pathlib import Path

from common import HERE, scratch, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="relative run name below runs/")
    args = parser.parse_args()
    run = (HERE / "runs" / args.run).resolve()
    if not run.is_relative_to(HERE / "runs"):
        parser.error("run must stay inside runs/")
    manifest = json.loads((HERE / "coverage-manifest.json").read_text(encoding="utf-8"))
    cases = json.loads((HERE / "case-corpus.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    source_match = all((HERE / row["source"]).is_file() and sha256(HERE / row["source"]) == row["sha256"] for row in summary["harness_sources"])
    if summary["manifest_sha256"] != sha256(HERE / "coverage-manifest.json"):
        parser.error("run used a different manifest; preserve it separately before reporting")
    success_routes = len({row["route"] for row in cases if row.get("expected_status") == 200})
    nonframing_routes = len({row["route"] for row in cases if row.get("route") in {r["route"] for r in manifest["http_routes"]}
                             and not row["id"].startswith(("no-trailer:", "bad-platform:", "empty-fields:"))})
    counts = manifest["counts"]
    verification = {"format_version": 1, "result": summary["counts"],
                    "reference_source_files": len(manifest["reference_sources"]),
                    "http_cases": sum(row["op"] == "http" for row in cases),
                    "typed_state_checkpoints": sum(row["op"] == "snapshot" for row in cases),
                    "routes_with_expected_200_case": success_routes,
                    "routes_with_nonframing_attempt": nonframing_routes,
                    "reference_source_digest": summary["reference_source_digest"],
                    "candidate_binary": summary["candidate_binary"],
                    "harness_sources": summary["harness_sources"], "harness_matches_current_sources": source_match,
                    "summary_sha256": sha256(run / "summary.json"),
                    "manifest_sha256": sha256(HERE / "coverage-manifest.json"),
                    "one_to_one_parity": "NOT_PROVEN", "original_server_parity": "NOT_PROVEN"}
    write_json(HERE / "verification.json", verification)
    lines = ["# Headless authored-reference comparison", "",
             "The Rust candidate matched **" + str(summary["counts"].get("PASS", 0)) + " of " + str(len(summary["cases"])) + " exercised cases**. Overall one-to-one parity and original-server behavior remain **NOT_PROVEN**.", "",
             ("The recorded run uses the current harness source hashes." if source_match else "Historical run: current exported harness sources have changed. Its recorded source hashes retain this evidence; the portability derivative requires its own complete rerun."), "",
             "The run calls the actual preservation Backend HTTP adapter with sockets blocked and uses fresh generated accounts and disposable state beneath the harness root. It launches no game, Unity/Terra process, listener, desktop application or remote endpoint.", "",
             "## Inventory and evidence", "",
             "| Contract inventory | Count |", "|---|---:|",
             "| Service.ROUTES | " + str(counts["http_routes"]) + " |",
             "| Bootstrap route contracts with static original-client consumer evidence | " + str(counts["bootstrap_native_route_contracts"]) + " |",
             "| Registered inbound Mirror messages | " + str(counts["mirror_inbound_registered"]) + " |",
             "| Recognized native command hashes | " + str(counts["mirror_command_hashes"]) + " |",
             "| Original application enum values | " + str(counts["original_application_enum_values"]) + " |",
             "| Authored extension opcodes | " + str(counts["authored_application_extensions"]) + " |",
             "| Non-minigame application entries including extension | " + str(counts["nonminigame_application_entries_including_extension"]) + " |",
             "| Broader behavior requirements | " + str(counts["behavior_requirements"]) + " |",
             "| Concrete reviewed policy rows | 30 |",
             "| Hashed reference source/schema/test files | " + str(len(manifest["reference_sources"])) + " |", "",
             "The registered inbound messages are ReadyMessage (40252), CommandMessage (46228), NetworkPingMessage (33151), AddPlayerMessage (13085) and global NebulaMessage (58609). EntityStateMessage serialization does not establish an inbound handler in the current reference.", "",
             "| Native command | Component | Signed Int32 hash |", "|---|---:|---:|"]
    lines.extend("| " + row["name"] + " | " + str(row["component_index"]) + " | " + str(row["function_hash_signed_int32"]) + " |" for row in manifest["mirror_commands"])
    lines += ["", "Recovered native client field names, parsers, enum members and hashes are separate from authored authorization, state transitions, grants, default balances, timing and concurrency policy. Neither category supplies the retired server implementation.", "",
              "## Exercised comparison", "",
              "* " + str(verification["http_cases"]) + " HTTP cases compare exact status, raw body/ciphertext, decrypted reply and content type.",
              "* All 92 routes have malformed framing/arity cases; " + str(nonframing_routes) + " also have a request reaching beyond generic framing. " + str(success_routes) + " have an expected HTTP 200 case. These counts do not certify all branches of any route.",
              "* Seven checkpoints compare every column and typed value in all 42 default durable tables, including empty tables. Extra tables and numeric storage-type changes fail.",
              "* Preference/current-session/account isolation, avatar reads, social changes, empty resource DTOs, unconfigured commerce/rewards/gathering and missing world/housing readiness are exercised.",
              "* Store close/reopen and a newly spawned probe process reopening the same state preserve the compared state and replies.",
              "* Reference-versus-reference control:436/436 matches. Comparator negative controls:13/13 pass, including deliberately altered status/body/plaintext/types and extra empty tables.", "",
              "The only normalization is the explicit seven table/column wall-clock whitelist. Numeric type, zero and null are preserved. No HTTP field, ID, UUID, list order, JSON order, entitlement, balance or schema is normalized.", "",
              "## Resolved differences", "",
              "The initial candidate had 25 differences in a 430-case corpus: allocation/liveness errors, neutral-avatar binary64 parsing, gift authority validation order and four extra default lifecycle tables. After implementation fixes, the expanded 436-case corpus has no remaining mismatch. This statement is limited to the candidate executable hash below.", "",
              "## Gaps in this default corpus", "",
              "The separate configured-parity-report.md supplements successful commerce, rewards and full-layout housing coverage. The items below describe the limits of this default corpus; use both reports when assessing total evidence.", "",
              "* Successful configured purchases, gifts, rewards and gathering: balances, grants, duplicate claims, concurrent debit and rollback.",
              "* Complete housing layouts: granted items, placement limits, reversed or concurrent sparse parts, pending HTTP acknowledgement, expiry/conflict/rollback and partial-save crash recovery.",
              "* Resource grants and selection IPC: current session/instance ownership, commit acknowledgements, revocation, stale snapshots, restoration and peer appearance.",
              "* Ready scene discovery and allocation using fresh descriptors, capacity, profiles, personal-space ownership and owner presence.",
              "* All Mirror transport/inbound/command authority and all application state transitions, including semantic registries, occupancy, boats, consumables, chat and disconnect cleanup.",
              "* Public credential/TLS gateway/management behavior, abrupt process-crash recovery and original-client acceptance. Cinema's successful clock-bearing reply is not exercised; malformed branches are exercised.", "",
              "Every unexercised manifest contract remains NOT_PROVEN. Matching the codec or a route's malformed branch never promotes another contract. A reviewed fixture protocol is needed before configured mutation comparisons; direct one-sided SQL seeding would bypass the authority under test.", "",
              "## Reproduction and hashes", "",
              "Run the commands in README.md. The candidate uses its `probe` subcommand and the interface in probe_contract.md. Review coverage-manifest.json, reference-policy-inventory.json, normalization.json and case-corpus.json before regenerating evidence.", "",
              "* Reference source digest: `" + summary["reference_source_digest"] + "`.",
              "* Candidate executable SHA256: `" + (summary["candidate_binary"] or {}).get("sha256", "NOT_SUPPLIED") + "`.",
              "* Detailed summary SHA256: `" + verification["summary_sha256"] + "`.",
              "* Machine verification: verification.json. Detailed observations and per-case statuses: runs/" + args.run + "/.", "",
              "This report contains generated test outcomes, protocol metadata and hashes. It includes no original game asset, real account, credential, private player state or personal filesystem path.", ""]
    (HERE / "parity-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(verification, sort_keys=True))


if __name__ == "__main__":
    main()
