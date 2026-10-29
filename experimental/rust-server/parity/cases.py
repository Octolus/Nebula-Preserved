"""Synthetic headless corpus. Case success never implies full route parity."""
from __future__ import annotations

import hashlib

ACCOUNT_A, ACCOUNT_B = "parity-synthetic-a", "parity-synthetic-b"
HASH_A, HASH_B, HASH_NEXT = "a" * 64, "b" * 64, "c" * 64


def guid(account, digest):
    return hashlib.sha256((account + "#" + digest).encode("ascii")).hexdigest()[:32]


GUID_A, GUID_B, GUID_NEXT = guid(ACCOUNT_A, HASH_A), guid(ACCOUNT_B, HASH_B), guid(ACCOUNT_A, HASH_NEXT)


def corpus(routes):
    cases = []

    def call(label, route, *fields, kind="happy", status=200, platform="StandaloneWindows", expect=None):
        row = {"id": label, "op": "http", "route": route, "method": "GET",
               "plaintext": "#".join(fields) + "#" + platform,
               "category": kind, "expected_status": status}
        if expect is not None:
            row["expected_plaintext"] = expect
        cases.append(row)

    def snapshot(label):
        cases.append({"id": label, "op": "snapshot", "category": "typed_durable_state"})

    # Each route gets framing and adapter errors. These prove only those branches.
    for route in sorted(routes):
        cases.extend([
            {"id": "no-trailer:" + route, "op": "http", "route": route,
             "plaintext": "synthetic", "category": "malformed", "expected_status": 400},
            {"id": "bad-platform:" + route, "op": "http", "route": route,
             "plaintext": "synthetic#UnknownPlatform", "category": "malformed", "expected_status": 400},
            {"id": "empty-fields:" + route, "op": "http", "route": route,
             "plaintext": "#StandaloneWindows", "category": "arity", "expected_status": 403 if route == "GetPurchases" else 400},
        ])
    for label, extra in [
        ("http-post", {"method": "POST", "plaintext": "a#b#StandaloneWindows"}),
        ("http-missing-query", {}),
        ("http-invalid-base64", {"data": "%%%"}),
        ("http-empty-ciphertext", {"data": ""}),
        ("http-invalid-padding", {"data": "AAAAAAAAAAAAAAAAAAAAAA=="}),
    ]:
        cases.append({"id": label, "op": "http", "route": "CheckServerStatusServlet",
                      "category": "adapter", "expected_status": 400, **extra})
    call("unknown-route", "UnreconstructedSyntheticRoute", "x", kind="unsupported", status=501)
    snapshot("state-after-malformed")
    for account, username, digest, suffix in [(ACCOUNT_A, "Parity A", HASH_A, "a"), (ACCOUNT_B, "Parity B", HASH_B, "b")]:
        call("login-" + suffix, "N2UserExist", username, "v72", "false", account, "1.25",
             expect=account + "##preservation#false#false##")
        call("channel-" + suffix, "ChannelGUIDServlet", account, digest, expect="true#")
    snapshot("state-after-login")
    call("server-status", "CheckServerStatusServlet", "Parity A", "4.125", expect="true#Parity A#4.125#1")
    call("checker", "CheckerServlet", "Parity A", "", "", "4.125", expect="OK#4.125#false##")
    call("steam-fixture", "STMGetUserInfo", "", ACCOUNT_A)
    call("legacy-exists", "UserExistsServlet", ACCOUNT_A, "v72", "false", ACCOUNT_A, "1.25")
    call("legacy-mismatch", "UserExistsServlet", "other-id", "v72", "false", ACCOUNT_A, "1.25", kind="isolation", status=409)
    call("channel-uppercase", "ChannelGUIDServlet", ACCOUNT_A, "A" * 64, kind="malformed", status=400)
    call("channel-too-short", "ChannelGUIDServlet", ACCOUNT_A, "a" * 63, kind="malformed", status=400)
    call("bootstrap", "GetIinitInfosNeededServlet", GUID_A, ACCOUNT_A)
    call("prefs-read-a", "GetPlayerPrefsServlet", GUID_A, ACCOUNT_A)
    call("prefs-trigger", "PlayerPrefsServlet", GUID_A, ACCOUNT_A, expect="true#")
    call("purchases-a", "GetPurchases", GUID_A)
    call("purchases-b", "GetPurchases", GUID_B)
    call("news", "GetNewsServlet", "42")
    call("news-range", "GetNewsServlet", "100", kind="edge", status=400)
    call("news-unicode-digit", "GetNewsServlet", "\u0661", kind="edge", status=400)
    call("maintenance", "checkerToServerDownMaintenanceServlet", GUID_A, ACCOUNT_A)
    call("online-a", "N2AddUserOnline", GUID_A, ACCOUNT_A, "Nexus")
    call("online-heartbeat", "N2UpdateUserOnline", GUID_A, ACCOUNT_A)
    call("telemetry-minimal", "InfoServlet", GUID_A, ACCOUNT_A, "synthetic-local")
    for key, value in [("MasterVolume", "0.375"), ("status", "Synthetic status \u2603"),
                       ("NotificationLoginFriend", "0"), ("PlatformOnly", "1"),
                       ("NameColorSelectedIndex", '{"x":0.2,"y":0.3,"z":0.4}')]:
        call("save-pref:" + key, "SavePlayerPref", GUID_A, key, value)
    for key, value in [("MasterVolume", "NaN"), ("MasterVolume", "Infinity"),
                       ("MasterVolume", "3.5e38"), ("PlatformOnly", "2"),
                       ("MissingPreference", "1"), ("NameColorSelectedIndex", '{"x":1,"y":2}')]:
        call("reject-pref:" + key + ":" + value, "SavePlayerPref", GUID_A, key, value, kind="edge", status=400)
    call("prefs-after-write", "GetPlayerPrefsServlet", GUID_A, ACCOUNT_A)
    call("prefs-other-unchanged", "GetPlayerPrefsServlet", GUID_B, ACCOUNT_B, kind="isolation")
    call("prefs-cross-account", "GetPlayerPrefsServlet", GUID_A, ACCOUNT_B, kind="isolation", status=403)
    call("prefs-unknown-session", "GetPlayerPrefsServlet", "0" * 32, ACCOUNT_A, kind="isolation", status=403)
    snapshot("state-after-preferences")
    for label, route, fields in [
        ("companion-empty", "GetCompanionsServlet", (GUID_A, ACCOUNT_A)),
        ("locomotion-empty", "GetLocomotionsServlet", (GUID_A, ACCOUNT_A)),
        ("personal-space-empty", "GetPersonalSpacesServlet", (GUID_A, ACCOUNT_A)),
        ("companion-cross-account", "GetCompanionsServlet", (GUID_A, ACCOUNT_B)),
        ("locomotion-cross-account", "GetLocomotionsServlet", (GUID_A, ACCOUNT_B)),
    ]:
        cross = "cross-account" in label
        call(label, route, *fields, kind="isolation" if cross else "happy", status=403 if cross else 200)
    for gender in ("0", "1"):
        call("avatar-remote:" + gender, "GetLastUsedPreset", GUID_A, ACCOUNT_A, GUID_B, gender)
        call("avatar-named:" + gender, "GetLoadPresetByName", GUID_A, ACCOUNT_A, GUID_A, gender, "Default")
        call("preset-list:" + gender, "ShowPresetsServlet", GUID_A, ACCOUNT_A, gender)
    call("avatar-game", "GetPresetGameServlet", GUID_A, ACCOUNT_A, GUID_A)
    call("label-remote", "PlayerLabelInfoServlet", GUID_A, ACCOUNT_A, GUID_B)
    call("wardrobe-check", "Send_CheckIsInWardrobeServlet", GUID_A, ACCOUNT_A, GUID_B)
    call("wardrobe-heartbeat", "InWardrobeCheckerServlet", GUID_A, ACCOUNT_A)
    call("wardrobe-remove", "RemoveInWardrobeServlet", GUID_A, ACCOUNT_A, "Nexus")
    call("wardrobe-empty-category", "GetInfoServlet", "0", GUID_A, ACCOUNT_A, "0", "missing-category", "0")
    call("wardrobe-list", "GetInfoServlet", "0", GUID_A, ACCOUNT_A, "0", "CLOTH_BODY_TORSO", "0")
    for route in ("N2AddBlock", "N2AddSilenced", "N2ToggleFavorite"):
        call("relation-add:" + route, route, GUID_A, "Parity B", "1")
        call("relation-duplicate:" + route, route, GUID_A, "Parity B", "1", kind="idempotence")
    for list_type in ("0", "1", "2"):
        call("social-modern:" + list_type, "GetSocialList", GUID_A, list_type)
        call("social-legacy:" + list_type, "N2GetSocialList", GUID_A, ACCOUNT_A, list_type, "0")
    call("relationship", "N2GetRelationship", GUID_A, ACCOUNT_A, GUID_B)
    call("relationship-reverse", "N2GetRelationship", GUID_B, ACCOUNT_B, GUID_A, kind="isolation")
    call("social-invalid-list", "GetSocialList", GUID_A, "4", kind="unsupported", status=501)
    for route in ("N2RemoveBlock", "N2RemoveSilenced"):
        call("relation-remove:" + route, route, GUID_A, "Parity B", "1")
    call("relation-remove-unknown-friend", "N2RemoveFriend", GUID_A, "Parity Missing", "1", kind="idempotence")
    call("lookup-unavailable", "N2GetPsidglobalAndGuidByUsernamePlatform", GUID_A, "Parity B", "1")
    call("reference-username", "GetrefusernameServlet", GUID_A, ACCOUNT_A, "Parity B")
    call("external-friends-empty", "checkStateNPFriendsServlet", GUID_A, ACCOUNT_A)
    call("space-event-empty", "GetSpaceEventServlet", GUID_A, ACCOUNT_A, "Nexus")
    call("space-type-unavailable", "N2GetUserTypeSpace", GUID_A, ACCOUNT_A, "Parity B", "1")
    call("allocation-no-listener", "N2LoadSpace", GUID_A, ACCOUNT_A, "Nexus", "false", "", "", kind="readiness", status=503)
    call("allocation-loading-empty", "N2SpaceLoading", GUID_A, ACCOUNT_A, kind="readiness")
    for selector in ("0", "1", "2", "3"):
        call("housing-empty:" + selector, "GetHousingTypeServlet", GUID_A, ACCOUNT_A, selector)
    call("housing-no-allocation", "HousingReadPresetServlet", GUID_A, ACCOUNT_A, "Home", kind="authority", status=403)
    call("housing-alias-no-allocation", "N2HousingReadPreset", GUID_A, ACCOUNT_A, "Home", kind="authority", status=403)
    call("housing-invalid-entry", "HousingSavePresetServletParts", GUID_A, ACCOUNT_A, "synthetic-invalid", "0", kind="malformed", status=400)
    call("space-liveness-empty", "spaceExistServlet", GUID_A, ACCOUNT_A, "127.0.0.1", "29001", "Nexus")
    call("instance-liveness-empty", "CheckIfSpaceStillExistServlet", GUID_A, ACCOUNT_A, "synthetic-instance")
    call("wardrobe-members-unallocated", "GetAllInWardrobe", GUID_A, "synthetic-instance", kind="authority", status=403)
    call("wardrobe-entry-unallocated", "SetUserInWardrobe", GUID_A, "synthetic-instance", "1", "MALE", "", "", "0", "1", "1", "1", "0", "0", "0", kind="authority", status=403)
    call("wardrobe-item-unknown", "WardrobeOptionItemServlet", GUID_A, ACCOUNT_A, "synthetic-missing-item", "2", kind="authority", status=404)
    call("legacy-pref-save", "SetPlayerPrefsServlet", GUID_A, ACCOUNT_A, "Music", "0.25")
    call("preset-reset-copy", "ResetDefaultPresetServlet", GUID_A, ACCOUNT_A, "SyntheticCopy", "0")
    call("preset-rename-copy", "RenamePresetServlet", GUID_A, ACCOUNT_A, "SyntheticCopy", "SyntheticRenamed", "0")
    call("preset-remove-copy", "RemovePresetServlet", GUID_A, ACCOUNT_A, "SyntheticRenamed", "SyntheticRenamed", "0")
    call("preset-reset-default-selection", "ResetDefaultPresetServlet", GUID_A, ACCOUNT_A, "Default", "0")
    call("preset-invalid-serialization", "N2SavePreset", GUID_A, ACCOUNT_A, "Invalid", "0", "synthetic-invalid", kind="malformed", status=400)
    call("account-add-existing", "N2AddUser", ACCOUNT_A, "Parity A", "", "false", "local", "1")
    call("report-empty-target", "ReportServlet", GUID_A, ACCOUNT_A, "0", "", "synthetic", kind="edge", status=400)
    for kind in ("coffee", "oktoberfest"):
        call("consumable-default-price:" + kind, "GetConsumablePriceServlet", GUID_A, ACCOUNT_A, kind, "0")
        call("consumable-no-balance:" + kind, "GetConsumableServlet", GUID_A, ACCOUNT_A, kind, "0")
    for route in ("GetFeaturesServlet", "GetShopInfoPlayerShop"):
        call("shop-empty:" + route, route, GUID_A, ACCOUNT_A)
    call("shop-list-empty", "GetShopDataShopServlet", GUID_A, ACCOUNT_A, "false", "false", "0")
    call("shop-genders-empty", "GetGenderDataShopServlet", GUID_A, ACCOUNT_A, "synthetic-shop")
    call("shop-types-empty", "GetShopTypeDataShopServlet", GUID_A, ACCOUNT_A, "synthetic-shop", "0")
    call("shop-items-empty", "GetItemAssetsDataServlet", GUID_A, ACCOUNT_A, "synthetic-shop", "0", "0")
    call("shop-bundle-missing", "NPShopBundleItemsServlet", GUID_A, ACCOUNT_A, "synthetic-offer", kind="unconfigured", status=404)
    call("shop-buy-missing", "NPShopBuyItemServlet", GUID_A, ACCOUNT_A, "synthetic-offer", "0", "0", "0", kind="unconfigured", status=404)
    call("shop-gift-not-friend", "NPShopGiftItemServlet", GUID_A, ACCOUNT_A, "synthetic-offer", "Parity B", "0", kind="authority", status=403)
    call("shop-owned-missing", "NPShopIsItemPurchasedServlet", GUID_A, ACCOUNT_A, "synthetic-offer", kind="unconfigured", status=404)
    call("shop-receipt-cannot-mint", "NPShopSyncCrystalsServlet", GUID_A, ACCOUNT_A, "synthetic-receipt", "", "1000000", kind="authority")
    call("reward-own-unconfigured", "CheckOwnGenericReward", GUID_A, ACCOUNT_A, "synthetic-reward")
    call("reward-available-unconfigured", "checkRewardAvailableServlet", GUID_A, ACCOUNT_A, "Halloween")
    for route, key in [("GenericReward", "synthetic-reward"), ("RewardClothServlet", "0"),
                       ("RewardConsumeServlet", "coffee"), ("SKLPromoServlet", "synthetic-promo"),
                       ("SKLPromoTriggerServlet", "synthetic-promo"), ("CinemaInteractionNPServlet", "0")]:
        call("reward-missing:" + route, route, GUID_A, ACCOUNT_A, key, kind="unconfigured", status=404)
    for route, fields, status in [
        ("Get_GatherStatus", ("1",), 404), ("Get_GatherPhaseGame", ("1",), 404),
        ("Get_GatherConsume", ("1", "0"), 404), ("Get_GatherConsumeReward", ("1", "0"), 404),
        ("Get_npGather", ("synthetic-event", "1"), 404),
        ("Get_npGatherProcessItem", ("synthetic-event", "1", "1"), 404),
        ("Get_npGatherChristmas", ("Nexus", "0"), 404),
        ("Send_GatherInitInSpace", ("Nexus", "1"), 404),
        ("Get_GatherMedievalVillage", ("1",), 200),
        ("Send_GatherMedievalVillageConsume", ("1",), 409),
    ]:
        call("gathering-default:" + route, route, GUID_A, ACCOUNT_A, *fields, kind="unconfigured", status=status)
    snapshot("state-before-restart")
    cases.append({"id": "restart-store", "op": "restart", "category": "persistence"})
    snapshot("state-after-restart")
    call("prefs-after-restart", "GetPlayerPrefsServlet", GUID_A, ACCOUNT_A, kind="persistence")
    call("avatar-after-restart", "GetLastUsedPreset", GUID_A, ACCOUNT_A, GUID_A, "0", kind="persistence")
    call("social-after-restart", "GetSocialList", GUID_A, "1", kind="persistence")
    cases.append({"id": "restart-probe-process", "op": "process_restart", "category": "persistence"})
    snapshot("state-after-process-restart")
    call("prefs-after-process-restart", "GetPlayerPrefsServlet", GUID_A, ACCOUNT_A, kind="persistence")
    call("avatar-after-process-restart", "GetLastUsedPreset", GUID_A, ACCOUNT_A, GUID_A, "0", kind="persistence")
    call("new-current-session", "ChannelGUIDServlet", ACCOUNT_A, HASH_NEXT)
    call("old-session-read", "GetPlayerPrefsServlet", GUID_A, ACCOUNT_A, kind="historical_session")
    call("old-session-write-denied", "SavePlayerPref", GUID_A, "MasterVolume", "0.5", kind="authority", status=403)
    call("new-session-write", "SavePlayerPref", GUID_NEXT, "MasterVolume", "0.25", kind="authority")
    call("new-session-read", "GetPlayerPrefsServlet", GUID_NEXT, ACCOUNT_A, kind="authority")
    call("other-account-still-isolated", "GetPlayerPrefsServlet", GUID_B, ACCOUNT_B, kind="isolation")
    snapshot("state-final")
    return cases
