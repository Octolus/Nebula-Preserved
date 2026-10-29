"""Generate a static-evidence audit of retired gathering client branches."""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import hashlib
import json
from pathlib import Path


ROOT = output_root()
REPOSITORY = workspace()
FUNCTIONS = REPOSITORY / "work/evidence/ghidra/functions"
DUMP = REPOSITORY / "work/decompiled/dump.cs"
PROTOCOL = ROOT / "protocol"
GAME_ASSEMBLY_SHA256 = "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac"


FUNCTIONS_USED = {
    "init_callback": "3f3cb0",
    "phase_callback": "3efa10",
    "consume_sender": "3f2e90",
    "consume_callback": "3ef680",
    "reward_callback": "3ef240",
    "memorion_result_callback": "3ef0c0",
    "christmas_item_trigger": "68f920",
    "easter_item_trigger": "68fbd0",
    "halloween2018_item_trigger": "68fe80",
    "halloween2018_process_item": "6901b0",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(rva: str) -> dict:
    path = FUNCTIONS / f"{rva}.c"
    return {
        "rva": "0x" + rva,
        "path": path.relative_to(REPOSITORY).as_posix(),
        "sha256": digest(path),
    }


def verify_sources() -> None:
    dump = DUMP.read_text(encoding="utf-8")
    for fragment in (
        "public string psidglobal; // 0x250",
        "public bool isNexus; // 0x148",
        "public bool isLeafPark; // 0x149",
        "public bool isDome; // 0x14A",
        "public bool isCube; // 0x14B",
        "public bool isBeach; // 0x14C",
        "public int currentCandies; // 0x9C",
        "public int currentCandies; // 0xA4",
    ):
        if fragment not in dump:
            raise RuntimeError("managed metadata fragment missing: " + fragment)
    init = (FUNCTIONS / "3f3cb0.c").read_text(encoding="utf-8")
    phase = (FUNCTIONS / "3efa10.c").read_text(encoding="utf-8")
    for offset in ("0x58", "0x60", "0x68", "0x70", "0x78"):
        if offset not in init or offset not in phase:
            raise RuntimeError("scene-flag consumer offset missing: " + offset)
    for rva in ("68f920", "68fbd0", "68fe80"):
        if "Send_GatherConsume" not in (FUNCTIONS / f"{rva}.c").read_text(encoding="utf-8"):
            raise RuntimeError("collection call path missing at 0x" + rva)


def build() -> dict:
    verify_sources()
    sources = {name: evidence(rva) for name, rva in FUNCTIONS_USED.items()}
    sources["managed_metadata"] = {
        "path": DUMP.relative_to(REPOSITORY).as_posix(),
        "sha256": digest(DUMP),
    }
    return {
        "schema": "nebula-preservation.gathering-branches.v1",
        "source_artifact": {"name": "GameAssembly.dll", "sha256": GAME_ASSEMBLY_SHA256},
        "route_inventory": {
            "implemented": 10,
            "deferred": ["Get_GatherChristmasGetSpacesCompleted"],
        },
        "sources": sources,
        "observations": [
            {
                "branch": "Send_GatherInitInSpace callback",
                "wire_after_identity": ["type", "current_gather", "rewards_earned", "cooldown_seconds"],
                "detail": "Indices 4, 5 and 6 are parsed as Int32; index 4 drives count/reward thresholds, index 5 drives completion and SetThumbnails, and index 6 is passed to ShowCoolDown.",
                "evidence": ["init_callback", "managed_metadata"],
            },
            {
                "branch": "Get_GatherPhaseGame callback",
                "wire_after_identity": ["type", "cooldown_seconds", "current_gather", "rewards_earned"],
                "detail": "The same values use a different order: index 4 is passed to ShowCoolDown, index 5 is rendered/threshold-tested as the gather count, and index 6 selects the reward stage.",
                "evidence": ["phase_callback", "managed_metadata"],
            },
            {
                "branch": "Christmas2018 extended response",
                "wire_indices_7_to_11": ["isNexus", "isLeafPark", "isDome", "isCube", "isBeach"],
                "psid_enum_values": {"Nexus": 0, "LeafPark": 1, "Dome": 19, "Cube": 7, "Beach": 5},
                "detail": "Each value is parsed as Int32 and stored as a bool. PhaseGame compares the corresponding flag with ManagerInstance.typePsidglobal before showing SpaceCompleted.",
                "evidence": ["init_callback", "phase_callback", "managed_metadata"],
            },
            {
                "branch": "Christmas2018 consume request",
                "wire_after_identity": ["type", "psidglobal"],
                "detail": "The sender loads ManagerInstance+0x250; managed metadata names that field psidglobal. It is not an unknown counter.",
                "evidence": ["consume_sender", "managed_metadata"],
            },
            {
                "branch": "Gather consume operation",
                "detail": "Christmas and Easter item-trigger collisions call Send_GatherConsume after an item is collected. Halloween2018 increments its local round counter and calls the same route when the round completes. The consume callback displays returned index 4 and opens reward collection at observed thresholds. Therefore this route advances collection progress; it does not decrement inventory.",
                "classification": "strong inference from independent sender and consumer paths",
                "evidence": ["christmas_item_trigger", "easter_item_trigger", "halloween2018_item_trigger", "halloween2018_process_item", "consume_callback"],
            },
            {
                "branch": "ConsumeReward response",
                "wire_after_identity": ["type", "current_gather", "rewards_earned"],
                "detail": "Index 4 updates the displayed gather count and index 5 is passed to ShowRewardGathered or used to select the reward sprite.",
                "evidence": ["reward_callback"],
            },
            {
                "branch": "Get_GatherChristmasGetSpacesCompleted",
                "wire_after_identity": ["memorion_score", "level_index"],
                "detail": "The callback compares score against a level threshold array and continues into the Memorion challenge. This is mini-game score validation, not an ordinary spaces-completed counter.",
                "evidence": ["memorion_result_callback", "managed_metadata"],
            },
        ],
        "preservation_decisions": [
            "Init and phase replies preserve their distinct observed field order.",
            "Current gather and rewards earned are separate durable per-account values.",
            "The five Christmas2018 PSIDs use unique durable rows; repeated scenes are idempotent and any other PSID fails closed.",
            "Gather consume increments progress, bounded by the explicitly configured local threshold.",
            "Reward grant, progress reset/increment and claim marker remain in Store.atomic().",
            "The Memorion score endpoint returns an explicit deferred-gameplay error instead of fabricating a score oracle.",
        ],
        "unknowns": [
            "The retired service's schedules, reward item definitions and Memorion score-validation policy were not recovered.",
            "Static client evidence establishes how fields are consumed, not historical production account values.",
        ],
    }


def markdown(report: dict) -> str:
    lines = [
        "# Gathering branch audit", "",
        f"Static source artifact: `GameAssembly.dll` SHA-256 `{GAME_ASSEMBLY_SHA256}`.", "",
        "This audit corrects field semantics using client sender/callback pseudocode and IL2CPP managed metadata. It does not claim runtime observation.", "",
        "Route inventory: 10 implemented gathering routes; `Get_GatherChristmasGetSpacesCompleted` remains documented but is deferred and is not advertised by `Gathering.ROUTES`.", "",
        "## Recovered branches", "",
    ]
    for item in report["observations"]:
        lines += [f"### {item['branch']}", "", item["detail"]]
        if "wire_after_identity" in item:
            lines += ["", "Wire suffix following `guid#ps4_id` (and `success` for responses): `" + "#".join(item["wire_after_identity"]) + "`."]
        if "wire_indices_7_to_11" in item:
            lines += ["", "Indices 7–11: `" + "#".join(item["wire_indices_7_to_11"]) + "`."]
        lines += ["", "Evidence: " + ", ".join(
            f"`{report['sources'][key].get('rva', report['sources'][key]['path'])}`"
            for key in item["evidence"]) + ".", ""]
    lines += ["## Preservation decisions", ""]
    lines.extend(f"- {value}" for value in report["preservation_decisions"])
    lines += ["", "## Remaining evidence boundaries", ""]
    lines.extend(f"- {value}" for value in report["unknowns"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    report = build()
    PROTOCOL.mkdir(parents=True, exist_ok=True)
    (PROTOCOL / "gathering-branches.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (PROTOCOL / "gathering-branches.md").write_text(markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
