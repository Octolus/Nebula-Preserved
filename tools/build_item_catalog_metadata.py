#!/usr/bin/env python3
"""Build protocol/item-catalog-metadata.json and resolve wardrobe identities.

Inputs are private research scans of the original game:

* ``--components``: JSONL from tools/recover_item_component_metadata.py
  (shipped MonoBehaviour classes/scalar fields and AnimatorController names).
* ``--names-scan`` (optional): JSONL from tools/recover_item_asset_metadata.py,
  used only to group items whose internal mesh-name sets are identical.

The output holds structured per-identity fields recovered from each item's own
bundle (heel type, hand grip type, locomotion speed, component classes,
housing component variant) plus explicitly *derived* variant families. It
holds no pixels, meshes or bundle bytes. Output is byte-identical for the same
inputs.

``--apply-wardrobe-resolutions`` additionally rewrites
protocol/avatar-asset-catalog.json in place (formatting preserved, idempotent):
a row whose ``category_conflict`` flag is set is cleared only when the shipped
manifest itself decides it, i.e. that exact gender/category folder contains the
item's own ``FBX/<id>.prefab`` *and* ``<id>Thumbnail.png``. The original client
loads wardrobe items only from ``Wardrobe_EAB/<gender>/<category>/<id>/FBX/<id>``
(SetShopBase.LoadItemSelected / wardrobe loaders), so such a row is loadable.
Rows outside ``Wardrobe_EAB`` (``00_CLOTHS``) are never loadable and stay
excluded.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

FORMAT_VERSION = 1
GENERATOR = "tools/build_item_catalog_metadata.py"
WARDROBE_PREFIXES = ("Assets/ResourcesART/Wardrobe_EAB/", "Assets/ART/ResourcesART/Wardrobe_EAB/")
# Unity effect/UI helpers that say nothing about the item's own behaviour.
HELPER_CLASSES = {"CFX_InspectorHelp", "Outline", "CanvasScaler", "GraphicRaycaster", "Text"}
GENERIC_MESH = re.compile(
    r"^(polySurface|pCube|pCylinder|pSphere|pPlane|pPipe|pTorus|Mesh|default|Object|Cube|Plane|Sphere|Cylinder|"
    r"group|node|Box|Combined Mesh)", re.I)
TYPE_GROUND = {0: "Default", 1: "FloorAsset"}  # HousingAssetGround.TypeGround (dump.cs TypeDefIndex 304)


def sha256_file(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def key(kind, item_id, gender, category):
    return (kind, item_id, gender or "", category or "") if kind == "wardrobe" else (kind, item_id, "", "")


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


# ---------------------------------------------------------------- wardrobe

def manifest_slots(row):
    """(gender, category) folders holding this item's own prefab/thumbnail."""
    item_id = row["item_id"]
    slots = defaultdict(set)
    for gender, category, path in (e for e in row.get("category_evidence", []) if len(e) == 3):
        if not path.startswith(WARDROBE_PREFIXES):
            continue
        base = WARDROBE_PREFIXES[0] if path.startswith(WARDROBE_PREFIXES[0]) else WARDROBE_PREFIXES[1]
        folder = gender + "/" + category + "/" + item_id + "/"
        if path == base + folder + "FBX/" + item_id + ".prefab":
            slots[(gender, category)].add("prefab")
        elif path == base + folder + item_id + "Thumbnail.png":
            slots[(gender, category)].add("thumbnail")
    return slots


def wardrobe_resolutions(document):
    """Decide conflicting rows from the item's own shipped manifest only."""
    decisions = []
    by_id = defaultdict(list)
    for row in document["items"]:
        if row.get("category_conflict") or row.get("category_conflict_resolution"):
            by_id[row["item_id"]].append(row)
    for item_id in sorted(by_id):
        rows = by_id[item_id]
        slots = manifest_slots(rows[0])
        loadable = sorted(slot for slot, kinds in slots.items() if kinds == {"prefab", "thumbnail"})
        thumbnail_only = sorted(slot for slot, kinds in slots.items() if kinds == {"thumbnail"})
        for row in rows:
            slot = (row["gender"], row["category"])
            if slot not in loadable:
                decisions.append({"item_id": item_id, "gender": row["gender"], "category": row["category"],
                                  "decision": "excluded", "reason": "no own prefab and thumbnail in this folder"})
                continue
            decisions.append({
                "item_id": item_id, "gender": row["gender"], "category": row["category"],
                "decision": "valid",
                "resolution": ("single_loadable_category" if len(loadable) == 1 else "multiple_loadable_categories"),
                "loadable_categories": [c for _g, c in loadable],
                "thumbnail_only_categories": [c for _g, c in thumbnail_only],
                "evidence": "shipped bundle manifest lists FBX/" + item_id + ".prefab and " + item_id
                            + "Thumbnail.png under Wardrobe_EAB/" + row["gender"] + "/" + row["category"],
            })
    return decisions


