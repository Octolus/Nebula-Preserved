"""Offline-callable handlers from bootstrap-response-contracts.json.

Response acceptance rules are recovered; local state policy is a replacement.
Unknown behavior fails explicitly. Importing this module opens no sockets.
"""
import json
import math
import time

from avatar import decode_save, neutral, schema_fields
from avatar_native_save import normalize_original_native_save
from avatar_entry_codec import encode_entry_fields, encode_value_texts
from allocation import InstanceDirectory
from resources import ResourceCatalog, ResourceEntitlements
from housing import HousingStore
from instance_lifecycle import ManagedInstanceLifecycle
from consumables import Consumables
from gathering import Gathering
from rewards import RewardService, ROUTES as REWARD_ROUTES
from shop import Shop
from notifications import NotificationOutbox
from public_access import require_actor
from state import Catalog, DEFAULT_PREFS, Store, canonical_platform
from wire import PLATFORMS, ProtocolError, Request, json_field, session_guid


# Authored preservation default for the versioned native hydration trailer.
# PlatformOnly is deliberately kept out of the legacy PlayerPrefsJson object:
# the shipped JSON DTO has no field for enum key 21.
PLATFORM_ONLY_DEFAULT = 0


def boolean(text):
    if text.lower() not in ("true", "false"):
        raise ProtocolError("Invalid Boolean")
    return text.lower() == "true"


def number(text):
    try:
        value = float(text)
    except ValueError as exc:
        raise ProtocolError("Invalid invariant-culture number") from exc
    if not math.isfinite(value) or abs(value) > 3.4028234663852886e38:
        raise ProtocolError("Non-finite number")
    return value


