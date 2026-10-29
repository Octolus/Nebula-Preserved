"""Generate evidence-bound contracts for the non-mini gathering HTTP surface."""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import hashlib
import json
from pathlib import Path


ROOT = output_root()
REPOSITORY = workspace()
EVIDENCE = REPOSITORY / "work" / "evidence" / "ghidra" / "functions"
PROTOCOL = ROOT / "protocol"
GAME_ASSEMBLY_SHA256 = "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac"


ROUTES = [
    ("Get_npGather", "3f4e70", "3f0fe0", ["guid", "ps4_id", "name_game", "max_available_items"],
     ["success", "guid", "ps4_id", "state", "cooldown_or_current", "total_if_active"]),
    ("Get_npGatherProcessItem", "3f18d0", "3f14f0", ["guid", "ps4_id", "name_game", "total", "type"],
     ["success", "guid", "ps4_id", "popup_or_name", "current", "total", "np_reward_amount"]),
    ("Get_GatherStatus", "3f4b30", "3f0470", ["guid", "ps4_id", "type"],
     ["success", "guid", "ps4_id", "available", "type", "amount"]),
    ("Send_GatherInitInSpace", "3f4730", "3f3cb0", ["guid", "ps4_id", "current_space_psid", "type"],
     ["success", "guid", "ps4_id", "type", "current_gather", "rewards_earned", "cooldown_seconds", "nexus_complete", "leaf_park_complete", "dome_complete", "cube_complete", "beach_complete"]),
    ("Get_GatherPhaseGame", "3f0130", "3efa10", ["guid", "ps4_id", "type"],
     ["success", "guid", "ps4_id", "type", "cooldown_seconds", "current_gather", "rewards_earned", "nexus_complete", "leaf_park_complete", "dome_complete", "cube_complete", "beach_complete"]),
    ("Get_GatherConsume", "3f2e90", "3ef680", ["guid", "ps4_id", "type", "type_dependent_value"],
     ["success", "guid", "ps4_id", "type", "current_gather", "rewards_earned"]),
    ("Get_GatherConsumeReward", "3f2590", "3ef240", ["guid", "ps4_id", "type", "type_dependent_value"],
     ["success", "guid", "ps4_id", "type", "current_gather", "rewards_earned"]),
    ("Get_npGatherChristmas", "3f2190", "3f0a50", ["guid", "ps4_id", "current_space_psid", "client_state"],
     ["success", "guid", "ps4_id", "state", "start_allowed", "phase_code", "cooldown_seconds", "current_gather"]),
    ("Get_GatherChristmasGetSpacesCompleted", "3f1d60", "3ef0c0", ["guid", "ps4_id", "level", "datetime_ticks"],
     ["success", "guid", "ps4_id", "memorion_score", "level_index"]),
    ("Get_GatherMedievalVillage", "690700", "690c60", ["guid", "ps4_id", "datetime_ticks"],
     ["success", "guid", "ps4_id", "available_bool", "cooldown_seconds_double", "amount_int32"]),
    ("Send_GatherMedievalVillageConsume", "691120", "690b10", ["guid", "ps4_id", "datetime_ticks"],
     ["success", "guid", "ps4_id", "result_code_int32", "cooldown_seconds_double", "popup_string"]),
]


