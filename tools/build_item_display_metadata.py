#!/usr/bin/env python3
"""Build protocol/item-display-metadata.json from a typed bundle scan.

Input is the private JSONL written by tools/recover_item_asset_metadata.py
(typed Unity object names and decoded component strings per catalog identity).
Output contains short derived labels and their exact source objects only: no
pixels, meshes, audio or bundle bytes. The derivation is deterministic: the same
scan and catalog always produce byte-identical output.

Naming policy (see docs/ITEM-METADATA-EVIDENCE.md):
* ``original_name``/``description`` are set only from a shipped string that is
  tied to exactly that item. None has been found in build 11018722; the fields
  stay null rather than being synthesized.
* ``derived_name`` is a humanized internal asset label (Avatar, Material, Mesh,
  Texture, AnimationClip or model GameObject names inside the item's own
  bundle). It is never presented as the historical storefront name.
* ``interaction_labels`` are shipped UI prompts found inside the item's own
  bundle (for example ``Light On Red Rocket``). They are hints, not names.

Usage:
  python tools/build_item_display_metadata.py --scan scan.private.jsonl \
      --output protocol/item-display-metadata.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

FORMAT_VERSION = 1
GENERATOR = "tools/build_item_display_metadata.py"
NAME_SOURCE_DERIVED = "derived_asset_name"
# Object type weights: names a modeller gives a rig, material or model root
# describe the product more often than texture channel or animation names.
WEIGHTS = {"Avatar": 3, "Material": 2, "Mesh": 2, "GameObject": 2, "Texture2D": 1, "AnimationClip": 1}
TECHNICAL_SUFFIXES = {
    "mat", "mtl", "material", "materials", "mesh", "geo", "geometry", "avatar", "rig", "rigavatar", "clr", "col",
    "c", "n", "e", "d", "m", "r", "s", "ao", "nrm", "norm", "normal", "normals", "nor", "nm", "diff", "diffuse",
    "dif", "base", "color", "colour", "smoothness", "metallic", "opengl", "directx", "alpha", "emissive",
    "emission", "emiss", "basecolor", "albedo", "mandr", "mr", "rgb", "rgba", "opacity", "height", "roughness",
    "spec", "specular", "tex", "texture", "lod", "lod0", "lod1", "lod2", "lod3", "low", "high", "hi", "lo", "shader",
    "copy", "256", "512", "1024", "2048", "4096", "msk", "mask", "op", "tp", "fbx", "prefab", "new", "final", "v2", "v3",
    "idle", "run", "walk", "jump", "eat", "move", "spin", "trigger", "fly", "flying", "sit", "loop", "anim",
    "animation", "alt", "take", "glow", "glowa", "light", "lights", "emit", "body", "transparent", "cutout",
}
ACTION_TOKEN = re.compile(r"^(idle|run|walk|jump|eat|move|spin|trigger|fly|sit|loop|alt|take|lod|v)\d*$", re.I)
PREFIXES = re.compile(r"^(?:(?:nr|fbx|sm|sk|mat|tx|t|pm)_|s_\d+_)+", re.I)
GENERIC = {
    "", "root", "scalar", "default", "material", "mat", "normal", "lambert", "phong", "blinn", "standard", "mesh",
    "selectionmarker", "badpositionmarker", "do not delete", "triggereditem", "point light", "spot light",
    "particle system", "audios", "audio", "seat", "light", "door", "companion", "locomotion", "locomotionroot",
    "locomotionpivotpoint", "master", "pivot", "model", "group", "base", "body", "geo", "take", "take 001",
    "new material", "sprites default", "default material", "unity", "shadow", "collider", "trigger", "glass",
    "metal", "wood", "plastic", "fabric", "cloth", "skin", "hair", "eyes", "eye", "teeth", "tongue", "jnt", "joint",
    "bone", "bones", "rig", "armature", "skeleton", "hips", "spine", "head", "neck", "tail", "flying", "idle", "run",
    "item", "items", "object", "prop", "props", "white", "black", "red", "blue", "green", "temp", "test", "new",
    "standard surface", "no name", "noname", "untitled", "basic", "simple", "main", "game object", "gameobject",
}
GENERIC_PATTERN = re.compile(
    r"^(lambert|phong|blinn|aisurfaceshader|standardsurface|polysurface|pcube|pcylinder|psphere|pplane|ppipe|"
    r"ptorus|object|mesh|group|material|joint|bone|null|nurbs|transform|default|box|cube|plane|cylinder|sphere|"
    r"cfx\d*|particle|sparkle|smoke|glow|light|shadow|collider|root|locator|dummy|bip|bn|ch|f ch|jnt|copy)[\s_\d]*$",
    re.I)
BONE = re.compile(r"(_jnt$|^f?_?ch_|^bip|^bn_|^joint\d*$|^(l|r|lf|rt|left|right)_|_(l|r)\d*$|"
                  r"(?:^|[_\s])(shoulder|elbow|wrist|hip|knee|ankle|toe|toes|finger|thumb|spine|clavicle|pelvis|neck|jaw|"
                  r"ear|eye|brow|lip|tail|wing|leg|arm|foot|hand|head)\d*(_[lr]\d*)?$)", re.I)
# A key made only of these words names a part, helper or rig, not a product.
GENERIC_WORDS = {
    "male", "female", "root", "back", "front", "head", "end", "tip", "base", "top", "bottom", "left", "right",
    "center", "centre", "middle", "pointer", "footsteps", "footstep", "collision", "colliders", "collider",
    "trigger", "game", "object", "particle", "particles", "system", "p", "cube", "cylinder", "sphere", "plane",
    "poly", "surface", "mesh", "group", "light", "point", "spot", "wing", "wings", "mouth", "eye", "eyes", "chest",
    "body", "tail", "ear", "ears", "leg", "legs", "arm", "arms", "hand", "hands", "foot", "feet", "nose", "teeth",
    "missing", "prefab", "dummy", "default", "material", "mat", "fx", "vfx", "effect", "effects", "glow", "shadow",
    "audio", "audios", "sound", "sounds", "seat", "seats", "door", "handle", "pivot", "marker", "upper", "lower",
    "inner", "outer", "a", "b", "c", "d", "l", "r", "f", "m", "x", "y", "z", "new", "old", "test", "temp", "geo",
    "part", "parts", "piece", "pieces", "detail", "details", "extra", "extras", "low", "high", "lod", "item",
    "items", "elements", "element", "texture", "textures", "uv", "uvs", "anim", "animation", "idle", "walk",
    "character", "torso", "bench", "hub", "bone", "ctrl", "control", "controller", "rest", "jumping",
    # Spanish rig vocabulary used by the original modellers.
    "pata", "pierna", "derecha", "izquierda", "der", "izq", "del", "tras", "trasera", "delantera", "delante",
    "dedo", "cadera", "cuello", "ala", "oreja", "cola", "cabeza", "brazo", "mano", "pie", "ojo", "boca",
}
GENDER_SUFFIXES = {"male", "female", "f", "fem", "mal"}
THIRD_PARTY = re.compile(r"^(cfx|cfxr|cfx4|jmo|ps_|fx_)", re.I)
ID_TOKEN = re.compile(r"(?<![A-Za-z0-9À-ɏ])[A-Za-z0-9À-ɏ]{32}(?![A-Za-z0-9À-ɏ])")
SEASONS = (
    ("Christmas", re.compile(r"xmas|christmas|santa|snowman|gingerbread|reindeer|noel", re.I)),
    ("Halloween", re.compile(r"hallow|pumpkin|spooky|witch|zombie|skeleton|ghost|demonic|vampire", re.I)),
    ("Easter", re.compile(r"easter", re.I)),
    ("Valentine's", re.compile(r"valentin", re.I)),
    ("Summer", re.compile(r"(?:^|[_\s])sum(?:mer)?\d{0,2}(?:[_\sA-Z]|$)|summer|beach|tropical", re.I)),
    ("Winter", re.compile(r"winter|snow|frost|\bice\b", re.I)),
)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def identity_key(kind, item_id, gender, category):
    wardrobe = kind == "wardrobe"
    return (kind, item_id, (gender or "") if wardrobe else "", (category or "") if wardrobe else "")


def split_words(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z])(\d)", r"\1 \2", text)
    return [w for w in re.split(r"[\s_\-.()\[\]]+", text) if w]


def stem(raw, item_id):
    """Return (key, label) for a raw internal object name, or None if unusable."""
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    lowered = name.lower()
    if not name or item_id.lower() in lowered or ID_TOKEN.search(name):
        return None
    if (any(c in name for c in "#\\/:�") or any(ord(c) < 32 for c in name) or THIRD_PARTY.match(name)
            or lowered.startswith("trigger")):
        return None
    if lowered in GENERIC or GENERIC_PATTERN.match(lowered) or BONE.search(name):
        return None
    name = re.sub(r"(?i)(rig)?avatar$", "", name)
    name = PREFIXES.sub("", name)
    tokens = [t for t in re.split(r"[\s_]+", name) if t]
    while tokens and (tokens[-1].lower() in TECHNICAL_SUFFIXES or ACTION_TOKEN.match(tokens[-1])):
        tokens.pop()
    # "Bike_Body" and "Wicker" are fine; a lone single-letter stem is not.
    words = []
    for token in tokens:
        words.extend(split_words(token))
    while words:
        last = words[-1].lower()
        if last in TECHNICAL_SUFFIXES or last in GENDER_SUFFIXES or ACTION_TOKEN.match(last):
            words.pop()
        elif last.isdigit() and len(words) > 1 and ACTION_TOKEN.match(words[-2]):
            del words[-2:]
        else:
            break
    if not words:
        return None
    key = " ".join(w.lower() for w in words)
    if (key in GENERIC or GENERIC_PATTERN.match(key) or len(key.replace(" ", "")) < 3 or key.isdigit()
            or all(w in GENERIC_WORDS or w.isdigit() for w in key.split())):
        return None
    label = " ".join(w if any(c.isupper() for c in w) or w.isdigit() else w[:1].upper() + w[1:] for w in words)
    return key, label[:80]


def derive(record):
    item_id = record["identity"][1]
    support = Counter()
    labels = {}
    evidence = defaultdict(list)
    for obj in record.get("names", []):
        weight = WEIGHTS.get(obj.get("type"))
        if not weight:
            continue
        result = stem(obj.get("name"), item_id)
        if result is None:
            continue
        key, label = result
        support[key] += weight
        # Deterministic label choice for a key: first in (type, name) order.
        labels[key] = min(labels.get(key, label), label)
        evidence[key].append({"type": obj["type"], "path_id": obj["path_id"], "name": obj["name"]})
    if not support:
        return None, []
    # A shared stem ("battle tank") also gains half the support of the more
    # specific names that extend it ("battle tank turret", "battle tank wheel").
    score = {k: 2 * support[k] + sum(support[o] for o in support if o.startswith(k + " ")) for k in support}
    ranked = sorted(support, key=lambda k: (-score[k], -len(k.split()), k))
    best = ranked[0]
    proof = sorted(evidence[best], key=lambda e: (-WEIGHTS[e["type"]], e["type"], e["name"], e["path_id"]))[:3]
    alternatives = [labels[k] for k in ranked[1:4]]
    total = sum(support.values())
    confidence = "high" if support[best] >= 4 and support[best] * 2 >= total else (
        "medium" if support[best] >= 2 else "low")
    return {"label": labels[best], "support": support[best], "score": score[best] / 2,
            "candidate_support_total": total,
            "confidence": confidence, "evidence": proof}, alternatives


def interaction_labels(record):
    found = []
    for component in record.get("component_strings", []):
        for value in component.get("values", []):
            field = value.get("field", "")
            if field in ("/_label", "/ShowText", "/HideText") and isinstance(value.get("value"), str):
                text = value["value"].strip()
                if text and len(text) <= 64 and "#" not in text:
                    found.append({"text": text, "field": field.lstrip("/"), "path_id": component["path_id"]})
    unique = {}
    for row in sorted(found, key=lambda r: (r["text"], r["field"], r["path_id"])):
        unique.setdefault(row["text"], row)
    return list(unique.values())[:8]


def season(names):
    for label, pattern in SEASONS:
        hits = sorted({n for n in names if pattern.search(n)})
        if hits:
            return {"value": label, "matched_names": hits[:3]}
    return None


def catalog_identities(repo):
    sys.path.insert(0, str(repo / "backend"))
    from state import Catalog, Store
    from service import Service
    from catalog_inventory import CatalogInventory
    with tempfile.TemporaryDirectory(prefix="display-metadata-") as scratch:
        store = Store(Path(scratch) / "catalog.sqlite3")
        try:
            return [identity_key(r["kind"], r["item_id"], r.get("gender"), r.get("category"))
                    for r in CatalogInventory(Service(store, Catalog(repo / "protocol"))).items]
        finally:
            store.close()


def build(scan_rows, identities, scan_name, scan_sha256):
    by_identity = {}
    for row in scan_rows:
        key = identity_key(*row["identity"])
        if key in by_identity:
            raise ValueError("Duplicate scan identity: %r" % (key,))
        by_identity[key] = row
    missing = [k for k in identities if k not in by_identity]
    unexpected = sorted(set(by_identity) - set(identities))
    if unexpected:
        raise ValueError("Scan contains identities absent from the catalog: %r" % unexpected[:3])
    items = []
    coverage = defaultdict(Counter)
    for key in sorted(identities):
        kind = key[0]
        coverage[kind]["items"] += 1
        record = by_identity.get(key)
        if record is None:
            coverage[kind]["not_scanned"] += 1
            continue
        derived, alternatives = derive(record)
        labels = interaction_labels(record)
        hint = season([o["name"] for o in record.get("names", []) if isinstance(o.get("name"), str)])
        entry = {"kind": key[0], "item_id": key[1], "gender": key[2] or None, "category": key[3] or None,
                 "original_name": None, "description": None,
                 "derived_name": derived["label"] if derived else None,
                 "name_source": NAME_SOURCE_DERIVED if derived else None,
                 "derived_name_confidence": derived["confidence"] if derived else None,
                 "derived_name_alternatives": alternatives,
                 "season_hint": hint["value"] if hint else None,
                 "interaction_labels": [r["text"] for r in labels],
                 "provenance": {
                     "bundle": record.get("bundle"), "bundle_sha256": record.get("sha256"),
                     "manifest_sha256": record.get("manifest_sha256"),
                     "derived_name": {"method": "weighted_internal_object_name_vote", "support": derived["support"],
                                      "score": derived["score"], "candidate_support_total": derived["candidate_support_total"],
                                      "objects": derived["evidence"]} if derived else None,
                     "season_hint": {"method": "derived_from_internal_object_names",
                                     "matched_names": hint["matched_names"]} if hint else None,
                     "interaction_labels": [{"field": r["field"], "path_id": r["path_id"]} for r in labels]}}
        items.append(entry)
        if derived:
            coverage[kind]["derived_name"] += 1
            coverage[kind]["derived_" + derived["confidence"]] += 1
        coverage[kind]["original_name"] += 0
        coverage[kind]["description"] += 0
        coverage[kind]["interaction_labels"] += bool(labels)
        coverage[kind]["season_hint"] += bool(hint)
    return {
        "format_version": FORMAT_VERSION,
        "generator": GENERATOR,
        "scope": ("Short internal labels derived from typed object names inside each item's own shipped bundle. "
                  "Derived names are preservation display labels, not historical storefront names. No original "
                  "item name, description, price or store membership string tied to an item was found."),
        "game": {"app_id": 919290, "build_id": 11018722, "unity": "2021.3.9f1"},
        "source_scan": {"name": scan_name, "sha256": scan_sha256, "rows": len(scan_rows),
                        "producer": "tools/recover_item_asset_metadata.py"},
        "sources_without_item_names": [
            "resources.assets, globalgamemanagers.assets, sharedassets0.assets, level0: no item ID in any "
            "MonoBehaviour string; TextAssets are licensing/currency/typography only",
            "StreamingAssets scene, pooler, nav and screenloader bundles: 24 MonoBehaviours in nexus, "
            "sorcererseyrie, thenebulian logic prefabs and pre hold 14 bare item IDs with no other string",
            "IL2CPP string literals: item IDs appear only as resource paths and gathering reward debug text, never "
            "beside a display name",
            "ShopData/ItemData names and descriptions are server-supplied (EntryData deserialization) and absent "
            "from the client",
        ],
        "field_status": {"original_name": "not_recovered", "description": "not_recovered",
                         "historical_price": "not_recovered", "historical_store": "not_recovered",
                         "rarity_tier_brand": "not_recovered",
                         "derived_name": "preservation display label from internal asset names",
                         "season_hint": "derived from internal asset names; not a historical collection"},
        "coverage": {kind: dict(sorted(counts.items())) for kind, counts in sorted(coverage.items())},
        "missing_from_scan": [list(k) for k in missing],
        "items": items,
    }


def render(document):
    """Stable, diff-friendly text: readable header, one compact line per item."""
    header = {k: v for k, v in document.items() if k != "items"}
    body = json.dumps(header, ensure_ascii=False, indent=1)[:-2]
    lines = [json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in document["items"]]
    return body + ',\n "items": [\n' + ",\n".join(lines) + "\n ]\n}\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scan", type=Path, required=True, help="JSONL from recover_item_asset_metadata.py")
    parser.add_argument("--output", type=Path, required=True, help="Metadata JSON to write")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    rows = [json.loads(line) for line in args.scan.read_text(encoding="utf-8").splitlines() if line.strip()]
    document = build(rows, catalog_identities(repo), args.scan.name, sha256_file(args.scan))
    args.output.write_text(render(document), encoding="utf-8", newline="\n")
    print(json.dumps(document["coverage"], indent=1))


if __name__ == "__main__":
    main()
