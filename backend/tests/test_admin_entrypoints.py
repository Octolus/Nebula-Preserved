"""Run documented offline admin commands without an inherited import path."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BACKEND = Path(__file__).resolve().parents[1]


class AdminEntrypoints(unittest.TestCase):
    def test_shop_and_housing_help_from_clean_process(self):
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONSTARTUP", None)
        with tempfile.TemporaryDirectory() as scratch:
            for name in ("housing_admin.py", "shop_admin.py"):
                with self.subTest(command=name):
                    result = subprocess.run([sys.executable, str(BACKEND / name), "--help"],
                                            cwd=scratch, env=environment, text=True,
                                            capture_output=True, timeout=20)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn("usage:", result.stdout)

    def test_account_credit_and_exact_furniture_grant_from_documented_commands(self):
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as scratch:
            state = Path(scratch) / "authored-state"

            def run(command, *arguments, success=True):
                result = subprocess.run([sys.executable, str(BACKEND / command),
                                         "--state-dir", str(state), *arguments],
                                        cwd=scratch, env=environment, text=True,
                                        capture_output=True, timeout=30)
                if success:
                    self.assertEqual(0, result.returncode, result.stderr)
                    return json.loads(result.stdout)
                self.assertNotEqual(0, result.returncode)

            account = "preservation-cli-regression"
            run("admin.py", "account", account, "--name", "CLI Regression")
            wallet = run("shop_admin.py", "wallet", account, "500", "--np", "200")
            self.assertEqual((500, 200), (wallet["crystals"], wallet["np"]))
            binding = run("housing_admin.py", "bind-space", account, "cli-home", "Home")
            self.assertEqual("Home", binding["psidglobal"])
            item = "A044fFy8Xtm2U2J1DuRolDt63P431gI8"
            run("housing_admin.py", "grant-item", account, item)
            inventory = run("housing_admin.py", "list-items", account)
            self.assertEqual([item], [row["item_id"] for row in inventory])
            run("housing_admin.py", "grant-item", account, item.lower(), success=False)
            self.assertEqual(inventory, run("housing_admin.py", "list-items", account))
            self.assertEqual(wallet, run("shop_admin.py", "wallet-show", account))


if __name__ == "__main__":
    unittest.main()

