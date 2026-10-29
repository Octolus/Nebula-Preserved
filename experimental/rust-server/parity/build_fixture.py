"""Author one immutable synthetic configuration using reviewed catalog identifiers."""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import sys

from common import HERE, environment, scratch, snapshot, write_json, sha256
from fixture_support import ALLOWLIST, FIXTURE_ID, account_guid, validate_fixture


def build(reference):
    os.environ.update(environment(HERE / "temp"))
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(reference / "backend"), str(reference / "tools")]
    from server import Backend
    from avatar_entry_codec import encode_entry_fields
    from housing import HOUSING_FIELDS
    from wire import json_field
    # This authoring database is private scratch and is never reused for a run.
    import uuid
    state = scratch(HERE / "runs" / ("fixture-author-" + uuid.uuid4().hex[:8]))
    backend = Backend(state)
    a, b = "fixture-parity-a", "fixture-parity-b"
    ga, gb = account_guid(a, "d" * 64), account_guid(b, "e" * 64)
    accounts = [{"account_id": a, "username": "Fixture A", "platform": "StandaloneWindows", "request_hash": "d" * 64},
                {"account_id": b, "username": "Fixture B", "platform": "StandaloneWindows", "request_hash": "e" * 64}]
    for account in accounts:
        backend.service.dispatch("N2UserExist", "#".join([account["username"], "v72", "false", account["account_id"], "1.25", "StandaloneWindows"]))
        backend.service.dispatch("ChannelGUIDServlet", "#".join([account["account_id"], account["request_hash"], "StandaloneWindows"]))
    service = backend.service
    pets = service.resources.catalog.list("companions")
    locomotions = service.resources.catalog.list("locomotions")
    ground = next(row for row in service.housing.catalog.values() if row["behaviour"] == "ground" and row["placement_cost"] == 1)
    shop = service.shop
    shop.configure_shop("fixture-shop", 0, "Synthetic Fixture Shop", "Synthetic parity only", "")
    definitions = [
        ("fixture-pet-buy", "companions", pets[0]["item_id"], 20, 7),
        ("fixture-pet-gift", "companions", pets[1]["item_id"], 15, 5),
        ("fixture-bundle-pet", "companions", pets[2]["item_id"], 12, 4),
        ("fixture-bundle-locomotion", "locomotions", locomotions[0]["item_id"], 9, 3),
        ("fixture-rollback-first", "locomotions", locomotions[1]["item_id"], 2, 1),
    ]
    for offer, kind, item, crystals, np in definitions:
        shop.configure_offer(offer, kind, item, "fixture-shop", kind, 0,
                             "Synthetic " + offer, crystals=crystals, np=np, featured=True)
    image = shop._offer("fixture-bundle-pet")["image_path"]
    for name, price in [("fixture-bundle-buy", 25), ("fixture-bundle-rollback", 10)]:
        shop.configure_offer(name, "bundle", None, "fixture-shop", "bundle", 0,
                             "Synthetic " + name, image_path=image, crystals=price, np=6)
    shop.set_wallet(a, 150, 40, 2)
    shop.set_wallet(b, 3, 1, 0)
    # A deliberately invalid second child provides an application-grant failure
    # after debit and the first valid child, to observe atomic rollback.
    broken = dict(shop._offer("fixture-rollback-first"))
    broken.update(offer_id="fixture-rollback-invalid", item_id="synthetic-invalid-resource", name="Synthetic invalid catalog fixture", featured=0)
    columns = ALLOWLIST["shop_offers"]
    with backend.store.db:
        backend.store.db.execute("INSERT INTO shop_offers VALUES(" + ",".join("?" for _ in columns) + ")", [broken[c] for c in columns])
        backend.store.db.executemany("INSERT INTO shop_bundle_items VALUES(?,?,?)", [
            ("fixture-bundle-buy", "fixture-bundle-pet", 0), ("fixture-bundle-buy", "fixture-bundle-locomotion", 1),
            ("fixture-bundle-rollback", "fixture-rollback-first", 0), ("fixture-bundle-rollback", "fixture-rollback-invalid", 1)])
        backend.store.db.executemany("INSERT INTO relations VALUES(?,?,?,?)", [(a, "Fixture B", "StandaloneWindows", "friend"), (b, "Fixture A", "StandaloneWindows", "friend")])
    service.rewards.configure("GenericReward", "fixture-generic", grant_kind="companions", item_id=pets[3]["item_id"], display_name="Synthetic reward pet")
    service.rewards.configure("RewardConsumeServlet", "fixture-coffee", grant_kind="coffee", item_id="coffee", units=2, uses=3)
    service.rewards.configure("RewardConsumeServlet", "fixture-locomotion", grant_kind="locomotions", item_id=locomotions[2]["item_id"], display_name="Synthetic reward locomotion")
    service.rewards.configure("CinemaInteractionNPServlet", "0")
    service.housing.bind_space("fixture-apartment", "Home", a)
    service.housing.grant_item(a, ground["item_id"], "Synthetic housing fixture")
    with backend.store.db:
        backend.store.db.executemany("INSERT INTO allocations VALUES(?,?,?,?,?,?)", [(ga, "fixture-apartment", "Home", "127.0.0.1", 29051, 1700000000.0), (gb, "fixture-apartment", "Home", "127.0.0.1", 29051, 1700000000.0)])
    whole = service.housing.empty_layout("Home")
    whole.update(aidasset=[ground["item_id"]] * 101, aidasset_tx=[1.0] * 100 + [2.0], aidasset_ty=[0.0] * 101, aidasset_tz=[0.0] * 101, aidasset_r=[90.0] * 101, atablename=None)
    parts, value_parts = [], []
    for index in (0, 1):
        part = copy.deepcopy(whole)
        for i in range(101):
            if (i < 100) != (index == 0):
                part["aidasset"][i] = "null"
                for key in ("aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r"):
                    part[key][i] = 0.0
        value_parts.append(copy.deepcopy(part))
        for key in ("aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r"):
            part[key] = [str(value) for value in part[key]]
        parts.append(encode_entry_fields(part, HOUSING_FIELDS))
    shared = {key: whole[key] for key in ("psidglobal", "aidassetWall", "aidassetWallSlot", "aidassetCeiling", "aidassetCeilingSlot")}
    shared["ground_count"] = 101
    with backend.store.db:
        backend.store.db.execute("INSERT INTO housing_save_stages VALUES(?,?,?,?,?,?,?,?,?,?)", ("fixture-apartment", ga, a, "f" * 32, json_field(shared), json_field(value_parts[0]), None, "open", 1700000000.0, 4102444800.0))
    notices = [(b, "Fixture A", 3, "Synthetic fixture-pet-gift", "shop-gift:" + a + ":" + b + ":fixture-pet-gift"),
               (a, "Fixture A", 4, "", "reward:GenericReward:fixture-generic"),
               (a, "Fixture A", 4, "", "reward:RewardConsumeServlet:fixture-coffee"),
               (a, "Fixture A", 4, "", "reward:RewardConsumeServlet:fixture-locomotion")]
    with backend.store.db:
        for index, (target, username, kind, arguments, dedupe) in enumerate(notices, 1):
            backend.store.db.execute("INSERT INTO notification_outbox VALUES(?,?,?,?,?,?,?,?,?,NULL)", (f"{index:032x}", target, username, 1, kind, arguments, 638355968000000000, dedupe, 1700000000.0))
    tables = snapshot(backend.store.db)["tables"]
    fixture_tables = {table: tables[table]["rows"] for table in ALLOWLIST}
    # Immutable seeded timestamps are fixed; only subsequently generated clocks
    # use the explicit per-column runtime normalization whitelist.
    for table, rows in fixture_tables.items():
        for row in rows:
            for column in ("created_at", "configured_at", "granted_at"):
                if column in row:
                    row[column] = 1700000000.0
    fixture = {"format_version": 1, "fixture_id": FIXTURE_ID, "provenance": "SYNTHETIC_PARITY_ONLY", "accounts": accounts, "tables": fixture_tables}
    validate_fixture(fixture)
    target = HERE / "fixtures" / (FIXTURE_ID + ".json")
    write_json(target, fixture)
    write_json(HERE / "fixtures" / "schema.json", {"format_version": 1, "fixture_ids": [FIXTURE_ID], "table_columns": ALLOWLIST,
        "rules": ["Synthetic two-account state only", "Fresh disposable database beneath the owned harness root only", "Parameterized INSERT with exact audited columns only", "No SQL, code, files, listeners, credentials or secret tables", "Deliberately invalid rollback child is fault data, not a supported grant", "Notice dedupe rows are preseeded; notification creation is not proven", "Housing part0 is preseeded; subsequent HTTP duplicate part0 and part1 commit are tested"]})
    write_json(HERE / "fixtures" / "registry.json", {"format_version": 1, "fixtures": [{"fixture_id": FIXTURE_ID, "file": target.name, "sha256": sha256(target)}]})
    write_json(HERE / "fixtures" / "housing-parts.json", {"fixture_id": FIXTURE_ID, "owner_guid": ga, "visitor_guid": gb, "parts": parts, "whole_layout": whole})
    normalization = json.loads((HERE / "normalization.json").read_text())
    for table, column, source in [
        ("resource_entitlements", "granted_at", "backend/resources.py"),
        ("shop_owned", "created_at", "backend/shop.py"),
        ("local_reward_claims", "claimed_at", "backend/rewards.py"),
        ("consumable_balances", "updated_at", "backend/consumables.py"),
        ("cinema_capabilities", "granted_at", "backend/rewards.py"),
        ("housing_layouts", "updated_at", "backend/housing_atomic.py"),
        ("housing_save_receipts", "committed_at", "backend/housing_atomic.py"),
    ]:
        normalization["durable_state"].append({"table": table, "column": column,
            "rule": "finite-positive-clock-to-sentinel-preserve-zero-null-and-numeric-type",
            "reason": "Exact reference field is assigned wall-clock time during configured mutation",
            "source": {"source": source, "sha256": sha256(reference / source)}})
    write_json(HERE / "fixtures/normalization.json", normalization)
    backend.log.close()
    backend.store.close()
    print(json.dumps({"fixture_id": FIXTURE_ID, "sha256": sha256(target), "row_counts": {table: len(rows) for table, rows in fixture_tables.items()}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    build(parser.parse_args().reference.resolve())
