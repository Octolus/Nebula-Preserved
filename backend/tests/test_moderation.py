"""Actual SQLite Store + TEMP databases only; no sockets or application starts."""
from pathlib import Path
import json
import math
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / "backend"))
from moderation import MAX_UTC, Moderation, report_id
from public_access import AccessDenied, actor_scope
from state import Store
from wire import ProtocolError

ACCOUNT, OTHER = "moderation-account", "moderation-other"
G1, G2, G3, GO = "1" * 32, "2" * 32, "3" * 32, "4" * 32
ACTOR = {"id": "moderator", "role": "moderator"}


def tables(db):
    names = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")
             if not row[0].startswith("sqlite_")]
    return {name: sorted((tuple(row) for row in db.execute('SELECT * FROM "' + name + '"')), key=repr)
            for name in names}


class ModerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nebula-moderation-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "preservation.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.now = 1000.25
        self.moderation = Moderation(self.store, clock=lambda: self.now)
        self.store.moderation = self.moderation
        self.store.account(ACCOUNT, "Target")
        self.store.account(OTHER, "Other")
        self.store.bind_session(ACCOUNT, G1)
        self.store.bind_session(ACCOUNT, G2)
        self.store.bind_session(OTHER, GO)

    def command(self, method, *arguments, **options):
        options = {"reason": "Temporary moderation unit check", "actor": ACTOR,
                   "request_id": uuid.uuid4().hex, **options}
        with self.store.atomic():
            return getattr(self.moderation, method)(*arguments, **options)

    def assert_protocol(self, status, function, *arguments, **options):
        with self.assertRaises(ProtocolError) as error:
            function(*arguments, **options)
        self.assertEqual(error.exception.status, status)

    def test_outer_atomic_required_and_reads_do_not_create_policy(self):
        before = tables(self.store.db)
        self.assert_protocol(409, self.moderation.ban, ACCOUNT, reason="test", actor=ACTOR,
                             request_id=uuid.uuid4().hex)
        self.assertFalse(self.moderation.status(ACCOUNT)["banned"])
        self.assertTrue(self.moderation.ensure_allowed("not-yet-provisioned", G3))
        self.assertEqual(tables(self.store.db), before)

    def test_player_context_cannot_authorize_mutation(self):
        before = tables(self.store.db)
        with actor_scope(ACCOUNT):
            for method, args in (("ban", (ACCOUNT,)), ("kick", (ACCOUNT,)),
                                 ("mute", (ACCOUNT,)), ("set_maintenance", (5,))):
                self.assert_protocol(403, self.command, method, *args)
        self.assertEqual(tables(self.store.db), before)

    def test_ban_revokes_every_existing_guid_without_deleting_gameplay_rows(self):
        with self.store.db:
            self.store.db.execute("CREATE TABLE future_protected(payload TEXT)")
            self.store.db.execute("INSERT INTO future_protected VALUES('keep forever')")
            self.store.db.execute("INSERT INTO preferences VALUES(?,?,?)", (ACCOUNT, "Music", "0.7"))
        before = tables(self.store.db)
        _, after, changed = self.command("ban", ACCOUNT)
        self.assertTrue(changed)
        self.assertEqual(after["newly_revoked_guids"], [G1, G2])
        self.assert_protocol(403, self.moderation.ensure_allowed, ACCOUNT, G3)
        self.assertTrue(self.moderation.ensure_allowed(OTHER, GO))
        current = tables(self.store.db)
        for table in before.keys() - {"moderation_accounts", "moderation_events", "moderation_revoked_sessions"}:
            self.assertEqual(current[table], before[table], table)

    def test_exact_expiry_boundary_does_not_resurrect_tombstones(self):
        self.command("ban", ACCOUNT, expires_at=1001)
        self.now = 1000.999
        self.assertTrue(self.moderation.status(ACCOUNT)["banned"])
        before = tables(self.store.db)
        self.now = 1001
        self.assertFalse(self.moderation.status(ACCOUNT)["banned"])
        self.assertTrue(self.moderation.ensure_allowed(ACCOUNT, G3))
        self.assert_protocol(403, self.moderation.ensure_allowed, ACCOUNT, G2)
        self.assertEqual(tables(self.store.db), before)

    def test_unban_never_rebinds_old_guid_but_fresh_session_can_login(self):
        self.command("ban", ACCOUNT)
        self.command("unban", ACCOUNT)
        self.assert_protocol(403, self.store.bind_session, ACCOUNT, G2)
        self.store.bind_session(ACCOUNT, G3)
        self.assertEqual(self.store.current_guid(ACCOUNT), G3)
        self.assertFalse(self.moderation.status(ACCOUNT)["banned"])

    def test_kick_current_only_and_new_guid_allowed_without_ban(self):
        _, after, changed = self.command("kick", ACCOUNT, guid=G2)
        self.assertTrue(changed)
        self.assertEqual(after["newly_revoked_guids"], [G2])
        self.assertTrue(self.moderation.ensure_allowed(ACCOUNT, G1))
        self.assert_protocol(403, self.moderation.ensure_allowed, ACCOUNT, G2)
        self.assertFalse(self.moderation.status(ACCOUNT)["banned"])
        self.store.bind_session(ACCOUNT, G3)
        self.assertTrue(self.moderation.ensure_allowed(ACCOUNT, G3))

    def test_stale_or_foreign_kick_is_rejected_without_mutation(self):
        before = tables(self.store.db)
        for guid in (G1, GO, "invalid#wire", "bad\ncontrol", "x" * 129):
            self.assert_protocol(400 if guid not in (G1, GO) else 409, self.command,
                                 "kick", ACCOUNT, guid=guid)
        self.assertEqual(tables(self.store.db), before)

    def test_second_kick_uses_raw_latest_even_after_store_hides_revoked_guid(self):
        self.command("kick", ACCOUNT)
        self.assertIsNone(self.store.current_guid(ACCOUNT))
        before, after, changed = self.command("kick", ACCOUNT)
        self.assertEqual(before["current_guid"], G2)
        self.assertTrue(before["revoked"])
        self.assertFalse(changed)
        self.assertEqual(after["newly_revoked_guids"], [])

    def test_legacy_opaque_store_sessions_keep_exact_revocation_without_native_id_assumptions(self):
        self.store.bind_session(ACCOUNT, "guid-a")
        self.assertTrue(self.moderation.ensure_allowed(ACCOUNT, "guid-a"))
        _, after, changed = self.command("kick", ACCOUNT, guid="guid-a")
        self.assertTrue(changed)
        self.assertEqual(after["newly_revoked_guids"], ["guid-a"])
        self.assert_protocol(403, self.store.bind_session, ACCOUNT, "guid-a")
        self.store.bind_session(ACCOUNT, "guid-b")
        self.command("ban", ACCOUNT)
        self.command("unban", ACCOUNT)
        self.assert_protocol(403, self.moderation.ensure_allowed, ACCOUNT, "guid-b")
        self.assertTrue(self.moderation.ensure_allowed(ACCOUNT, "guid-c"))

    def test_mute_expiry_and_unmute_do_not_block_login(self):
        self.command("mute", ACCOUNT, expires_at=1001)
        self.assertTrue(self.moderation.status(ACCOUNT)["muted"])
        self.assertTrue(self.moderation.ensure_allowed(ACCOUNT, G2))
        self.now = 1001
        self.assertFalse(self.moderation.status(ACCOUNT)["muted"])
        self.command("mute", ACCOUNT)
        self.command("unmute", ACCOUNT)
        self.assertFalse(self.moderation.status(ACCOUNT)["muted"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM moderation_revoked_sessions").fetchone()[0], 0)

    def test_expiry_reason_and_actor_validation_leave_every_table_unchanged(self):
        before = tables(self.store.db)
        for expiry in (True, 1000, -1, 1001.0, "1001", MAX_UTC + 1):
            self.assert_protocol(400, self.command, "ban", ACCOUNT, expires_at=expiry)
        for reason in ("", "  ", "split#payload", "line\nfeed", "control\x85", "x" * 513):
            self.assert_protocol(400, self.command, "ban", ACCOUNT, reason=reason)
        for actor in ({}, {"id": "player", "role": "owner#injection"}, {"id": "bad#id", "role": "owner"}):
            self.assert_protocol(403, self.command, "ban", ACCOUNT, actor=actor)
        self.assertEqual(tables(self.store.db), before)

    def test_missing_account_and_duplicate_request_id_fail_without_extra_history(self):
        self.assert_protocol(404, self.command, "ban", "missing-account")
        identity = uuid.uuid4().hex
        self.command("mute", ACCOUNT, request_id=identity)
        before = tables(self.store.db)
        self.assert_protocol(409, self.command, "ban", OTHER, request_id=identity)
        self.assertEqual(tables(self.store.db), before)

    def test_history_failure_rolls_back_policy_revocations_and_future_tables(self):
        before = tables(self.store.db)
        with patch.object(self.moderation, "_event", side_effect=RuntimeError("injected audit failure")):
            with self.assertRaises(RuntimeError):
                self.command("ban", ACCOUNT)
        self.assertEqual(tables(self.store.db), before)

    def test_restart_retains_ban_history_and_all_old_guid_tombstones(self):
        self.command("ban", ACCOUNT, expires_at=1001)
        other_store = Store(self.path)
        try:
            other = Moderation(other_store, clock=lambda: 1001)
            self.assertFalse(other.status(ACCOUNT)["banned"])
            self.assert_protocol(403, other.ensure_allowed, ACCOUNT, G2)
            self.assertEqual(other_store.db.execute("SELECT COUNT(*) FROM moderation_events").fetchone()[0], 1)
        finally:
            other_store.close()

    def test_maintenance_is_ceil_countdown_without_access_block(self):
        self.command("set_maintenance", 2)
        self.assertEqual(self.moderation.maintenance(), {"started_at": 1000, "end_at": 1120,
                         "reason": "Temporary moderation unit check", "minutes": 2})
        self.assertTrue(self.moderation.ensure_allowed(ACCOUNT, G2))
        self.now = 1060
        self.assertEqual(self.moderation.maintenance_minutes(), 1)
        before = tables(self.store.db)
        self.now = 1120
        self.assertEqual(self.moderation.maintenance_minutes(), 0)
        self.assertEqual(tables(self.store.db), before)
        self.command("set_maintenance", 0)
        self.assertEqual(self.moderation.maintenance_minutes(), 0)

    def test_bad_maintenance_and_clock_fail_closed(self):
        before = tables(self.store.db)
        for minutes in (True, -1, 1441, 1.0, "5"):
            self.assert_protocol(400, self.command, "set_maintenance", minutes)
        self.assertEqual(tables(self.store.db), before)
        for clock in (math.nan, math.inf, -1, True):
            self.now = clock
            self.assert_protocol(503, self.moderation.ensure_allowed, ACCOUNT, G3)

    def report(self, guid=G2, target="AmbiguousTarget", option=0, text="Report details"):
        with self.store.atomic():
            return self.moderation.record_report(guid, target, option, text)

    def test_report_duplicate_preserves_original_text_and_stable_index(self):
        self.assertTrue(self.report())
        self.assertFalse(self.report(text="replacement must not happen"))
        rows = self.moderation.reports()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["report_id"], report_id(G2, "AmbiguousTarget", 0))
        self.assertEqual(rows[0]["text"], "Report details")
        self.assertEqual(rows[0]["reporter_account_id"], ACCOUNT)
        self.assertEqual(rows[0]["target"], "AmbiguousTarget")
        self.assertEqual(rows[0]["status"], "open")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM moderation_events").fetchone()[0], 0)

    def test_report_validation_stale_foreign_and_revoked_session(self):
        before = tables(self.store.db)
        for option in (True, -1, 3, "1"):
            self.assert_protocol(400, self.report, option=option)
        for text in ("bad#wire", "newline\n", "x" * 513):
            self.assert_protocol(400, self.report, text=text)
        self.assert_protocol(403, self.report, guid=G1)
        with actor_scope(OTHER):
            with self.assertRaises(AccessDenied): self.report()
        self.assertEqual(tables(self.store.db), before)
        self.command("kick", ACCOUNT)
        self.assert_protocol(403, self.report)

    def test_report_insert_and_index_rollback_together(self):
        before = tables(self.store.db)
        with patch.object(self.moderation, "_index_report", side_effect=RuntimeError("index failure")):
            with self.assertRaises(RuntimeError): self.report()
        self.assertEqual(tables(self.store.db), before)

    def test_legacy_reports_backfill_without_rewriting_or_guessing_target_account(self):
        with self.store.db:
            self.store.db.execute("INSERT INTO local_reports VALUES(?,?,?,?,?)",
                                  ("legacy-missing-session", "old#raw-target", -8, "old\nraw text", 500))
        old = [tuple(r) for r in self.store.db.execute("SELECT * FROM local_reports")]
        Moderation(self.store, clock=lambda: self.now)
        row = self.moderation.reports()[0]
        self.assertIsNone(row["reporter_account_id"])
        self.assertEqual((row["target"], row["option"], row["text"]), ("old#raw-target", -8, "old\nraw text"))
        self.assertEqual([tuple(r) for r in self.store.db.execute("SELECT * FROM local_reports")], old)
        self.assertEqual(row["report_id"], report_id("legacy-missing-session", "old#raw-target", -8))

    def test_review_is_separate_from_original_report_and_audit_rollback(self):
        self.report()
        identity = self.moderation.reports()[0]["report_id"]
        raw = [tuple(r) for r in self.store.db.execute("SELECT * FROM local_reports")]
        _, after, changed = self.command("review_report", identity, "resolved", "Reviewed evidence")
        self.assertTrue(changed)
        self.assertEqual(after["status"], "resolved")
        self.assertEqual(self.moderation.reports()[0]["actor_id"], ACTOR["id"])
        self.assertEqual([tuple(r) for r in self.store.db.execute("SELECT * FROM local_reports")], raw)
        before = tables(self.store.db)
        with patch.object(self.moderation, "_event", side_effect=RuntimeError("event failure")):
            with self.assertRaises(RuntimeError):
                self.command("review_report", identity, "dismissed", "Not persisted")
        self.assertEqual(tables(self.store.db), before)

    def test_review_validation_and_read_pagination_do_not_mutate(self):
        self.report(option=0)
        self.report(option=1)
        before = tables(self.store.db)
        identity = self.moderation.reports()[0]["report_id"]
        self.assert_protocol(400, self.command, "review_report", identity, "autoban", "invalid")
        self.assert_protocol(400, self.command, "review_report", identity, "resolved", "bad#wire")
        self.assert_protocol(404, self.command, "review_report", "0" * 64, "resolved", "missing")
        self.assertEqual(len(self.moderation.reports(limit=1, offset=1)), 1)
        self.assert_protocol(400, self.moderation.reports, limit=True)
        self.assert_protocol(400, self.moderation.reports, offset=-1)
        self.assertEqual(tables(self.store.db), before)

    def test_review_and_original_report_survive_restart_without_duplicate_index(self):
        self.report()
        identity = self.moderation.reports()[0]["report_id"]
        self.command("review_report", identity, "dismissed", "Closed after review")
        before = tables(self.store.db)
        restarted = Store(self.path)
        try:
            row = restarted.moderation.reports()[0]
            self.assertEqual((row["report_id"], row["status"], row["note"]),
                             (identity, "dismissed", "Closed after review"))
            self.assertEqual(row["reporter_account_id"], ACCOUNT)
            self.assertEqual(tables(restarted.db), before)
        finally:
            restarted.close()

    def test_original_report_receipt_cannot_be_rewritten_or_deleted(self):
        self.report()
        for statement in ("UPDATE local_reports SET text='silently changed'", "DELETE FROM local_reports"):
            before = tables(self.store.db)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "Report receipts are append-only"):
                with self.store.atomic(): self.store.db.execute(statement)
            self.assertEqual(tables(self.store.db), before)

    def test_ban_and_kick_clear_online_only_without_clearing_other_profile_fields(self):
        for method, account in (("ban", ACCOUNT), ("kick", OTHER)):
            with self.store.db:
                self.store.db.execute("UPDATE profile_state SET online=1,in_wardrobe=1,last_preset='Saved' WHERE ps4_id=?",
                                      (account,))
            _, after, changed = self.command(method, account)
            self.assertTrue(changed)
            self.assertEqual(after["online"], 0)
            row = self.store.db.execute("SELECT online,in_wardrobe,last_preset FROM profile_state WHERE ps4_id=?", (account,)).fetchone()
            self.assertEqual(tuple(row), (0, 1, "Saved"))

    def test_staff_label_is_owner_only_plain_display_not_authority(self):
        before = tables(self.store.db)
        for role in ("moderator", "admin"):
            self.assert_protocol(403, self.command, "set_staff_label", ACCOUNT, "Staff", actor={"id": role, "role": role})
        self.assertEqual(tables(self.store.db), before)
        self.command("set_staff_label", ACCOUNT, "Preservation Staff", actor={"id": "owner", "role": "owner"})
        status = self.moderation.status(ACCOUNT)
        self.assertEqual(status["staff_label"], "Preservation Staff")
        self.assertEqual(status["role"], "player")
        self.assertTrue(self.moderation.ensure_allowed(ACCOUNT, G2))
        self.command("set_staff_label", ACCOUNT, "", actor={"id": "owner", "role": "owner"})
        self.assertEqual(self.moderation.status(ACCOUNT)["staff_label"], "")

    def test_staff_rejects_wire_controls_rich_text_and_oversize_labels(self):
        before = tables(self.store.db)
        for label in ("x" * 33, "<b>Owner</b>", "bad>label", "wire#split", "bad\nlabel"):
            self.assert_protocol(400, self.command, "set_staff_label", ACCOUNT, label,
                                 actor={"id": "owner", "role": "owner"})
        self.assertEqual(tables(self.store.db), before)

    def test_news_publication_expiry_and_archive_are_durable_login_news_only(self):
        _, item, changed = self.command("publish_news", "Server update scheduled", expires_at=1001,
                                        actor={"id": "admin", "role": "admin"})
        self.assertTrue(changed)
        self.assertEqual(str(uuid.UUID(item["news_id"])), item["news_id"])
        self.assertEqual(item["date_label"], "1970-01-01T00:16:40Z")
        self.assertEqual(self.moderation.news(), [item])
        before = tables(self.store.db)
        self.now = 1001
        self.assertEqual(self.moderation.news(), [])
        self.assertEqual(tables(self.store.db), before)
        _, other, _ = self.command("publish_news", "Persistent login news", actor={"id": "owner", "role": "owner"})
        self.command("archive_news", other["news_id"], actor={"id": "admin", "role": "admin"})
        self.assertEqual(self.moderation.news(), [])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM moderation_news").fetchone()[0], 2)

    def test_staff_and_news_survive_restart_without_privilege_grants(self):
        self.command("set_staff_label", ACCOUNT, "Guide", actor={"id": "owner", "role": "owner"})
        _, item, _ = self.command("publish_news", "Welcome", actor={"id": "admin", "role": "admin"})
        restarted = Store(self.path)
        try:
            self.assertEqual(restarted.moderation.status(ACCOUNT)["staff_label"], "Guide")
            self.assertEqual(restarted.moderation.status(ACCOUNT)["role"], "player")
            self.assertEqual(restarted.moderation.news()[0]["news_id"], item["news_id"])
        finally:
            restarted.close()

    def test_news_validation_authority_and_event_failure_leave_no_partial_publication(self):
        before = tables(self.store.db)
        self.assert_protocol(403, self.command, "publish_news", "No moderator publication")
        for text in ("", "bad#wire", "bad\nnews", "x" * 1001):
            self.assert_protocol(400, self.command, "publish_news", text, actor={"id": "admin", "role": "admin"})
        self.assert_protocol(400, self.command, "publish_news", "Expired", expires_at=1000,
                             actor={"id": "admin", "role": "admin"})
        with patch.object(self.moderation, "_event", side_effect=RuntimeError("publication audit failure")):
            with self.assertRaises(RuntimeError):
                self.command("publish_news", "Must roll back", actor={"id": "owner", "role": "owner"})
        self.assertEqual(tables(self.store.db), before)

    def test_news_content_is_immutable_archive_does_not_delete_history(self):
        _, item, _ = self.command("publish_news", "Original", actor={"id": "owner", "role": "owner"})
        for statement in ("UPDATE moderation_news SET text='rewritten'", "DELETE FROM moderation_news"):
            before = tables(self.store.db)
            with self.assertRaises(sqlite3.IntegrityError):
                with self.store.atomic(): self.store.db.execute(statement)
            self.assertEqual(tables(self.store.db), before)
        self.command("archive_news", item["news_id"], actor={"id": "owner", "role": "owner"})
        _, _, changed = self.command("archive_news", item["news_id"], actor={"id": "owner", "role": "owner"})
        self.assertFalse(changed)
        self.assertEqual(self.store.db.execute("SELECT text,active FROM moderation_news").fetchone()["text"], "Original")

    def test_history_tombstones_and_report_keys_are_immutable(self):
        self.command("ban", ACCOUNT)
        # Other account can still submit a report while this one is banned.
        self.report(guid=GO)
        for table in ("moderation_events", "moderation_revoked_sessions", "moderation_report_index"):
            for statement in ('DELETE FROM "' + table + '"', 'UPDATE "' + table + '" SET ' +
                              ("reason=reason" if table != "moderation_report_index" else "target=target")):
                before = tables(self.store.db)
                with self.assertRaises(sqlite3.IntegrityError):
                    with self.store.atomic(): self.store.db.execute(statement)
                self.assertEqual(tables(self.store.db), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
