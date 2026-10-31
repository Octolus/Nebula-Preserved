"""Backup sets include verified instance JSON state; retention keeps days plus deploys."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BACKUP = load(ROOT / "tools/backup_state.py", "backup_state_under_test")


class BackupState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state, self.destination = root / "state", root / "backups"
        (self.state / "instances" / "apt-1").mkdir(parents=True)
        db = sqlite3.connect(self.state / "preservation.sqlite3")
        db.execute("CREATE TABLE t(v)")
        db.execute("INSERT INTO t VALUES('kept')")
        db.commit()
        db.close()
        (self.state / "instance-accounts.json").write_text('{"accounts": []}', encoding="utf-8")
        (self.state / "instance-housing.json").write_text('{"bindings": []}', encoding="utf-8")
        (self.state / "instances" / "apt-1" / "instance-housing-state.json").write_text('{"v": 1}', encoding="utf-8")
        (self.state / "instances" / "apt-1" / "notes.txt").write_text("not state", encoding="utf-8")
        (self.state / "desired-instances.json").write_text("{}", encoding="utf-8")
        self.start = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)

    def test_set_contains_verified_database_and_instance_json_state(self):
        final = BACKUP.backup(self.state, self.destination, now=self.start)
        receipt = json.loads(final.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual((receipt["kind"], receipt["sha256"]), ("scheduled", BACKUP.sha256(final)))
        self.assertEqual([row["path"] for row in receipt["state_files"]],
                         ["instance-accounts.json", "instance-housing.json", "instances/apt-1/instance-housing-state.json"])
        self.assertTrue(all(row["json_valid"] for row in receipt["state_files"]))
        archive = final.with_suffix(".state.tar.gz")
        self.assertEqual(receipt["state_archive_sha256"], BACKUP.sha256(archive))
        with tarfile.open(archive) as stream:
            self.assertEqual(json.loads(stream.extractfile("instance-housing.json").read()), {"bindings": []})
        restored = sqlite3.connect(final)
        self.assertEqual(restored.execute("SELECT v FROM t").fetchone()[0], "kept")
        restored.close()
        self.assertEqual([path.name for path in self.destination.iterdir() if path.name.startswith(".")], [])

    def test_corrupt_state_json_is_preserved_and_flagged(self):
        (self.state / "instance-housing.json").write_text("{truncated", encoding="utf-8")
        final = BACKUP.backup(self.state, self.destination, now=self.start)
        rows = json.loads(final.with_suffix(".json").read_text(encoding="utf-8"))["state_files"]
        self.assertFalse(next(row for row in rows if row["path"] == "instance-housing.json")["json_valid"])

    def test_retention_keeps_newest_per_day_for_14_days_plus_5_deploys(self):
        # Legacy daily backups predate this format and count as scheduled sets.
        legacy = self.destination / "preservation-20260920T030000Z.sqlite3"
        self.destination.mkdir()
        legacy.write_bytes(b"")
        for day in range(20):
            for hour in (3, 9):
                BACKUP.backup(self.state, self.destination, now=self.start + timedelta(days=day, hours=hour - 3))
        for minute in range(7):  # Many deploys in one day must not flush daily history.
            BACKUP.backup(self.state, self.destination, kind="deploy",
                          now=self.start + timedelta(days=19, hours=10, minutes=minute))
        sets = BACKUP.backup_sets(self.destination)
        deploys = [row for row in sets if row["kind"] == "deploy"]
        self.assertEqual(len(deploys), 5)
        self.assertEqual(deploys[0]["created"], self.start + timedelta(days=19, hours=10, minutes=6))
        days = sorted({row["created"].date() for row in sets if row["kind"] == "scheduled"})
        self.assertEqual(len(days), 13)  # Day 19 is represented by its newest (deploy) set.
        self.assertEqual(days[0], (self.start + timedelta(days=6)).date())
        self.assertFalse(legacy.exists())
        scheduled = [row for row in sets if row["kind"] == "scheduled"]
        self.assertTrue(all(row["created"].hour == 9 for row in scheduled))
        for row in sets:
            for suffix in (".json", ".state.tar.gz"):
                self.assertTrue(row["database"].with_suffix(suffix).exists())
        names = {path.name for path in self.destination.iterdir()}
        self.assertEqual(len(names), 3 * len(sets))

    def test_offsite_hook_runs_only_when_configured_and_sees_paths(self):
        final = BACKUP.backup(self.state, self.destination, now=self.start)
        self.assertIsNone(BACKUP.run_offsite(final, hook=self.destination / "missing.sh", command=""))
        marker = Path(self.temp.name) / "copied.txt"
        command = (f'"{sys.executable}" -c "import os,pathlib; pathlib.Path(r\'{marker}\').write_text('
                   f'os.environ[\'NEBULA_BACKUP_STATE_ARCHIVE\'])"')
        self.assertEqual(BACKUP.run_offsite(final, command=command), 0)
        self.assertEqual(marker.read_text(), str(final.with_suffix(".state.tar.gz")))
        self.assertNotEqual(BACKUP.run_offsite(final, command=f'"{sys.executable}" -c "raise SystemExit(4)"'), 0)

    def test_deployment_copy_is_identical(self):
        self.assertEqual((ROOT / "tools/backup_state.py").read_bytes(),
                         (ROOT / "deployment/tools/backup_state.py").read_bytes())


class BackupUnits(unittest.TestCase):
    def test_units_use_day_and_deploy_retention(self):
        for path in (ROOT / "deployment/ansible/files/nebula-preserved-backup.service",
                     ROOT / "deployment/instance-supervisor/nebula-preservation-backup.service"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("--keep-days 14 --keep-deploy 5", text)
            self.assertNotIn("\r", text)
        site = (ROOT / "deployment/ansible/site.yaml").read_text(encoding="utf-8")
        self.assertIn("--kind, deploy", site)
        self.assertIn("nebula_backup_offsite_command", site)


if __name__ == "__main__": unittest.main()
