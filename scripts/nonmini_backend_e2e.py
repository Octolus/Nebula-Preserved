"""Disposable real-process HTTP/persistence acceptance, never native gameplay.

Starts only owned loopback listeners against a new temporary database. Scene
status/presence and the trusted Mirror friendship handoff are explicit fixtures;
no Unity world, chat transport, game client, TLS or production state is tested.
Run separately from the fast unit suite with --artifacts pointing outside Git.
"""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tools")]
from avatar_entry_codec import encode_entry_fields, encode_value_texts
from housing import HOUSING_FIELDS
from public_access import AccessAuthority, migrate
from service import Service
from state import Catalog, Store
from wire import decrypt, encrypt, session_guid

# Deliberate fictitious identities: these are not live Steam accounts.
OWNER, VISITOR = "7656119" + "0000000001", "7656119" + "0000000002"
NAMES = {OWNER: "E2EOwner", VISITOR: "E2EVisitor"}
INSTANCE = "e2e-fixture-apartment"


class AcceptanceFailure(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise AcceptanceFailure("loopback_acceptance_must_not_follow_redirects")


def require(value, label):
    if not value:
        raise AcceptanceFailure(label)


def unused_ports():
    sockets = []
    try:
        for _ in range(2):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            sockets.append(listener)
        return tuple(listener.getsockname()[1] for listener in sockets)
    finally:
        for listener in sockets:
            listener.close()


def json_file(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
    temporary.replace(path)


class Scenario:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.state = self.directory / "state"
        self.state.mkdir()
        self.http_port, self.admin_port = unused_ports()
        self.process = self.log = None
        self.guids, self.checks = {}, []
        self.token = secrets.token_urlsafe(32)
        self.credentials = {}
        self.sequence = 0
        self.phase = "setup"
        # Never send fixture credentials through a machine-wide proxy or a
        # redirect response; only our two explicitly owned loopback ports exist.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def check(self, label, condition=True):
        require(condition, label)
        self.checks.append(label)

    def seed(self):
        store = Store(self.state / "preservation.sqlite3")
        try:
            catalog = Catalog(ROOT / "protocol")
            service = Service(store, catalog)
            for account, name in NAMES.items():
                store.account(account, name)
            migrate(store.db)
            authority = AccessAuthority(store.db)
            authority.initialize_operator(secrets.token_bytes(32))
            self.credentials = {account: authority.issue(account) for account in NAMES}
            self.item = next(row for row in catalog.items.values()
                             if row["gender"] == "MALE" and row["category"] == "CLOTH_HEAD_HAT")
            service.shop.configure_shop("e2e-shop", 0, "Disposable acceptance store")
            service.shop.configure_offer("e2e-offer", "wardrobe", self.item["item_id"],
                "e2e-shop", self.item["category"], 0, "Disposable acceptance hat", "",
                23, 0, self.item["gender"], self.item["category"], True)
            service.housing.bind_space(INSTANCE, "Home", OWNER)
            self.furniture = next(key for key, value in service.housing.catalog.items()
                                  if value["behaviour"] == "ground" and value["placement_cost"] == 1)
        finally:
            store.close()
        token_file = self.directory / "management-token.txt"
        token_file.write_text(self.token, encoding="ascii")
        token_file.chmod(0o600)
        json_file(self.directory / "operators.json", {"operators": [
            {"id": "owner", "role": "owner", "enabled": True},
            {"id": "moderator", "role": "moderator", "enabled": True}]})
        self.check("isolated_state_and_operator_provisioning")

    def fixtures(self):
        """Fixture only: no real scene listener or Mirror peer is represented."""
        instance = self.state / "instances" / INSTANCE
        instance.mkdir(parents=True, exist_ok=True)
        now = time.time()
        json_file(instance / "instance-status.json", dict(
            format_version=1, protocol_complete=False, game_ready=False,
            networking_parity="unproven", listening=True, listener_bound=True,
            readiness_scope="nonmini-core-v1", core_test_eligible=True,
            board_tables=0, darts_tables=0, heartbeat=now, ip="127.0.0.1",
            bind="127.0.0.1", port=28002, instance_id=INSTANCE, psidglobal="Home",
            players=len(self.guids), maxusers=32, scene_registry_verified=True,
            housing_bound=True, housing_owner=OWNER))
        json_file(instance / "instance-presence.json", dict(
            format_version=1, generation=now, instance_id=INSTANCE, psidglobal="Home",
            players=[{"guid": guid, "status": 0} for guid in self.guids.values()]))

    def request(self, port, route, *, authorization=None, body=None, headers=None):
        supplied = dict(headers or {})
        if authorization:
            supplied["Authorization"] = authorization
        if body is not None:
            supplied["Content-Type"] = "application/json"
        request = urllib.request.Request(f"http://127.0.0.1:{port}/{route}",
            data=None if body is None else json.dumps(body).encode(), headers=supplied)
        try:
            response = self.opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, "bounded_response")
            return response.status, raw.decode("utf-8")

    def start(self):
        self.phase = "start"
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
            NEBULA_ADMIN_TOKEN_FILE=str(self.directory / "management-token.txt"),
            NEBULA_ADMIN_OPERATORS_FILE=str(self.directory / "operators.json"),
            NEBULA_ADMIN_BIND="127.0.0.1", NEBULA_ADMIN_PORT=str(self.admin_port))
        environment.update({key: str(self.directory) for key in ("TEMP", "TMP", "TMPDIR")})
        self.log = (self.directory / "backend.log").open("ab")
        self.process = subprocess.Popen([sys.executable, "-B", str(ROOT / "backend/server.py"),
            "--listen", "--state-dir", str(self.state), "--port", str(self.http_port),
            "--public-access", "--core-test-profile", "nonmini-core-v1"],
            cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "backend_process_stayed_alive_during_start")
            try:
                status, body = self.request(self.http_port, "preservation/health")
                if status == 200:
                    health = json.loads(body)
                    require(health["public_access"] is True and health["game_ready"] is False,
                            "health_reports_authentication_and_unproven_gameplay")
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.05)
        raise AcceptanceFailure("backend_start_deadline")

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def wire(self, route, *fields, account=OWNER, expected=200, authenticated=True, refresh=True):
        if refresh:
            self.fixtures()
        query = urllib.parse.urlencode({"data": encrypt("#".join(str(x) for x in fields)
                                                            + "#StandaloneWindows")})
        status, body = self.request(self.http_port, route + "?" + query,
            authorization=self.credentials[account] if authenticated else None)
        require(status == expected, "wire_status_" + route + "_" + str(expected))
        return decrypt(body)

    def management(self, route, body=None, *, actor="owner", key=None, expected=200):
        self.sequence += 1
        headers = {"X-Management-Actor": actor,
                   "Idempotency-Key": key or "e2e-command-" + str(self.sequence)}
        status, raw = self.request(self.admin_port, "management/v1/" + route,
            authorization="Bearer " + self.token, body=body, headers=headers)
        require(status == expected, "management_status_" + route + "_" + str(expected))
        result = json.loads(raw)
        return result.get("data") if expected == 200 else result["error"]

    def login(self, account, nonce):
        response = self.wire("N2UserExist", NAMES[account], "v72", "false", account,
                             "1.25", account=account)
        require(response.split("#") == [account, "", "preservation", "false", "false", "", ""],
                "native_login_response_shape")
        require(self.wire("ChannelGUIDServlet", account, nonce * 64, account=account) == "true#",
                "channel_guid_acknowledgement")
        self.guids[account] = session_guid(account, nonce * 64)
        return self.guids[account]

    def preset(self, account=OWNER):
        guid = self.guids[account]
        fields = self.wire("GetLastUsedPreset", guid, account, guid, "0",
                           account=account).split("#")
        require(fields[:3] == ["true", account, "MALE"] and len(fields) == 6,
                "preset_response_shape")
        return json.loads(fields[3])

    def purchase_data(self, account=OWNER):
        return json.loads(self.wire("GetPurchases", self.guids[account], account=account).split("#")[2])

    def household_load(self, account, owner_guid=""):
        guid = self.guids[account]
        require(self.wire("N2LoadSpace", guid, account, "Home", "false", "", owner_guid,
                          account=account) == guid + "#false#false", "apartment_allocation_ack")
        loading = self.wire("N2SpaceLoading", guid, account, account=account).split("#")
        require(loading[:4] == [guid, "true", INSTANCE, "Home"], "apartment_loading_contract")

    def layout_parts(self):
        layout = {field["name"]: "Home" if field["name"] == "psidglobal" else []
                  for field in HOUSING_FIELDS}
        layout.update(aidasset=[self.furniture] * 101, aidasset_tx=["1.25"] * 100 + ["2.5"],
                      aidasset_ty=["0"] * 101, aidasset_tz=["0"] * 101,
                      aidasset_r=["90"] * 101, atablename=None)
        parts = []
        for first in (True, False):
            value = copy.deepcopy(layout)
            for index in range(101):
                if (index < 100) != first:
                    value["aidasset"][index] = "null"
                    for key in ("aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r"):
                        value[key][index] = "0"
            parts.append(encode_entry_fields(value, HOUSING_FIELDS))
        return parts

    def run(self):
        self.seed()
        self.start()
        self.phase = "account_and_authentication"
        owner_guid = self.login(OWNER, "a")
        visitor_guid = self.login(VISITOR, "b")
        self.check("real_http_bootstrap_two_credential_bound_accounts")
        self.wire("GetPlayerPrefsServlet", owner_guid, OWNER, authenticated=False, expected=403)
        self.wire("GetPlayerPrefsServlet", owner_guid, OWNER, account=VISITOR, expected=403)
        self.check("anonymous_and_cross_account_http_denial")
        self.phase = "wallet_shop_customization"
        self.check("store_offer_is_not_owned_before_purchase",
                   self.item["item_id"] not in self.purchase_data()["cloths"])
        route = "users/" + OWNER + "/wallet-adjustments"
        body = {"currency": "crystals", "delta": 100, "reason": "Disposable E2E credit"}
        first = self.management(route, body, key="e2e-stable-wallet")
        repeat = self.management(route, body, key="e2e-stable-wallet")
        self.check("management_wallet_http_idempotent_receipt",
                   first["request_id"] == repeat["request_id"] and repeat["replayed"])
        self.management(route, {**body, "delta": 101}, key="e2e-stable-wallet", expected=409)
        self.management(route, body, actor="moderator", expected=403)
        self.check("wallet_key_conflict_and_moderator_economy_denial")
        self.wire("NPShopBuyItemServlet", owner_guid, OWNER, "e2e-offer", 0, 0, 0, expected=409)
        self.check("client_price_tampering_refused_without_debit",
                   self.management("users/" + OWNER + "/wallet")["crystals"] == 100)
        self.fixtures()
        def buy(_):
            return self.wire("NPShopBuyItemServlet", owner_guid, OWNER,
                             "e2e-offer", 23, 0, 0, refresh=False)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(buy, range(8)))
        prefix = "true#" + owner_guid + "#" + OWNER + "#"
        require(results.count(prefix + "OK") == 1
                and results.count(prefix + "ISPURCHASED") == 7, "concurrent_purchase_acknowledgements")
        self.check("eight_concurrent_http_purchases_debit_and_grant_once",
                   self.management("users/" + OWNER + "/wallet")["crystals"] == 77
                   and self.item["item_id"] in self.purchase_data()["cloths"]
                   and self.management("users/" + VISITOR + "/wallet")["crystals"] == 0)
        self.saved_preset = self.preset()
        slot = next("item" + str(i) for i in range(1, 40)
                    if self.saved_preset["item" + str(i)] == "null")
        self.saved_preset[slot] = self.item["item_id"]
        schema = json.loads((ROOT / "protocol/bootstrap-response-contracts.json").read_text())
        fields = next(row["fields"] for row in schema["json_and_enum_declarations"]
                      if row["name"] == "JsonClasses.PresetMaleJson")
        float_key = next(row["name"] for row in fields if "float" in row["type_and_modifiers"])
        self.saved_preset[float_key] = 1.125
        tokens = [None if self.saved_preset[row["name"]] is None
                  else format(self.saved_preset[row["name"]], ".9g")
                  if "float" in row["type_and_modifiers"] else self.saved_preset[row["name"]]
                  for row in fields]
        require(self.wire("N2SavePreset", owner_guid, OWNER, "E2ESaved", "0",
                          encode_value_texts(tokens)) == "true#true", "avatar_save_ack")
        self.saved_preset["presetname"] = "E2ESaved"
        self.check("native_serialized_customization_http_roundtrip", self.preset() == self.saved_preset)
        self.wire("SavePlayerPref", owner_guid, "NotificationLoginFriend", "0")
        self.check("settings_http_save")
        self.phase = "social_housing"
        directory = self.state / "friend-events"
        directory.mkdir()
        event = str(uuid.uuid4())
        json_file(directory / (event + ".json"), dict(format_version=1, event_id=event,
            policy="correlated_online_request_v1", operation="accept_friendship",
            actor_ps4_id=OWNER, other_ps4_id=VISITOR, created_at=time.time()))
        for account, guid in ((OWNER, owner_guid), (VISITOR, visitor_guid)):
            result = self.wire("N2GetSocialList", guid, account, "0", "0", account=account).split("#")
            require(result[3] == "1", "reciprocal_friend_handoff_projection")
        self.check("trusted_mirror_friendship_fixture_import_and_reciprocal_http_projection")
        self.management("users/" + OWNER + "/items", dict(kind="housing", item_id=self.furniture,
                         reason="Disposable E2E furniture"))
        self.household_load(OWNER)
        self.household_load(VISITOR, owner_guid)
        parts = self.layout_parts()
        self.wire("HousingSavePresetServletParts", visitor_guid, VISITOR, parts[0], "0",
                  account=VISITOR, expected=403)
        self.check("apartment_visitor_edit_denied_over_http")
        for part in ("0", "1", "1"):
            response = self.wire("HousingSavePresetServletParts", owner_guid, OWNER,
                                 parts[int(part)], part)
            require(response == "true#" + owner_guid + "#" + OWNER + "#true", "atomic_layout_ack")
            if part == "0":
                pending = self.wire("HousingReadPresetServlet", owner_guid, OWNER, "Home").split("#")
                self.check("uncommitted_first_housing_part_is_not_published",
                           json.loads(pending[3])["aidasset"] == [])
        layout = self.wire("HousingReadPresetServlet", visitor_guid, VISITOR, "Home",
                           account=VISITOR).split("#")
        self.saved_layout = json.loads(layout[3])
        self.check("atomic_101_item_apartment_save_retry_and_visitor_read",
                   self.saved_layout["aidasset_tx"] == [1.25] * 100 + [2.5]
                   and layout[4] == owner_guid)
        self.phase = "process_restart"
        self.stop()
        self.start()
        owner_guid = self.login(OWNER, "c")
        visitor_guid = self.login(VISITOR, "d")
        self.check("fresh_process_and_fresh_session_restore_customization", self.preset() == self.saved_preset)
        prefs = json.loads(self.wire("GetPlayerPrefsServlet", owner_guid, OWNER).split("#")[2])
        self.check("fresh_process_restore_settings_and_wallet", prefs["notificationLoginFriend"] == 0
                   and self.management("users/" + OWNER + "/wallet")["crystals"] == 77)
        self.check("fresh_process_restore_item_purchase_and_ownership",
                   self.item["item_id"] in self.purchase_data()["cloths"]
                   and self.wire("NPShopIsItemPurchasedServlet", owner_guid, OWNER, "e2e-offer")
                   == "true#" + owner_guid + "#" + OWNER + "#True")
        self.check("fresh_process_restore_friendship",
                   self.wire("N2GetSocialList", visitor_guid, VISITOR, "0", "0",
                             account=VISITOR).split("#")[3] == "1")
        self.household_load(OWNER)
        self.household_load(VISITOR, owner_guid)
        layout = self.wire("HousingReadPresetServlet", owner_guid, OWNER, "Home").split("#")
        self.check("fresh_process_restore_complete_apartment", json.loads(layout[3]) == self.saved_layout)
        self.wire("SavePlayerPref", session_guid(OWNER, "a" * 64), "NotificationLoginFriend", "1",
                  expected=403)
        self.check("historical_session_cannot_overwrite_fresh_settings")
        self.phase = "moderation"
        route = "users/" + OWNER + "/kick"
        first = self.management(route, {"reason": "Disposable E2E kick"},
                                actor="moderator", key="e2e-stable-kick")
        self.wire("GetPlayerPrefsServlet", owner_guid, OWNER, expected=403)
        fresh = self.login(OWNER, "e")
        replay = self.management(route, {"reason": "Disposable E2E kick"},
                                 actor="moderator", key="e2e-stable-kick")
        self.wire("GetPlayerPrefsServlet", fresh, OWNER)
        self.check("live_http_kick_revokes_session_and_replay_preserves_fresh_login",
                   first["request_id"] == replay["request_id"] and replay["replayed"])
        self.management("users/" + OWNER + "/ban", {"reason": "Disposable E2E ban"}, actor="moderator")
        banned = self.wire("N2UserExist", NAMES[OWNER], "v72", "false", OWNER, "1.25").split("#")
        self.check("moderator_ban_uses_original_login_ban_response", banned[4:6] == ["true", "null"])
        self.stop()
        self.start()
        self.check("fresh_process_preserves_ban_and_economy",
                   self.management("users/" + OWNER + "/moderation")["banned"]
                   and self.management("users/" + OWNER + "/wallet")["crystals"] == 77)
        self.management("users/" + OWNER + "/unban", {"reason": "Disposable E2E unban"}, actor="moderator")
        self.login(OWNER, "f")
        self.check("unban_allows_new_login_without_data_loss", self.preset() == self.saved_preset)
        self.phase = "complete"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True,
                        help="New private output directory; never an existing state directory")
    args = parser.parse_args(argv)
    args.artifacts = args.artifacts.resolve()
    require(not args.artifacts.is_relative_to(ROOT.resolve()), "artifacts_must_be_outside_checkout")
    require(not args.artifacts.exists(), "artifacts_directory_must_be_new")
    args.artifacts.mkdir(parents=True, mode=0o700)
    started = time.monotonic()
    scenario = Scenario(args.artifacts)
    passed, failure = False, None
    try:
        scenario.run()
        passed = True
    except Exception as error:
        failure = str(error) if isinstance(error, AcceptanceFailure) else type(error).__name__
    finally:
        scenario.stop()
    result = {"format": "nebula-nonmini-http-e2e-v1", "passed": passed,
        "seconds": round(time.monotonic() - started, 3), "checks": scenario.checks,
        "phase": scenario.phase, "failure": failure,
        "scope": "Disposable real backend process, authenticated HTTP, SQLite, restart and management",
        "fixtures": ["scene readiness/presence metadata", "trusted Mirror friendship event"],
        "not_tested": ["native game client", "Mirror/chat transport", "TLS ingress", "minigames"],
        "source_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"):
            hashlib.sha256(path.read_bytes()).hexdigest() for path in
            [Path(__file__).resolve(), *sorted((ROOT / "backend").glob("*.py")),
             *sorted((ROOT / "tools").glob("*.py")), *sorted((ROOT / "protocol").glob("*.json"))]}}
    (args.artifacts / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("passed", "seconds", "phase", "failure")}
                     | {"checks": len(result["checks"])}))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
