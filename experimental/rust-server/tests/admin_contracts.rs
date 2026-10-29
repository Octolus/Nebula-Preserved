use nebula_preserved_server::{admin, state::State};
use rusqlite::params;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs,
    path::PathBuf,
    sync::{Arc, Barrier},
};

const TOKEN: &[u8] = b"synthetic-test-management-token-only-000000000000";
const GA: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const GB: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
fn operators() -> Value {
    json!([
        {"id":"owner","role":"owner","enabled":true,"password_scrypt":"synthetic-never-persist"},
        {"id":"admin","role":"admin","enabled":true},
        {"id":"moderator","role":"moderator","enabled":true},
        {"id":"disabled","role":"owner","enabled":false}
    ])
}
fn headers(actor: &str, key: &str) -> HashMap<String, String> {
    HashMap::from([
        (
            "Authorization".into(),
            format!("Bearer {}", std::str::from_utf8(TOKEN).unwrap()),
        ),
        ("X-Management-Actor".into(), actor.into()),
        (
            "Content-Type".into(),
            "application/json; charset=utf-8".into(),
        ),
        ("Idempotency-Key".into(), key.into()),
    ])
}
struct Fixture {
    root: PathBuf,
    state: State,
}
impl Fixture {
    fn new() -> Self {
        Self::make(true)
    }
    fn make(initialized: bool) -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("target/admin-tests")
            .join(uuid::Uuid::new_v4().to_string());
        let protocol = root.join("protocol");
        fs::create_dir_all(&protocol).unwrap();
        let write = |name: &str, v: Value| fs::write(protocol.join(name), v.to_string()).unwrap();
        write(
            "avatar-asset-catalog.json",
            json!({"items":[
                {"item_id":"hat","gender":"MALE","category":"HATS","bundle":"00/hat"},
                {"item_id":"otherhat","gender":"FEMALE","category":"HATS","bundle":"00/otherhat"},
                {"item_id":"removehat","gender":"MALE","category":"HATS","bundle":"00/removehat"}
            ]}),
        );
        write(
            "wardrobe-removal-sentinels.json",
            json!({"sentinels":[{"item_id":"removehat","gender":"MALE","category":"HATS"}]}),
        );
        write(
            "resource-entitlements.json",
            json!({"format_version":1,"items":[{"kind":"companions","item_id":"PetA","grantable":true,"conflicts":[],"table":"COMPANIONS","bundle":"02/peta","requested_resource_path":"Wardrobe_EAB/COMPANIONS/PetA/PetA","asset_path":"Assets/ResourcesART/Wardrobe_EAB/COMPANIONS/PetA/PetA.prefab"}]}),
        );
        write(
            "http-nonminigame-gap-audit.json",
            json!({"housing_catalog":[{"item_id":"chair","table":"HOUSING_CHAIR","bundle":"01/chair","asset_path":"Assets/ResourcesART/Housing/HOUSING_CHAIR/chair/FBX/chair.prefab","grantable":true,"manifest_sha256":"synthetic-proof"}],"personal_space_navigator_names":["Home"]}),
        );
        write(
            "housing-placement-contracts.json",
            json!({"format_version":1,"max_placement_space":200,"items":{"chair":{"table":"HOUSING_CHAIR","bundle":"01/chair","manifest_sha256":"synthetic-proof","behaviour":"ground","placement_cost":1}},"personal_spaces":{"Home":{"wall_slots":2,"ceiling_slots":2}}}),
        );
        let mut state = State::open(&root.join("state"), &protocol).unwrap();
        state.fixed_time = Some(1000.);
        {
            let db = state.connection().unwrap();
            for (id, name, guid) in [
                ("a", "Synthetic Alice", GA),
                ("b", "Synthetic Bob", GB),
                ("c", "Synthetic Cora", "cccccccccccccccccccccccccccccccc"),
            ] {
                db.execute(
                    "INSERT INTO profiles VALUES(?,?,?,'MALE',100)",
                    params![id, name, "StandaloneWindows"],
                )
                .unwrap();
                db.execute("INSERT INTO sessions VALUES(?,?,100)", params![guid, id])
                    .unwrap();
                db.execute("INSERT INTO profile_state(ps4_id,online) VALUES(?,1)", [id])
                    .unwrap();
            }
            db.execute("INSERT INTO shop_wallets VALUES('a',100,50,7)", [])
                .unwrap();
            db.execute(
                "INSERT INTO shop_catalogs VALUES('s',0,'Synthetic shop','','',1)",
                [],
            )
            .unwrap();
        }
        let out = Self { root, state };
        if initialized {
            admin::initialize(&out.state, TOKEN, &operators()).unwrap();
        }
        out
    }
    fn call(
        &self,
        method: &str,
        route: &str,
        actor: &str,
        key: &str,
        body: Value,
    ) -> admin::AdminResponse {
        admin::handle(&self.state, method, route, &headers(actor, key), &body)
    }
    fn get(&self, route: &str, actor: &str) -> Value {
        let r = self.call("GET", route, actor, "unused-key", json!({}));
        assert_eq!(r.status, 200, "{}", r.body);
        r.body["data"].clone()
    }
    fn post(&self, route: &str, actor: &str, key: &str, body: Value) -> Value {
        let r = self.call("POST", route, actor, key, body);
        assert_eq!(r.status, 200, "{}", r.body);
        r.body["data"].clone()
    }
    fn count(&self, table: &str) -> i64 {
        self.state
            .connection()
            .unwrap()
            .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0))
            .unwrap()
    }
    fn offer(&self, id: &str, kind: &str, item: Option<&str>) {
        self.state.connection().unwrap().execute("INSERT INTO shop_offers VALUES(?,?,?,?,?,'s','type',0,?,'MALE/HATS/hat/hatThumbnail.png',10,7,1,1,100)",params![id,kind,item,if kind=="wardrobe"{Some("MALE")}else{None},if kind=="wardrobe"{Some("HATS")}else{None},id]).unwrap();
    }
    fn reopen(&mut self) {
        let mut state = State::open(&self.root.join("state"), &self.root.join("protocol")).unwrap();
        state.fixed_time = Some(1000.);
        self.state = state;
        admin::initialize(&self.state, TOKEN, &operators()).unwrap();
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let expected = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target/admin-tests");
        assert!(self.root.starts_with(expected));
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn authentication_permissions_and_structured_errors() {
    let f = Fixture::make(false);
    assert_eq!(
        f.call("GET", "health", "owner", "unused-key", json!({}))
            .status,
        503
    );
    admin::initialize(&f.state, TOKEN, &operators()).unwrap();
    let mut h = headers("owner", "unused-key");
    h.remove("Authorization");
    let r = admin::handle(&f.state, "GET", "health", &h, &json!({}));
    assert_eq!(r.status, 401);
    assert_eq!(r.body["error"]["code"], "unauthorized");
    for who in ["missing", "disabled", ""] {
        assert_eq!(
            f.call("GET", "health", who, "unused-key", json!({})).status,
            403
        );
    }
    let mut h = headers("moderator", "unused-key");
    h.insert("X-Management-Role".into(), "owner".into());
    assert_eq!(
        admin::handle(&f.state, "GET", "me", &h, &json!({})).body["data"]["role"],
        "moderator"
    );
    h.insert("Origin".into(), "https://synthetic.invalid".into());
    assert_eq!(
        admin::handle(&f.state, "GET", "health", &h, &json!({})).status,
        403
    );
    assert_eq!(
        f.call(
            "POST",
            "users/a/wallet-adjustments",
            "moderator",
            "unique-001",
            json!({"currency":"np","delta":1,"reason":"Synthetic test"})
        )
        .status,
        403
    );
    assert_eq!(
        f.call(
            "POST",
            "operators/second",
            "admin",
            "unique-002",
            json!({"role":"owner","enabled":true,"reason":"Synthetic test"})
        )
        .status,
        403
    );
    assert_eq!(
        f.call("GET", "operators", "admin", "unused-key", json!({}))
            .status,
        403
    );
    assert_eq!(
        f.call("DELETE", "health", "owner", "unused-key", json!({}))
            .status,
        405
    );
    let mut h = headers("owner", "unique-003");
    h.remove("Content-Type");
    assert_eq!(
        admin::handle(
            &f.state,
            "POST",
            "users/a/wallet-adjustments",
            &h,
            &json!({})
        )
        .status,
        415
    );
    assert_eq!(
        f.get("capabilities", "owner")["game_privilege_mutation_supported"],
        false
    );
    assert_eq!(
        f.call(
            "POST",
            "users/a/developer",
            "owner",
            "unique-004",
            json!({"reason":"Synthetic test"})
        )
        .status,
        404
    );
}

#[test]
fn strict_json_and_local_secret_configuration() {
    for raw in [
        r#"{"a":1,"a":2}"#,
        r#"{"a":{"b":1,"b":2}}"#,
        r#"[]"#,
        r#"{"n":NaN}"#,
        r#"{"n":1e400}"#,
        r#"{"n":1} false"#,
    ] {
        assert_eq!(admin::parse_body(raw.as_bytes()).unwrap_err().status, 400);
    }
    assert_eq!(
        admin::parse_body(&vec![b' '; admin::MAX_BODY + 1])
            .unwrap_err()
            .status,
        413
    );
    assert_eq!(
        admin::parse_body("{\"text\":\"🚀\"}".as_bytes()).unwrap()["text"],
        "🚀"
    );
    let f = Fixture::new();
    let path = f.root.join("operators.synthetic.json");
    fs::write(&path,r#"{"operators":[{"id":"synthetic","role":"owner","password_scrypt":"private-synthetic"}]}"#).unwrap();
    let parsed = admin::load_operator_file(&path).unwrap();
    assert_eq!(parsed[0]["enabled"], true);
    assert!(parsed[0].get("password_scrypt").is_none());
    fs::write(
        &path,
        r#"{"operators":[{"id":"synthetic","role":"admin","role":"owner"}]}"#,
    )
    .unwrap();
    assert!(admin::load_operator_file(&path).is_err());
    let path = f.root.join("token.synthetic");
    let mut raw = TOKEN.to_vec();
    raw.extend(b"\r\n");
    fs::write(&path, raw).unwrap();
    assert_eq!(admin::load_secret_file(&path).unwrap(), TOKEN);
    fs::write(&path, b"short").unwrap();
    assert!(admin::load_secret_file(&path).is_err());
    let audit = f.get("audit?limit=100", "owner").to_string();
    assert!(!audit.contains("password_scrypt"));
    assert!(!audit.contains("synthetic-never-persist"));
    assert!(!audit.contains(std::str::from_utf8(TOKEN).unwrap()));
}

#[test]
fn wallet_receipts_replay_scope_validation_and_reopen() {
    let mut f = Fixture::new();
    let body = json!({"currency":"np","delta":23,"reason":"Synthetic compensation"});
    let first = f.post(
        "users/a/wallet-adjustments",
        "admin",
        "wallet-0001",
        body.clone(),
    );
    assert_eq!(first["after"]["np"], 73);
    assert_eq!(first["after"]["level"], 7);
    let second = f.post(
        "users/a/wallet-adjustments",
        "admin",
        "wallet-0001",
        body.clone(),
    );
    assert_eq!(second["request_id"], first["request_id"]);
    assert_eq!(second["replayed"], true);
    assert_eq!(f.count("management_wallet_ledger"), 1);
    assert_eq!(
        f.call(
            "POST",
            "users/b/wallet-adjustments",
            "admin",
            "wallet-0001",
            body.clone()
        )
        .status,
        409
    );
    let mut changed = body.clone();
    changed["delta"] = json!(24);
    assert_eq!(
        f.call(
            "POST",
            "users/a/wallet-adjustments",
            "admin",
            "wallet-0001",
            changed
        )
        .status,
        409
    );
    f.post(
        "users/b/wallet-adjustments",
        "owner",
        "wallet-0001",
        body.clone(),
    );
    assert_eq!(f.get("users/b/wallet", "owner")["np"], 23);
    for (i, delta) in [
        json!(true),
        json!("1"),
        json!(1.0),
        json!(0),
        json!(i64::MAX),
    ]
    .into_iter()
    .enumerate()
    {
        assert_eq!(
            f.call(
                "POST",
                "users/a/wallet-adjustments",
                "admin",
                &format!("bad-delta-{i}"),
                json!({"currency":"np","delta":delta,"reason":"Synthetic invalid"})
            )
            .status,
            400
        );
    }
    assert_eq!(
        f.call(
            "POST",
            "users/a/wallet-adjustments",
            "admin",
            "overflow-001",
            json!({"currency":"crystals","delta":2_147_483_647i64,"reason":"Synthetic overflow"})
        )
        .status,
        409
    );
    assert_eq!(
        f.call(
            "POST",
            "users/a/wallet-adjustments",
            "admin",
            "negative-001",
            json!({"currency":"np","delta":-1000,"reason":"Synthetic insufficient"})
        )
        .status,
        409
    );
    assert_eq!(
        f.call(
            "POST",
            "users/a/wallet-adjustments",
            "admin",
            "short",
            body.clone()
        )
        .status,
        400
    );
    f.reopen();
    let replay = f.post("users/a/wallet-adjustments", "admin", "wallet-0001", body);
    assert_eq!(replay["replayed"], true);
    assert_eq!(replay["request_id"], first["request_id"]);
    assert_eq!(f.get("users/a/wallet", "owner")["np"], 73);
    assert_eq!(f.count("management_wallet_ledger"), 2);
}

#[test]
fn audit_failure_rolls_back_wallet_grant_and_moderation() {
    let f = Fixture::new();
    let audit = f.count("management_audit");
    f.state.connection().unwrap().execute_batch("CREATE TRIGGER synthetic_audit_failure BEFORE INSERT ON management_audit WHEN NEW.actor_id<>'bootstrap' BEGIN SELECT RAISE(ABORT,'synthetic transaction failure'); END;").unwrap();
    for (route, key, body) in [
        (
            "users/a/wallet-adjustments",
            "rollback-wallet",
            json!({"currency":"np","delta":10,"reason":"Synthetic rollback"}),
        ),
        (
            "users/a/items",
            "rollback-grant",
            json!({"kind":"wardrobe","item_id":"hat","reason":"Synthetic rollback"}),
        ),
        (
            "users/a/ban",
            "rollback-ban",
            json!({"reason":"Synthetic rollback"}),
        ),
    ] {
        assert_eq!(f.call("POST", route, "owner", key, body).status, 409);
    }
    assert_eq!(f.get("users/a/wallet", "owner")["np"], 50);
    assert_eq!(f.count("entitlements"), 0);
    assert_eq!(f.count("moderation_accounts"), 0);
    assert_eq!(f.count("moderation_revoked_sessions"), 0);
    assert_eq!(f.count("moderation_events"), 0);
    assert_eq!(f.count("management_requests"), 0);
    assert_eq!(f.count("management_wallet_ledger"), 0);
    assert_eq!(f.count("management_audit"), audit);
}

#[test]
fn grants_use_shipped_assets_and_atomic_bundle_authority() {
    let f = Fixture::new();
    for (kind, item) in [
        ("wardrobe", "hat"),
        ("companions", "PetA"),
        ("housing", "chair"),
    ] {
        let body = json!({"kind":kind,"item_id":item,"reason":"Synthetic entitlement"});
        let r = f.post(
            "users/a/items",
            "admin",
            &format!("grant-{kind}-1"),
            body.clone(),
        );
        assert_eq!(r["changed"], true);
        let again = f.post("users/a/items", "admin", &format!("grant-{kind}-2"), body);
        assert_eq!(again["changed"], false);
    }
    assert_eq!(f.get("users/a/owned?limit=2", "owner")["total"], 3);
    assert_eq!(f.get("users/a/owned?limit=2", "owner")["next_cursor"], "2");
    assert_eq!(
        f.call(
            "POST",
            "users/a/items",
            "admin",
            "remove-control",
            json!({"kind":"wardrobe","item_id":"removehat","reason":"Synthetic invalid control"})
        )
        .status,
        400
    );
    assert_eq!(
        f.call(
            "POST",
            "users/a/items",
            "admin",
            "missing-asset",
            json!({"kind":"wardrobe","item_id":"missing","reason":"Synthetic absent"})
        )
        .status,
        404
    );
    assert_eq!(f.call("POST","users/a/items","admin","unexpected-gender",json!({"kind":"companions","item_id":"PetA","gender":null,"reason":"Synthetic invalid field"})).status,400);
    assert_eq!(f.get("catalog?kind=wardrobe", "owner")["total"], 2);
    assert_eq!(f.get("catalog?kind=wardrobe&q=%25", "owner")["total"], 0);
    f.offer("offer-hat", "wardrobe", Some("hat"));
    f.offer("offer-pet", "companions", Some("PetA"));
    f.offer("bundle", "bundle", None);
    {
        let db = f.state.connection().unwrap();
        db.execute(
            "INSERT INTO shop_bundle_items VALUES('bundle','offer-hat',0)",
            [],
        )
        .unwrap();
        db.execute(
            "INSERT INTO shop_bundle_items VALUES('bundle','offer-pet',1)",
            [],
        )
        .unwrap();
    }
    let r = f.post(
        "users/b/items",
        "admin",
        "bundle-grant",
        json!({"kind":"offer","offer_id":"bundle","reason":"Synthetic bundle"}),
    );
    assert_eq!(r["changed"], true);
    assert_eq!(f.get("users/b/owned", "owner")["total"], 2);
    let purchases = f.get("users/b/purchases", "owner");
    assert_eq!(purchases["items"][0]["source"], "admin");
    assert_eq!(purchases["items"][0]["granted_by"], "admin");
    assert_eq!(purchases["items"][0]["historical_price_known"], false);
    assert_eq!(f.get("users/b/wallet", "owner")["np"], 0);
    f.offer("bad-child", "wardrobe", Some("missing"));
    f.offer("bad-bundle", "bundle", None);
    {
        let db = f.state.connection().unwrap();
        db.execute(
            "INSERT INTO shop_bundle_items VALUES('bad-bundle','offer-hat',0)",
            [],
        )
        .unwrap();
        db.execute(
            "INSERT INTO shop_bundle_items VALUES('bad-bundle','bad-child',1)",
            [],
        )
        .unwrap();
    }
    assert_eq!(
        f.call(
            "POST",
            "users/c/items",
            "admin",
            "bad-bundle-grant",
            json!({"kind":"offer","offer_id":"bad-bundle","reason":"Synthetic rollback"})
        )
        .status,
        404
    );
    assert_eq!(f.get("users/c/owned", "owner")["total"], 0);
}

#[test]
fn bans_kicks_and_mutes_preserve_permanent_session_tombstones() {
    let mut f = Fixture::new();
    let later = "dddddddddddddddddddddddddddddddd";
    f.state
        .connection()
        .unwrap()
        .execute("INSERT INTO sessions VALUES(?,'a',200)", [later])
        .unwrap();
    let ban = f.post(
        "users/a/ban",
        "moderator",
        "ban-session-001",
        json!({"expires_at":1100,"reason":"Synthetic temporary ban"}),
    );
    assert_eq!(ban["after"]["newly_revoked_guids"], json!([GA, later]));
    assert_eq!(ban["after"]["online"], 0);
    assert_eq!(f.get("users/a/moderation", "owner")["banned"], true);
    f.post(
        "users/a/unban",
        "moderator",
        "unban-session-001",
        json!({"reason":"Synthetic release"}),
    );
    assert_eq!(f.get("users/a/moderation", "owner")["banned"], false);
    assert_eq!(f.count("moderation_revoked_sessions"), 2);
    f.post(
        "users/b/mute",
        "moderator",
        "mute-session-001",
        json!({"expires_at":1001,"reason":"Synthetic mute"}),
    );
    assert_eq!(f.get("users/b/moderation", "owner")["muted"], true);
    assert_eq!(f.get("users/b/moderation", "owner")["role"], "player");
    assert_eq!(f.count("moderation_revoked_sessions"), 2);
    f.state.fixed_time = Some(1001.);
    assert_eq!(f.get("users/b/moderation", "owner")["muted"], false);
    let kick = f.post(
        "users/b/kick",
        "moderator",
        "kick-session-001",
        json!({"reason":"Synthetic kick"}),
    );
    assert_eq!(kick["after"]["current_guid"], GB);
    assert_eq!(kick["changed"], true);
    let kick = f.post(
        "users/b/kick",
        "moderator",
        "kick-session-002",
        json!({"reason":"Synthetic repeated kick"}),
    );
    assert_eq!(kick["changed"], false);
    assert_eq!(f.count("moderation_revoked_sessions"), 3);
    f.reopen();
    assert_eq!(f.count("moderation_revoked_sessions"), 3);
    assert!(f
        .state
        .connection()
        .unwrap()
        .execute("DELETE FROM moderation_revoked_sessions", [])
        .is_err());
    assert!(f
        .state
        .connection()
        .unwrap()
        .execute("UPDATE moderation_events SET reason='rewrite'", [])
        .is_err());
}

#[test]
fn enabled_operator_links_enforce_all_sanction_hierarchy_pairs() {
    let f = Fixture::new();
    for (operator, id) in [("owner", "a"), ("admin", "b"), ("moderator", "c")] {
        f.post(
            &format!("operators/{operator}/player-link"),
            "owner",
            &format!("link-{operator}-001"),
            json!({"account_id":id,"reason":"Synthetic hierarchy link"}),
        );
    }
    let actors = ["moderator", "admin", "owner"];
    let targets = [("c", 0), ("b", 1), ("a", 2)];
    for (rank, actor) in actors.iter().enumerate() {
        for (id, target_rank) in targets {
            for action in ["ban", "unban", "kick", "mute", "unmute"] {
                let r = f.call(
                    "POST",
                    &format!("users/{id}/{action}"),
                    actor,
                    &format!("hierarchy-{actor}-{id}-{action}"),
                    json!({"reason":"Synthetic hierarchy check"}),
                );
                assert_eq!(
                    r.status,
                    if rank == 2 || rank > target_rank {
                        200
                    } else {
                        403
                    },
                    "{actor} {id} {action}: {}",
                    r.body
                );
            }
        }
    }
    f.post(
        "operators/admin",
        "owner",
        "disable-linked-admin",
        json!({"role":"admin","enabled":false,"reason":"Synthetic disabled operator"}),
    );
    assert_eq!(
        f.call(
            "POST",
            "users/b/mute",
            "moderator",
            "disabled-link-policy",
            json!({"reason":"Synthetic disabled link"})
        )
        .status,
        200
    );
}

#[test]
fn staff_unicode_boundaries_and_news_codepoint_lengths() {
    let f = Fixture::new();
    assert_eq!(
        f.call(
            "POST",
            "users/a/staff-label",
            "admin",
            "staff-role-001",
            json!({"label":"Helper","reason":"Synthetic label"})
        )
        .status,
        403
    );
    for (i, bad) in [
        "#", "\0", "\n", "\r", "\u{7f}", "\u{85}", "\u{200b}", "\u{202e}", "\u{e000}", "\u{0378}",
        "\u{1c89}", "<admin>",
    ]
    .iter()
    .enumerate()
    {
        assert_eq!(
            f.call(
                "POST",
                "users/a/staff-label",
                "owner",
                &format!("bad-label-{i}"),
                json!({"label":bad,"reason":"Synthetic invalid label"})
            )
            .status,
            400
        );
    }
    assert_eq!(f.count("moderation_events"), 0);
    assert_eq!(f.count("management_requests"), 0);
    assert_eq!(f.count("management_audit"), 4);
    let label = "é".repeat(32);
    f.post(
        "users/a/staff-label",
        "owner",
        "good-label-001",
        json!({"label":label,"reason":"Synthetic valid label"}),
    );
    assert_eq!(f.get("users/a/moderation", "owner")["staff_label"], label);
    assert_eq!(
        f.call(
            "POST",
            "users/a/staff-label",
            "owner",
            "long-label-001",
            json!({"label":"é".repeat(33),"reason":"Synthetic overlong label"})
        )
        .status,
        400
    );
    let news = f.post(
        "moderation/news",
        "admin",
        "unicode-news-001",
        json!({"text":"🚀".repeat(1000),"reason":"Synthetic Unicode news"}),
    );
    assert_eq!(
        news["after"]["text"].as_str().unwrap().chars().count(),
        1000
    );
    assert_eq!(
        f.call(
            "POST",
            "moderation/news",
            "admin",
            "unicode-news-002",
            json!({"text":"🚀".repeat(1001),"reason":"Synthetic overlong news"})
        )
        .status,
        400
    );
}

#[test]
fn maintenance_news_and_report_reviews_are_audited_without_receipt_rewrites() {
    let f = Fixture::new();
    let r = f.post(
        "moderation/maintenance",
        "admin",
        "maintenance-001",
        json!({"minutes":2,"reason":"Synthetic maintenance"}),
    );
    assert_eq!(
        r["after"],
        json!({"started_at":1000,"end_at":1120,"reason":"Synthetic maintenance","minutes":2})
    );
    assert_eq!(
        f.get("moderation/status", "owner")["maintenance_minutes"],
        2
    );
    for (i, value) in [json!(true), json!(1.0), json!(-1), json!(1441)]
        .into_iter()
        .enumerate()
    {
        assert_eq!(
            f.call(
                "POST",
                "moderation/maintenance",
                "admin",
                &format!("maintenance-bad-{i}"),
                json!({"minutes":value,"reason":"Synthetic invalid"})
            )
            .status,
            400
        );
    }
    let news = f.post(
        "moderation/news",
        "admin",
        "news-publish-001",
        json!({"text":"Synthetic local news","expires_at":1200,"reason":"Synthetic publish"}),
    );
    assert_eq!(news["after"]["date_label"], "1970-01-01T00:16:40Z");
    let id = news["after"]["news_id"].as_str().unwrap();
    let route = format!("moderation/news/{id}/archive");
    assert_eq!(
        f.post(
            &route,
            "admin",
            "news-archive-001",
            json!({"reason":"Synthetic archive"})
        )["after"]["active"],
        0
    );
    assert_eq!(
        f.post(
            &route,
            "admin",
            "news-archive-002",
            json!({"reason":"Synthetic archive again"})
        )["changed"],
        false
    );
    {
        let db = f.state.connection().unwrap();
        assert!(db
            .execute("UPDATE moderation_news SET text='rewrite'", [])
            .is_err());
        assert!(db.execute("DELETE FROM moderation_news", []).is_err());
        db.execute(
            "INSERT INTO local_reports VALUES(?,'opaque-target',1,'Synthetic original report',900)",
            [GA],
        )
        .unwrap();
    }
    // Initialization indexes existing legacy receipts with the shared canonical digest.
    admin::initialize(&f.state, TOKEN, &operators()).unwrap();
    let reports = f.get("moderation/reports", "owner");
    assert_eq!(reports["total"], 1);
    let id = reports["items"][0]["report_id"].as_str().unwrap();
    let r = f.post(
        &format!("moderation/reports/{id}"),
        "moderator",
        "review-report-001",
        json!({"status":"resolved","note":"Synthetic reviewed","reason":"Synthetic report review"}),
    );
    assert_eq!(r["before"]["status"], "open");
    assert_eq!(r["after"]["status"], "resolved");
    assert_eq!(
        f.get("moderation/reports", "owner")["items"][0]["text"],
        "Synthetic original report"
    );
    assert!(f
        .state
        .connection()
        .unwrap()
        .execute("UPDATE local_reports SET text='rewrite'", [])
        .is_err());
    let events = f.get("moderation/events?limit=100", "owner");
    assert_eq!(events["total"], 5);
    assert!(events["items"][0].get("before_json").is_none());
    assert!(events["items"][0].get("before").is_some());
}

#[test]
fn rename_migrates_all_inbound_relations_and_rejects_ambiguity() {
    let f = Fixture::new();
    {
        let db = f.state.connection().unwrap();
        for kind in ["friend", "favorite", "block", "silenced"] {
            db.execute(
                "INSERT INTO relations VALUES('b','Synthetic Alice','StandaloneWindows',?)",
                [kind],
            )
            .unwrap();
        }
    }
    let r = f.post(
        "users/a/rename",
        "admin",
        "rename-alice-001",
        json!({"username":"Synthetic Renamed","reason":"Synthetic rename"}),
    );
    assert_eq!(r["after"]["username"], "Synthetic Renamed");
    let count: i64 = f
        .state
        .connection()
        .unwrap()
        .query_row(
            "SELECT COUNT(*) FROM relations WHERE target='Synthetic Renamed'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(count, 4);
    assert_eq!(
        f.call(
            "POST",
            "users/a/rename",
            "admin",
            "rename-collision",
            json!({"username":"Synthetic Bob","reason":"Synthetic collision"})
        )
        .status,
        409
    );
    assert_eq!(f.get("users/a", "owner")["username"], "Synthetic Renamed");
    assert_eq!(f.get("users?q=%25", "owner")["total"], 0);
    assert_eq!(f.get("users?limit=1", "owner")["next_cursor"], "1");
    assert_eq!(
        f.get("users?limit=1&cursor=1", "owner")["items"][0]["account_id"],
        "b"
    );
    assert_eq!(
        f.call("GET", "users?limit=101", "owner", "unused-key", json!({}))
            .status,
        400
    );
}

#[test]
fn operator_protection_links_and_persisted_roles() {
    let mut f = Fixture::new();
    let before = f.count("management_requests");
    assert_eq!(
        f.call(
            "POST",
            "operators/owner",
            "owner",
            "last-owner-demote",
            json!({"role":"admin","enabled":true,"reason":"Synthetic last owner"})
        )
        .status,
        409
    );
    assert_eq!(f.count("management_requests"), before);
    f.post(
        "operators/second",
        "owner",
        "create-second-owner",
        json!({"role":"owner","enabled":true,"reason":"Synthetic second owner"}),
    );
    f.post(
        "operators/admin",
        "owner",
        "demote-admin-001",
        json!({"role":"moderator","enabled":true,"reason":"Synthetic demotion"}),
    );
    f.post(
        "operators/owner/player-link",
        "owner",
        "link-player-owner",
        json!({"account_id":"a","reason":"Synthetic link"}),
    );
    assert_eq!(
        f.call(
            "POST",
            "operators/second/player-link",
            "owner",
            "duplicate-player-link",
            json!({"account_id":"a","reason":"Synthetic duplicate"})
        )
        .status,
        409
    );
    assert_eq!(
        f.call(
            "POST",
            "operators/owner/player-link",
            "owner",
            "missing-unlink-field",
            json!({"reason":"Synthetic missing"})
        )
        .status,
        400
    );
    f.post(
        "operators/owner/player-link",
        "owner",
        "unlink-player-owner",
        json!({"account_id":null,"reason":"Synthetic unlink"}),
    );
    f.post(
        "operators/second/player-link",
        "owner",
        "relink-player-second",
        json!({"account_id":"a","reason":"Synthetic relink"}),
    );
    f.reopen();
    assert_eq!(f.get("me", "admin")["role"], "moderator");
    let ops = f.get("operators?limit=100", "owner");
    assert_eq!(
        ops["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["id"] == "second")
            .unwrap()["account_id"],
        "a"
    );
    {
        let db = f.state.connection().unwrap();
        assert!(db.execute("DELETE FROM management_audit", []).is_err());
        assert!(db
            .execute("UPDATE management_requests SET response_json='{}'", [])
            .is_err());
    }
}

#[test]
fn same_receipt_serializes_across_independent_sqlite_connections() {
    let f = Fixture::new();
    let mut other = State::open(&f.root.join("state"), &f.root.join("protocol")).unwrap();
    other.fixed_time = Some(1000.);
    admin::initialize(&other, TOKEN, &operators()).unwrap();
    let barrier = Arc::new(Barrier::new(2));
    let mut threads = Vec::new();
    for state in [f.state.clone(), other] {
        let b = barrier.clone();
        threads.push(std::thread::spawn(move||{b.wait();admin::handle(&state,"POST","users/a/wallet-adjustments",&headers("admin","parallel-receipt-001"),&json!({"currency":"crystals","delta":20,"reason":"Synthetic concurrent adjustment"}))}));
    }
    let results = threads
        .into_iter()
        .map(|t| t.join().unwrap())
        .collect::<Vec<_>>();
    for r in &results {
        assert_eq!(r.status, 200, "{}", r.body);
    }
    assert_eq!(
        results[0].body["data"]["request_id"],
        results[1].body["data"]["request_id"]
    );
    assert_ne!(
        results[0].body["data"]["replayed"],
        results[1].body["data"]["replayed"]
    );
    assert_eq!(f.count("management_requests"), 1);
    assert_eq!(f.count("management_wallet_ledger"), 1);
    assert_eq!(f.get("users/a/wallet", "owner")["crystals"], 120);
}

#[test]
fn shared_grant_constraint_preserves_conflict_and_rolls_back_the_receipt() {
    let f = Fixture::new();
    let before = f.count("management_audit");
    f.state.connection().unwrap().execute_batch("CREATE TRIGGER synthetic_grant_failure BEFORE INSERT ON entitlements BEGIN SELECT RAISE(ABORT,'synthetic shared grant failure'); END;").unwrap();
    let body =
        json!({"kind":"wardrobe","item_id":"hat","reason":"Synthetic shared authority failure"});
    let failed = f.call(
        "POST",
        "users/a/items",
        "admin",
        "shared-grant-constraint",
        body.clone(),
    );
    assert_eq!(failed.status, 409);
    assert_eq!(
        failed.body["error"],
        json!({"code":"conflict","message":"The command could not be committed"})
    );
    assert_eq!(f.count("entitlements"), 0);
    assert_eq!(f.count("management_requests"), 0);
    assert_eq!(f.count("management_audit"), before);
    f.state
        .connection()
        .unwrap()
        .execute_batch("DROP TRIGGER synthetic_grant_failure")
        .unwrap();
    let successful = f.post("users/a/items", "admin", "shared-grant-constraint", body);
    assert_eq!(successful["changed"], true);
    assert_eq!(successful["replayed"], false);
    assert_eq!(f.count("entitlements"), 1);
    assert_eq!(f.count("management_requests"), 1);
}

#[test]
fn historical_reserved_username_cannot_receive_admin_grants_or_wallet_changes() {
    let f = Fixture::new();
    f.state
        .connection()
        .unwrap()
        .execute(
            "UPDATE profiles SET username='[test] preservation client synthetic' WHERE ps4_id='a'",
            [],
        )
        .unwrap();
    f.offer("reserved-profile-offer", "wardrobe", Some("hat"));
    let before = f.count("management_audit");
    for (route, key, body) in [
        (
            "users/a/wallet-adjustments",
            "reserved-wallet-change",
            json!({"currency":"np","delta":-10,"reason":"Synthetic historical identity"}),
        ),
        (
            "users/a/items",
            "reserved-asset-grant",
            json!({"kind":"wardrobe","item_id":"hat","reason":"Synthetic historical identity"}),
        ),
        (
            "users/a/items",
            "reserved-offer-grant",
            json!({"kind":"offer","offer_id":"reserved-profile-offer","reason":"Synthetic historical identity"}),
        ),
    ] {
        let response = f.call("POST", route, "owner", key, body);
        assert_eq!(response.status, 403, "{}", response.body);
        assert_eq!(
            response.body["error"]["message"],
            "Local test identities are disabled"
        );
    }
    assert_eq!(f.get("users/a/wallet", "owner")["np"], 50);
    assert_eq!(f.count("entitlements"), 0);
    assert_eq!(f.count("shop_owned"), 0);
    assert_eq!(f.count("management_requests"), 0);
    assert_eq!(f.count("management_wallet_ledger"), 0);
    assert_eq!(f.count("management_audit"), before);
}
