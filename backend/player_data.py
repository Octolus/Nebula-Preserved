"""Operator view and audited edits of a player's saved game state.

Management owns routing, authorization, idempotency, the Store.atomic group
and the append-only audit; this module owns no listener or schema. Edits touch
only rows the game already persists, mirror the native handlers' own rules and
never invent client data. A connected client may keep cached copies of
presets, preferences or position until it next loads them from the server.
"""
from __future__ import annotations

import json
import math
import re
import time

from apartments import NATIVE_DEFAULT_APARTMENT
from housing import PERSONAL_SPACE_SCENES
from management import ManagementError, fields, require, text
from state import DEFAULT_PREFS, canonical_platform
from wire import ProtocolError, json_field

GENDERS = ("MALE", "FEMALE")
ITEM_KINDS = ("wardrobe", "companions", "locomotions", "housing")
RESOURCE_KINDS = {"companions": "companion", "locomotions": "locomotion"}
HEAVY = ("asset_metadata", "dependencies", "category_evidence")
RELATIONS = ("friend", "favorite", "block", "silenced")
GROUND = ("aidasset", "aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r")
SLOTS = 40
MAX_SPACE = 200
NOT_WIRE = re.compile(r"[#!/\\\x00-\x1f\x7f]")
SECTIONS = (("presets", "Saved outfits"), ("items", "Owned items"), ("preferences", "Settings"),
            ("social", "Friends & blocks"), ("housing", "Apartments"), ("resources", "Companions & locomotions"),
            ("position", "Last position"), ("consumables", "Consumables"))
# key: (label, group, type, minimum, maximum). Ranges are local validation policy.
PREFERENCES = {
    "status": ("Status message", "Profile", "text", 0, 128),
    "mood": ("Mood", "Profile", "digits", 0, 3),
    "DisplayOthersName": ("Show other players' names", "Display", "flag", 0, 1),
    "DisplayOthersStatus": ("Show other players' status", "Display", "flag", 0, 1),
    "DisplayOthersMood": ("Show other players' mood", "Display", "flag", 0, 1),
    "DisplayMyName": ("Show my name", "Display", "flag", 0, 1),
    "DisplayMyStatus": ("Show my status", "Display", "flag", 0, 1),
    "DisplayMyMood": ("Show my mood", "Display", "flag", 0, 1),
    "MasterVolume": ("Master volume", "Audio", "number", 0.0, 1.0),
    "Music": ("Music volume", "Audio", "number", 0.0, 1.0),
    "Fx": ("Effects volume", "Audio", "number", 0.0, 1.0),
    "Ambient": ("Ambient volume", "Audio", "number", 0.0, 1.0),
    "InvertYAxis": ("Invert Y axis", "Controls", "flag", 0, 1),
    "velocityCam": ("Camera speed", "Controls", "number", 0.0, 10.0),
    "ProfanityFilter": ("Profanity filter", "Chat", "flag", 0, 1),
    "ChatFontSize": ("Chat font size", "Chat", "number", 1.0, 100.0),
    "NameColorSelectedIndex_r": ("Name color (red)", "Profile", "number", 0.0, 1.0),
    "NameColorSelectedIndex_g": ("Name color (green)", "Profile", "number", 0.0, 1.0),
    "NameColorSelectedIndex_b": ("Name color (blue)", "Profile", "number", 0.0, 1.0),
    "spaceTutorialPhase": ("Apartment tutorial progress", "Tutorials", "digits", 0, 3),
    "editorTutorialPhase": ("Editor tutorial progress", "Tutorials", "digits", 0, 3),
    "notificationLoginFriend": ("Friend login notifications", "Notifications", "flag", 0, 1),
    "ShowPets": ("Show companions", "Display", "flag", 0, 1),
    "PlatformOnly": ("Same-platform players only", "Social", "flag", 0, 1),
}
DEFAULTS = {**DEFAULT_PREFS, "ShowPets": None, "PlatformOnly": 0}


def spaced(value):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)


def preset_name(value, label="preset name"):
    text(value, label, maximum=64)
    require(not NOT_WIRE.search(value) and value == value.strip(), "Invalid " + label)
    return value


def gender(value):
    require(value in GENDERS, "Gender must be MALE or FEMALE")
    return value


