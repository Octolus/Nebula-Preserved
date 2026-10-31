"""Publish trusted semantic interaction registries for Mirror instances."""

import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time

from allocation import NONMINI_PUBLIC_SCENES


def _f32(value):
    value = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    return 0.0 if value == 0.0 else value


def _entry(text, kind, classification, extension_arity=0):
    path, class_name, slot = text.split("|")
    if not slot.startswith("slot"):
        raise ValueError("invalid reviewed interaction slot")
    return {"kind": kind, "anchor": "__unresolved_dynamic_root__",
            "path": [int(v) for v in path.split("/") if v and v != "."],
            "class": class_name, "slot": int(slot[4:]), "ground_index": -1,
            "item_id": "", "classification": classification,
            "extension_arity": extension_arity}


class InteractionRegistryPublisher:
    # Exact empty static baselines used by the current apartment restoration
    # path. Other scenes remain unavailable to opt-in clients until a semantic
    # static manifest exists; legacy clients keep their existing behavior.
    EMPTY_STATIC_SCENES = set()
    # These reviewed relative keys prove component order/classification, but
    # not the dynamically instantiated logic-prefab root selector. Publishing
    # them as full runtime paths would be unsafe until the canonical root
    # namespace is source-bound on both client and server.
    UNRESOLVED_DYNAMIC_ROOT_SCENES = {"CampSilverLake", "CutteridgeEstate", "SorcerersEyrie1"}
    # Single source with backend allocation/lifecycle admission.
    PUBLIC_SCENES = NONMINI_PUBLIC_SCENES
    def __init__(self, store, protocol_dir):
        self.store = store
        self.protocol_dir = Path(protocol_dir)
        bridge_path = self.protocol_dir / "interaction-mapping-bridge.json"
        furniture_path = self.protocol_dir / "housing-interaction-manifest.json"
        static_path = self.protocol_dir / "static-interaction-manifest.json"
        self.bridge_hash = hashlib.sha256(bridge_path.read_bytes()).hexdigest()
        self.furniture_hash = hashlib.sha256(furniture_path.read_bytes()).hexdigest()
        self.static_hash = ""
        if static_path.exists():
            self.static_hash = hashlib.sha256(static_path.read_bytes()).hexdigest()
            self.scene_profiles = self._static_scene_profiles(json.loads(static_path.read_text(encoding="utf-8")))
            self.anchored_static = True
        else:
            self.scene_profiles = self._scene_profiles(json.loads(bridge_path.read_text(encoding="utf-8")))
            self.anchored_static = False
        furniture = json.loads(furniture_path.read_text(encoding="utf-8"))
        if furniture.get("format_version") != 1 or furniture.get("effective_ground_item_count") != 1035:
            raise ValueError("unsupported housing interaction manifest")
        self.furniture = {row["item_id"]: row for row in furniture["items"]}

    @staticmethod
    def _static_scene_profiles(document):
        if (document.get("format_version") != 1 or
                document.get("path_convention") != "anchor_relative_excludes_root_v1" or
                not isinstance(document.get("scenes"), list)):
            raise ValueError("unsupported static interaction manifest")
        profiles = {}
        for scene in document["scenes"]:
            if not isinstance(scene, dict) or not isinstance(scene.get("scene"), str):
                raise ValueError("invalid static scene row")
            entries, anchors = scene.get("entries"), scene.get("active_anchor_counts")
            complete = (scene.get("status") in {"complete_verified", "verified_empty"} and
                        scene.get("unresolved") == [] and isinstance(entries, list) and
                        isinstance(anchors, dict) and all(isinstance(k, str) and k and type(v) is int and v == 1
                                                         for k, v in anchors.items()) and
                        (scene.get("status") != "verified_empty" or entries == []))
            converted = []
            if complete:
                for entry in entries:
                    if (not isinstance(entry, dict) or entry.get("root") not in anchors or
                            entry.get("kind") not in {"generic", "occupable"} or
                            entry.get("source") not in {"geometry", "logic", "event"} or
                            entry.get("classification") not in {"ordinary", "deferred_minigame", "separate_protocol"} or
                            not isinstance(entry.get("path"), list) or
                            any(type(v) is not int or v < 0 for v in entry["path"]) or
                            not isinstance(entry.get("class"), str) or not entry["class"] or
                            type(entry.get("slot")) is not int or entry["slot"] < 0 or
                            type(entry.get("extension_arity")) is not int or not 0 <= entry["extension_arity"] <= 32):
                        complete = False
                        break
                    converted.append({"kind": entry["kind"], "anchor": entry["root"],
                        "path": entry["path"], "class": entry["class"], "slot": entry["slot"],
                        "ground_index": -1, "item_id": "", "classification": entry["classification"],
                        "extension_arity": entry["extension_arity"]})
            profiles[scene["scene"]] = {"available": complete,
                "bundle_sha256": scene.get("bundle_sha256", ""),
                "entries": sorted(converted, key=lambda v: (v["kind"], v["anchor"], v["path"], v["class"], v["slot"])) if complete else [],
                "status": scene.get("status", "unresolved")}
        return profiles

    @staticmethod
    def _scene_profiles(document):
        profiles = {}
        for row in document["static_registry"]["profiles"]:
            scene, entries = row["scene"], []
            if scene == "CampSilverLake":
                entries += [_entry(v, "generic", "ordinary") for v in row["ordinary_keys"]]
                entries.append(_entry(row["deferred"], "generic", "deferred_minigame"))
            elif scene == "CutteridgeEstate":
                entries += [_entry(v, "generic", "ordinary") for v in row["ordinary_generic_keys"]]
                entries += [_entry(v, "occupable", "ordinary") for v in row["ordinary_occupable_keys"]]
                entries.append(_entry(row["deferred"], "generic", "deferred_minigame"))
            elif scene == "SorcerersEyrie1":
                entries.append(_entry(row["ordinary_key"], "generic", "ordinary"))
                entries += [_entry(v, "generic", "deferred_minigame") for v in row["deferred_keys"]]
            else:
                raise ValueError("unknown reviewed static interaction scene")
            profiles[scene] = {"bundle_sha256": row["bundle_sha256"],
                               "entries": sorted(entries, key=lambda v: (v["kind"], v["path"], v["class"], v["slot"]))}
        return profiles

    @staticmethod
    def _digest(value):
        body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def _layout(self, instance_id):
        row = self.store.db.execute("SELECT layout_json,updated_at FROM housing_layouts WHERE instance_id=?",
                                    (instance_id,)).fetchone()
        return (None, 0.0) if not row else (json.loads(row[0]), float(row[1]))

    def _instance(self, binding):
        scene = binding["psidglobal"]
        profile = self.scene_profiles.get(scene)
        dynamic_root_unresolved = (not self.anchored_static and scene in self.UNRESOLVED_DYNAMIC_ROOT_SCENES)
        static_available = ((profile is not None and profile.get("available", True) and not dynamic_root_unresolved) or
                            (not self.anchored_static and scene in self.EMPTY_STATIC_SCENES))
        static_entries = [] if not static_available or profile is None else profile["entries"]
        layout, updated_at = self._layout(binding["instance_id"])
        ground_sig, furniture_entries, errors = [], [], []
        if dynamic_root_unresolved:
            errors.append("static_dynamic_root_normalization_unresolved")
        elif not static_available:
            errors.append("static_interaction_manifest_unavailable" if not self.anchored_static
                          else "static_interaction_manifest_unresolved")
        if layout:
            keys = ("aidasset", "aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r")
            if any(not isinstance(layout.get(key), list) for key in keys):
                errors.append("layout_arrays_missing")
            elif len({len(layout[key]) for key in keys}) != 1:
                errors.append("layout_arrays_mismatched")
            else:
                compact_index = 0
                for source_index, item_id in enumerate(layout["aidasset"]):
                    if item_id == "null":
                        continue
                    item = self.furniture.get(item_id)
                    values = [layout[key][source_index] for key in keys[1:]]
                    if item is None or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                                           for v in values):
                        errors.append("untrusted_ground_item_or_transform")
                        compact_index += 1
                        continue
                    ground_sig.append({"item_id": item_id, "index": compact_index,
                                       "tx": _f32(values[0]), "ty": _f32(values[1]),
                                       "tz": _f32(values[2]), "r": _f32(values[3])})
                    if item["status"] == "interactive_verified":
                        for component in item["interactions"]:
                            if component.get("admission") != "allow":
                                continue
                            furniture_entries.append({"kind": component["registry_kind"], "anchor": "",
                                "path": component["sibling_index_chain"], "class": component["class"],
                                "slot": component["component_slot"], "ground_index": compact_index,
                                "item_id": item_id, "classification": component["classification"],
                                "extension_arity": component["extension_arity"]})
                    elif item["status"] != "noninteractive_verified_empty":
                        errors.append("layout_contains_unresolved_interaction_item")
                    compact_index += 1
        epoch_body = {"scene": scene, "static": static_entries, "ground_sig": ground_sig,
                      "furniture": furniture_entries}
        return {"instance_id": binding["instance_id"], "scene": scene,
                "owner_ps4_id": binding["owner_ps4_id"], "trusted": not errors,
                "errors": sorted(set(errors)), "static_profile_available": static_available,
                "static_bundle_sha256": "" if profile is None else profile["bundle_sha256"],
                "static_entries": static_entries, "ground_sig": ground_sig,
                "furniture_entries": furniture_entries, "layout_updated_at": updated_at,
                "epoch": self._digest(epoch_body)}

    def export(self, state_dir):
        rows = {row["instance_id"]: dict(row) for row in self.store.db.execute(
            "SELECT instance_id,psidglobal,owner_ps4_id FROM housing_spaces ORDER BY instance_id").fetchall()}
        registry = Path(state_dir) / "instances"
        try:
            for directory in registry.iterdir():
                if not directory.is_dir() or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", directory.name):
                    continue
                try:
                    path = directory / "instance-status.json"
                    if path.stat().st_size > 65536:
                        continue
                    status = json.loads(path.read_text(encoding="utf-8-sig"))
                    if (status.get("format_version") == 1 and status.get("instance_id") == directory.name and
                            status.get("psidglobal") in self.PUBLIC_SCENES and directory.name not in rows):
                        rows[directory.name] = {"instance_id": directory.name,
                                                "psidglobal": status["psidglobal"], "owner_ps4_id": ""}
                except (OSError, ValueError, TypeError):
                    continue
        except OSError:
            pass
        document = {"format_version": 1, "generation": time.time(),
                    "bridge_manifest_sha256": self.bridge_hash,
                    "static_manifest_sha256": self.static_hash,
                    "furniture_manifest_sha256": self.furniture_hash,
                    "instances": [self._instance(rows[key]) for key in sorted(rows)]}
        path = Path(state_dir) / "instance-interactions.json"
        self.store._publish_snapshot(path, json.dumps(document, ensure_ascii=True, separators=(",", ":")))
        return path