class Service:
    ROUTES = {
        "STMGetUserInfo", "CheckerServlet", "CheckServerStatusServlet",
        "N2UserExist", "UserExistsServlet", "ChannelGUIDServlet",
        "GetIinitInfosNeededServlet", "GetPlayerPrefsServlet", "PlayerPrefsServlet",
        "GetCinemaFilmsServlet", "GetPurchases", "SavePlayerPref", "InfoServlet",
        "N2AddUserOnline", "N2UpdateUserOnline", "GetLastUsedPreset",
        "GetLoadPresetByName", "GetPresetGameServlet", "PlayerLabelInfoServlet",
        "N2AddBlock", "N2AddSilenced", "N2RemoveBlock", "N2RemoveSilenced",
        "N2RemoveFriend", "N2ToggleFavorite", "Send_CheckIsInWardrobeServlet",
        "SetUserInWardrobe", "GetAllInWardrobe",
        "N2AddUser", "N2SavePreset", "ShowPresetsServlet", "RemovePresetServlet",
        "RenamePresetServlet", "GetInfoServlet", "WardrobeOptionItemServlet",
        "SetPlayerPrefsServlet",
        "N2LoadSpace", "N2SpaceLoading", "spaceExistServlet",
        "ResetDefaultPresetServlet", "GetCompanionsServlet", "GetLocomotionsServlet",
        "GetPersonalSpacesServlet", "InWardrobeCheckerServlet", "RemoveInWardrobeServlet",
        "GetSpaceEventServlet", "GetrefusernameServlet",
        "N2GetSocialList", "GetSocialList", "N2GetRelationship",
        "N2GetPsidglobalAndGuidByUsernamePlatform",
        "GetNewsServlet", "GetHousingTypeServlet", "HousingReadPresetServlet",
        "N2HousingReadPreset", "HousingSavePresetServletParts", "N2GetUserTypeSpace",
        "ReportServlet", "checkStateNPFriendsServlet",
        "GetConsumableServlet", "GetConsumablePriceServlet",
        "CheckOwnGenericReward", "GenericReward", "RewardClothServlet",
        "RewardConsumeServlet", "SKLPromoServlet", "SKLPromoTriggerServlet",
        "checkRewardAvailableServlet", "CinemaInteractionNPServlet",
        "CheckIfSpaceStillExistServlet",
        "Get_GatherConsume",
        "Get_GatherConsumeReward", "Get_GatherMedievalVillage", "Get_GatherPhaseGame",
        "Get_GatherStatus", "Get_npGather", "Get_npGatherChristmas",
        "Get_npGatherProcessItem", "Send_GatherInitInSpace", "Send_GatherMedievalVillageConsume",
        "GetFeaturesServlet", "GetGenderDataShopServlet", "GetItemAssetsDataServlet",
        "GetShopDataShopServlet", "GetShopInfoPlayerShop", "GetShopTypeDataShopServlet",
        "NPShopBundleItemsServlet", "NPShopBuyItemServlet", "NPShopGiftItemServlet",
        "NPShopIsItemPurchasedServlet", "NPShopSyncCrystalsServlet",
        "checkerToServerDownMaintenanceServlet",
    }

    def __init__(self, store: Store, catalog: Catalog, *, core_test_profile=None,
                 managed_instances=False):
        self.store = store
        self.catalog = catalog
        self.wardrobe_removal_sentinels = self._load_wardrobe_removal_sentinels()
        self.instances = InstanceDirectory(store.state_dir, core_test_profile=core_test_profile)
        self.resources = ResourceEntitlements(store, ResourceCatalog(catalog.protocol_dir))
        self.housing = HousingStore(store, catalog.protocol_dir)
        self.lifecycle = (ManagedInstanceLifecycle(store, self.housing, self.instances, core_test_profile)
                          if managed_instances else None)
        self.consumables = Consumables(store)
        self.notifications = NotificationOutbox(store)
        self.rewards = RewardService(store, catalog, self.instances)
        self.rewards.notifications = self.notifications
        self.gathering = Gathering(store, catalog, self.resources, self.housing)
        self.shop = Shop(store, catalog, self.resources, self.housing)
        self.shop.notifications = self.notifications
        store.instance_resources = self.resources

    def _load_wardrobe_removal_sentinels(self):
        """Load only native-recognized removal tiles with shipped asset evidence."""
        document = json.loads((self.catalog.protocol_dir / "wardrobe-removal-sentinels.json").read_text(encoding="utf-8"))
        policy = document["policy"]
        if (policy["view"] != "ordinary_only" or policy["entitlement"] is not False
                or policy["storage_or_deleted_item"] is not False):
            raise RuntimeError("Unsafe wardrobe removal sentinel policy")
        result = {}
        for row in document["sentinels"]:
            evidence_kind = row.get("evidence_kind", "wearable_manifest")
            if evidence_kind == "wearable_manifest":
                asset = self.catalog.resolve(row["item_id"], row["gender"], row["category"])
                if (asset["bundle"] != row["bundle"]
                        or asset["manifest_sha256"] != row["manifest_sha256"]):
                    raise RuntimeError("Wardrobe removal sentinel evidence differs from the shipped asset catalog")
            elif evidence_kind == "thumbnail_control":
                expected_path = ("Assets/ResourcesART/Wardrobe_EAB/" + row["gender"] + "/" +
                                 row["category"] + "/" + row["item_id"] + "/" +
                                 row["item_id"] + "Thumbnail.png")
                expected_bundle = "th/" + row["item_id"].lower() + "thumbnail"
                digest = row["manifest_sha256"]
                if (row.get("thumbnail_asset_path") != expected_path or row["bundle"] != expected_bundle
                        or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)):
                    raise RuntimeError("Invalid thumbnail-backed wardrobe removal sentinel evidence")
            else:
                raise RuntimeError("Unknown wardrobe removal sentinel evidence kind")
            key = (row["gender"], row["category"])
            if key in result:
                raise RuntimeError("Multiple wardrobe removal sentinels for one gender/category")
            result[key] = {
                **row,
                "asset_status": policy["asset_status"],
                "item_type": policy["item_type"],
                "display_name": policy["display_name"],
            }
        self.wardrobe_removal_sentinel_ids = {row["item_id"] for row in result.values()}
        return result

    def dispatch(self, command, plaintext):
        if command not in self.ROUTES:
            raise ProtocolError("Route behavior has not been reconstructed", 501)
        request = Request.parse(plaintext, maxsplit=4 if command == "N2SavePreset" else -1)
        self.store.import_friend_events()
        self.consumables.import_claims()
        self.notifications.import_acknowledgements(self.store.state_dir)
        if command in REWARD_ROUTES:
            response = self.rewards.dispatch(command, request)
        elif command in Gathering.ROUTES:
            response = self.gathering.dispatch(command, request)
        elif command in Shop.ROUTES:
            response = self.shop.dispatch(command, request)
        else:
            response = getattr(self, "route_" + command)(request)
        if "#" not in response and not (command == "GetInfoServlet" and request.fields[0] == "0"):
            raise RuntimeError("Response violates recovered shared sender framing")
        return response

    def identify(self, request, count, ps4_index=1):
        f = request.require(count)
        profile = self.store.session(f[0], f[ps4_index] if ps4_index is not None else None)
        require_actor(profile["ps4_id"])
        return f, profile

    def route_STMGetUserInfo(self, request):
        _, account_id = request.require(2)
        self.store.account(account_id, platform=request.platform)
        # Country/currency are local fixture values, not Steam billing data.
        payload = {"response": {"result": "OK", "params": {
            "state": "", "country": "US", "currency": "USD", "status": "Active"}}}
        return "OK#" + json_field(payload) + "\n"  # parser strips final char

    def route_CheckerServlet(self, request):
        f = request.require(4)
        return "OK#" + f[3] + "#false##"

    def route_CheckServerStatusServlet(self, request):
        username, nonce = request.require(2)
        return "true#" + username + "#" + nonce + "#1"

    def route_checkerToServerDownMaintenanceServlet(self, request):
        fields, _profile = self.identify(request, 2)
        # Native callback4233b0 parses field3 as minutes; Show4ddac0 ignores0.
        # Explicit local policy: no scheduled maintenance announcement.
        return "true#" + fields[0] + "#" + fields[1] + "#0"

    def route_N2UserExist(self, request):
        username, _version, _developer, account_id, _nonce = request.require(5)
        profile = self.store.account(account_id, username, request.platform)
        self.ensure_default_avatars(profile)
        if self.lifecycle:
            self.lifecycle.provision_account(profile["ps4_id"])
        # Synthetic local legacy login marker; never a Steam password.
        return account_id + "##preservation#false#false##"

    def route_UserExistsServlet(self, request):
        # The direct legacy coroutine sends PS4ID, not the Steam persona name.
        ps4_id, _version, _developer, account_id, _nonce = request.require(5)
        if ps4_id != account_id:
            raise ProtocolError("Legacy identity differs from recovered Steam account binding", 409)
        profile = self.store.account(account_id, platform=request.platform)
        self.ensure_default_avatars(profile)
        if self.lifecycle:
            self.lifecycle.provision_account(profile["ps4_id"])
        return ps4_id + "##preservation#false#false##"

    def ensure_default_avatars(self, profile):
        """Local starter policy using authored, manifest-backed neutral fixtures."""
        defaults = json.loads((self.catalog.protocol_dir / "avatar-default-catalog.json").read_text(encoding="utf-8"))
        for gender in ("MALE", "FEMALE"):
            exists = self.store.db.execute("SELECT 1 FROM presets WHERE ps4_id=? AND gender=? LIMIT 1", (profile["ps4_id"], gender)).fetchone()
            if exists:
                continue
            preset, assets, position = neutral(self.catalog.protocol_dir, profile["ps4_id"], gender)
            for item in defaults["defaults"][gender]["items"]:
                self.store.grant(profile["ps4_id"], self.catalog.resolve(item["item_id"], gender, item["category"]))
            self.store.save_preset(profile["ps4_id"], "Default", gender, preset, assets, position)
        with self.store.db:
            self.store.db.execute("UPDATE profiles SET gender=? WHERE ps4_id=?", (profile["gender"], profile["ps4_id"]))

    def route_N2AddUser(self, request):
        account_id, username, _mail, _plus, _region, platform = request.require(6)
        if platform != str(PLATFORMS[request.platform]):
            raise ProtocolError("Mismatched platform")
        profile = self.store.account(account_id, username, request.platform)
        self.ensure_default_avatars(profile)
        if self.lifecycle:
            self.lifecycle.provision_account(profile["ps4_id"])
        return "true#"  # original direct coroutine checks network success only

    def route_ChannelGUIDServlet(self, request):
        account_id, request_hash = request.require(2)
        if len(request_hash) != 64 or any(x not in "0123456789abcdef" for x in request_hash):
            raise ProtocolError("Invalid client-generated session hash")
        self.store.bind_session(account_id, session_guid(account_id, request_hash))
        return "true#"

    def route_GetIinitInfosNeededServlet(self, request):
        f, _ = self.identify(request, 2)
        # Local policy: validate GUID/presets; defer optional memorion feature.
        return f[0] + "#true#true#false"

    def route_GetPlayerPrefsServlet(self, request):
        f, profile = self.identify(request, 2)
        stored = self.store.preferences(profile["ps4_id"])
        prefs = {k: v for k, v in stored.items()
                 if k in DEFAULT_PREFS}
        platform_only = stored.get("PlatformOnly", PLATFORM_ONLY_DEFAULT)
        if platform_only not in (0, 1):
            # SavePlayerPref enforces this invariant. Refuse corrupt legacy or
            # manually edited state instead of hydrating an ambiguous value.
            raise ProtocolError("Invalid stored PlatformOnly preference", 409)
        # The first three fields retain their exact legacy grammar. The fixed
        # marker makes the new native consumer fail closed on other trailers.
        return ("true#" + f[0] + "#" + json_field(prefs)
                + "#prefs-v1#" + str(platform_only))

    def route_PlayerPrefsServlet(self, request):
        self.identify(request, 2)  # trigger/ack with no preference data
        return "true#"

    def route_GetCinemaFilmsServlet(self, request):
        f, _ = self.identify(request, 2)
        now = time.gmtime()
        # An empty film list hangs native CinemaFilms.Set (0x5568b0).
        # The exact one-day sentinel advances its loop without creating any
        # ScheduleFilm: 1800 + 84600 == 86400, and Add requires <86400.
        # Count-guarded consumers therefore see no screenings; this token is
        # never displayed or passed to the local MP4 loader. No trailer.
        return f"{f[0]}#{now.tm_hour}#{now.tm_min}#{now.tm_sec}#0#LOCAL_NO_FILMS#84600"

    def route_GetNewsServlet(self, request):
        nonce, = request.require(1)
        if not nonce.isascii() or not nonce.isdigit() or not 0 <= int(nonce) < 100:
            raise ProtocolError("Invalid native news random value")
        # A zero count cannot pass the shared sender's '#' gate. An empty
        # trailer crashes both native all-pairs loops, so serve authored local
        # text with the exact count/date/text shape instead.
        return "1#Local preservation#This is a local preservation service. Original online news is unavailable."

    def route_GetPurchases(self, request):
        f, profile = self.identify(request, 1, None)
        data = self.store.purchases(profile["ps4_id"], f[0])
        data.update(self.resources.purchase_fields(profile["ps4_id"]))
        data.update(self.housing.purchase_fields(profile["ps4_id"]))
        return "true#" + f[0] + "#" + json_field(data)

    def route_SavePlayerPref(self, request):
        f, profile = self.identify(request, 3, None)
        key, text = f[1:]
        # Native enum19 uses an uppercase N; PlayerPrefsJson's field starts
        # lowercase. Keep one canonical persisted/response key.
        if key == "NotificationLoginFriend":
            key = "notificationLoginFriend"
        if key == "NameColorSelectedIndex":
            try:
                color = json.loads(text)
                if not isinstance(color, dict) or set(color) != {"x", "y", "z"}:
                    raise ValueError("Expected x,y,z")
                values = {k: number(str(color[axis])) for k, axis in zip(
                    ("NameColorSelectedIndex_r", "NameColorSelectedIndex_g", "NameColorSelectedIndex_b"), ("x", "y", "z"))}
            except (ValueError, TypeError) as exc:
                raise ProtocolError("Invalid name color JSON") from exc
            # Three component writes are atomic.
            with self.store.db:
                self.store.db.executemany("INSERT INTO preferences VALUES(?,?,?) ON CONFLICT(ps4_id,key) DO UPDATE SET value=excluded.value",
                    [(profile["ps4_id"], k, json_field(v)) for k, v in values.items()])
            return "true#" + f[0]
        if key in ("ShowPets", "PlatformOnly"):
            try:
                value = int(text)
            except ValueError as exc:
                raise ProtocolError("Invalid Boolean integer preference") from exc
            if value not in (0, 1):
                raise ProtocolError("Expected Boolean integer preference")
        elif key not in DEFAULT_PREFS:
            raise ProtocolError("Unknown preference key", 400)
        elif isinstance(DEFAULT_PREFS[key], str):
            value = text
        elif isinstance(DEFAULT_PREFS[key], int):
            try:
                value = int(text)
            except ValueError as exc:
                raise ProtocolError("Invalid integer preference") from exc
        else:
            value = number(text)
        self.store.save_preference(profile["ps4_id"], key, value)
        return "true#" + f[0]

    def route_InfoServlet(self, request):
        # Legacy sends one opaque data field; modern sends nine telemetry
        # fields. Neither consumer parses a response body or requires storage.
        if len(request.fields) < 3:
            raise ProtocolError("Invalid network-info request")
        self.store.session(request.fields[0], request.fields[1])
        return "true#"  # no need to persist personal network telemetry

    def route_N2AddUserOnline(self, request):
        _, profile = self.identify(request, 3)
        with self.store.db:
            self.store.db.execute("UPDATE profile_state SET online=1 WHERE ps4_id=?", (profile["ps4_id"],))
        return "OK#true"

    def route_N2UpdateUserOnline(self, request):
        self.identify(request, 2)
        return "true#"

    def preset_response(self, request, count, named=False, has_gender=True):
        f, _ = self.identify(request, count)
        target = self.store.session(f[2])
        gender = self.numeric_gender(f[3]) if has_gender else target["gender"]
        preset = self.store.preset(target["ps4_id"], gender, f[4] if named else None)
        position = {**preset["position"], "GUID": f[2], "PS4ID": target["ps4_id"]}
        saved_position = self.store.position(target["ps4_id"])
        if saved_position["updated_at"]:
            position.update({"lastPosition_" + k: v for k, v in saved_position["position"].items()})
        # Response1 is REQUESTER identity even for a remote target avatar.
        return "#".join(("true", f[1], gender, json_field(preset["preset"]),
                         json_field(preset["assets"]), json_field(position)))

    def route_GetLastUsedPreset(self, request):
        return self.preset_response(request, 4)

    def route_GetLoadPresetByName(self, request):
        return self.preset_response(request, 5, named=True)

    def route_GetPresetGameServlet(self, request):
        return self.preset_response(request, 3, has_gender=False)

    def route_PlayerLabelInfoServlet(self, request):
        f, _ = self.identify(request, 3)
        target = self.store.session(f[2])
        return "#".join(("true", f[0], f[1], f[2], json_field(self.player_label(target, f[2]))))

    def player_label(self, target, guid):
        prefs = self.store.preferences(target["ps4_id"])
        position = self.store.position(target["ps4_id"])["position"]
        return {"GUID": guid, "userName": target["username"],
                 "status": prefs["status"], "mood": prefs["mood"],
                 "nameColorX": prefs["NameColorSelectedIndex_r"],
                 "nameColorY": prefs["NameColorSelectedIndex_g"],
                 "nameColorZ": prefs["NameColorSelectedIndex_b"],
                 "lastPosX": position["x"], "lastPosY": position["y"], "lastPosZ": position["z"],
                 "gender": target["gender"]}

    def relation_change(self, request, kind, operation):
        f, profile = self.identify(request, 3, None)
        if f[2] not in ("0", "1"):
            raise ProtocolError("Unsupported relation platform")
        platform = canonical_platform(f[2])
        key = (profile["ps4_id"], f[1], platform, kind)
        exists = self.store.db.execute("SELECT 1 FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind=?", key).fetchone()
        if kind == "friend" and operation == "remove":
            target = self.store.find_username(f[1], platform)
            if target:
                self.store.remove_friendship(profile["ps4_id"], target["ps4_id"])
                return "OK#true"
        with self.store.db:
            if kind == "friend" and operation == "remove":
                self.store.db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind IN ('friend','favorite')", key[:3])
                return "OK#true"
            if operation == "remove" or (operation == "toggle" and exists):
                self.store.db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind=?", key)
            else:
                self.store.db.execute("INSERT OR IGNORE INTO relations VALUES(?,?,?,?)", key)
        return "OK#true"

    def route_N2AddBlock(self, request):
        return self.relation_change(request, "block", "add")

    def route_N2AddSilenced(self, request):
        return self.relation_change(request, "silenced", "add")

    def route_N2RemoveBlock(self, request):
        return self.relation_change(request, "block", "remove")

    def route_N2RemoveSilenced(self, request):
        return self.relation_change(request, "silenced", "remove")

    def route_N2RemoveFriend(self, request):
        return self.relation_change(request, "friend", "remove")

    def route_N2ToggleFavorite(self, request):
        return self.relation_change(request, "favorite", "toggle")

    def social_entries(self, profile, list_type):
        # The observed native menus request0 Friends/1 Silenced/2 Blocked.
        # External PSN and other list selection policies remain unreconstructed.
        kinds = {"0": "friend", "1": "silenced", "2": "block"}
        if list_type not in kinds:
            raise ProtocolError("Social list selection has not been reconstructed", 501)
        presence = self.store.presence()
        entries = []
        for row in self.store.db.execute("SELECT target,target_platform FROM relations WHERE ps4_id=? AND kind=? ORDER BY target,target_platform", (profile["ps4_id"], kinds[list_type])):
            target = self.store.find_username(row["target"], row["target_platform"])
            statuses = []
            if target:
                statuses = [presence[s[0]] for s in self.store.db.execute("SELECT guid FROM sessions WHERE ps4_id=?", (target["ps4_id"],)) if s[0] in presence]
            status = 3 if 3 in statuses else 0 if 0 in statuses else 1 if 1 in statuses else 2
            entries.append({"isFavourite": "favorite" in self.store.relation_kinds(profile["ps4_id"], row["target"], row["target_platform"]),
                            "status": ("Online", "Away", "Offline", "Wardrobe")[status],
                            "name": row["target"], "platform": PLATFORMS[canonical_platform(row["target_platform"])],
                            "listType": ("Friends", "Silenced", "Blocked")[int(list_type)]})
        # Deterministic replacement ordering; original database order is unknown.
        return sorted(entries, key=lambda e: (not e["isFavourite"], e["status"] == "Offline", e["name"], e["platform"]))

    def route_N2GetSocialList(self, request):
        f, profile = self.identify(request, 4)
        if f[3] not in ("0", "1"):
            raise ProtocolError("Unknown legacy social UI selector", 501)
        entries = self.social_entries(profile, f[2])
        schema = [{"name": "isFavourite", "type": "bool"},
                  {"name": "status", "type": {"enum": ["Online", "Away", "Offline", "Wardrobe"]}},
                  {"name": "name", "type": "string"}, {"name": "platform", "type": "int"},
                  {"name": "listType", "type": {"enum": ["Friends", "Silenced", "Blocked", "SpaceUsers", "PSN"]}}]
        serialized = [encode_entry_fields(entry, schema) for entry in entries]
        if any("#" in entry for entry in serialized):
            raise ProtocolError("Username cannot be represented in legacy social framing")
        # Unlike the generic sender's other commands, N2GetSocialList does not
        # validate fields0/1. Handler parses selector2, count3 and exactly count entries.
        return "#".join(["true", f[0], f[3], str(len(entries)), *serialized])

    def route_GetSocialList(self, request):
        f, profile = self.identify(request, 2, None)
        # Native request/JSON shape is exact. Reusing ListType selection here is
        # a local interpretation: no direct caller of this task was recovered.
        entries = self.social_entries(profile, f[1])
        return "OK#" + json_field({"lUsernames": [entry["name"] for entry in entries]})

    def route_N2GetRelationship(self, request):
        f, profile = self.identify(request, 3)
        target = self.store.session(f[2])
        own = self.store.relation_kinds(profile["ps4_id"], target["username"], target["platform"])
        reverse = self.store.relation_kinds(target["ps4_id"], profile["username"], profile["platform"])
        # Native codes/flag effects are recovered. This precedence for overlapping
        # relations is explicit replacement policy, not original server behavior.
        code = (5 if "block" in own else 6 if "block" in reverse else
                3 if "silenced" in own else 4 if "silenced" in reverse else
                2 if "favorite" in own else 1 if "friend" in own else 0)
        return "OK####" + str(code)  # exact five fields; receiver reads only4

    def route_N2GetPsidglobalAndGuidByUsernamePlatform(self, request):
        f, _ = self.identify(request, 3, None)
        if f[2] not in ("0", "1"):
            raise ProtocolError("Unsupported lookup platform")
        target = self.store.find_username(f[1], f[2])
        presence = self.store.presence()
        if target:
            for row in self.store.db.execute("SELECT a.guid,a.psidglobal,a.instance_id FROM allocations a JOIN sessions s USING(guid) WHERE s.ps4_id=? ORDER BY a.allocated_at DESC", (target["ps4_id"],)):
                instance = self.instances.ready(psidglobal=row["psidglobal"], instance_id=row["instance_id"])
                if row["guid"] in presence and instance:
                    return "OK#" + row["psidglobal"] + "#" + row["guid"]
        # Invite acceptance branches safely when callback's psidglobal is empty.
        return "OK##"

    def route_Send_CheckIsInWardrobeServlet(self, request):
        f, _ = self.identify(request, 3)
        target = self.store.session(f[2])
        active = self.store.wardrobe_active(target["ps4_id"], f[2])
        return "#".join(("OK", f[0], "", "true" if active else "false", ""))

    def route_SetUserInWardrobe(self, request):
        f, profile = self.identify(request, 13, None)
        if f[2] not in ("0", "1"):
            raise ProtocolError("Invalid integer wardrobe state")
        active = f[2] == "1"
        if self.store.current_guid(profile["ps4_id"]) != f[0]:
            raise ProtocolError("Historical session cannot change current wardrobe state", 403)
        values = [number(value) for value in f[7:13]]
        if f[3] not in ("MALE", "FEMALE"):
            raise ProtocolError("Unsupported avatar gender")
        with self.store.db:
            allocation = self.store.db.execute("SELECT instance_id FROM allocations WHERE guid=?", (f[0],)).fetchone()
            if active and (not allocation or allocation[0] != f[1] or self.store.current_guid(profile["ps4_id"]) != f[0]):
                raise ProtocolError("Wardrobe session is not allocated to this instance", 403)
            self.store.db.execute("UPDATE profile_state SET in_wardrobe=?,wardrobe_instance_id=?,wardrobe_updated_at=? WHERE ps4_id=?", (active, f[1] if active else "", time.time(), profile["ps4_id"]))
            self.store.db.execute("UPDATE profiles SET gender=? WHERE ps4_id=?", (f[3], profile["ps4_id"]))
            self.store.db.execute("INSERT INTO positions VALUES(?,?,?,?,?) ON CONFLICT(ps4_id) DO UPDATE SET x=excluded.x,y=excluded.y,z=excluded.z,updated_at=excluded.updated_at", (profile["ps4_id"], *values[3:], time.time()))
            preferences = {"status": f[5], "mood": f[6], "NameColorSelectedIndex_r": values[0], "NameColorSelectedIndex_g": values[1], "NameColorSelectedIndex_b": values[2]}
            self.store.db.executemany("INSERT INTO preferences VALUES(?,?,?) ON CONFLICT(ps4_id,key) DO UPDATE SET value=excluded.value", [(profile["ps4_id"], k, json_field(v)) for k, v in preferences.items()])
        return "OK#true"

    def route_GetAllInWardrobe(self, request):
        f, _ = self.identify(request, 2, None)
        allocation = self.store.db.execute("SELECT instance_id,psidglobal FROM allocations WHERE guid=?", (f[0],)).fetchone()
        if not allocation or allocation[0] != f[1]:
            raise ProtocolError("Wardrobe query is not allocated to this instance", 403)
        if self.store.wardrobe_delivery(f[1], allocation[1]):
            return "OK#"
        rows = self.store.db.execute("SELECT s.guid FROM sessions s JOIN profile_state p USING(ps4_id) JOIN allocations a ON a.guid=s.guid WHERE p.in_wardrobe=1 AND a.instance_id=? AND s.guid<>? ORDER BY s.guid", (f[1], f[0]))
        members = [json_field(self.player_label(self.store.session(row[0]), row[0])) for row in rows
                   if self.store.wardrobe_active(self.store.session(row[0])["ps4_id"], row[0], f[1])]
        # Empty field1 intentionally suppresses the callback in this client.
        # Nonempty replies REQUIRE the documented client loop fix at608323.
        # The original loop produces a null final entry and its caller crashes.
        # Corrected loop copies all JSON entries, with NO discarded trailer.
        return "OK#" + "#".join(members)

    def route_N2SavePreset(self, request):
        f, profile = self.identify(request, 5)
        if f[3] not in ("0", "1"):
            raise ProtocolError("Invalid numeric gender")
        gender = "MALE" if f[3] == "0" else "FEMALE"
        preset, assets = decode_save(self.catalog.protocol_dir, f[4], gender)
        preset = normalize_original_native_save(preset, gender)
        owned = {(row["item_id"], row["gender"]) for row in self.store.inventory(profile["ps4_id"])}
        for index in range(1, 41):
            item_id = preset["item" + str(index)]
            if item_id != "null" and (item_id, gender) not in owned:
                raise ProtocolError("Preset contains an ungranted local wardrobe item", 403)
        preset["iduser"] = profile["ps4_id"]
        preset["presetname"] = f[2]
        previous = self.store.db.execute("SELECT position_json FROM presets WHERE ps4_id=? AND gender=? ORDER BY updated_at DESC LIMIT 1", (profile["ps4_id"], gender)).fetchone()
        position = json.loads(previous[0]) if previous else {"lastPosition_x": 0.0, "lastPosition_y": 0.0, "lastPosition_z": 0.0}
        position.update(GUID=f[0], PS4ID=f[1])
        self.store.save_preset(profile["ps4_id"], f[2], gender, preset, assets, position)
        return "true#true"

    def numeric_gender(self, value):
        if value not in ("0", "1"):
            raise ProtocolError("Invalid numeric gender")
        return "MALE" if value == "0" else "FEMALE"

    def route_ShowPresetsServlet(self, request):
        f, profile = self.identify(request, 3)
        gender = self.numeric_gender(f[2])
        names = [row[0] for row in self.store.db.execute("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY name", (profile["ps4_id"], gender))]
        return "#".join(["true", f[0], *names])

    def route_RemovePresetServlet(self, request):
        f, profile = self.identify(request, 5)
        gender = self.numeric_gender(f[4])
        with self.store.db:
            self.store.db.execute("DELETE FROM presets WHERE ps4_id=? AND name=? AND gender=?", (profile["ps4_id"], f[2], gender))
            current = self.store.db.execute("SELECT name FROM preset_selection WHERE ps4_id=? AND gender=?", (profile["ps4_id"], gender)).fetchone()
            if current and current[0] == f[2]:
                next_preset = self.store.db.execute("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY updated_at DESC LIMIT 1", (profile["ps4_id"], gender)).fetchone()
                if next_preset:
                    self.store.db.execute("UPDATE preset_selection SET name=? WHERE ps4_id=? AND gender=?", (next_preset[0], profile["ps4_id"], gender))
                else:
                    self.store.db.execute("DELETE FROM preset_selection WHERE ps4_id=? AND gender=?", (profile["ps4_id"], gender))
        return "true#"

    def route_RenamePresetServlet(self, request):
        f, profile = self.identify(request, 5)
        gender = self.numeric_gender(f[4])
        old = self.store.preset(profile["ps4_id"], gender, f[2])
        if self.store.db.execute("SELECT 1 FROM presets WHERE ps4_id=? AND name=? AND gender=?", (profile["ps4_id"], f[3], gender)).fetchone():
            raise ProtocolError("Preset name already exists", 409)
        old["preset"]["presetname"] = f[3]
        with self.store.db:
            self.store.db.execute("UPDATE presets SET name=?,preset_json=?,updated_at=? WHERE ps4_id=? AND name=? AND gender=?", (f[3], json_field(old["preset"]), time.time(), profile["ps4_id"], f[2], gender))
            self.store.db.execute("UPDATE preset_selection SET name=? WHERE ps4_id=? AND gender=? AND name=?", (f[3], profile["ps4_id"], gender, f[2]))
        return "true#"

    def route_GetInfoServlet(self, request):
        f = request.fields
        if not f:
            raise ProtocolError("Missing legacy preset mode")
        if f[0] != "0":
            count = {"1": 3, "2": 4, "3": 5}.get(f[0])
            if count is None:
                raise ProtocolError("Unknown legacy preset mode")
            request.require(count)
            profile = self.store.session(f[1], f[2])
            gender = profile["gender"] if f[0] == "1" else self.numeric_gender(f[3])
            selected = self.store.preset(profile["ps4_id"], gender, f[4] if f[0] == "3" else None)
            if f[0] == "3":
                return "#".join(("true", f[1], json_field(selected["preset"]), json_field(selected["assets"])))
            tokens = [None if selected["preset"][field["name"]] is None else str(selected["preset"][field["name"]])
                      for field in schema_fields(self.catalog.protocol_dir, gender)]
            serialized = encode_value_texts(tokens)
            if "#" in serialized:
                raise ProtocolError("Legacy preset is not representable in outer framing", 409)
            if f[0] == "1":
                return "#".join(("true", f[1], "", serialized, gender))
            return "#".join(("true", f[1], serialized, f[3]))
        request.require(6)
        profile = self.store.session(f[1], f[2])
        gender = self.numeric_gender(f[3])
        filters = {"0": {0, 1}, "1": {2}, "2": {3}}
        if f[5] not in filters:
            raise ProtocolError("Invalid wardrobe view")
        items = [row for row in self.store.inventory(profile["ps4_id"])
                 if row["gender"] == gender and row["category"] == f[4]
                 and row["asset_status"] in filters[f[5]]
                 and row["item_id"] not in self.wardrobe_removal_sentinel_ids]
        # The native client recognizes fixed, manifest-backed item IDs as
        # category-removal tiles. They are response-only controls: never grants,
        # purchases, storage entries or deleted entries. ImgOnclickPS4 handles
        # them before ordinary asset loading and removes the current category.
        if f[5] == "0":
            sentinel = self.wardrobe_removal_sentinels.get((gender, f[4]))
            if sentinel and all(row["item_id"] != sentinel["item_id"] for row in items):
                items.append(sentinel)
        # Legacy response has ! between its seven fields and # within arrays.
        # Categories without a reviewed native sentinel remain exactly empty.
        names = [row["display_name"] if not any(c in row["display_name"] for c in "#!") else row["item_id"] for row in items]
        return "!".join(("true", f[1], "#".join(row["item_id"] for row in items),
                         "#".join(str(row["asset_status"]) for row in items), "#".join(names),
                         "#".join(str(row["item_type"]) for row in items), gender))

    def route_WardrobeOptionItemServlet(self, request):
        if len(request.fields) not in (4, 5):
            raise ProtocolError("Invalid wardrobe mutation field count")
        f = request.fields
        profile = self.store.session(f[0], f[1])
        if f[2] in self.wardrobe_removal_sentinel_ids:
            raise ProtocolError("Wardrobe removal controls are not mutable entitlements", 403)
        if f[3] not in ("0", "1", "2", "3"):
            raise ProtocolError("Invalid wardrobe item status")
        with self.store.db:
            changed = self.store.db.execute("UPDATE entitlements SET asset_status=? WHERE ps4_id=? AND item_id=?", (int(f[3]), profile["ps4_id"], f[2])).rowcount
            if not changed:
                raise ProtocolError("Unknown local wardrobe entitlement", 404)
        return "true#" + f[0]

    def route_SetPlayerPrefsServlet(self, request):
        f, _ = self.identify(request, 4)
        return self.route_SavePlayerPref(Request((f[0], f[2], f[3]), request.platform))

    def route_ResetDefaultPresetServlet(self, request):
        f, profile = self.identify(request, 4)
        gender = self.numeric_gender(f[3])
        preset, assets, position = neutral(self.catalog.protocol_dir, f[1], gender, f[2])
        self.store.save_preset(profile["ps4_id"], f[2], gender, preset, assets, position)
        return "true#"

    def route_N2LoadSpace(self, request):
        f, profile = self.identify(request, 6)
        if self.lifecycle:
            return self.lifecycle.request_load(f, profile)
        binding = self.housing.resolve_load(profile["ps4_id"], f[2], f[5])
        # Native MANAGERLogin login closure requests the literal Login. The
        # space-loading response must name an actual scene bundle. This is an
        # explicit local default, not recovered retired-service routing policy.
        scene = binding["psidglobal"] if binding else ("Nexus" if f[2] == "Login" else f[2])
        forced_instance = binding["instance_id"] if binding else None
        if f[5]:
            target = self.store.db.execute("SELECT instance_id,psidglobal FROM allocations WHERE guid=?", (f[5],)).fetchone()
            if not target or target[1] != scene or (forced_instance and target[0] != forced_instance):
                raise ProtocolError("Requested player has no ready local instance", 503)
            forced_instance = target[0]
        instance = self.instances.require(psidglobal=scene, instance_id=forced_instance, exclude_instance=f[4] or None)
        if instance["players"] >= instance["maxusers"]:
            return f[0] + "#false#true"
        with self.store.db:
            self.store.db.execute("INSERT INTO allocations VALUES(?,?,?,?,?,?) ON CONFLICT(guid) DO UPDATE SET instance_id=excluded.instance_id,psidglobal=excluded.psidglobal,ip=excluded.ip,port=excluded.port,allocated_at=excluded.allocated_at", (f[0], instance["instance_id"], instance["psidglobal"], instance["ip"], int(instance["port"]), time.time()))
        return f[0] + "#false#false"

    def route_N2SpaceLoading(self, request):
        f, profile = self.identify(request, 2)
        if self.lifecycle:
            return self.lifecycle.poll(f[0], profile)
        allocation = self.store.db.execute("SELECT * FROM allocations WHERE guid=?", (f[0],)).fetchone()
        instance = self.instances.ready(instance_id=allocation["instance_id"], psidglobal=allocation["psidglobal"]) if allocation else None
        if not allocation or not instance:
            return f[0] + "#false"
        # A preserved instance may restart on a different loopback port between
        # allocation and the client's polling callback. The fresh descriptor is
        # the liveness authority; never advertise the cached endpoint after it
        # has changed.
        return "#".join((f[0], "true", instance["instance_id"], instance["psidglobal"],
                         instance["ip"], str(instance["port"])))

    def route_spaceExistServlet(self, request):
        f, _ = self.identify(request, 5)
        allocation = self.store.db.execute("SELECT instance_id FROM allocations WHERE guid=?", (f[0],)).fetchone()
        instance = self.instances.ready(psidglobal=f[4], instance_id=allocation[0]) if allocation else None
        exists = instance is not None and f[2] == instance["ip"] and f[3] == str(instance["port"])
        return "true#" + f[0] + ("#true" if exists else "#false")

    def collection(self, request, group):
        f, profile = self.identify(request, 2)
        return self.resources.response(profile["ps4_id"], f[0], group)

    def route_GetCompanionsServlet(self, request):
        return self.collection(request, "companions")

    def route_GetLocomotionsServlet(self, request):
        return self.collection(request, "locomotions")

    def route_GetPersonalSpacesServlet(self, request):
        f, profile = self.identify(request, 2)
        return "#".join(("true", f[0], f[1], "!".join(self.housing.personal_spaces(profile["ps4_id"]))))

    def route_InWardrobeCheckerServlet(self, request):
        f, profile = self.identify(request, 2)
        with self.store.db:
            if self.store.current_guid(profile["ps4_id"]) == f[0]:
                self.store.db.execute("UPDATE profile_state SET wardrobe_updated_at=? WHERE ps4_id=? AND in_wardrobe=1", (time.time(), profile["ps4_id"]))
        return "true#"

    def route_RemoveInWardrobeServlet(self, request):
        f, profile = self.identify(request, 3)
        with self.store.db:
            if self.store.current_guid(profile["ps4_id"]) == f[0]:
                self.store.db.execute("UPDATE profile_state SET in_wardrobe=0,wardrobe_instance_id='',wardrobe_updated_at=? WHERE ps4_id=?", (time.time(), profile["ps4_id"]))
        return "true#"

    def route_GetSpaceEventServlet(self, request):
        f, _ = self.identify(request, 3)
        return "true#" + f[0] + "#false"  # no local event scheduled

    def route_GetrefusernameServlet(self, request):
        f, _ = self.identify(request, 3)
        row = self.store.db.execute("SELECT s.guid FROM profiles p JOIN sessions s USING(ps4_id) WHERE p.username=? ORDER BY s.created_at DESC LIMIT 1", (f[2],)).fetchone()
        return "true#" + f[0] + "#" + (row[0] if row else "")

    def route_GetHousingTypeServlet(self, request):
        f, profile = self.identify(request, 3)
        from housing import TYPE_TABLES
        if f[2] not in {str(key) for key in TYPE_TABLES}:
            raise ProtocolError("Invalid housing category selector")
        items = self.housing.inventory(profile["ps4_id"], TYPE_TABLES[int(f[2])])
        fields = ["true", f[0], f[1], f[2]]
        for item in items:
            fields.extend((item["item_id"], item["table"], item["display_name"]))
        return "#".join(fields)

    def route_HousingReadPresetServlet(self, request):
        f, profile = self.identify(request, 3)
        binding = self.housing.allocated_binding(f[0], f[2])
        current_owner = self.store.current_guid(binding["owner_ps4_id"])
        if profile["ps4_id"] == binding["owner_ps4_id"]:
            # The owner loads the layout during scene setup, before its first
            # announced-presence heartbeat. Its current exact allocation is
            # already established by allocated_binding above.
            if f[0] != current_owner:
                raise ProtocolError("Historical owner session cannot load this housing instance", 403)
            owner_guid = f[0]
        else:
            # The client stores this field as guidOwner and uses it to leave
            # when that owner disconnects. Never return a newer session in
            # some other world, or a historical session left in allocations.
            presence = self.store.presence()
            matches = [row[0] for row in self.store.db.execute(
                """SELECT a.guid FROM allocations a JOIN sessions s USING(guid)
                WHERE s.ps4_id=? AND a.instance_id=? AND a.psidglobal=?""",
                (binding["owner_ps4_id"], binding["instance_id"], binding["psidglobal"]))
                if row[0] == current_owner and row[0] in presence]
            if len(matches) != 1:
                raise ProtocolError("Personal-space owner is no longer present in this instance", 503)
            owner_guid = matches[0]
        return "#".join(("true", f[0], f[1], json_field(self.housing.load(binding)), owner_guid))

    route_N2HousingReadPreset = route_HousingReadPresetServlet

    def route_HousingSavePresetServletParts(self, request):
        f, _ = self.identify(request, 4)
        self.housing.save_part(f[0], f[2], f[3])
        return "#".join(("true", f[0], f[1], "true"))

    def route_N2GetUserTypeSpace(self, request):
        f, _ = self.identify(request, 4)
        if f[3] not in ("0", "1"):
            raise ProtocolError("Unsupported personal-space platform")
        target = self.store.find_username(f[2], f[3])
        presence = self.store.presence()
        available = False
        if target:
            for row in self.store.db.execute("SELECT a.guid,a.instance_id,a.psidglobal FROM allocations a JOIN sessions s USING(guid) WHERE s.ps4_id=?", (target["ps4_id"],)):
                binding = self.housing.binding(row["instance_id"])
                if (row["guid"] in presence and binding and binding["owner_ps4_id"] == target["ps4_id"]
                        and self.instances.ready(instance_id=row["instance_id"], psidglobal=row["psidglobal"])):
                    available = True
        return "OK##" + ("true" if available else "false")

    def route_ReportServlet(self, request):
        f, _ = self.identify(request, 5)
        try:
            option = int(f[2])
        except ValueError as exc:
            raise ProtocolError("Invalid report option") from exc
        if option < 0 or not f[3]:
            raise ProtocolError("Invalid report target/option")
        # Durable local receipt; no external message or original moderation claim.
        with self.store.db:
            self.store.db.execute("CREATE TABLE IF NOT EXISTS local_reports (guid TEXT NOT NULL,target TEXT NOT NULL,option INTEGER NOT NULL,text TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(guid,target,option))")
            accepted = self.store.db.execute("INSERT OR IGNORE INTO local_reports VALUES(?,?,?,?,?)", (f[0], f[3], option, f[4], time.time())).rowcount == 1
        return "#".join(("true", f[0], f[1], "true" if accepted else "false"))

    def route_checkStateNPFriendsServlet(self, request):
        if len(request.fields) < 2:
            raise ProtocolError("Missing external-friend identity")
        f = request.fields
        self.store.session(f[0], f[1])
        # This Steam preservation service has no PSN credential/session source.
        # Zero returned entries follows the recovered empty-list UI branch.
        return "true#" + f[0]

    def consumable_response(self, request, purchase):
        f, _ = self.identify(request, 4)
        if not f[3].isascii() or not f[3].isdigit() or int(f[3]) != 0:
            raise ProtocolError("Unsupported consumable table ID")
        method = self.consumables.issue_response if purchase else self.consumables.price_response
        return method(ps4_id=f[1], guid=f[0], kind=f[2], table_id=0)

    def route_GetConsumablePriceServlet(self, request):
        return self.consumable_response(request, False)

    def route_GetConsumableServlet(self, request):
        return self.consumable_response(request, True)