def unloadable_wardrobe_rows(document):
    return [{"item_id": row["item_id"], "asset_path": row.get("asset_path"),
             "reason": "prefab is outside Wardrobe_EAB/<gender>/<category>; the client wardrobe loader cannot "
                       "request it and the manifest records no gender or category"}
            for row in document["items"]
            if row.get("gender") not in ("MALE", "FEMALE") or row.get("category") in (None, "UNKNOWN")]


def apply_wardrobe_resolutions(path):
    """Idempotent in-place update preserving the file's exact formatting."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    body = text.rstrip()
    trailer = text[len(body):]
    document = json.loads(body)
    if json.dumps(document, indent=2, ensure_ascii=False) != body:
        raise SystemExit("avatar-asset-catalog.json formatting is not reproducible; refusing to rewrite")
    decisions = {(d["item_id"], d["gender"], d["category"]): d for d in wardrobe_resolutions(document)}
    changed = 0
    for row in document["items"]:
        decision = decisions.get((row["item_id"], row["gender"], row["category"]))
        if not decision or decision["decision"] != "valid":
            continue
        resolution = {k: decision[k] for k in ("resolution", "loadable_categories", "thumbnail_only_categories",
                                                "evidence")}
        resolution["manifest_category_conflict"] = True
        if row.get("category_conflict") or row.get("category_conflict_resolution") != resolution:
            row["category_conflict"] = False
            row["category_conflict_resolution"] = resolution
            changed += 1
    resolved = sum(bool(r.get("category_conflict_resolution")) for r in document["items"])
    document["summary"]["category_conflict_resolved_rows"] = resolved
    document["summary"]["category_conflict_resolution_tool"] = GENERATOR
    output = (json.dumps(document, indent=2, ensure_ascii=False) + trailer).encode("utf-8")
    if output != raw:
        Path(path).write_bytes(output)
    return changed, resolved


# ---------------------------------------------------------------- components

def component_fields(record):
    classes = sorted({c["class"] for c in record["components"] if c.get("class")})
    fields = {"component_classes": [c for c in classes if c not in HELPER_CLASSES],
              "animator_controllers": sorted({a["name"] for a in record["animator_controllers"]}),
              "heel_type": None, "hand_type": None, "locomotion": None, "housing_component": None}
    sources = []
    for component in record["components"]:
        cls, values = component.get("class"), component.get("scalars", {})
        if cls == "HighHeel" and isinstance(values.get("_type"), int):
            fields["heel_type"] = "HighHeel" + str(values["_type"])
            sources.append({"class": cls, "path_id": component["path_id"], "field": "_type"})
        elif cls == "HandType" and isinstance(values.get("_type"), int):
            fields["hand_type"] = "HandType" + str(values["_type"])
            sources.append({"class": cls, "path_id": component["path_id"], "field": "_type"})
        elif cls == "Locomotion":
            fields["locomotion"] = {
                "type_gender": {0: "MALE", 1: "FEMALE"}.get(values.get("typeGender")),
                "max_speed": round(float(values["MaxSpeed"]), 4) if isinstance(values.get("MaxSpeed"), (int, float)) else None,
                "has_male_and_female_animations": {"MaleAnims", "FemaleAnims"} <= set(component.get("field_names", [])),
            }
            sources.append({"class": cls, "path_id": component["path_id"], "field": "typeGender,MaxSpeed"})
        elif cls in ("HousingAssetGround", "HousingAssetWall", "HousingAssetCeiling", "HousingAssetFloor"):
            fields["housing_component"] = {
                "class": cls, "serialized_size": values.get("size"),
                "type_ground": TYPE_GROUND.get(values.get("typeGround")) if cls == "HousingAssetGround" else None,
                "serialized_tablename": values.get("tablename") or None,
            }
            sources.append({"class": cls, "path_id": component["path_id"], "field": "size,typeGround,tablename"})
    return fields, sources


# ---------------------------------------------------------------- variants

def variant_families(names_rows, min_length=5):
    """Derived: identical non-generic internal mesh-name sets in one category."""
    groups = defaultdict(list)
    for row in names_rows:
        kind, item_id, gender, category = row["identity"]
        meshes = frozenset(x["name"] for x in row["names"] if x["type"] == "Mesh"
                           and item_id.lower() not in x["name"].lower() and not GENERIC_MESH.match(x["name"]))
        if meshes and max(map(len, meshes)) >= min_length:
            groups[(kind, gender or "", category or "", meshes)].append(key(kind, item_id, gender, category))
    families = {}
    for (kind, gender, category, meshes), members in groups.items():
        if len(members) < 2:
            continue
        label = json.dumps([kind, gender, category, sorted(meshes)], ensure_ascii=True)
        family = "vf-" + hashlib.sha256(label.encode("ascii")).hexdigest()[:12]
        for member in members:
            families[member] = {"variant_family": family, "variant_family_size": len(members),
                                "variant_basis": "derived_identical_internal_mesh_names",
                                "shared_mesh_names": sorted(meshes)[:4]}
    return families


# ---------------------------------------------------------------- build

def build(protocol, components_path, names_path=None):
    protocol = Path(protocol)
    wardrobe = json.loads((protocol / "avatar-asset-catalog.json").read_text(encoding="utf-8"))
    components = read_jsonl(components_path)
    by_key = {}
    for record in components:
        kind, item_id, gender, category = record["identity"]
        by_key.setdefault(key(kind, item_id, gender, category), record)
    bundle_identities = defaultdict(set)
    for k, record in by_key.items():
        bundle_identities[record["bundle"]].add(k)
    families = variant_families(read_jsonl(names_path)) if names_path else {}
    items = []
    for k in sorted(by_key):
        record = by_key[k]
        kind, item_id, gender, category = record["identity"]
        if kind == "wardrobe" and (gender not in ("MALE", "FEMALE") or category in (None, "UNKNOWN")):
            continue
        fields, sources = component_fields(record)
        entry = {"kind": kind, "item_id": item_id, "gender": gender if kind == "wardrobe" else None,
                 "category": category, **fields, **families.get(k, {}),
                 "provenance": {"bundle": record["bundle"], "bundle_sha256": record["sha256"],
                                "manifest_sha256": record["manifest_sha256"], "component_fields": sources,
                                "bundle_shared_with_identities": len(bundle_identities[record["bundle"]]) - 1}}
        items.append(entry)
    document = {
        "format_version": FORMAT_VERSION, "generator": GENERATOR,
        "scope": ("Per-item fields read from each item's own shipped bundle (component classes and scalar "
                  "serialized fields, animator controller names). variant_family is derived from identical "
                  "internal mesh names and is not a recovered commercial collection, colour name or set."),
        "game": {"app_id": 919290, "build_id": 11018722, "unity": "2021.3.9f1"},
        "source_scans": [{"name": Path(components_path).name, "sha256": sha256_file(components_path),
                          "rows": len(components), "producer": "tools/recover_item_component_metadata.py"}]
                        + ([{"name": Path(names_path).name, "sha256": sha256_file(names_path),
                             "producer": "tools/recover_item_asset_metadata.py",
                             "used_for": "variant_family"}] if names_path else []),
        "field_status": {
            "heel_type": "recovered: HighHeel._type (HighHeel.HighHeelType enum) on the item's prefab",
            "hand_type": "recovered: HandType._type (HandType.HandTypeenum) on the item's prefab",
            "locomotion": "recovered: Locomotion.typeGender and MaxSpeed on the item's prefab",
            "housing_component": "recovered: HousingAsset* class, size, typeGround and serialized tablename",
            "component_classes": "recovered: MonoBehaviour script classes in the item's own bundle",
            "animator_controllers": "recovered: AnimatorController names in the item's own bundle",
            "variant_family": "derived: identical non-generic internal mesh-name sets within one kind/gender/category",
            "rarity_tier": "not_recovered: no shipped field",
        },
        "wardrobe_category_resolutions": wardrobe_resolutions(wardrobe),
        "unloadable_wardrobe_rows": unloadable_wardrobe_rows(wardrobe),
        "items": items,
    }
    return document


def render(document):
    return json.dumps(document, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--components", type=Path, help="Private component scan JSONL")
    parser.add_argument("--names-scan", type=Path, help="Private typed-name scan JSONL (variant families)")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "protocol/item-catalog-metadata.json")
    parser.add_argument("--apply-wardrobe-resolutions", action="store_true",
                        help="Clear manifest-decided category conflicts in protocol/avatar-asset-catalog.json")
    args = parser.parse_args()
    protocol = Path(__file__).resolve().parents[1] / "protocol"
    if args.apply_wardrobe_resolutions:
        changed, resolved = apply_wardrobe_resolutions(protocol / "avatar-asset-catalog.json")
        print(json.dumps({"changed_rows": changed, "resolved_rows": resolved}))
    if args.components:
        args.output.write_text(render(build(protocol, args.components, args.names_scan)), encoding="utf-8")
        print("wrote", args.output)


if __name__ == "__main__":
    main()
