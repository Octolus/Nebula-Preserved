"""Bind baseline, configured and optional admin evidence to one executable hash."""
import json
from common import HERE, write_json, sha256


def main():
    baseline = json.loads((HERE / "verification.json").read_text())
    configured = json.loads((HERE / "configured-verification.json").read_text())
    if baseline["candidate_binary"] != configured["candidate_binary"] or baseline["reference_source_digest"] != configured["reference_source_digest"]:
        raise ValueError("Reports must refer to the same candidate and reference")
    report = {"format_version": 1, "candidate_binary": baseline["candidate_binary"],
              "harness_matches_current_sources": baseline.get("harness_matches_current_sources", False) and configured.get("harness_matches_current_sources", False),
              "reference_source_digest": baseline["reference_source_digest"],
              "default_result": baseline["result"], "configured_result": configured["result"],
              "passed_cases": baseline["result"].get("PASS", 0) + configured["result"].get("PASS", 0),
              "exact_http_cases": baseline["http_cases"] + configured["case_counts"]["http"],
              "whole_typed_state_checkpoints": baseline["typed_state_checkpoints"] + configured["case_counts"]["snapshot"],
              "raw_no_change_boundaries": configured["raw_no_change_assertions"],
              "fixture": configured["fixture"],
              "verification_sha256": sha256(HERE / "verification.json"),
              "configured_verification_sha256": sha256(HERE / "configured-verification.json"),
              "one_to_one_parity": "NOT_PROVEN", "original_client_acceptance": "NOT_PROVEN",
              "resource_selection_cas": "NOT_PROVEN", "new_notification_creation": "NOT_PROVEN", "consumable_receipt_issue": "NOT_PROVEN"}
    admin_path = HERE / "admin-verification.json"
    if admin_path.exists():
        admin = json.loads(admin_path.read_text())
        if admin["candidate_binary"]["sha256"] != baseline["candidate_binary"]["sha256"] or admin["reference_source_digest"] != baseline["reference_source_digest"]:
            raise ValueError("Admin report must refer to the same candidate and reference")
        report.update(admin_result=admin["result"], admin_verification_sha256=sha256(admin_path),
                      admin_route_patterns_exercised=admin["route_patterns_exercised"], admin_route_patterns_total=admin["route_patterns_total"],
                      structured_admin_cases=admin["case_counts"]["admin"])
        report["harness_matches_current_sources"] = report["harness_matches_current_sources"] and admin.get("harness_matches_current_sources", False)
        report["passed_cases"] += admin["result"].get("PASS", 0)
        report["exact_http_cases"] += admin["case_counts"].get("http", 0)
        report["whole_typed_state_checkpoints"] += admin["case_counts"]["snapshot"]
        report["raw_no_change_boundaries"] += admin["raw_no_change_assertions"]
    report["evidence_status"] = "CURRENT_RECORDED_HARNESS" if report["harness_matches_current_sources"] else "HISTORICAL_RUN_SOURCES_CHANGED"
    write_json(HERE / "combined-verification.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
