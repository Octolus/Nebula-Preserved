#!/usr/bin/env python3
"""Generate the source-vs-native rewards/cinema/liveness second-pass ledger.

Static only: this reads retained pseudocode, metadata and Python source.  It
does not import the backend, open sockets, start a listener, or run the game.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import hashlib
import json
from pathlib import Path


ROUTES = (
    "CheckOwnGenericReward", "GenericReward", "RewardClothServlet",
    "RewardConsumeServlet", "SKLPromoServlet", "SKLPromoTriggerServlet",
    "checkRewardAvailableServlet", "CinemaInteractionNPServlet",
    "CheckIfSpaceStillExistServlet",
)
REWARD_TYPES = (
    "Halloween", "ArcheryBow", "ArcheryCarcaj", "Chess", "CastleSword",
    "PatricksDay2018", "Cube", "CampSilverLake0", "CampSilverLake1",
    "CampSilverLake2", "CampSilverLake3", "GhostWolf",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(root: Path, relative: str) -> dict:
    path = root / relative
    return {"path": relative.replace("\\", "/"), "sha256": sha256(path)}


def build(root: Path) -> dict:
    backend_path = root / "results/backend/rewards.py"
    backend = backend_path.read_text(encoding="utf-8")
    legacy_path = root / "results/protocol/http-legacy-contracts.json"
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    by_route = {item["route"]: item for item in legacy["routes"]}
    missing = sorted(set(ROUTES[:-1]) - set(by_route))
    if missing:
        raise SystemExit("legacy contract routes missing: " + ", ".join(missing))

    # Guard the implementation assumptions used by this review.  A changed
    # backend requires re-review rather than silently replaying stale findings.
    checks = {
        "cloth trigger is exactly native0": 'if trigger_key != "0":' in backend,
        "cloth target is wardrobe": 'route == "RewardClothServlet" and grant_kind != "wardrobe"' in backend,
        "reward availability uses closed enum": 'trigger_key not in REWARD_TYPES' in backend,
        "SKL uses shipped promo catalog": 'sprite_id not in self._skl_promo(trigger_key)' in backend,
        "numeric parser requires canonical Int32 text": 'value != str(result)' in backend,
        "cinema is bounded to enum 0..1": 'integer(trigger_key, "cinema interaction", 0, 1)' in backend,
        "liveness matches instance and world": 'self.instances.ready(psidglobal=allocation[1], instance_id=instance_id)' in backend,
        "session platform is locally enforced": 'profile["platform"] != request.platform' in backend,
    }
    if not all(checks.values()):
        raise SystemExit("implementation changed; failed assumptions: " +
                         ", ".join(k for k, ok in checks.items() if not ok))

    reviews = []
    for route in ROUTES[:-1]:
        item = by_route[route]
        reviews.append({
            "route": route,
            "request_fields": item["request_fields"],
            "response_fields": item["response_fields"],
            "minimum_success_fields": item["minimum_success_fields"],
            "wire_shape_verdict": "matches_current_dispatch",
            "original_server_policy": "unknown",
        })
    reviews.append({
        "route": "CheckIfSpaceStillExistServlet",
        "request_fields": ["SessionGUID", "PS4ID", "SpaceParams.id_instance"],
        "response_fields": [
            {"index": 0, "type": "string", "rule": "exact true enables bool parse"},
            {"index": 1, "type": "Boolean.Parse", "rule": "true loads current scene locally; false calls LoadSpace"},
        ],
        "minimum_success_fields": 2,
        "wire_shape_verdict": "matches_current_dispatch",
        "original_server_policy": "unknown; current allocation/fresh-ready rule is compatible local policy",
    })

    source_paths = [
        "results/tools/rewards_second_pass.py",
        "results/tools/extract_skl_promo_assets.py",
        "results/backend/rewards.py",
        "results/protocol/skl-promo-catalog.json",
        "results/protocol/http-legacy-contracts.json",
        "work/decompiled/dump.cs",
        "work/evidence/ghidra/functions/3ee650.c",
        "work/evidence/ghidra/functions/3ffd70.c",
        "work/evidence/ghidra/functions/4161b0.c",
        "work/evidence/ghidra/functions/5bee40.c",
        "work/evidence/ghidra/functions/5bef90.c",
        "work/evidence/ghidra/functions/5bed10.c",
        "work/evidence/ghidra/functions/44e200.c",
        "work/evidence/ghidra/functions/44e370.c",
        "work/evidence/ghidra/functions/44e5f0.c",
        "work/evidence/ghidra/functions/44e7a0.c",
        "work/evidence/ghidra/functions/44e800.c",
        "work/evidence/ghidra/functions/414e40.c",
        "work/evidence/ghidra/functions/46e360.c",
        "work/evidence/ghidra/functions/466380.c",
        "work/evidence/ghidra/functions/4663f0.c",
        "work/evidence/ghidra/functions/4663e0.c",
        "work/evidence/ghidra/functions/4665f0.c",
        "work/evidence/mitm-space-callcontext-native.json",
    ]
    return {
        "format_version": 1,
        "scope": "static second-pass source-vs-native audit; no runtime or connection evidence",
        "implementation_sha256": sha256(backend_path),
        "wire_summary": {"reviewed_routes": 9, "matching_shapes": 9, "shape_mismatches": 0},
        "closed_enums": {
            "Utils.RewardType": list(REWARD_TYPES),
            "CinemaBoxOfficeTrigger.TypeCinemaBoxOffice": {"0": "Ticket", "1": "PopCorn"},
        },
        "findings": [
            {
                "id": "RSP-001", "severity": "high", "route": "RewardClothServlet",
                "status": "resolved",
                "native_fact": "Send_rewardBeachTShirt writes request reward=0 unconditionally; callback UI success is additionally gated on request reward==0.",
                "implementation_fact": "configuration and stored-definition readback now require canonical trigger0 and a wardrobe target.",
                "required_change": "implemented",
            },
            {
                "id": "RSP-002", "severity": "medium", "route": "checkRewardAvailableServlet",
                "status": "resolved",
                "native_fact": "request uses Utils.RewardType.ToString over a closed 12-name enum.",
                "implementation_fact": "configuration and dispatch now whitelist the exact 12 enum names; enabling each remains administrator policy.",
                "required_change": "implemented",
            },
            {
                "id": "RSP-003", "severity": "high", "route": "SKLPromoServlet",
                "status": "resolved",
                "native_fact": "response[3] is Int32.Parse; SetSprites indexes aSprites[2*id] and aSprites[2*id+1], throwing when either index is outside the serialized array.",
                "implementation_fact": "UnityPy extraction recovered promo IDs0..5 and six 12-entry arrays; configuration/readback validate both promo ID and sprite-pair index0..5 against that catalog.",
                "required_change": "implemented with protocol/skl-promo-catalog.json",
            },
            {
                "id": "RSP-004", "severity": "medium", "route": "CinemaInteractionNPServlet",
                "status": "authored_policy_not_native_parity",
                "native_fact": "success Ticket sets an in-memory ticket flag and popup; success PopCorn sets a flag, instantiates a ConsumablePopCorn and initializes it with 10 uses. CinemaSpaceTrigger.Interact itself loads the cinema without checking the ticket flag.",
                "implementation_fact": "both are represented as durable generic cinema capabilities and every configured/repeated claim returns success; no price, charge, 10-use prop state or admission rule is modeled.",
                "required_change": "Keep no-commerce behavior explicitly local; document the distinct client effects and do not claim recovered ticket/admission/popcorn persistence semantics.",
            },
            {
                "id": "RSP-005", "severity": "high", "route": "CheckIfSpaceStillExistServlet",
                "status": "resolved",
                "native_fact": "true#true loads SpaceParams.scene locally; false/error calls LoadSpace for that scene. Request field3 is SpaceParams.id_instance.",
                "implementation_fact": "the allocation query and ready descriptor now match both instance_id and psidglobal.",
                "required_change": "implemented; freshness/protocol completeness remains stricter local policy",
            },
            {
                "id": "RSP-006", "severity": "medium", "route": "CinemaInteractionNPServlet and numeric reward routes",
                "status": "resolved",
                "native_fact": "Int32.ToString emits canonical decimal text; the cinema client can emit only `0` or `1`.",
                "implementation_fact": "integer() now requires value == str(parsed_int), so aliases such as `-0` and `00` fail closed.",
                "required_change": "implemented",
            },
            {
                "id": "RSP-007", "severity": "medium", "route": "CheckOwnGenericReward / GenericReward",
                "status": "semantic_risk_original_predicate_unknown",
                "native_fact": "the check Boolean controls Show and the claim Boolean controls ShowReward; method/field labels describe ownership and grant, but no retired-server predicate was recovered.",
                "implementation_fact": "ownership is only the local route claim marker. An entitlement acquired through another local source reports false; a first route claim can report newly granted true even when the idasset entitlement already existed.",
                "required_change": "Either document claim-history semantics explicitly or correlate the configured target with actual entitlement ownership before choosing fields3; do not label this recovered parity.",
            },
            {
                "id": "RSP-008", "severity": "medium", "route": "all nine routes",
                "status": "resolved_local_hardening",
                "native_fact": "the encrypted request trailer carries a supported platform name; retired-server enforcement is unknown.",
                "implementation_fact": "dispatch now requires request.platform to equal the profile's stored platform after GUID/account validation.",
                "required_change": "implemented as explicit local hardening; retired-server behavior remains unknown",
            },
        ],
        "route_reviews": reviews,
        "call_context_limitations": [
            "Static analysis did not observe execution or establish which scene instances are shipped/active.",
            "Bounded disassembly proves Start0x4663E0 tail-jumps loadScene0x4665F0 and callback0x4663F0 starts the liveness coroutine after a successful unload; this is static reachability, not runtime observation.",
            "Shipped SKL trigger IDs and sprite-array bounds are recovered from static Unity type trees; actual runtime scene activation was not observed.",
        ],
        "original_policy_unknowns": [
            "reward eligibility, schedules, cooldowns and historical claims",
            "asset-to-entitlement mappings and repeat-claim behavior",
            "cinema prices, currency deductions, ticket lifetime and admission policy",
            "original SKL eligibility and server rule selecting the returned sprite-pair index",
        ],
        "implementation_assumption_checks": checks,
        "sources": [source(root, p) for p in source_paths],
    }


def markdown(report: dict) -> str:
    lines = [
        "# Rewards, cinema and liveness: native second pass", "",
        "This is a static source-vs-native review. It did not run the game, open a listener, attach to a process, or make a connection. All original reward and commercial policy remains unknown unless explicitly labeled as local preservation policy.", "",
        "## Outcome", "",
        "All nine current response shapes have the field count, order and parse type consumed by the reviewed client. The five concrete over-broad acceptance surfaces found in this pass are now closed. This still is not semantic parity: generic ownership semantics and cinema policy remain authored or unresolved.", "",
        "| ID | Severity | Route | Finding |", "|---|---|---|---|",
    ]
    for finding in report["findings"]:
        lines.append(f"| {finding['id']} | {finding['severity']} | `{finding['route']}` | {finding['implementation_fact']} |")
    lines += ["", "## Concrete corrections", ""]
    for finding in [x for x in report["findings"] if x["id"] in {"RSP-001", "RSP-002", "RSP-003", "RSP-005", "RSP-006"}]:
        lines += [f"### {finding['id']} — `{finding['route']}`", "",
                  f"Native: {finding['native_fact']}", "",
                  f"Required: {finding['required_change']}", ""]
    lines += [
        "## Cinema acceptance transitions", "",
        "The request enum is exactly `Ticket=0` and `PopCorn=1`. A generic `OnSend` success must be `true#<local GUID>#<local PS4ID>#<Boolean>`. Callback `false` performs no mutation. Callback `true` sets the corresponding in-memory flag. Ticket then displays the purchase popup. PopCorn instantiates the prefab and initializes `ConsumablePopCorn` with 10 uses. The reviewed `CinemaSpaceTrigger.Interact` loads the cinema without checking the ticket flag; therefore server-side price, ticket lifetime and admission enforcement must not be claimed as recovered.", "",
        "## Space liveness", "",
        "The request is `SessionGUID#PS4ID#SpaceParams.id_instance`; the callback consumes `true#Boolean`. True loads `SpaceParams.scene` locally, while false or network failure calls `LoadSpace` for that scene. The backend's freshness rule is compatible local policy, but its ready descriptor must match both allocation instance ID and `psidglobal`. Bounded disassembly proves `Start` tail-jumps `loadScene`, whose successful unload callback starts the liveness coroutine; this is static reachability, not runtime observation.", "",
        "## Residual unknowns", "",
    ]
    lines += [f"- {item}." for item in report["original_policy_unknowns"]]
    lines += ["", "Machine-readable findings and verified source hashes are in `rewards-second-pass.json`.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=workspace())
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    report = build(args.root.resolve())
    text = json.dumps(report, indent=2) + "\n"
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.markdown:
        args.markdown.write_text(markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
