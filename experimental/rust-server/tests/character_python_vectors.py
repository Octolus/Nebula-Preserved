"""Capture offline reference behavior for Rust conformance tests.

This executes Python only while authoring test fixtures. The Rust server never
imports, launches or delegates requests to Python. No native client is run.
"""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("NEBULA_REFERENCE", Path(__file__).resolve().parents[3]))
STATE = ROOT / "test-state" / "character-reference-capture"
STATE.mkdir(parents=True, exist_ok=True)
db_path = STATE / "preservation.sqlite3"
for suffix in ("", "-wal", "-shm"):
    db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
sys.path[:0] = [str(SOURCE / "backend"), str(SOURCE / "tools")]
from service import Service
from state import Store, Catalog
from wire import session_guid
from avatar_entry_codec import encode_value_texts
from avatar import schema_fields

time.time = lambda: 1_700_000_000.0
account = "76561198000000001"
username = "Rust differential user"
request_hash = "ab" * 32
guid = session_guid(account, request_hash)
store = Store(db_path)
service = Service(store, Catalog(SOURCE / "protocol"))
vectors = []


def call(route, fields, *, platform="StandaloneWindows", status=200):
    wire = "#".join(fields + [platform])
    try:
        response = service.dispatch(route, wire)
        code = 200
    except Exception as exc:
        response = str(exc)
        code = getattr(exc, "status", 500)
    if code != status:
        raise AssertionError((route, code, status, response))
    vectors.append({"route": route, "fields": fields, "platform": platform,
                    "status": code, "response": response})


call("STMGetUserInfo", ["opaque", account])
call("N2UserExist", [username, "1.0", "false", account, "43"])
call("ChannelGUIDServlet", [account, request_hash])
call("GetIinitInfosNeededServlet", [guid, account])
call("GetPlayerPrefsServlet", [guid, account])
call("SavePlayerPref", [guid, "NameColorSelectedIndex", '{"x":0.25,"y":0.5,"z":0.75}'])
call("SavePlayerPref", [guid, "status", "Snowman \u2603 and emoji \U0001f680"])
call("SavePlayerPref", [guid, "PlatformOnly", "1"])
call("SavePlayerPref", [guid, "NotificationLoginFriend", "0"])
call("SavePlayerPref", [guid, "NameColorSelectedIndex", '{"x":1,"y":2,"z":false}'], status=400)
call("GetPlayerPrefsServlet", [guid, account])
call("GetPurchases", [guid])
call("GetCompanionsServlet", [guid, account])
call("GetLocomotionsServlet", [guid, account])
call("GetLastUsedPreset", [guid, account, guid, "0"])
call("GetLastUsedPreset", [guid, account, guid, "1"])
call("GetInfoServlet", ["1", guid, account])
call("GetInfoServlet", ["2", guid, account, "1"])
call("GetInfoServlet", ["0", guid, account, "0", "CLOTH_HEAD_BEARD", "0"])
call("GetInfoServlet", ["0", guid, account, "0", "CLOTH_HEAD_BEARD", "1"])
call("ShowPresetsServlet", [guid, account, "0"])
call("ResetDefaultPresetServlet", [guid, account, "Authored neutral", "0"])
call("RenamePresetServlet", [guid, account, "Authored neutral", "Renamed neutral", "0"])
call("GetLoadPresetByName", [guid, account, guid, "0", "Renamed neutral"])

# The original native writer's female fields are compensated at this ingress.
female = store.preset(account, "FEMALE")["preset"]
female["f_ch_r_pectoral_jnt_t_x"] = 0.125
female["f_ch_l_pectoral_jnt_s_x"] = 0.875
tokens = [None if female[f["name"]] is None else str(female[f["name"]])
          for f in schema_fields(SOURCE / "protocol", "FEMALE")]
call("N2SavePreset", [guid, account, "Original native female", "1", encode_value_texts(tokens)])
call("GetLoadPresetByName", [guid, account, guid, "1", "Original native female"])
call("RemovePresetServlet", [guid, account, "Renamed neutral", "ignored", "0"])
call("ShowPresetsServlet", [guid, account, "0"])
call("GetInfoServlet", ["3", guid, account, "1", "Original native female"])
call("PlayerLabelInfoServlet", [guid, account, guid])
call("ChannelGUIDServlet", [account, "AB" * 32], status=400)
call("UserExistsServlet", ["different", "1.0", "false", account, "43"], status=409)
call("N2UserExist", ["[TEST] Preservation Client 1", "1.0", "false", "local-preservation-test-1", "43"], status=403)
call("SavePlayerPref", [guid, "PlatformOnly", "2"], status=400)
store.close()
output = ROOT / "tests" / "character_python_vectors.json"
output.write_text(json.dumps({"format_version": 1,
    "evidence": "Offline Python handler responses; no native-client acceptance test",
    "fixed_time": time.time(), "vectors": vectors}, ensure_ascii=True, indent=2), encoding="utf-8")
print(json.dumps({"vectors": len(vectors), "output": str(output)}))

# Keep the integration test self-contained: only the two schemas and catalog
# rows exercised by these vectors are copied. Their values are unmodified.
def document(name):
    return json.loads((SOURCE / "protocol" / name).read_text(encoding="utf-8"))


files = {name: document(name) for name in (
    "avatar-neutral-male.json", "avatar-neutral-female.json",
    "avatar-default-catalog.json", "wardrobe-removal-sentinels.json")}
bootstrap = document("bootstrap-response-contracts.json")
files["bootstrap-response-contracts.json"] = {"json_and_enum_declarations": [
    row for row in bootstrap["json_and_enum_declarations"]
    if row["name"] in ("JsonClasses.PresetMaleJson", "JsonClasses.PresetFemaleJson")]}
ids = {row["item_id"] for gender in ("MALE", "FEMALE")
       for row in files["avatar-default-catalog.json"]["defaults"][gender]["items"]}
ids.update(row["item_id"] for row in files["wardrobe-removal-sentinels.json"]["sentinels"])
files["avatar-asset-catalog.json"] = {"items": [
    row for row in document("avatar-asset-catalog.json")["items"] if row["item_id"] in ids]}
files["resource-entitlements.json"] = {"format_version": 1, "items": []}
fixture_path = ROOT / "tests" / "character_catalog_fixtures.json"
fixture_path.write_text(json.dumps(files, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
print(json.dumps({"catalog_fixture": str(fixture_path), "bytes": fixture_path.stat().st_size}))