class PlayerData:
    def __init__(self, manager):
        self.manager = manager
        self.service, self.db = manager.service, manager.db
        self.store = manager.store
        defaults = json.loads((self.service.catalog.protocol_dir / "avatar-default-catalog.json").read_text(encoding="utf-8"))
        self.starter = {(g, row["item_id"]) for g in GENDERS for row in defaults["defaults"][g]["items"]}

    # ---- shared helpers -------------------------------------------------
    def _table(self, name):
        return self.db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def _page(self, items, query, **extra):
        limit, offset = self.manager.pagination(query)
        return {"items": items[offset:offset + limit], "total": len(items), "limit": limit,
                "next_cursor": str(offset + limit) if offset + limit < len(items) else None, **extra}

    def _assets(self, rows):
        result = []
        for row in self.manager._with_assets(rows):
            for key in HEAVY:
                row.pop(key, None)
            offers = row.pop("offers", None) or []
            offer = next((o for o in offers if o.get("active")), None)
            row["label"] = row.get("readable_name") or (offer or {}).get("name") or row.get("name") or row["item_id"]
            row["offer_ids"] = [o["offer_id"] for o in offers]
            result.append(row)
        return result

    def _profile(self, account_id):
        return self.manager.profile(account_id)

    def _selected(self, account_id, sex):
        row = self.db.execute("SELECT name FROM preset_selection WHERE ps4_id=? AND gender=?", (account_id, sex)).fetchone()
        if row and self.db.execute("SELECT 1 FROM presets WHERE ps4_id=? AND name=? AND gender=?", (account_id, row[0], sex)).fetchone():
            return row[0]
        latest = self.db.execute("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY updated_at DESC,name LIMIT 1", (account_id, sex)).fetchone()
        return latest[0] if latest else None

    def _preset_row(self, account_id, name, sex):
        row = self.db.execute("SELECT * FROM presets WHERE ps4_id=? AND name=? AND gender=?", (account_id, name, sex)).fetchone()
        require(row is not None, "Saved outfit not found", 404, "not_found")
        return dict(row)

    @staticmethod
    def _asset_pairs(assets_json):
        parts = (json.loads(assets_json).get("data") or "").split("!")
        half = len(parts) // 2 if parts != [""] else 0
        return dict(zip(parts[:half], parts[half:]))

    def _outfit(self, account_id, row):
        preset = json.loads(row["preset_json"])
        categories = self._asset_pairs(row["assets_json"])
        owned = {r[0] for r in self.db.execute("SELECT item_id FROM entitlements WHERE ps4_id=? AND gender=?", (account_id, row["gender"]))}
        items = []
        for slot in range(1, SLOTS + 1):
            item = preset.get("item" + str(slot))
            if not isinstance(item, str) or item in ("", "null"):
                continue
            color = {c: preset.get("itemColor%d_%s" % (slot, c)) for c in "rgb"}
            category = categories.get(item)
            if category is None:
                try:
                    category = self.service.catalog.resolve(item, row["gender"])["category"]
                except ProtocolError:
                    pass
            items.append({"kind": "wardrobe", "slot": slot, "item_id": item, "gender": row["gender"],
                          "category": category, "owned": item in owned,
                          "starter": (row["gender"], item) in self.starter,
                          "color": color if all(isinstance(v, (int, float)) for v in color.values()) else None})
        return self._assets(items)

    def _preset_view(self, account_id, row, selected, active_gender, detail=False):
        preset = json.loads(row["preset_json"])
        items = self._outfit(account_id, row)
        value = {"preset_name": row["name"], "gender": row["gender"], "updated_at": row["updated_at"],
                 "selected": row["name"] == selected, "active": row["name"] == selected and row["gender"] == active_gender,
                 "item_count": len(items), "unowned_item_count": sum(not i["owned"] for i in items)}
        if detail:
            value.update(items=items, appearance={
                "skin_color": {c: preset.get("skin_color_" + c) for c in "rgb"},
                "hair_color": {c: preset.get("skin_hairbasecolor_" + c) for c in "rgb"},
                "eye_color": {c: preset.get("skin_coloreye_" + c) for c in "rgb"},
                "high_heel": preset.get("highHeel")}, field_count=len(preset),
                saved_position={k[len("lastPosition_"):]: v for k, v in json.loads(row["position_json"]).items()
                                if k.startswith("lastPosition_")})
        else:
            value["preview_items"] = items[:6]
        return value

    def _selection(self, account_id):
        if not self._table("resource_selections"):
            return None
        return {kind: tuple(r) for kind, *r in self.db.execute(
            "SELECT kind,item_id,revision,updated_at FROM resource_selections WHERE ps4_id=?", (account_id,))}

    def _equipped(self, account_id):
        selection = self._selection(account_id)
        result = {"selection_supported": selection is not None}
        for kind, stem in RESOURCE_KINDS.items():
            item, revision = (selection or {}).get(kind, ("", 0, 0))[:2]
            row = None
            if item:
                row = self._assets([{"kind": kind, "item_id": item}])[0]
                row["owned"] = self.db.execute("SELECT 1 FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?",
                                               (account_id, kind, item)).fetchone() is not None
            result[stem] = row
            result[stem + "_revision"] = revision
        return result

    def _position(self, account_id):
        row = self.db.execute("SELECT x,y,z,updated_at FROM positions WHERE ps4_id=?", (account_id,)).fetchone()
        stored = {"position": {"x": row[0], "y": row[1], "z": row[2]}, "updated_at": row[3]} if row else None
        try:
            live = self.store.position(account_id)
        except (ProtocolError, OSError, ValueError):
            live = None
        source = "default"
        if live and live["updated_at"] and (not stored or live["updated_at"] != stored["updated_at"]):
            source = "live_instance"
        elif stored:
            source = "saved"
        current = live if source == "live_instance" else stored or {"position": {"x": 0.0, "y": 0.0, "z": 0.0}, "updated_at": 0.0}
        return {"position": current["position"], "updated_at": current["updated_at"], "source": source, "saved": stored}

    def _identity(self, account_id):
        profile = self._profile(account_id)
        return profile["username"], canonical_platform(profile["platform"])

    def _kinds(self, owner, target, platform):
        return {r[0] for r in self.db.execute("SELECT kind FROM relations WHERE ps4_id=? AND target=? AND target_platform=?", (owner, target, platform))}

    def _resolve(self, target, platform):
        matches = [r[0] for r in self.db.execute("SELECT ps4_id,platform FROM profiles WHERE username=?", (target,))
                   if canonical_platform(r[1]) == platform]
        return matches[0] if len(matches) == 1 else None

    def _social_rows(self, account_id, query):
        direction, kind = query.get("direction", "outgoing"), query.get("kind", "")
        require(direction in ("outgoing", "incoming"), "Invalid social direction")
        require(kind in ("", *RELATIONS), "Invalid social relation kind")
        me = self._identity(account_id)
        if direction == "outgoing":
            pairs = [(r[0], r[1], self._resolve(r[0], r[1])) for r in self.db.execute(
                "SELECT DISTINCT target,target_platform FROM relations WHERE ps4_id=? ORDER BY target,target_platform", (account_id,))]
        else:
            pairs = [(*self._identity(r[0]), r[0]) for r in self.db.execute(
                "SELECT DISTINCT ps4_id FROM relations WHERE target=? AND target_platform=? AND ps4_id<>? ORDER BY ps4_id", (*me, account_id))]
        items = []
        for target, platform, other in pairs:
            kinds = self._kinds(account_id, target, platform)
            reverse = self._kinds(other, *me) if other else set()
            if kind and kind not in (kinds if direction == "outgoing" else reverse):
                continue
            items.append({"target": target, "target_platform": platform, "target_account_id": other,
                          "relations": sorted(kinds), "is_friend": "friend" in kinds, "is_favorite": "favorite" in kinds,
                          "is_blocked": "block" in kinds, "is_silenced": "silenced" in kinds,
                          "their_relations": sorted(reverse), "mutual_friend": "friend" in kinds and "friend" in reverse,
                          "blocked_by_them": "block" in reverse})
        return items

    def _layout(self, instance_id):
        row = self.db.execute("SELECT layout_json,updated_at FROM housing_layouts WHERE instance_id=?", (instance_id,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else (None, None)

    def _space_view(self, row, detail=False):
        housing = self.service.housing
        layout, updated = self._layout(row["instance_id"])
        layout = layout or housing.empty_layout(row["psidglobal"])
        ground = [(i, x) for i, x in enumerate(layout["aidasset"]) if x != "null"]
        wall_slots, ceiling_slots = housing.space_slots.get(row["logical_space_key"], (None, None))
        placed = [x for _, x in ground] + layout["aidassetWall"] + layout["aidassetCeiling"]
        stage = self.db.execute("SELECT state FROM housing_save_stages WHERE instance_id=?", (row["instance_id"],)).fetchone()
        key = row["logical_space_key"]
        value = {"instance_id": row["instance_id"], "space_key": key,
                 "space_label": spaced(key), "scene": row["psidglobal"], "created_at": row["created_at"],
                 "default": key == NATIVE_DEFAULT_APARTMENT, "starter": key in self.service.apartments.spaces,
                 "removable": key != NATIVE_DEFAULT_APARTMENT,
                 "layout_saved": updated is not None, "layout_updated_at": updated, "placed_count": len(placed),
                 "ground_count": len(ground), "wall_count": len(layout["aidassetWall"]),
                 "ceiling_count": len(layout["aidassetCeiling"]),
                 "placement_used": sum(housing.catalog.get(x, {}).get("placement_cost", 1) for x in placed),
                 "placement_max": MAX_SPACE, "wall_slots": wall_slots, "ceiling_slots": ceiling_slots,
                 "save_in_progress": stage is not None, "save_state": stage[0] if stage else None}
        if detail:
            items = [{"kind": "housing", "item_id": x, "placement": "ground", "index": i,
                      "position": {a: layout["aidasset_t" + a][i] for a in "xyz"}, "rotation": layout["aidasset_r"][i]}
                     for i, x in ground]
            for placement, ids, slots in (("wall", "aidassetWall", "aidassetWallSlot"), ("ceiling", "aidassetCeiling", "aidassetCeilingSlot")):
                items += [{"kind": "housing", "item_id": x, "placement": placement, "index": i, "slot": layout[slots][i]}
                          for i, x in enumerate(layout[ids])]
            value["items"] = self._assets(items)
        return value

    def _spaces(self, account_id):
        return [dict(r) for r in self.db.execute("SELECT * FROM housing_spaces WHERE owner_ps4_id=? ORDER BY logical_space_key", (account_id,))]

    def _owned_rows(self, account_id):
        rows = [{"kind": "wardrobe", **dict(r)} for r in self.db.execute(
            "SELECT item_id,gender,category,display_name,granted_at,asset_status FROM entitlements WHERE ps4_id=? ORDER BY item_id,gender,category", (account_id,))]
        rows += [dict(r) for r in self.db.execute(
            "SELECT kind,item_id,NULL AS gender,NULL AS category,display_name,granted_at FROM resource_entitlements WHERE ps4_id=? ORDER BY kind,item_id", (account_id,))]
        rows += [{"kind": "housing", **dict(r)} for r in self.db.execute(
            "SELECT item_id,NULL AS gender,NULL AS category,display_name,granted_at FROM housing_entitlements WHERE ps4_id=? ORDER BY item_id", (account_id,))]
        return rows

    # ---- reads ----------------------------------------------------------
    def read(self, account_id, path, query):
        profile = self._profile(account_id)
        if not path:
            return self._overview(profile)
        section = path[0]
        if section == "presets" and len(path) == 1:
            sex = query.get("gender", "")
            require(sex in ("", *GENDERS), "Gender must be MALE or FEMALE")
            selected = {g: self._selected(account_id, g) for g in GENDERS}
            rows = [dict(r) for r in self.db.execute("SELECT * FROM presets WHERE ps4_id=? AND (?='' OR gender=?) ORDER BY gender,name", (account_id, sex, sex))]
            page = self._page(rows, query, selected=selected, active_gender=profile["gender"])
            page["items"] = [self._preset_view(account_id, r, selected[r["gender"]], profile["gender"]) for r in page["items"]]
            return page
        if section == "presets" and len(path) == 3:
            sex = gender(path[2])
            row = self._preset_row(account_id, path[1], sex)
            value = self._preset_view(account_id, row, self._selected(account_id, sex), profile["gender"], detail=True)
            if query.get("raw") == "1":
                value["raw"] = {"preset": json.loads(row["preset_json"]), "assets": json.loads(row["assets_json"]),
                                "position": json.loads(row["position_json"])}
            return value
        require(len(path) == 1 or (section == "housing" and len(path) == 2), "Character section not found", 404, "not_found")
        if section == "housing-options":
            owned = {r["logical_space_key"] for r in self._spaces(account_id)}
            starter = self.service.apartments.spaces
            items = [{"space_key": key, "space_label": spaced(key), "owned": key in owned,
                      "default": key == NATIVE_DEFAULT_APARTMENT, "starter": key in starter}
                     for key in sorted(PERSONAL_SPACE_SCENES, key=lambda k: (k != NATIVE_DEFAULT_APARTMENT, spaced(k)))]
            return {"items": items, "total": len(items)}
        if section == "items":
            kind, search = query.get("kind", ""), query.get("q", "")
            require(kind in ("", *ITEM_KINDS), "Unsupported item kind")
            require(isinstance(search, str) and len(search) <= 128, "Invalid item search")
            equipped = {}
            for row in self.db.execute("SELECT name,gender,preset_json FROM presets WHERE ps4_id=?", (account_id,)):
                preset = json.loads(row["preset_json"])
                for slot in range(1, SLOTS + 1):
                    equipped.setdefault((row["gender"], preset.get("item" + str(slot))), []).append(row["name"])
            placed = {}
            for space in self._spaces(account_id):
                layout, _ = self._layout(space["instance_id"])
                for item in (layout or {}).get("aidasset", []) + (layout or {}).get("aidassetWall", []) + (layout or {}).get("aidassetCeiling", []):
                    placed.setdefault(item, set()).add(space["logical_space_key"])
            selection = self._selection(account_id) or {}
            rows = [r for r in self._owned_rows(account_id) if not kind or r["kind"] == kind]
            items = []
            for row in self._assets(rows):
                if row["kind"] == "wardrobe":
                    row["equipped_in"] = sorted(equipped.get((row["gender"], row["item_id"]), []))
                    row["starter"] = (row["gender"], row["item_id"]) in self.starter
                    row["revocable"] = not row["starter"]
                else:
                    row["equipped_in"] = []
                    row["equipped"] = row["kind"] in RESOURCE_KINDS and selection.get(row["kind"], ("",))[0] == row["item_id"]
                    row["placed_in"] = sorted(placed.get(row["item_id"], ())) if row["kind"] == "housing" else []
                    row["revocable"] = True
                if search.casefold() in " ".join(str(row.get(k) or "") for k in ("item_id", "label", "display_name", "category", "category_label")).casefold():
                    items.append(row)
            return self._page(items, query)
        if section == "preferences":
            stored = {r[0]: json.loads(r[1]) for r in self.db.execute("SELECT key,value FROM preferences WHERE ps4_id=?", (account_id,))}
            items = []
            for key, (label, group, kind, low, high) in PREFERENCES.items():
                items.append({"key": key, "label": label, "group": group, "type": kind,
                              "value": stored.get(key, DEFAULTS[key]), "default": DEFAULTS[key], "stored": key in stored,
                              "editable": True, "minimum": low, "maximum": high})
            items += [{"key": key, "label": spaced(key), "group": "Other", "type": "unknown", "value": value,
                       "default": None, "stored": True, "editable": False, "minimum": None, "maximum": None}
                      for key, value in sorted(stored.items()) if key not in PREFERENCES]
            return self._page(items, query)
        if section == "social":
            return self._page(self._social_rows(account_id, query), query)
        if section == "housing" and len(path) == 1:
            return self._page([self._space_view(r) for r in self._spaces(account_id)], query)
        if section == "housing":
            row = self.db.execute("SELECT * FROM housing_spaces WHERE instance_id=? AND owner_ps4_id=?", (path[1], account_id)).fetchone()
            require(row is not None, "Apartment not found", 404, "not_found")
            return self._space_view(dict(row), detail=True)
        if section == "resources":
            selection = self._selection(account_id) or {}
            rows = [r for r in self._owned_rows(account_id) if r["kind"] in RESOURCE_KINDS]
            items = [{**r, "equipped": selection.get(r["kind"], ("",))[0] == r["item_id"]} for r in self._assets(rows)]
            return self._page(items, query, equipped=self._equipped(account_id))
        if section == "position":
            value = self._position(account_id)
            value["preset_positions"] = [{"preset_name": r["name"], "gender": r["gender"],
                                          **{k[len("lastPosition_"):]: v for k, v in json.loads(r["position_json"]).items() if k.startswith("lastPosition_")}}
                                         for r in self.db.execute("SELECT name,gender,position_json FROM presets WHERE ps4_id=? ORDER BY gender,name", (account_id,))]
            return value
        if section == "consumables":
            items = []
            if self._table("consumable_balances"):
                items = [{**dict(r), "label": {"coffee": "Coffee", "oktoberfest": "Oktoberfest drinks"}.get(r["kind"], r["kind"]),
                          "rewarded": bool(r["rewarded"])}
                         for r in self.db.execute("SELECT kind,units,prop_use_count,reward_index,rewarded,updated_at FROM consumable_balances WHERE ps4_id=? ORDER BY kind", (account_id,))]
            return self._page(items, query)
        require(False, "Character section not found", 404, "not_found")

    def _overview(self, profile):
        account_id, active = profile["account_id"], profile["gender"]
        genders, outfit = {}, None
        for sex in GENDERS:
            selected = self._selected(account_id, sex)
            count = self.db.execute("SELECT COUNT(*) FROM presets WHERE ps4_id=? AND gender=?", (account_id, sex)).fetchone()[0]
            genders[sex] = {"selected_preset": selected, "preset_count": count}
            if sex == active and selected:
                row = self._preset_row(account_id, selected, sex)
                items = self._outfit(account_id, row)
                outfit = {"gender": sex, "preset_name": selected, "updated_at": row["updated_at"], "items": items, "item_count": len(items)}
        counts = {kind: n for kind, n in self.db.execute("SELECT 'wardrobe',COUNT(*) FROM entitlements WHERE ps4_id=? UNION ALL SELECT 'housing',COUNT(*) FROM housing_entitlements WHERE ps4_id=?", (account_id, account_id))}
        for kind in RESOURCE_KINDS:
            counts[kind] = self.db.execute("SELECT COUNT(*) FROM resource_entitlements WHERE ps4_id=? AND kind=?", (account_id, kind)).fetchone()[0]
        prefs = self.store.preferences(account_id)
        stored_prefs = self.db.execute("SELECT COUNT(*) FROM preferences WHERE ps4_id=?", (account_id,)).fetchone()[0]
        relation = dict(self.db.execute("SELECT kind,COUNT(*) FROM relations WHERE ps4_id=? GROUP BY kind", (account_id,)).fetchall())
        social = {"friends": relation.get("friend", 0), "favorites": relation.get("favorite", 0),
                  "blocked": relation.get("block", 0), "silenced": relation.get("silenced", 0)}
        spaces = self._spaces(account_id)
        housing = {"apartments": len(spaces), "layouts_saved": sum(self._layout(s["instance_id"])[1] is not None for s in spaces),
                   "furniture_owned": counts["housing"], "apartment_names": [spaced(s["logical_space_key"]) for s in spaces]}
        consumables = [dict(r) for r in self.db.execute("SELECT kind,units FROM consumable_balances WHERE ps4_id=? ORDER BY kind", (account_id,))] if self._table("consumable_balances") else []
        presets = sum(g["preset_count"] for g in genders.values())
        position = self._position(account_id)
        section_counts = {"presets": presets, "items": sum(counts.values()), "preferences": len(PREFERENCES),
                          "social": self.db.execute("SELECT COUNT(*) FROM (SELECT DISTINCT target,target_platform FROM relations WHERE ps4_id=?)", (account_id,)).fetchone()[0],
                          "housing": len(spaces), "resources": counts["companions"] + counts["locomotions"],
                          "position": 1, "consumables": len(consumables)}
        return {"account_id": account_id, "username": profile["username"], "online": bool(profile["online"]),
                "gender": active, "outfit": outfit, "genders": genders, "equipped": self._equipped(account_id),
                "position": position,
                "summaries": {"presets": {"count": presets, **{g.lower(): v for g, v in genders.items()}},
                              "items": counts,
                              "preferences": {"stored": stored_prefs, "status": prefs.get("status"), "mood": prefs.get("mood")},
                              "social": social, "housing": housing, "consumables": consumables},
                "sections": [{"id": key, "label": label, "count": section_counts[key], "editable": key != "consumables"}
                             for key, label in SECTIONS],
                "live_changes_note": "Edits are saved immediately; a connected client may show cached data until its next login or load."}

    # ---- mutations ------------------------------------------------------
    def change(self, account_id, path, body, actor, request_id):
        handlers = {("items", "revoke"): self._revoke, ("presets", "delete"): self._delete_preset,
                    ("presets", "select"): self._select_preset, ("presets", "rename"): self._rename_preset,
                    ("preferences", "set"): self._set_preference, ("social", "remove"): self._remove_relation,
                    ("position", "reset"): self._reset_position, ("housing", "reset-layout"): self._reset_layout,
                    ("housing", "grant"): self._grant_space, ("housing", "remove"): self._remove_space,
                    ("resources", "select"): self._select_resource}
        handler = handlers.get(tuple(path))
        require(handler is not None, "Character change not supported", 404, "not_found")
        self._profile(account_id)
        return handler(account_id, body)

    def _live(self, value):
        return {**value, "applies_on_next_login": True}

    def _revoke(self, account_id, body):
        fields(body, ("kind", "item_id", "gender", "category", "reason"))
        kind, item_id = body.get("kind"), text(body.get("item_id"), "item ID")
        require(kind in ITEM_KINDS, "Unsupported item kind")
        if kind != "wardrobe":
            require(not ({"gender", "category"} & body.keys()), "Only wardrobe items have gender/category")
        if kind == "wardrobe":
            for key in ("gender", "category"):
                require(key not in body or (isinstance(body[key], str) and len(body[key]) <= 64), "Invalid " + key)
            rows = [dict(r) for r in self.db.execute("SELECT * FROM entitlements WHERE ps4_id=? AND item_id=?", (account_id, item_id))
                    if body.get("gender") in (None, r["gender"]) and body.get("category") in (None, r["category"])]
            require(rows, "Item is not owned", 404, "not_found")
            require(len(rows) == 1, "Item is owned in several variants; supply gender and category", 409, "conflict")
            row = rows[0]
            require((row["gender"], item_id) not in self.starter, "Starter body items are required by the default avatar and cannot be revoked", 409, "conflict")
            before = {"kind": kind, "item_id": item_id, "gender": row["gender"], "category": row["category"],
                      "display_name": row["display_name"], "owned": True}
            unequipped = []
            for preset in [dict(r) for r in self.db.execute("SELECT * FROM presets WHERE ps4_id=? AND gender=? ORDER BY name", (account_id, row["gender"]))]:
                value = json.loads(preset["preset_json"])
                slots = [s for s in range(1, SLOTS + 1) if value.get("item" + str(s)) == item_id]
                if not slots:
                    continue
                for slot in slots:
                    value["item" + str(slot)] = "null"
                pairs = self._asset_pairs(preset["assets_json"])
                pairs.pop(item_id, None)
                assets = {**json.loads(preset["assets_json"]), "data": "!".join([*pairs, *pairs.values()])}
                self.db.execute("UPDATE presets SET preset_json=?,assets_json=? WHERE ps4_id=? AND name=? AND gender=?",
                                (json_field(value), json_field(assets), account_id, preset["name"], preset["gender"]))
                unequipped.append(preset["name"])
            self.db.execute("DELETE FROM entitlements WHERE ps4_id=? AND item_id=? AND gender=? AND category=?",
                            (account_id, item_id, row["gender"], row["category"]))
            after = {**before, "owned": False, "unequipped_from_presets": unequipped}
        elif kind in RESOURCE_KINDS:
            row = self.db.execute("SELECT display_name FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?", (account_id, kind, item_id)).fetchone()
            require(row is not None, "Item is not owned", 404, "not_found")
            before = {"kind": kind, "item_id": item_id, "display_name": row[0], "owned": True}
            self.db.execute("DELETE FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?", (account_id, kind, item_id))
            selection = (self._selection(account_id) or {}).get(kind)
            unequipped = bool(selection and selection[0] == item_id)
            if unequipped:  # Same invalidation SelectionAuthority.snapshot applies.
                self.db.execute("UPDATE resource_selections SET item_id='',revision=revision+1,updated_at=? WHERE ps4_id=? AND kind=?",
                                (time.time(), account_id, kind))
            after = {**before, "owned": False, "unequipped": unequipped}
        else:
            row = self.db.execute("SELECT display_name FROM housing_entitlements WHERE ps4_id=? AND item_id=?", (account_id, item_id)).fetchone()
            require(row is not None, "Item is not owned", 404, "not_found")
            before = {"kind": kind, "item_id": item_id, "display_name": row[0], "owned": True}
            removed = []
            for space in self._spaces(account_id):
                layout, _ = self._layout(space["instance_id"])
                if not layout:
                    continue
                keep = [i for i, x in enumerate(layout["aidasset"]) if x != item_id]
                count = len(layout["aidasset"]) - len(keep)
                for key in GROUND:
                    layout[key] = [layout[key][i] for i in keep]
                for ids, slots in (("aidassetWall", "aidassetWallSlot"), ("aidassetCeiling", "aidassetCeilingSlot")):
                    keep = [i for i, x in enumerate(layout[ids]) if x != item_id]
                    count += len(layout[ids]) - len(keep)
                    layout[ids], layout[slots] = [layout[ids][i] for i in keep], [layout[slots][i] for i in keep]
                if count:
                    self.db.execute("UPDATE housing_layouts SET layout_json=?,updated_at=? WHERE instance_id=?",
                                    (json_field(layout), time.time(), space["instance_id"]))
                    removed.append({"instance_id": space["instance_id"], "space_key": space["logical_space_key"], "removed": count})
            self.db.execute("DELETE FROM housing_entitlements WHERE ps4_id=? AND item_id=?", (account_id, item_id))
            after = {**before, "owned": False, "removed_from_layouts": removed}
        receipts = self.db.execute("""SELECT COUNT(*) FROM shop_owned s JOIN shop_offers o USING(offer_id)
            WHERE s.ps4_id=? AND o.kind=? AND o.item_id=?""", (account_id, kind, item_id)).fetchone()[0] if self._table("shop_owned") else 0
        after["purchase_receipts_retained"] = receipts
        return before, self._live(after), True

    def _preset_body(self, account_id, body, extra=()):
        fields(body, ("name", "gender", "reason", *extra))
        # Existing names are looked up exactly; only new names are restricted.
        name, sex = text(body.get("name"), "preset name"), gender(body.get("gender"))
        return name, sex, self._preset_row(account_id, name, sex)

    def _preset_state(self, account_id, sex):
        return {"gender": sex, "selected_preset": self._selected(account_id, sex),
                "presets": [r[0] for r in self.db.execute("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY name", (account_id, sex))],
                "active_gender": self._profile(account_id)["gender"]}

    def _delete_preset(self, account_id, body):
        name, sex, _row = self._preset_body(account_id, body)
        before = self._preset_state(account_id, sex)
        require(len(before["presets"]) > 1, "The last saved outfit for a character cannot be deleted", 409, "conflict")
        # Mirrors RemovePresetServlet: the newest remaining outfit becomes selected.
        self.db.execute("DELETE FROM presets WHERE ps4_id=? AND name=? AND gender=?", (account_id, name, sex))
        current = self.db.execute("SELECT name FROM preset_selection WHERE ps4_id=? AND gender=?", (account_id, sex)).fetchone()
        if current and current[0] == name:
            fallback = self.db.execute("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY updated_at DESC,name LIMIT 1", (account_id, sex)).fetchone()
            self.db.execute("UPDATE preset_selection SET name=? WHERE ps4_id=? AND gender=?", (fallback[0], account_id, sex))
        return before, self._live({**self._preset_state(account_id, sex), "deleted": name}), True

    def _select_preset(self, account_id, body):
        name, sex, _row = self._preset_body(account_id, body, ("activate_gender",))
        activate = body.get("activate_gender", False)
        require(type(activate) is bool, "activate_gender must be a Boolean")
        before = self._preset_state(account_id, sex)
        self.db.execute("INSERT INTO preset_selection VALUES(?,?,?) ON CONFLICT(ps4_id,gender) DO UPDATE SET name=excluded.name", (account_id, sex, name))
        if activate:
            self.db.execute("UPDATE profiles SET gender=? WHERE ps4_id=?", (sex, account_id))
        after = self._preset_state(account_id, sex)
        return before, self._live(after), before != after

    def _rename_preset(self, account_id, body):
        name, sex, row = self._preset_body(account_id, body, ("new_name",))
        new = preset_name(body.get("new_name"), "new preset name")
        before = self._preset_state(account_id, sex)
        if new == name:
            return before, self._live(before), False
        require(not self.db.execute("SELECT 1 FROM presets WHERE ps4_id=? AND name=? AND gender=?", (account_id, new, sex)).fetchone(),
                "A saved outfit with that name already exists", 409, "conflict")
        preset = json.loads(row["preset_json"]); preset["presetname"] = new
        self.db.execute("UPDATE presets SET name=?,preset_json=? WHERE ps4_id=? AND name=? AND gender=?",
                        (new, json_field(preset), account_id, name, sex))
        self.db.execute("UPDATE preset_selection SET name=? WHERE ps4_id=? AND gender=? AND name=?", (new, account_id, sex, name))
        return before, self._live({**self._preset_state(account_id, sex), "renamed": {"from": name, "to": new}}), True

    def _set_preference(self, account_id, body):
        fields(body, ("key", "value", "reason"))
        key = body.get("key")
        require(isinstance(key, str) and key in PREFERENCES, "Unknown or read-only preference")
        require("value" in body, "An explicit value, or null to restore the default, is required")
        _label, _group, kind, low, high = PREFERENCES[key]
        value = body["value"]
        if value is not None:
            if kind == "flag":
                require(type(value) is bool or (type(value) is int and value in (0, 1)), "Expected a Boolean or 0/1 value")
                value = int(value)
            elif kind == "number":
                require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
                        "Expected a number from %s to %s" % (low, high))
                value = float(value)
            elif kind == "digits":
                require(isinstance(value, str) and re.fullmatch(r"[0-9]{1,%d}" % high, value), "Expected a short numeric text value")
            else:
                require(isinstance(value, str) and len(value) <= high and not re.search(r"[#\x00-\x1f\x7f]", value),
                        "Invalid text preference")
        row = self.db.execute("SELECT value FROM preferences WHERE ps4_id=? AND key=?", (account_id, key)).fetchone()
        before = {"key": key, "value": json.loads(row[0]) if row else DEFAULTS[key], "stored": row is not None}
        if value is None:
            self.db.execute("DELETE FROM preferences WHERE ps4_id=? AND key=?", (account_id, key))
            after = {"key": key, "value": DEFAULTS[key], "stored": False}
        else:
            self.store.save_preference(account_id, key, value)
            after = {"key": key, "value": value, "stored": True}
        return before, self._live(after), before != after

    def _relation_state(self, account_id, target, platform, other):
        return {"target": target, "target_platform": platform, "target_account_id": other,
                "relations": sorted(self._kinds(account_id, target, platform)),
                "their_relations": sorted(self._kinds(other, *self._identity(account_id))) if other else []}

    def _remove_relation(self, account_id, body):
        fields(body, ("kind", "target", "platform", "reason"))
        kind, target = body.get("kind"), text(body.get("target"), "relation target", maximum=128)
        require(kind in RELATIONS, "Relation kind must be friend, favorite, block or silenced")
        try:
            platform = canonical_platform(body.get("platform"))
        except ProtocolError:
            require(False, "Unsupported relation platform")
        require(self.db.execute("SELECT 1 FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind=?",
                                (account_id, target, platform, kind)).fetchone(), "Relation not found", 404, "not_found")
        other = self._resolve(target, platform)
        other = None if other == account_id else other
        before = self._relation_state(account_id, target, platform, other)
        if kind == "friend" and other:
            # Same symmetric removal and anti-resurrection event as N2RemoveFriend.
            self.store.remove_friendship(account_id, other)
        elif kind == "friend":
            self.db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind IN ('friend','favorite')", (account_id, target, platform))
        else:
            self.db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind=?", (account_id, target, platform, kind))
        return before, self._live(self._relation_state(account_id, target, platform, other)), True

    def _reset_position(self, account_id, body):
        fields(body, ("reason",))
        stored = self.db.execute("SELECT x,y,z,updated_at FROM positions WHERE ps4_id=?", (account_id,)).fetchone()
        presets = [dict(r) for r in self.db.execute("SELECT name,gender,position_json FROM presets WHERE ps4_id=?", (account_id,))]
        before = {"saved": dict(zip(("x", "y", "z", "updated_at"), stored)) if stored else None, "preset_positions_reset": []}
        changed_presets = []
        for row in presets:
            value = json.loads(row["position_json"])
            if any(value.get("lastPosition_" + a, 0.0) != 0.0 for a in "xyz"):
                value.update({"lastPosition_" + a: 0.0 for a in "xyz"})
                self.db.execute("UPDATE presets SET position_json=? WHERE ps4_id=? AND name=? AND gender=?",
                                (json_field(value), account_id, row["name"], row["gender"]))
                changed_presets.append(row["name"] + "/" + row["gender"])
        # No stored row is the server's own default: the client's native spawn.
        self.db.execute("DELETE FROM positions WHERE ps4_id=?", (account_id,))
        after = {"saved": None, "preset_positions_reset": changed_presets, "spawn": "native_default"}
        return before, self._live(after), stored is not None or bool(changed_presets)

    def _reset_layout(self, account_id, body):
        fields(body, ("instance_id", "reason"))
        instance = text(body.get("instance_id"), "apartment instance ID")
        space = self.db.execute("SELECT * FROM housing_spaces WHERE instance_id=? AND owner_ps4_id=?", (instance, account_id)).fetchone()
        require(space is not None, "Apartment not found", 404, "not_found")
        stage = self.db.execute("SELECT state FROM housing_save_stages WHERE instance_id=?", (instance,)).fetchone()
        require(stage is None or stage[0] != "open", "The owner is saving this apartment; retry shortly", 409, "conflict")
        before = self._space_view(dict(space))
        self.db.execute("DELETE FROM housing_layouts WHERE instance_id=?", (instance,))
        after = self._space_view(dict(space))
        return before, {**after, "applies_on_next_load": True}, before["layout_saved"]

    def _space_key(self, body):
        fields(body, ("space_key", "reason"))
        key = body.get("space_key")
        require(isinstance(key, str) and key in PERSONAL_SPACE_SCENES, "Unknown apartment", 404, "not_found")
        return key

    def _owned_space(self, account_id, key):
        row = self.db.execute("SELECT * FROM housing_spaces WHERE owner_ps4_id=? AND logical_space_key=?",
                              (account_id, key)).fetchone()
        return self._space_view(dict(row)) if row else None

    def _grant_space(self, account_id, body):
        key = self._space_key(body)
        before = self._owned_space(account_id, key)
        if before is not None:
            return before, self._live(before), False
        try:
            self.service.apartments.bind(account_id, key)
        except ProtocolError as error:
            raise ManagementError(error.status, "conflict" if error.status == 409 else "invalid_request", str(error)) from None
        return {"space_key": key, "owned": False}, self._live(self._owned_space(account_id, key)), True

    def _remove_space(self, account_id, body):
        key = self._space_key(body)
        require(key != NATIVE_DEFAULT_APARTMENT, "Home is the native default apartment every player is offered; it cannot be removed", 409, "conflict")
        before = self._owned_space(account_id, key)
        require(before is not None, "Apartment is not owned", 404, "not_found")
        try:
            removed = self.service.apartments.remove(account_id, key)
        except ProtocolError as error:
            raise ManagementError(error.status, {404: "not_found", 409: "conflict"}.get(error.status, "invalid_request"), str(error)) from None
        # The audit keeps the removed layout so staff can restore it by hand.
        before["layout"] = json.loads(removed["layout_json"]) if removed["layout_json"] else None
        return before, self._live({"space_key": key, "owned": False, "instance_id": removed["instance_id"]}), True

    def _select_resource(self, account_id, body):
        fields(body, ("kind", "item_id", "reason"))
        kind, item = body.get("kind"), body.get("item_id")
        require(kind in RESOURCE_KINDS, "Kind must be companions or locomotions")
        require(isinstance(item, str) and len(item) <= 128 and (item == "" or re.fullmatch(r"[A-Za-z0-9]+", item)), "Invalid item ID")
        selection = self._selection(account_id)
        require(selection is not None, "Equipped resource selection is not initialized on this server", 409, "conflict")
        if item:
            require(self.db.execute("SELECT 1 FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?", (account_id, kind, item)).fetchone(),
                    "Only an owned item can be equipped", 409, "conflict")
        current, revision = selection.get(kind, ("", 0))[:2]
        before = {"kind": kind, "item_id": current, "revision": revision}
        if current == item:
            return before, self._live(before), False
        # Revision bump makes any in-flight instance request fail its revision check.
        self.db.execute("""INSERT INTO resource_selections VALUES(?,?,?,?,?) ON CONFLICT(ps4_id,kind) DO UPDATE SET
            item_id=excluded.item_id,revision=excluded.revision,updated_at=excluded.updated_at""",
                        (account_id, kind, item, revision + 1, time.time()))
        return before, self._live({"kind": kind, "item_id": item, "revision": revision + 1}), True
