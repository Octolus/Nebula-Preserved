"""Create source-bound management evidence without exporting disposable state."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import unicodedata
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import HERE, sha256, write_json
from admin.normalize import TABLE_CLOCKS, PAYLOAD_CLOCKS


def patterns():
    get = ["health", "me", "roles", "capabilities", "stats", "moderation/status", "moderation/events", "moderation/reports", "moderation/news", "users", "operators", "audit", "transactions", "catalog"]
    get += ["users/{account}" + suffix for suffix in ("", "/wallet", "/moderation", "/owned", "/transactions", "/audit", "/purchases")]
    post = ["users/{account}/" + action for action in ("wallet-adjustments", "items", "rename", "ban", "unban", "kick", "mute", "unmute", "staff-label")]
    post += ["moderation/maintenance", "moderation/reports/{report}", "moderation/news", "moderation/news/{news}/archive", "operators/{operator}", "operators/{operator}/player-link"]
    return [("GET", route) for route in get] + [("POST", route) for route in post]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--edge-run", required=True)
    args = parser.parse_args()
    root = HERE / "admin"
    run = (HERE / "runs" / args.run).resolve()
    edge = (HERE / "runs" / args.edge_run).resolve()
    if not all(path.is_relative_to(HERE / "runs") for path in (run, edge)):
        parser.error("run must remain below runs")
    normal = json.loads((run / "summary.json").read_text())
    source_match = all((HERE / row["source"]).is_file() and sha256(HERE / row["source"]) == row["sha256"] for row in normal["harness_sources"])
    extra = json.loads((edge / "summary.json").read_text())
    if normal["candidate_sha256"] != extra["candidate_sha256"] or normal["source_digest"] != extra["source_digest"]:
        parser.error("ordinary and Unicode evidence must use the same candidate and reference")
    cases = json.loads((root / "corpus.json").read_text())
    edge_cases = json.loads((root / "unicode-edge-corpus.json").read_text())
    if normal["corpus_sha256"] != sha256(root / "corpus.json") or extra["corpus_sha256"] != sha256(root / "unicode-edge-corpus.json"):
        parser.error("case corpus changed since run")
    source_manifest = json.loads((HERE / "coverage-manifest.json").read_text())
    source_names = {"backend/management.py", "backend/moderation.py", "backend/public_access.py", "backend/state.py", "backend/shop.py", "backend/resources.py"}
    source_hashes = [row for row in source_manifest["reference_sources"] if row["source"] in source_names]
    route_rows = []
    for method, pattern in patterns():
        regex = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(pattern))
        matching = [case["id"] for case in cases if case["op"] == "admin" and case["method"] == method and re.fullmatch(regex, case["tail"])]
        route_rows.append({"method": method, "route": pattern, "exercised_case_ids": matching,
                           "case_evidence": "EXERCISED" if matching else "NOT_PROVEN", "full_contract_parity": "NOT_PROVEN"})
    gaps = ["News archive route", "Successful direct wardrobe, locomotion and housing admin grants", "Duplicate raw JSON keys, invalid UTF-8/raw JSON and actual HTTP body framing", "Secret/operator file loading, listeners/TLS and header duplication", "Concurrent idempotent commands and database busy/constraint fault injection", "Runtime sync publication failure/retry and client acknowledgement", "Timed ban/mute/news expiry boundaries and maintenance expiry", "Exhaustive Unicode scalar classification and operator-protected policy combinations", "Abrupt process crash durability and original-client acceptance"]
    manifest = {"format_version": 1, "comparison_target": "AUTHORED_PRESERVATION_REFERENCE", "source_digest": normal["source_digest"],
                "source_hashes": source_hashes, "routes": route_rows, "route_count": len(route_rows),
                "get_patterns": sum(m == "GET" for m, _ in patterns()), "post_patterns": sum(m == "POST" for m, _ in patterns()),
                "exercised_route_patterns": sum(bool(row["exercised_case_ids"]) for row in route_rows),
                "normalization": {"base_clock_whitelist": "fixtures/normalization.json", "extra_table_clock_columns": TABLE_CLOCKS,
                    "flat_payload_clock_keys": sorted(PAYLOAD_CLOCKS),
                    "payload_locations": ["command.before/after", "audit/event.before/after", "users.items", "operators.items", "users/{account}", "users/{account}/owned.items", "users/{account}/purchases.items", "reports.items", "news.items", "audit/event/ledger.items", "management_audit.before_json/after_json", "moderation_events.before_json/after_json", "management_requests.response_json.before/after", "moderation_news", "moderation_maintenance"],
                    "uuid_locations": ["command.request_id", "audit/event/ledger.request_id", "management_audit.request_id", "management_wallet_ledger.request_id", "moderation_events.request_id", "moderation_revoked_sessions.request_id", "management_requests.response_json.request_id", "news.news_id", "news event target_id"],
                    "uuid_rule": "32 lowercase hex request IDs correlate to the exact command case; bootstrap IDs correlate to audit ordinal+operator; news UUID must equal the known publishing request UUID. Replayed IDs retain their first correlation.",
                    "invariants": ["UUID syntax and cross-table correlations", "news.date_label equals UTC ISO seconds of created_at", "maintenance end-start duration is exact integer minutes", "durable audit and receipt JSON must be canonical before normalization", "clock zero/null/numeric storage type preserved", "within-probe no-change assertions preserve every raw value"],
                    "forbidden": ["arbitrary UUID removal", "fingerprint normalization", "schema/extra-table removal", "array reordering", "business-value normalization", "unknown clock columns"]},
                "unexercised_contracts": [{"contract": gap, "status": "NOT_PROVEN"} for gap in gaps],
                "original_server_semantics": "NOT_PROVEN", "one_to_one_parity": "NOT_PROVEN"}
    write_json(root / "coverage-manifest.json", manifest)
    counter = Counter(normal["status_counts"]); counter.update(extra["status_counts"])
    evidence = {"format_version": 1, "candidate_binary": {"name": "nebula-preserved-server.exe", "sha256": normal["candidate_sha256"]},
                "reference_source_digest": normal["source_digest"], "result": dict(counter), "ordinary_result": normal["status_counts"], "unicode_edge_result": extra["status_counts"],
                "case_counts": dict(Counter(case["op"] for case in cases + edge_cases)), "raw_no_change_assertions": sum("same_as" in case for case in cases + edge_cases),
                "route_patterns_exercised": manifest["exercised_route_patterns"], "route_patterns_total": 36,
                "typed_table_count": 47, "python_unicode_data_version": unicodedata.unidata_version, "rust_unicode_data_version": "15.0.0",
                "fixture_sha256": normal["fixture_sha256"], "game_fixture_sha256": normal["game_fixture_sha256"],
                "ordinary_summary_sha256": sha256(run / "summary.json"), "unicode_edge_summary_sha256": sha256(edge / "summary.json"),
                "admin_manifest_sha256": sha256(root / "coverage-manifest.json"), "negative_controls": 11,
                "harness_sources": normal["harness_sources"], "harness_matches_current_sources": source_match,
                "one_to_one_parity": "NOT_PROVEN", "original_server_parity": "NOT_PROVEN"}
    write_json(HERE / "admin-verification.json", evidence)
    lines = ["# Management differential supplement", "",
             f"The candidate matched **{counter.get('PASS', 0)}/{sum(counter.values())} exercised cases** against the actual Python Management adapter. Overall parity remains **NOT_PROVEN**.", "",
             ("The recorded run uses the current harness source hashes." if source_match else "Historical run: current exported harness sources have changed. Its recorded source hashes retain this evidence; the portability derivative requires its own complete rerun."), "",
             "All state is disposable. The reviewed fixture supplies two synthetic game accounts and four synthetic management operators; its fixed 32-byte token is public test data, not a secret. Both implementations receive identical init data. No listener, desktop, game, original native runtime or remote service runs.", "",
             f"The corpus reaches {manifest['exercised_route_patterns']}/36 management route patterns (21 GET, 15 POST inventory). A route observation proves its exercised branch only. Complete typed snapshots include every column and value in all 47 tables, including empty tables.", "",
             "Cases cover authentication and role precedence; Origin and forged-role guards; body type, size and content-type rejection; literal search and pagination; wallet debit limits, typed deltas, actor-specific idempotency, replay and conflict; successful companion and bundle-offer grants; rename/social-state persistence; staff labels; report creation/review; mute/unmute; maintenance; news creation/replay; kick/ban/unban with revoked sessions; linked-owner sanction denial; disabled operator persistence and graceful process reopen.", "",
             "The mandatory isolated Unicode regression submits U+1C89 as a staff label. Python Unicode15 categorizes it as unassigned and rejects it without writing state. An initial Rust Unicode16 implementation accepted it and committed data; the final corpus retains this regression and checks the complete raw state after rejection.", "",
             "Normalization is limited to explicitly listed source-proven clock paths and correlated management request/news UUIDs. It checks canonical durable audit/receipt JSON before transforming it; IDs retain cross-table and replay identity. News dates must derive from the exact creation clock, and maintenance duration remains exact. Raw no-change boundaries preserve timestamps and UUIDs. Eleven deliberate comparator mutations pass their rejection controls.", "",
             "## Remaining gaps", ""]
    lines += ["* " + gap + ": **NOT_PROVEN**." for gap in gaps]
    lines += ["", "## Reproduction", "", "```sh", "python -B admin/test_controls.py", "python -B admin/run_admin.py --reference ../../.. --name admin-control --self-control", "python -B admin/run_admin.py --reference ../../.. --name admin-final --candidate ../target/debug/nebula-preserved-server", "python -B admin/run_admin.py --reference ../../.. --name admin-edge-final --candidate ../target/debug/nebula-preserved-server --unicode-version-edge", "```", "",
              "Run from experimental/rust-server/parity; append .exe to the candidate filename on Windows. Python must provide the reference Unicode15 data (Python3.12).",
              "The candidate uses its `probe` subcommand. Each run copies its executable into private disposable scratch before launch, fixing its hash even if another build occurs. Both ordinary and Unicode reports must use the same binary and reference digest.", "",
              "* Candidate SHA256: `" + normal["candidate_sha256"] + "`.", "* Python Unicode data: `" + unicodedata.unidata_version + "`; final Rust pin: `15.0.0`.",
              "* Machine evidence: admin-verification.json and admin/coverage-manifest.json. No run database, stderr, original asset, real account, real credential or personal path is part of this report.", ""]
    (HERE / "admin-parity-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"result": dict(counter), "route_patterns_exercised": manifest["exercised_route_patterns"]}))


if __name__ == "__main__":
    main()
