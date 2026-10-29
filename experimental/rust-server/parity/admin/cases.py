"""Actual-management guard/read/mutation corpus; entirely synthetic accounts."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixture_support import account_guid

HERE = Path(__file__).resolve().parent


def corpus(unicode_edge=False):
    fixture = json.loads((HERE / "fixture.json").read_text())
    a, b = "fixture-parity-a", "fixture-parity-b"
    ga, gb = account_guid(a, "d" * 64), account_guid(b, "e" * 64)
    cases = []
    def headers(role="owner", key="admin-parity-key-0001"):
        return {"Authorization": "Bearer " + fixture["token"], "X-Management-Actor": role, "Idempotency-Key": key}
    def request(label, tail, method="GET", body=None, role="owner", status=200, key=None, custom_headers=None, query=None):
        selected_headers = custom_headers if custom_headers is not None else headers(role, key or label)
        if method == "POST":
            selected_headers = {"Content-Type": "application/json", **selected_headers}
        cases.append({"id": label, "op": "admin", "tail": tail, "method": method, "body": body,
                      "headers": selected_headers,
                      "query": query or {}, "expected_status": status})
    def post(label, tail, body=None, **kwargs):
        request(label, tail, "POST", {"reason": "Synthetic parity audit", **(body or {})}, **kwargs)
    def snap(label, same_as=None):
        row = {"id": label, "op": "snapshot"}
        if same_as:
            row["same_as"] = same_as
        cases.append(row)
    def game(label, route, *fields, status=200):
        cases.append({"id": label, "op": "http", "route": route, "plaintext": "#".join(fields) + "#StandaloneWindows", "method": "GET", "expected_status": status})
    if unicode_edge:
        snap("admin-unicode-edge-before")
        post("admin-unicode16-unassigned-in-source", "users/" + a + "/staff-label", {"label": "\u1c89"}, status=400)
        snap("admin-unicode-edge-after", "admin-unicode-edge-before")
        return cases
    snap("admin-state-initial")
    request("admin-missing-auth", "health", custom_headers={}, status=401)
    request("admin-bad-auth", "health", custom_headers={"Authorization": "Bearer synthetic-wrong", "X-Management-Actor": "owner"}, status=401)
    request("admin-missing-actor", "health", custom_headers={"Authorization": "Bearer " + fixture["token"]}, status=403)
    request("admin-unknown-actor", "health", role="unknown", status=403)
    request("admin-disabled-actor", "health", role="disabled", status=403)
    request("admin-origin-denied", "health", custom_headers={**headers(), "Origin": "https://synthetic.invalid"}, status=403)
    request("admin-method-denied", "health", method="DELETE", status=405)
    request("admin-unknown-route", "synthetic-missing-route", status=404)
    request("admin-headers-lowercase", "health", custom_headers={"authorization": "Bearer " + fixture["token"], "x-management-actor": "owner"})
    request("admin-origin-lowercase-denied", "health", custom_headers={**headers(), "origin": "https://synthetic.invalid"}, status=403)
    request("admin-post-auth-before-body", "users/" + a + "/wallet-adjustments", "POST", True, custom_headers={}, status=401)
    request("admin-post-content-type", "users/" + a + "/wallet-adjustments", "POST", {}, custom_headers={**headers(), "Content-Type": "text/plain"}, status=415)
    for label, body in (("null", None), ("array", []), ("bool", True), ("string", "synthetic")):
        request("admin-post-object-" + label, "users/" + a + "/wallet-adjustments", "POST", body, status=400)
    request("admin-post-size-limit", "users/" + a + "/wallet-adjustments", "POST", {"reason": "S" * 17000}, status=413)
    request("admin-forged-role-denied", "operators", role="moderator", custom_headers={**headers("moderator"), "X-Management-Role": "owner"}, status=403)
    for role in ("moderator", "admin", "owner"):
        request("admin-me-" + role, "me", role=role)
    for tail in ("health", "roles", "capabilities", "stats", "moderation/status", "moderation/reports", "moderation/news", "moderation/events", "transactions", "audit", "operators"):
        request("admin-read-" + tail.replace("/", "-"), tail)
    request("admin-operators-admin-denied", "operators", role="admin", status=403)
    request("admin-users", "users")
    request("admin-users-search-literal", "users", query={"q": "%_' OR 1=1", "limit": "1"})
    request("admin-users-page", "users", query={"limit": "1", "cursor": "1"})
    request("admin-users-limit-zero", "users", query={"limit": "0"}, status=400)
    request("admin-users-cursor-invalid", "users", query={"cursor": "-1"}, status=400)
    request("admin-user-missing", "users/synthetic-missing", status=404)
    for suffix in ("", "/wallet", "/moderation", "/owned", "/transactions", "/audit", "/purchases"):
        request("admin-user-a" + suffix.replace("/", "-"), "users/" + a + suffix)
    for kind in ("companions", "locomotions", "housing", "offer"):
        request("admin-catalog-" + kind, "catalog", query={"kind": kind, "limit": "3"})
    request("admin-catalog-kind-denied", "catalog", query={"kind": "game-admin"}, status=400)
    request("admin-catalog-wardrobe", "catalog", query={"kind": "wardrobe", "limit": "3"})
    request("admin-search-too-long", "users", query={"q": "x" * 129}, status=400)
    request("admin-users-limit-overflow", "users", query={"limit": "101"}, status=400)
    request("admin-users-cursor-overflow", "users", query={"cursor": "1000000000"}, status=400)
    post("admin-moderator-wallet-denied", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 1}, role="moderator", status=403)
    post("admin-admin-operator-denied", "operators/new", {"role": "owner", "enabled": True}, role="admin", status=403)
    post("admin-last-owner-denied", "operators/owner", {"role": "admin", "enabled": False}, status=409)
    post("admin-wallet-no-key", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 1}, custom_headers={"Authorization": "Bearer " + fixture["token"], "X-Management-Actor": "owner"}, status=400)
    post("admin-wallet-bool-denied", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": True}, status=400)
    post("admin-wallet-underflow-denied", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": -151}, status=409)
    post("admin-wallet-extra-field-denied", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 1, "synthetic_extra": True}, status=400)
    post("admin-wallet-zero-denied", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 0}, status=400)
    post("admin-wallet-level-denied", "users/" + a + "/wallet-adjustments", {"currency": "level", "delta": 1}, status=400)
    post("admin-wallet-overflow-denied", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 2147483647}, status=409)
    post("admin-wallet-short-key-denied", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 1}, key="short", status=400)
    post("admin-wallet-control-reason-denied", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 1, "reason": "synthetic\u0001"}, status=400)
    post("admin-grant-missing-housing", "users/" + a + "/items", {"kind": "housing", "item_id": "synthetic-missing"}, status=404)
    for label, value in (("format", "\u200b"), ("private-use", "\ue000"), ("unassigned", "\u0378"), ("delete", "\u007f"), ("delimiter", "synthetic#label")):
        post("admin-staff-unicode-" + label, "users/" + a + "/staff-label", {"label": value}, status=400)
    snap("admin-after-guards", "admin-state-initial")
    post("admin-wallet-credit", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 7}, key="admin-wallet-credit-key")
    snap("admin-after-wallet")
    post("admin-wallet-replay", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 7}, key="admin-wallet-credit-key")
    snap("admin-after-wallet-replay", "admin-after-wallet")
    post("admin-wallet-conflict", "users/" + a + "/wallet-adjustments", {"currency": "crystals", "delta": 8}, key="admin-wallet-credit-key", status=409)
    snap("admin-after-wallet-conflict", "admin-after-wallet")
    request("admin-wallet-current-a", "users/" + a + "/wallet")
    request("admin-wallet-isolated-b", "users/" + b + "/wallet")
    request("admin-wallet-ledger", "transactions")
    request("admin-wallet-audit", "audit")
    post("admin-wallet-other-actor-same-key", "users/" + b + "/wallet-adjustments", {"currency": "np", "delta": 2}, role="admin", key="admin-wallet-credit-key")
    request("admin-wallet-other-actor-b", "users/" + b + "/wallet")
    post("admin-grant-companion", "users/" + a + "/items", {"kind": "companions", "item_id": "A0IQgRXmw2UMG8T5UGrVE022o7Id25GU"}, role="admin")
    post("admin-grant-existing-companion", "users/" + a + "/items", {"kind": "companions", "item_id": "A0IQgRXmw2UMG8T5UGrVE022o7Id25GU"}, role="admin")
    post("admin-grant-offer", "users/" + b + "/items", {"kind": "offer", "offer_id": "fixture-bundle-buy"}, role="admin")
    request("admin-granted-owned", "users/" + b + "/owned")
    request("admin-granted-purchases", "users/" + b + "/purchases")
    snap("admin-after-grants")
    post("admin-staff-admin-denied", "users/" + a + "/staff-label", {"label": "Staff"}, role="admin", status=403)
    post("admin-staff-richtext-denied", "users/" + a + "/staff-label", {"label": "<b>Staff</b>"}, status=400)
    post("admin-staff-label", "users/" + a + "/staff-label", {"label": "Synthetic Staff"})
    request("admin-staff-status", "users/" + a + "/moderation")
    game("admin-game-report-create", "ReportServlet", ga, a, "0", "Fixture B", "Synthetic report only")
    identity = hashlib.sha256(json.dumps([ga, "Fixture B", 0], separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
    request("admin-report-read", "moderation/reports")
    post("admin-report-review", "moderation/reports/" + identity, {"status": "resolved", "note": "Synthetic reviewed"}, role="moderator")
    request("admin-report-read-resolved", "moderation/reports")
    post("admin-report-status-denied", "moderation/reports/" + identity, {"status": "invalid", "note": "Synthetic"}, role="moderator", status=400)
    post("admin-rename-b", "users/" + b + "/rename", {"username": "Fixture Renamed B"}, role="admin")
    request("admin-renamed-profile", "users/" + b)
    post("admin-mute", "users/" + a + "/mute", {"expires_at": None}, role="moderator")
    request("admin-muted-status", "users/" + a + "/moderation")
    post("admin-unmute", "users/" + a + "/unmute", role="moderator")
    post("admin-maintenance", "moderation/maintenance", {"minutes": 5}, role="admin")
    request("admin-maintenance-status", "moderation/status")
    post("admin-news-publish", "moderation/news", {"text": "Synthetic preservation news", "expires_at": None}, role="admin", key="admin-news-key-0001")
    snap("admin-after-news")
    post("admin-news-replay", "moderation/news", {"text": "Synthetic preservation news", "expires_at": None}, role="admin", key="admin-news-key-0001")
    snap("admin-after-news-replay", "admin-after-news")
    request("admin-news-read", "moderation/news")
    post("admin-kick", "users/" + b + "/kick", role="moderator")
    game("admin-kicked-session-denied", "GetPlayerPrefsServlet", gb, b, status=403)
    post("admin-ban", "users/" + b + "/ban", {"expires_at": None}, role="moderator")
    request("admin-banned-status", "users/" + b + "/moderation")
    post("admin-unban", "users/" + b + "/unban", role="moderator")
    request("admin-unbanned-status", "users/" + b + "/moderation")
    game("admin-unban-does-not-resurrect-session", "GetPlayerPrefsServlet", gb, b, status=403)
    post("admin-owner-player-link", "operators/owner/player-link", {"account_id": b})
    post("admin-equal-higher-sanction-denied", "users/" + b + "/ban", {"expires_at": None}, role="moderator", status=403)
    post("admin-disable-moderator", "operators/moderator", {"role": "moderator", "enabled": False})
    request("admin-disabled-moderator-denied", "health", role="moderator", status=403)
    request("admin-final-events", "moderation/events")
    request("admin-final-audit", "audit")
    request("admin-final-stats", "stats")
    snap("admin-before-process-reopen")
    cases.append({"id": "admin-process-reopen", "op": "process_restart"})
    snap("admin-after-process-reopen", "admin-before-process-reopen")
    request("admin-wallet-after-process-reopen", "users/" + a + "/wallet")
    request("admin-disabled-role-survives-reopen", "health", role="moderator", status=403)
    request("admin-news-after-process-reopen", "moderation/news")
    return cases


if __name__ == "__main__":
    cases = corpus()
    (HERE / "corpus.json").write_text(json.dumps(cases, indent=2, ensure_ascii=True) + "\n")
    print(json.dumps({"admin_cases": len(cases)}))
