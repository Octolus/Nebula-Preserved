"""Offline oracle: execute the actual preserved Python publishers, never assets.

Set NEBULA_REFERENCE_PROTOCOL_DIR and (when not its sibling) NEBULA_REFERENCE_BACKEND_DIR.
All temporary DBs/publications remain beneath this Rust project. No sockets or
client processes are permitted. Rust tests consume the resulting static JSON.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
PROTOCOL = Path(os.environ.get("NEBULA_REFERENCE_PROTOCOL_DIR", PROJECT / "../../protocol")).resolve()
BACKEND = Path(os.environ.get("NEBULA_REFERENCE_BACKEND_DIR", PROTOCOL.parent / "backend")).resolve()
sys.path.insert(0, str(BACKEND))
from state import Store
from housing import HousingStore, PERSONAL_SPACE_SCENES
from interaction_registry import InteractionRegistryPublisher

NOW = 1_800_000_000.0
OWNER = "registry-owner"


def ground(ids, tx=None, ty=None, tz=None, rotation=None):
    return {"aidasset": ids, "aidasset_tx": tx or [0.0] * len(ids),
            "aidasset_ty": ty or [0.0] * len(ids),
            "aidasset_tz": tz or [0.0] * len(ids),
            "aidasset_r": rotation or [0.0] * len(ids)}


def capture(name, bindings, layouts=None, public=None):
    layouts, public = layouts or {}, public or []
    with tempfile.TemporaryDirectory(prefix="registry-oracle-", dir=PROJECT) as folder:
        root = Path(folder)
        store = Store(root / "oracle.sqlite3")
        try:
            store.account(OWNER, "Registry Owner")
            housing = HousingStore(store, PROTOCOL)
            for binding in bindings:
                housing.bind_space(binding["instance_id"], binding["psidglobal"], OWNER,
                                   binding["logical_space_key"])
            for instance_id, record in layouts.items():
                with store.db:
                    store.db.execute("INSERT INTO housing_layouts VALUES(?,?,?)",
                                     (instance_id, json.dumps(record["layout"]), record["updated_at"]))
            for status in public:
                path = root / "instances" / status["instance_id"] / "instance-status.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(status), encoding="utf-8")
            publisher = InteractionRegistryPublisher(store, PROTOCOL)
            interactions = json.loads(publisher.export(root).read_text(encoding="utf-8"))
            housing_snapshot = json.loads(housing.export_bindings(root).read_text(encoding="utf-8"))
            return dict(name=name, bindings=bindings, layouts=layouts, public_statuses=public,
                        interactions=interactions, housing=housing_snapshot)
        finally:
            store.close()


def binding(instance="home-oracle", logical="Home", scene="Home"):
    return {"instance_id": instance, "logical_space_key": logical,
            "psidglobal": scene, "owner_ps4_id": OWNER}


def run():
    furniture = json.loads((PROTOCOL / "housing-interaction-manifest.json").read_text(encoding="utf-8"))["items"]
    by_id = sorted(furniture, key=lambda row: row["item_id"])
    seat = next(row["item_id"] for row in by_id if row["status"] == "interactive_verified"
                and any(c.get("admission") == "allow" and c.get("registry_kind") == "occupable"
                        for c in row["interactions"]))
    generic = next(row["item_id"] for row in by_id if row["status"] == "interactive_verified"
                   and any(c.get("admission") == "allow" and c.get("registry_kind") == "generic"
                           for c in row["interactions"]))
    empty = next(row["item_id"] for row in by_id if row["status"] == "noninteractive_verified_empty")
    unresolved = next((row["item_id"] for row in by_id if row["status"] == "unresolved_denied"), None)
    cases = [capture("empty_home", [binding()])]

    def case(name, layout):
        cases.append(capture(name, [binding()], {"home-oracle": {"layout": layout, "updated_at": 1234.5}}))

    case("duplicate_furniture_null_compaction_f32", ground(
        ["null", seat, empty, seat, generic],
        [0.0, -0.0, 0.1, 1.1, 16_777_217],
        [0.0, 1.0000000596046448, -0.1, 1.0e-45, 3.4028234663852886e38],
        [0.0, 1.0e-8, -3.1e-20, 1.0e20, 1.0e-4],
        [0.0, 90.0, -0.0, 180.0, -360.0]))
    case("subnormal_signed_zero_and_exponents", ground(
        [generic, seat], [-1.0e-45, 1.1754943508222875e-38],
        [-0.0, 0.0], [1.0e16, 0.00001], [1.0e-20, -1.0e20]))
    if unresolved is not None:
        case("unresolved_known_ground", ground([unresolved]))
    case("unknown_ground_keeps_compact_source_index", ground(["unknown-preservation-item", seat], [0.0, 1.1]))
    case("boolean_transform_rejected", ground([seat, empty], [True, 0.5]))
    case("layout_arrays_missing", {"aidasset": [seat]})
    case("layout_arrays_mismatched", {"aidasset": [seat], "aidasset_tx": [],
                                       "aidasset_ty": [], "aidasset_tz": [], "aidasset_r": []})
    case("null_sentinel_ignores_unused_transform_types", ground(["null", seat], [False, 2.5]))
    case("empty_layout_object", {})
    cases.append(capture("eyrie_exact_alias", [binding("eyrie-oracle", "SorcerersEyrie", "SorcerersEyrie1")]))
    all_bindings = [binding(f"scene-{index:02}", logical, scene)
                    for index, (logical, scene) in enumerate(sorted(PERSONAL_SPACE_SCENES.items()))]
    public = [dict(format_version=1, instance_id="public-" + scene.lower(), psidglobal=scene)
              for scene in ("Nexus", "LeafPark", "Beach", "Cinema")]
    cases.append(capture("all_35_authored_static_scenes", all_bindings, public=public))
    hashes = {name: hashlib.sha256((BACKEND / name).read_bytes()).hexdigest()
              for name in ("interaction_registry.py", "housing.py", "state.py", "wire.py")}
    output = {"format_version": 1, "purpose": "Actual Python publisher oracle; authored metadata/SQLite only",
              "fixed_time": NOW, "source_sha256": hashes, "unresolved_ground_case":
              "captured" if unresolved is not None else "No unresolved_denied item exists in the exact public authored metadata; synthetic Rust negative test covers this policy branch",
              "selected_ground_items":
              {"occupable": seat, "generic": generic, "empty": empty, "unresolved": unresolved},
              "cases": cases}
    target = PROJECT / "tests/registry_snapshot_oracle.json"
    target.write_text(json.dumps(output, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"oracle": str(target), "cases": len(cases),
                      "instances": sum(len(c["interactions"]["instances"]) for c in cases)}, separators=(",", ":")))


if __name__ == "__main__":
    with patch.object(socket, "socket", side_effect=AssertionError("Oracle sockets forbidden")), \
            patch("time.time", return_value=NOW):
        run()