def source(rva: str) -> dict:
    path = EVIDENCE / f"{rva}.c"
    data = path.read_bytes()
    return {
        "rva": "0x" + rva,
        "path": path.relative_to(REPOSITORY).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def build() -> dict:
    contracts = []
    for name, sender, callback, request, response in ROUTES:
        variant = None
        if name == "Get_GatherConsume":
            variant = {
                "types_1_2_3_5_7": "four fields; final field is component Int32 counter",
                "type_4": "four fields; final field is ManagerInstance.psidglobal (Nexus, LeafPark, Dome, Cube, or Beach for the five-space challenge)",
                "types_6_8": "three fields; type is final field",
            }
        elif name == "Get_GatherConsumeReward":
            variant = {
                "types_1_2_3_5_7": "four fields; final field is component Int32 counter",
                "types_4_6_8": "three fields; type is final field",
            }
        contracts.append({
            "command": name,
            "implementation_status": ("deferred_minigame_score_oracle"
                                      if name == "Get_GatherChristmasGetSpacesCompleted"
                                      else "restored_local_preservation"),
            "request_fields": request,
            "request_variant": variant,
            "response_fields_consumed": response,
            "evidence": {"sender": source(sender), "callback": source(callback)},
        })
    return {
        "schema": "nebula-preservation.http-gathering.v2",
        "source_artifact": {"name": "GameAssembly.dll", "sha256": GAME_ASSEMBLY_SHA256},
        "delimiter": "#",
        "type_enum_observed_in_client": {
            "0": "Halloween", "1": "Christmas", "2": "Easter", "3": "Halloween2018",
            "4": "Christmas2018", "5": "Halloween2019", "6": "Christmas2019",
            "7": "Halloween2020", "8": "Christmas2020",
        },
        "route_inventory": {
            "observed_contracts": 11,
            "implemented_routes": 10,
            "deferred_minigame_routes": ["Get_GatherChristmasGetSpacesCompleted"],
        },
        "routes": contracts,
        "preservation_policy": {
            "classification": "new local policy, not recovered original service data",
            "fail_closed": ["unconfigured event", "inactive event mutation", "unknown reward", "client/local counter mismatch"],
            "durable": ["configuration", "per-account current gather and rewards earned", "Christmas2018 unique scene flags", "reward claim marker", "medieval progress"],
            "idempotency": "Store.atomic BEGIN IMMEDIATE groups the progress recheck, entitlement grant and claim marker; an injected post-grant failure rolls all writes back, including after reopening SQLite",
        },
        "unknowns": [
            "Original event schedules and reward definitions were not present in the reviewed client artifacts.",
            "The retired server's Memorion score-validation rules were not present in the reviewed client artifacts; Get_GatherChristmasGetSpacesCompleted therefore fails explicitly as deferred gameplay.",
            "No claim is made that locally configured event content reproduces retired production data.",
        ],
        "excluded": ["archery gameplay", "Memorion gameplay", "other mini-game mechanics"],
    }


def markdown(contract: dict) -> str:
    lines = [
        "# Gathering and ordinary-event HTTP contract", "",
        f"Source artifact: `GameAssembly.dll` SHA-256 `{GAME_ASSEMBLY_SHA256}`.", "",
        "This document separates client-observed wire shapes from new preservation policy. It does not assert that retired schedules or rewards were recovered.", "",
        "Inventory: 11 observed contracts, 10 implemented preservation routes, and 1 deferred mini-game score route.", "",
        "## Observed routes", "",
        "| Command | Request fields after command | Response fields consumed | Evidence |",
        "|---|---|---|---|",
    ]
    for route in contract["routes"]:
        ev = route["evidence"]
        evidence = f"sender `{ev['sender']['rva']}`, callback `{ev['callback']['rva']}`"
        lines.append(f"| `{route['command']}` | `{' # '.join(route['request_fields'])}` | `{' # '.join(route['response_fields_consumed'])}` | {evidence} |")
        if route["request_variant"]:
            lines.append(f"|  | Type variants: {'; '.join(route['request_variant'].values())} |  |  |")
    lines += [
        "", "The five scene flags at indices 7–11 apply to type 4 (Christmas2018); other event types end after index 6. `Get_GatherChristmasGetSpacesCompleted` is the deferred Memorion score oracle and returns an explicit 501 rather than fabricated results.",
        "", "## Local preservation policy", "",
        "Event configuration is explicit and durable. Unconfigured or unknown content fails closed. Progress is account-bound; client counters must agree with durable progress where the shipped sender supplies them. Christmas 2018 scene completion accepts only the five client-observed PSIDs and is unique per account, so repeats are idempotent. Store.atomic uses BEGIN IMMEDIATE to group the progress recheck, entitlement grant and claim marker. Injected failure after a grant rolls everything back, including after reopening SQLite.",
        "", "Original scheduling and reward definitions remain unknown and are never synthesized as historical fact. Administrators must define any replacement event and reward locally.",
        "", "## Evidence boundaries", "",
    ]
    lines.extend(f"- {item}" for item in contract["unknowns"])
    lines += ["", "Mini-gameplay is deferred: archery, Memorion, and other full mini-game mechanics are outside this contract.", ""]
    return "\n".join(lines)


def main() -> None:
    contract = build()
    PROTOCOL.mkdir(parents=True, exist_ok=True)
    (PROTOCOL / "http-gathering.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    (PROTOCOL / "http-gathering.md").write_text(markdown(contract), encoding="utf-8")


if __name__ == "__main__":
    main()
