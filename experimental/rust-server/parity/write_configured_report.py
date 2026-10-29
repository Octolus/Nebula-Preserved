"""Redacted evidence supplement; reads completed runs without touching state."""
import argparse
from collections import Counter
import json
from pathlib import Path
from common import HERE, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    root = (HERE / "runs" / args.run).resolve()
    if not root.is_relative_to(HERE / "runs"):
        parser.error("run must remain under runs")
    summary = json.loads((root / "summary.json").read_text())
    source_match = all((HERE / row["source"]).is_file() and sha256(HERE / row["source"]) == row["sha256"] for row in summary["harness_sources"])
    if not summary.get("fixture"):
        parser.error("run must use the reviewed configured fixture")
    cases = json.loads((HERE / "fixtures/configured-corpus.json").read_text())
    guards = sum("reference_same_state_as" in row for row in cases)
    evidence = {"format_version": 1, "fixture": summary["fixture"], "candidate_binary": summary["candidate_binary"],
                "harness_sources": summary["harness_sources"], "harness_matches_current_sources": source_match,
                "reference_source_digest": summary["reference_source_digest"], "result": summary["counts"],
                "case_counts": dict(Counter(row["op"] for row in cases)), "raw_no_change_assertions": guards,
                "summary_sha256": sha256(root / "summary.json"), "configured_corpus_sha256": sha256(HERE / "fixtures/configured-corpus.json"),
                "one_to_one_parity": "NOT_PROVEN", "resource_selection_cas": "NOT_PROVEN", "consumable_receipt_issue": "NOT_PROVEN"}
    write_json(HERE / "configured-verification.json", evidence)
    passed = summary["counts"].get("PASS", 0)
    lines = ["# Configured mutation differential supplement", "",
             f"The configured candidate comparison matched **{passed}/{len(cases)} cases**. This supplements the separate default 436-case corpus; overall one-to-one parity remains **NOT_PROVEN**.", "",
             ("The recorded run uses the current harness source hashes." if source_match else "Historical run: current exported harness sources have changed. Its recorded source hashes retain this evidence; the portability derivative requires its own complete rerun."), "",
             "The immutable fixture seeds exactly two synthetic accounts and 30 rows in eleven whitelisted tables into fresh disposable state. Both implementations receive the same JSON object through init. Names and columns come from the audited fixture schema; no caller SQL, code, credential, secret table, file publication or listener is accepted.", "",
             "## Exercised successful state changes", "",
             "* A server-priced companion purchase, duplicate purchase and ownership query.",
             "* A two-child bundle purchase, duplicate bundle and a deliberately invalid second-child failure after debit and the first grant. Whole typed state must match its pre-request state after rollback.",
             "* A gift to an actual local friend, duplicate gift, wrong-price rejection and block-based denial. Wallet and recipient grants are compared.",
             "* Generic companion reward, duplicate claim, locomotion reward and a coffee reward. Coffee units and prop-use policy are durable; another account's coffee balance stays empty.",
             "* Cinema capability grant and duplicate claim.",
             "* A 101-item housing layout committed by the real HTTP part1 path after a duplicate original part0. A visitor write is denied. Partial staging and complete layouts survive fresh probe processes.",
             "* Resource and purchase DTOs expose the resulting account-specific grants.", "",
             f"The corpus contains {sum(row['op']=='http' for row in cases)} exact HTTP comparisons, {sum(row['op']=='snapshot' for row in cases)} complete 42-table typed checkpoints, two full process reopens and {guards} explicit no-change boundaries. Every no-change boundary compares each probe's raw durable state, including timestamps, so clock normalization cannot conceal an idempotence or rollback write.", "",
             "## Deliberate fixture boundaries", "",
             "One original housing counterpart is pre-staged with a fixed batch ID. This tests the real duplicate-part0 and part1 promotion paths, authority and durability; it does not prove fresh stage creation, concurrent part1 waiting, timeout/conflict handling or abrupt-crash recovery.", "",
             "Exact notification dedupe rows are pre-staged. Grant/gift success exercises existing-notice validation and idempotence; new notification UUID creation remains unproven. Successful consumable receipt issuance and resource-selection CAS/IPC remain NOT_PROVEN. Configured gathering and the remaining Mirror/application/world contracts remain NOT_PROVEN.", "",
             "The default seven-field clock whitelist is unchanged. Configured mode adds seven source-proven clock columns in its separate whitelist. It normalizes no HTTP value or UUID and keeps every table, identifier, entitlement, balance and numeric type observable.", "",
             "## Reproduction and evidence", "",
             "Use the configured command in README.md and inspect fixtures/schema.json, fixtures/registry.json, fixtures/configured-mutations-v1.json and fixtures/configured-corpus.json. The deliberate invalid rollback child is synthetic fault data, not a supported catalog item.", "",
             "* Fixture SHA256: `" + summary["fixture"]["sha256"] + "`.",
             "* Candidate executable SHA256: `" + summary["candidate_binary"]["sha256"] + "`.",
             "* Detailed summary SHA256: `" + evidence["summary_sha256"] + "`.",
             "* Machine evidence: configured-verification.json; detailed observations and statuses are in runs/" + args.run + "/.", "",
             "Reference-versus-reference configured control: 76/76 matches. Comparator and fixture validation controls are in test_harness.py. No game, native scene server, desktop application, listener or remote endpoint was run. This supplement contains no real account, credential, original asset or personal filesystem path.", ""]
    (HERE / "configured-parity-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
