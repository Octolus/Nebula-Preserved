"""Narrow management UUID correlations and source-proven clock locations."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import json
import math
import re
import uuid
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_parity import canonical, normalized_state

HEX = re.compile(r"[0-9a-f]{32}\Z")
TABLE_CLOCKS = {
    "management_operators": ["created_at", "updated_at"], "management_audit": ["created_at"],
    "management_requests": ["created_at"], "management_wallet_ledger": ["created_at"],
    "moderation_events": ["created_at"], "moderation_revoked_sessions": ["revoked_at"],
    "moderation_report_reviews": ["updated_at"], "local_reports": ["created_at"],
}
PAYLOAD_CLOCKS = {"created_at", "updated_at", "last_login_at", "last_avatar_save_at", "started_at", "end_at", "granted_at"}


def clock(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("INVALID_EXPLICIT_CLOCK")
    if value == 0:
        return value
    return {"clock_type": "real" if type(value) is float else "integer"}


class Normalizer:
    def __init__(self, base_whitelist):
        self.ids = {}
        self.base_whitelist = base_whitelist

    def bind(self, identity, label):
        if not isinstance(identity, str) or not HEX.fullmatch(identity):
            raise ValueError("INVALID_MANAGEMENT_REQUEST_UUID")
        if identity in self.ids and self.ids[identity] != label:
            raise ValueError("UUID_CORRELATION_REUSED_FOR_ANOTHER_OPERATION")
        self.ids[identity] = label

    def request_id(self, identity):
        if not isinstance(identity, str) or not HEX.fullmatch(identity) or identity not in self.ids:
            raise ValueError("UNCORRELATED_MANAGEMENT_REQUEST_UUID")
        return "request_uuid:" + self.ids[identity]

    def news_id(self, identity):
        if not isinstance(identity, str):
            raise ValueError("INVALID_NEWS_UUID")
        parsed = uuid.UUID(identity)
        if str(parsed) != identity:
            raise ValueError("NONCANONICAL_NEWS_UUID")
        return "news_uuid:" + self.request_id(parsed.hex)

    def payload(self, value):
        if not isinstance(value, dict):
            return value
        row = copy.deepcopy(value)
        if "news_id" in row:
            expected = datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            if row.get("date_label") != expected:
                raise ValueError("NEWS_DATE_DOES_NOT_MATCH_CREATED_CLOCK")
            row["news_id"] = self.news_id(row["news_id"])
            row["date_label"] = {"derived_utc_date": "created_at"}
        if row.get("started_at") is not None and row.get("end_at") is not None:
            duration = row["end_at"] - row["started_at"]
            if type(duration) is not int or not 0 <= duration <= 86400 or duration % 60:
                raise ValueError("MAINTENANCE_DEADLINE_INVARIANT_FAILED")
            row["duration_seconds"] = duration
        for key in PAYLOAD_CLOCKS.intersection(row):
            row[key] = clock(row[key])
        return row

    def result(self, value):
        row = copy.deepcopy(value)
        if not isinstance(row, dict):
            return row
        if "request_id" in row:
            row["request_id"] = self.request_id(row["request_id"])
        for key in ("before", "after"):
            if key in row:
                row[key] = self.payload(row[key])
        return row

    def observe(self, case, observation):
        if case["op"] == "admin" and observation.get("ok") and observation.get("status") == 200:
            data = observation.get("body", {}).get("data")
            if isinstance(data, dict) and "request_id" in data:
                identity = data["request_id"]
                if identity not in self.ids:
                    self.bind(identity, "case:" + case["id"])
        if case["op"] == "snapshot" and observation.get("ok"):
            for row in observation["state"]["tables"].get("management_audit", {}).get("rows", []):
                if row["actor_id"] == "bootstrap":
                    self.bind(row["request_id"], "bootstrap-audit:" + str(row["audit_id"]) + ":" + row["target_id"])
                else:
                    self.request_id(row["request_id"])

    def read_row(self, row, kind):
        row = copy.deepcopy(row)
        if kind in ("audit", "event", "ledger"):
            row["request_id"] = self.request_id(row["request_id"])
            if kind == "event" and row.get("operation") in ("news.publish", "news.archive"):
                row["target_id"] = self.news_id(row["target_id"])
            if kind == "audit" and row.get("operation") == "moderation.news" and row.get("target_id") != "server":
                row["target_id"] = self.news_id(row["target_id"])
            for key in ("before", "after"):
                if key in row:
                    row[key] = self.payload(row[key])
        if kind == "news":
            return self.payload(row)
        keys = {"created_at", "updated_at", "granted_at", "last_login_at", "last_avatar_save_at"}
        for key in keys.intersection(row):
            row[key] = clock(row[key])
        return row

    def body(self, case, value):
        value = copy.deepcopy(value)
        if "data" not in value:
            return value
        data = value["data"]
        if isinstance(data, dict) and "request_id" in data:
            value["data"] = self.result(data)
            return value
        tail = case["tail"]
        if isinstance(data, dict) and "items" in data:
            kind = "event" if tail == "moderation/events" else "news" if tail == "moderation/news" else "audit" if tail.endswith("audit") else "ledger" if tail.endswith("transactions") else "read"
            if tail in ("users", "operators", "audit", "transactions", "moderation/events", "moderation/news", "moderation/reports") or tail.endswith(("/owned", "/transactions", "/audit", "/purchases")):
                data["items"] = [self.read_row(row, kind) for row in data["items"]]
        elif isinstance(data, dict) and tail.startswith("users/") and len(tail.split("/")) == 2:
            value["data"] = self.read_row(data, "read")
        return value

    def state(self, value):
        value = normalized_state(value, self.base_whitelist)
        tables = value["tables"]
        for name, table in tables.items():
            for row in table["rows"]:
                if name in TABLE_CLOCKS:
                    for key in TABLE_CLOCKS[name]:
                        row[key] = clock(row[key])
                if name in ("management_audit", "management_wallet_ledger", "moderation_events", "moderation_revoked_sessions"):
                    row["request_id"] = self.request_id(row["request_id"])
                if name == "moderation_events" and row["operation"] in ("news.publish", "news.archive"):
                    row["target_id"] = self.news_id(row["target_id"])
                if name == "management_audit" and row["operation"] == "moderation.news" and row["target_id"] != "server":
                    row["target_id"] = self.news_id(row["target_id"])
                if name in ("management_audit", "moderation_events"):
                    for column in ("before_json", "after_json"):
                        parsed = json.loads(row[column])
                        if canonical(parsed) != row[column]:
                            raise ValueError("NONCANONICAL_DURABLE_AUDIT_JSON")
                        row[column] = canonical(self.payload(parsed))
                if name == "management_requests":
                    parsed = json.loads(row["response_json"])
                    if canonical(parsed) != row["response_json"]:
                        raise ValueError("NONCANONICAL_DURABLE_RECEIPT_JSON")
                    row["response_json"] = canonical(self.result(parsed))
                if name == "moderation_news":
                    replacement = self.payload(row)
                    row.clear(); row.update(replacement)
                if name == "moderation_maintenance":
                    replacement = self.payload(row)
                    row.clear(); row.update(replacement)
            table["rows"].sort(key=canonical)
        return value
