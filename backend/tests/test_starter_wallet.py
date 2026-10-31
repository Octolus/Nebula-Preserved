"""Starter wallet is credited once, atomically, only for profiles created under the policy."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from service import Service
from starter_policy import StarterPolicy, starter_amounts
from state import Catalog, Store

LEDGER = """CREATE TABLE management_wallet_ledger (
    ledger_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
    actor_id TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES profiles(ps4_id),
    currency TEXT NOT NULL CHECK(currency IN ('crystals','np')), delta INTEGER NOT NULL,
    before_balance INTEGER NOT NULL, after_balance INTEGER NOT NULL, reason TEXT NOT NULL,
    created_at REAL NOT NULL)"""


class StarterWallet(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "preservation.sqlite3")
        self.addCleanup(self.store.close)

    def service(self, **env):
        with patch.dict(os.environ, {"NEBULA_STARTER_CRYSTALS": "", "NEBULA_STARTER_NP": "", **env}):
            return Service(self.store, Catalog(BACKEND.parent / "protocol"))

    def wallet(self, service, account):
        value = service.shop.wallet(account)
        return value["crystals"], value["np"]

    def test_default_policy_keeps_new_accounts_empty(self):
        service = self.service()
        self.store.account("fresh")
        self.assertEqual(self.wallet(service, "fresh"), (0, 0))
        self.assertEqual(service.starter.grant("fresh")["crystals"], 0)

    def test_configured_wallet_is_applied_once_and_never_retroactively(self):
        self.store.account("before-policy")
        with self.store.db:
            self.store.db.execute(LEDGER)
        service = self.service(NEBULA_STARTER_CRYSTALS="250", NEBULA_STARTER_NP="40")
        self.assertEqual(self.wallet(service, "before-policy"), (0, 0))
        self.assertIsNone(service.starter.grant("before-policy"))
        self.store.account("newcomer", "Newcomer")
        self.store.account("newcomer", "Newcomer")  # Repeat login: no second grant.
        self.assertEqual(self.wallet(service, "newcomer"), (250, 40))
        ledger = self.store.db.execute(
            "SELECT request_id,actor_id,currency,delta,before_balance,after_balance FROM management_wallet_ledger "
            "ORDER BY currency").fetchall()
        self.assertEqual([tuple(row) for row in ledger], [
            ("starter-wallet:newcomer:crystals", "system:starter-policy", "crystals", 250, 0, 250),
            ("starter-wallet:newcomer:np", "system:starter-policy", "np", 40, 0, 40)])
        service.shop.set_wallet("newcomer", 5, 1)
        # A restart with new amounts never touches existing accounts.
        service = self.service(NEBULA_STARTER_CRYSTALS="999")
        self.assertEqual(self.wallet(service, "newcomer"), (5, 1))
        self.store.account("later")
        self.assertEqual(self.wallet(service, "later"), (999, 0))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM starter_wallet_grants").fetchone()[0], 2)

    def test_grant_rolls_back_with_the_profile_transaction(self):
        service = self.service(NEBULA_STARTER_CRYSTALS="10")
        with self.assertRaises(RuntimeError), self.store.atomic():
            self.store.account("rolled-back")
            raise RuntimeError("abort")
        self.assertIsNone(self.store.db.execute("SELECT 1 FROM profiles WHERE ps4_id='rolled-back'").fetchone())
        self.assertIsNone(service.starter.grant("rolled-back"))
        self.assertEqual(self.wallet(service, "rolled-back"), (0, 0))

    def test_invalid_amounts_are_refused(self):
        for env in ({"NEBULA_STARTER_CRYSTALS": "-1"}, {"NEBULA_STARTER_NP": "lots"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                starter_amounts(env)
        with self.assertRaises(ValueError):
            StarterPolicy(self.store, crystals=-5, env={})


if __name__ == "__main__": unittest.main()
