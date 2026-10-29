"""Offline compatibility checks for encrypted HTTP ProtocolError responses."""
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1]
PROTOCOL = BACKEND.parent / "protocol"
sys.path.insert(0, str(BACKEND))

import server
from service import Service
from state import Catalog, Store
from wire import ProtocolError, Request, decrypt, encrypt

def drive(coroutine):
    """Run an async function proven to contain no await on the selected path."""
    try:
        coroutine.send(None)
    except StopIteration as stopped:
        return stopped.value
    raise AssertionError("selected adapter path unexpectedly yielded")


def request(route, plaintext):
    return SimpleNamespace(path="/" + route, method="GET", query={"data": encrypt(plaintext)})


def backend_for(service):
    backend = server.Backend.__new__(server.Backend)
    backend.service = service
    backend.access = None  # Explicit default/private mode for this legacy fixture.
    backend.log = io.StringIO()
    backend.publish_state = lambda: None
    return backend


class RaisingService:
    ROUTES = set()

    def __init__(self, status, message):
        self.status = status
        self.message = message

    def dispatch(self, _command, _plaintext):
        raise ProtocolError(self.message, self.status)


class SuccessService:
    ROUTES = {"Success"}

    @staticmethod
    def dispatch(_command, _plaintext):
        return "true#session#OK"


class HTTPAdapterErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(PROTOCOL)

    def setUp(self):
        self.socket_guard = patch.object(socket, "socket", side_effect=AssertionError(
            "sockets forbidden in HTTP adapter compatibility stage"))
        self.connect_guard = patch.object(socket, "create_connection", side_effect=AssertionError(
            "connections forbidden in HTTP adapter compatibility stage"))
        self.socket_guard.start()
        self.connect_guard.start()
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "preservation.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.connect_guard.stop()
        self.socket_guard.stop()

    def real_service(self):
        return Service(self.store, self.catalog)

    def account(self):
        guid = "a" * 32
        self.store.account("account-a", "Player A")
        self.store.bind_session("account-a", guid)
        return guid

    def test_canonical_adapter_contains_only_the_fixed_encrypted_error_form(self):
        source = (BACKEND / "server.py").read_text(encoding="utf-8")
        old = 'return web.Response(status=exc.status, text=str(exc))'
        new = 'return web.Response(status=exc.status, text=encrypt("ERROR"), content_type="text/plain")'
        self.assertEqual(source.count(old), 0)
        self.assertEqual(source.count(new), 1)

    def test_protocol_errors_preserve_status_encrypt_fixed_delimiter_free_token_and_audit_detail(self):
        for status in (400, 403, 404, 409, 500, 501):
            with self.subTest(status=status):
                detail = f"private detail #{status}"
                backend = backend_for(RaisingService(status, detail))
                response = drive(backend.handle(request("Denied", "payload#StandaloneWindows")))
                self.assertEqual(response.status, status)
                self.assertEqual(response.content_type, "text/plain")
                self.assertEqual(decrypt(response.text), "ERROR")
                self.assertNotIn("#", decrypt(response.text))
                self.assertNotIn(detail, response.text)
                event = json.loads(backend.log.getvalue())
                self.assertEqual((event["command"], event["status"], event["error"]),
                                 ("Denied", status, detail))
                self.assertEqual(len(event["request_sha256"]), 64)

    def test_success_response_remains_status_200_and_original_encrypted_frame(self):
        backend = backend_for(SuccessService())
        response = drive(backend.handle(request("Success", "payload#StandaloneWindows")))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/plain")
        self.assertEqual(decrypt(response.text), "true#session#OK")
        event = json.loads(backend.log.getvalue())
        self.assertEqual((event["command"], event["status"], event["response_bytes"]),
                         ("Success", 200, len("true#session#OK")))

    def test_steam_completed_order_reconciliation_stays_unreconstructed_501_and_write_free(self):
        service = self.real_service()
        self.assertNotIn("STMCompleteSucceededOrders", service.ROUTES)
        changes = self.store.db.total_changes
        backend = backend_for(service)
        response = drive(backend.handle(request(
            "STMCompleteSucceededOrders", "session#steam-id#StandaloneWindows")))
        self.assertEqual(response.status, 501)
        self.assertEqual(decrypt(response.text), "ERROR")
        self.assertEqual(self.store.db.total_changes, changes)
        event = json.loads(backend.log.getvalue())
        self.assertEqual(event["error"], "Route behavior has not been reconstructed")

    def test_shop_native_200_insufficient_and_duplicate_statuses_are_unchanged(self):
        self.account()
        service = self.real_service()
        item = next(iter(self.catalog.items.values()))
        service.shop.configure_shop("avatar-shop", 0, "Local avatar shop", "Preservation offers")
        service.shop.configure_offer(
            "wardrobe-offer", "wardrobe", item["item_id"], "avatar-shop", item["category"],
            0, "Local wardrobe item", "", 100, 7, item["gender"], item["category"], True)
        service.shop.set_wallet("account-a", 3, 6)

        def buy(option):
            return service.shop.dispatch("NPShopBuyItemServlet", Request((
                "a" * 32, "account-a", "wardrobe-offer", "100", "7", str(option)),
                "StandaloneWindows"))

        self.assertTrue(buy(0).endswith("#NOCRYSTALS"))
        self.assertTrue(buy(1).endswith("#NOXP"))
        service.shop.set_wallet("account-a", 100, 7)
        self.assertTrue(buy(0).endswith("#OK"))
        wallet = dict(service.shop.wallet("account-a"))
        self.assertTrue(buy(0).endswith("#ISPURCHASED"))
        self.assertEqual(dict(service.shop.wallet("account-a")), wallet)

    def test_reward_check_suppression_stays_200_but_disabled_claim_is_encrypted_404(self):
        guid = self.account()
        service = self.real_service()
        backend = backend_for(service)
        check = drive(backend.handle(request(
            "CheckOwnGenericReward", f"{guid}#account-a#missing#StandaloneWindows")))
        self.assertEqual(check.status, 200)
        self.assertEqual(decrypt(check.text).split("#"),
                         ["false", guid, "account-a", "true"])
        changes = self.store.db.total_changes

        backend.log = io.StringIO()
        claim = drive(backend.handle(request(
            "GenericReward", f"{guid}#account-a#missing#StandaloneWindows")))
        self.assertEqual(claim.status, 404)
        self.assertEqual(decrypt(claim.text), "ERROR")
        self.assertEqual(self.store.db.total_changes, changes)
        self.assertEqual(json.loads(backend.log.getvalue())["error"],
                         "No enabled local reward definition")


if __name__ == "__main__":
    unittest.main()

