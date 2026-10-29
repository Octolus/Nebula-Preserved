"""Audited synthetic data seeding. No caller-controlled SQL or secret tables."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

FIXTURE_ID = "configured-mutations-v1"
ALLOWLIST = {
    "shop_wallets": "ps4_id crystals np level".split(),
    "shop_catalogs": "shop_id type_shop name description url active".split(),
    "shop_offers": "offer_id kind item_id gender category shop_id type_id gender_id name image_path crystals np featured active created_at".split(),
    "shop_bundle_items": "bundle_offer_id child_offer_id ordinal".split(),
    "relations": "ps4_id target target_platform kind".split(),
    "local_reward_definitions": "route trigger_key enabled grant_kind item_id gender category display_name sprite_id units uses configured_at".split(),
    "housing_spaces": "instance_id logical_space_key psidglobal owner_ps4_id created_at".split(),
    "housing_entitlements": "ps4_id item_id display_name granted_at".split(),
    "allocations": "guid instance_id psidglobal ip port allocated_at".split(),
    "housing_save_stages": "instance_id guid owner_ps4_id batch_id shared_json part0_json part1_json state started_at deadline".split(),
    "notification_outbox": "event_id target_ps4_id source_username source_platform notification_type arguments ticks dedupe_key created_at accepted_at".split(),
}


def validate_fixture(fixture):
    if not isinstance(fixture, dict) or set(fixture) != {"format_version", "fixture_id", "provenance", "accounts", "tables"}:
        raise ValueError("INVALID_FIXTURE_SHAPE")
    if fixture["format_version"] != 1 or fixture["fixture_id"] != FIXTURE_ID or fixture["provenance"] != "SYNTHETIC_PARITY_ONLY":
        raise ValueError("UNREVIEWED_FIXTURE")
    if not isinstance(fixture["accounts"], list) or len(fixture["accounts"]) != 2:
        raise ValueError("INVALID_FIXTURE_ACCOUNTS")
    for account in fixture["accounts"]:
        if set(account) != {"account_id", "username", "platform", "request_hash"} or account["account_id"] not in {"fixture-parity-a", "fixture-parity-b"} or account["platform"] != "StandaloneWindows":
            raise ValueError("INVALID_SYNTHETIC_ACCOUNT")
        if len(account["request_hash"]) != 64 or any(c not in "0123456789abcdef" for c in account["request_hash"]):
            raise ValueError("INVALID_FIXTURE_HASH")
    if not isinstance(fixture["tables"], dict) or set(fixture["tables"]) != set(ALLOWLIST):
        raise ValueError("UNREVIEWED_FIXTURE_TABLE")
    for table, columns in ALLOWLIST.items():
        rows = fixture["tables"][table]
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("FIXTURE_ROW_LIMIT")
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns) or any(isinstance(value, (dict, list)) for value in row.values()):
                raise ValueError("UNREVIEWED_FIXTURE_COLUMN_OR_VALUE")
    return fixture


def apply_fixture(backend, fixture):
    validate_fixture(fixture)
    reviewed = json.loads((Path(__file__).resolve().parent / "fixtures" / (FIXTURE_ID + ".json")).read_text(encoding="utf-8"))
    if fixture != reviewed:
        raise ValueError("IMMUTABLE_FIXTURE_CONTENT_MISMATCH")
    if backend.store.db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]:
        raise ValueError("FIXTURE_REQUIRES_FRESH_DATABASE")
    for account in fixture["accounts"]:
        fields = [account["username"], "v72", "false", account["account_id"], "1.25", account["platform"]]
        backend.service.dispatch("N2UserExist", "#".join(fields))
        backend.service.dispatch("ChannelGUIDServlet", "#".join([account["account_id"], account["request_hash"], account["platform"]]))
    with backend.store.atomic():
        for table, columns in ALLOWLIST.items():
            # Names originate exclusively from this audited module allowlist.
            query = 'INSERT INTO "' + table + '" (' + ",".join('"' + column + '"' for column in columns) + ") VALUES(" + ",".join("?" for _ in columns) + ")"
            for row in fixture["tables"][table]:
                backend.store.db.execute(query, [row[column] for column in columns])


def account_guid(account, request_hash):
    return hashlib.sha256((account + "#" + request_hash).encode("ascii")).hexdigest()[:32]
