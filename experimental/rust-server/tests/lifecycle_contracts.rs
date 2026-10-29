//! Offline allocation and managed demand tests; no native-client acceptance is
//! inferred from synthetic listener descriptors used by this test harness.
use nebula_preserved_server::{
    character, lifecycle,
    state::State,
    wire::{session_guid, Request},
};
use rusqlite::params;
use serde_json::{json, Value};
use std::{fs, path::PathBuf};
use tempfile::TempDir;
const OWNER: &str = "76561198000000001";
const VISITOR: &str = "76561198000000002";
struct Fixture {
    _dir: TempDir,
    root: PathBuf,
    protocol: PathBuf,
    state: State,
}
impl Fixture {
    fn new(managed: bool) -> Self {
        let base = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("test-state");
        fs::create_dir_all(&base).unwrap();
        let dir = tempfile::Builder::new()
            .prefix("lifecycle-")
            .tempdir_in(&base)
            .unwrap();
        let root = dir.path().to_path_buf();
        let protocol = root.join("protocol");
        fs::create_dir(&protocol).unwrap();
        let docs: Value =
            serde_json::from_str(include_str!("character_catalog_fixtures.json")).unwrap();
        for (name, body) in docs.as_object().unwrap() {
            fs::write(protocol.join(name), serde_json::to_vec(body).unwrap()).unwrap();
        }
        let mut state = State::open(&root.join("state"), &protocol).unwrap();
        state.fixed_time = Some(1_700_000_000.);
        state.managed_instances = managed;
        if managed {
            state.readiness_profile = Some("nonmini-semantic-v1".into());
            lifecycle::initialize(&state).unwrap();
        }
        Self {
            _dir: dir,
            root,
            protocol,
            state,
        }
    }
    fn login(&self, id: &str, name: &str, hash: &str) -> String {
        character::handle(
            &self.state,
            "N2UserExist",
            &req(&[name, "v", "false", id, "0"]),
        )
        .unwrap();
        character::handle(&self.state, "ChannelGUIDServlet", &req(&[id, hash])).unwrap();
        session_guid(id, hash)
    }
    fn call(&self, route: &str, f: &[&str]) -> String {
        lifecycle::handle(&self.state, route, &req(f))
            .unwrap()
            .unwrap()
    }
    fn error(&self, route: &str, f: &[&str]) -> u16 {
        lifecycle::handle(&self.state, route, &req(f))
            .unwrap_err()
            .status
    }
    fn status(&self, instance: &str, scene: &str, port: u16, players: i64) -> Value {
        json!({"format_version":1,"instance_id":instance,"psidglobal":scene,"ip":"127.0.0.1","bind":"127.0.0.1","port":port,"maxusers":32,"players":players,"heartbeat":self.state.now(),"listening":true,"listener_bound":true,"protocol_complete":true,"game_ready":true})
    }
    fn write_status(&self, v: &Value) {
        fs::write(
            self.state.state_dir.join("instance-status.json"),
            serde_json::to_vec(v).unwrap(),
        )
        .unwrap();
    }
    fn reopen(&mut self) {
        let mut s = State::open(&self.root.join("state"), &self.protocol).unwrap();
        s.fixed_time = self.state.fixed_time;
        s.managed_instances = self.state.managed_instances;
        s.readiness_profile = self.state.readiness_profile.clone();
        self.state = s;
    }
}
fn req(fields: &[&str]) -> Request {
    Request {
        fields: fields.iter().map(|s| s.to_string()).collect(),
        platform: "StandaloneWindows".into(),
    }
}

#[test]
fn default_routes_create_no_managed_schema_and_require_fresh_eligible_descriptor() {
    let f = Fixture::new(false);
    let guid = f.login(OWNER, "Owner", &"ab".repeat(32));
    lifecycle::initialize(&f.state).unwrap();
    assert_eq!(
        f.state
            .connection()
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='managed_instances'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
    assert_eq!(
        f.error("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]),
        503
    );
    assert_eq!(
        f.call("N2SpaceLoading", &[&guid, OWNER]),
        format!("{guid}#false")
    );
    let base = f.status("nexus-one", "Nexus", 7777, 0);
    for (field, value) in [
        ("listening", json!(false)),
        ("protocol_complete", json!(false)),
        ("heartbeat", json!(f.state.now() - 16.)),
        ("heartbeat", json!(true)),
        ("ip", json!("127.0.0.2")),
        ("port", json!(0)),
        ("maxusers", json!(64)),
    ] {
        let mut v = base.clone();
        v[field] = value;
        f.write_status(&v);
        assert_eq!(
            f.error("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]),
            503,
            "{field}"
        );
    }
    f.write_status(&base);
    assert_eq!(
        f.call("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]),
        format!("{guid}#false#false")
    );
    assert_eq!(
        f.call("N2SpaceLoading", &[&guid, OWNER]),
        format!("{guid}#true#nexus-one#Nexus#127.0.0.1#7777")
    );
}

#[test]
fn allocation_reopen_uses_live_endpoint_and_refuses_ambiguous_descriptors() {
    let mut f = Fixture::new(false);
    let guid = f.login(OWNER, "Owner", &"ab".repeat(32));
    let mut status = f.status("nexus-one", "Nexus", 7777, 0);
    f.write_status(&status);
    f.call("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]);
    f.reopen();
    status["port"] = json!(8888);
    f.write_status(&status);
    assert!(f.call("N2SpaceLoading", &[&guid, OWNER]).ends_with("#8888"));
    assert_eq!(
        f.call(
            "spaceExistServlet",
            &[&guid, OWNER, "127.0.0.1", "8888", "Nexus"]
        ),
        format!("true#{guid}#true")
    );
    assert_eq!(
        f.call(
            "spaceExistServlet",
            &[&guid, OWNER, "127.0.0.1", "7777", "Nexus"]
        ),
        format!("true#{guid}#false")
    );
    let dir = f.state.state_dir.join("instances/nexus-one");
    fs::create_dir_all(&dir).unwrap();
    fs::write(
        dir.join("instance-status.json"),
        serde_json::to_vec(&status).unwrap(),
    )
    .unwrap();
    assert_eq!(
        f.call("N2SpaceLoading", &[&guid, OWNER]),
        format!("{guid}#false")
    );
}

#[test]
fn default_capacity_current_actor_and_platform_are_enforced() {
    let mut f = Fixture::new(false);
    let guid = f.login(OWNER, "Owner", &"ab".repeat(32));
    f.write_status(&f.status("full", "Nexus", 7777, 32));
    assert_eq!(
        f.call("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]),
        format!("{guid}#false#true")
    );
    let mut r = req(&[&guid, OWNER, "Login", "false", "", ""]);
    assert_eq!(
        lifecycle::handle_as(&f.state, "N2LoadSpace", &r, Some(VISITOR))
            .unwrap_err()
            .status,
        403
    );
    r.platform = "PS4".into();
    assert_eq!(
        lifecycle::handle(&f.state, "N2LoadSpace", &r)
            .unwrap_err()
            .status,
        403
    );
    f.state.fixed_time = Some(f.state.now() + 1.);
    character::handle(
        &f.state,
        "ChannelGUIDServlet",
        &req(&[OWNER, &"cd".repeat(32)]),
    )
    .unwrap();
    assert_eq!(
        f.error("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]),
        403
    );
}

#[test]
fn explicit_core_profile_requires_bilateral_scope_and_trusted_semantic_snapshot() {
    let mut f = Fixture::new(false);
    let guid = f.login(OWNER, "Owner", &"ab".repeat(32));
    let mut v = f.status("nexus-core", "Nexus", 7777, 0);
    v["protocol_complete"] = json!(false);
    v["game_ready"] = json!(false);
    v["readiness_scope"] = json!("nexus-core-v1");
    v["core_test_eligible"] = json!(true);
    v["networking_parity"] = json!("unproven");
    v["board_tables"] = json!(0);
    v["darts_tables"] = json!(0);
    f.write_status(&v);
    assert_eq!(
        f.error("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]),
        503
    );
    f.state.readiness_profile = Some("nexus-core-v1".into());
    f.call("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]);
    f.state.readiness_profile = Some("nonmini-semantic-v1".into());
    v["readiness_scope"] = json!("nonmini-semantic-v1");
    v["scene_registry_verified"] = json!(true);
    v["interaction_bridge_required"] = json!(true);
    v["interaction_registry_trusted"] = json!(true);
    v["housing_bound"] = json!(false);
    v["housing_owner"] = json!("");
    f.write_status(&v);
    assert_eq!(
        f.error("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]),
        503
    );
    fs::write(f.state.state_dir.join("instance-interactions.json"),serde_json::to_vec(&json!({"format_version":1,"generation":f.state.now(),"instances":[{"instance_id":"nexus-core","scene":"Nexus","trusted":true,"static_profile_available":true,"epoch":"test-fixture","static_entries":[],"furniture_entries":[],"ground_sig":[]}]})).unwrap()).unwrap();
    f.call("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]);
}

#[test]
fn managed_demand_provisions_home_reuses_pending_and_survives_reopen() {
    let mut f = Fixture::new(true);
    let guid = f.login(OWNER, "Owner", &"ab".repeat(32));
    let home:String=f.state.connection().unwrap().query_row("SELECT instance_id FROM housing_spaces WHERE owner_ps4_id=? AND logical_space_key='Home'",[OWNER],|r|r.get(0)).unwrap();
    assert!(home.starts_with("apt-"));
    assert!(!home.contains(OWNER));
    f.call("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]);
    let first: String = f
        .state
        .connection()
        .unwrap()
        .query_row(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?",
            [&guid],
            |r| r.get(0),
        )
        .unwrap();
    assert!(first.starts_with("pub-"));
    assert_eq!(
        f.call("N2SpaceLoading", &[&guid, OWNER]),
        format!("{guid}#false")
    );
    f.reopen();
    f.call("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]);
    let second: String = f
        .state
        .connection()
        .unwrap()
        .query_row(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?",
            [&guid],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(first, second);
    let desired = lifecycle::export_desired(&f.state).unwrap();
    let public = desired["instances"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["instance_id"] == first)
        .unwrap();
    assert_eq!(public["desired_state"], "running");
    assert_eq!(public["pending_reservations"], 1);
    let idle_home = desired["instances"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["instance_id"] == home)
        .unwrap();
    assert_eq!(idle_home["desired_state"], "stopped");
    f.write_status(&f.status(&first, "Nexus", 7777, 0));
    assert!(f.call("N2SpaceLoading", &[&guid, OWNER]).contains("#true#"));
    f.state.fixed_time = Some(f.state.now() + 31.);
    let desired = lifecycle::export_desired(&f.state).unwrap();
    assert_eq!(
        desired["instances"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["instance_id"] == first)
            .unwrap()["desired_state"],
        "stopped"
    );
}

#[test]
fn managed_existing_accounts_do_not_implicitly_gain_home_and_unknown_scenes_fail() {
    let mut f = Fixture::new(false);
    let guid = f.login(OWNER, "Owner", &"ab".repeat(32));
    f.state.fixed_time = Some(f.state.now() + 10.);
    f.state.managed_instances = true;
    f.state.readiness_profile = Some("nonmini-semantic-v1".into());
    lifecycle::initialize(&f.state).unwrap();
    character::handle(
        &f.state,
        "N2UserExist",
        &req(&["Owner", "v", "false", OWNER, "0"]),
    )
    .unwrap();
    assert_eq!(
        f.state
            .connection()
            .unwrap()
            .query_row(
                "SELECT default_home FROM managed_account_policy WHERE ps4_id=?",
                [OWNER],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
    assert_eq!(
        f.error("N2LoadSpace", &[&guid, OWNER, "Home", "false", "", ""]),
        403
    );
    assert_eq!(
        f.error("N2LoadSpace", &[&guid, OWNER, "BoardGame", "false", "", ""]),
        404
    );
}

#[test]
fn managed_home_visitors_need_live_owner_and_relation_and_blocks_revoke_renewal() {
    let f = Fixture::new(true);
    let owner_guid = f.login(OWNER, "Owner", &"ab".repeat(32));
    let visitor_guid = f.login(VISITOR, "Visitor", &"cd".repeat(32));
    let instance:String=f.state.connection().unwrap().query_row("SELECT instance_id FROM housing_spaces WHERE owner_ps4_id=? AND logical_space_key='Home'",[OWNER],|r|r.get(0)).unwrap();
    f.call(
        "N2LoadSpace",
        &[&owner_guid, OWNER, "Home", "false", "", ""],
    );
    f.write_status(&f.status(&instance, "Home", 7777, 0));
    f.call("N2SpaceLoading", &[&owner_guid, OWNER]);
    fs::write(f.state.state_dir.join("instance-presence.json"),serde_json::to_vec(&json!({"format_version":1,"generation":f.state.now(),"players":[{"guid":owner_guid,"status":3}]})).unwrap()).unwrap();
    assert_eq!(
        f.error(
            "N2LoadSpace",
            &[&visitor_guid, VISITOR, "Home", "false", "", &owner_guid]
        ),
        403
    );
    f.state
        .connection()
        .unwrap()
        .execute(
            "INSERT INTO relations VALUES(?,?,?,'friend')",
            params![VISITOR, "Owner", "StandaloneWindows"],
        )
        .unwrap();
    f.call(
        "N2LoadSpace",
        &[&visitor_guid, VISITOR, "Home", "false", "", &owner_guid],
    );
    assert!(f
        .call("N2SpaceLoading", &[&visitor_guid, VISITOR])
        .contains("#true#"));
    f.state
        .connection()
        .unwrap()
        .execute(
            "INSERT INTO relations VALUES(?,?,?,'block')",
            params![OWNER, "Visitor", "StandaloneWindows"],
        )
        .unwrap();
    assert_eq!(
        f.call("N2SpaceLoading", &[&visitor_guid, VISITOR]),
        format!("{visitor_guid}#false")
    );
    assert_eq!(
        f.state
            .connection()
            .unwrap()
            .query_row(
                "SELECT expires_at FROM instance_demands WHERE requester_guid=?",
                [visitor_guid],
                |r| r.get::<_, f64>(0)
            )
            .unwrap(),
        f.state.now()
    );
}

#[test]
fn expired_managed_poll_cannot_revive_above_thirty_two_reserved_slots() {
    let f = Fixture::new(true);
    let guid = f.login(OWNER, "Owner", &"ab".repeat(32));
    f.call("N2LoadSpace", &[&guid, OWNER, "Login", "false", "", ""]);
    let instance: String = f
        .state
        .connection()
        .unwrap()
        .query_row(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?",
            [&guid],
            |r| r.get(0),
        )
        .unwrap();
    {
        let mut db = f.state.connection().unwrap();
        let tx = db.transaction().unwrap();
        tx.execute(
            "UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
            params![f.state.now() - 1., guid],
        )
        .unwrap();
        for i in 0..32 {
            let id = format!("7656119800001{i:04}");
            let g = format!("{i:032x}");
            tx.execute("INSERT INTO profiles(ps4_id,username,platform,created_at) VALUES(?,?,'StandaloneWindows',?)",params![id,format!("Reservation {i}"),f.state.now()]).unwrap();
            tx.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                params![g, id, f.state.now()],
            )
            .unwrap();
            tx.execute(
                "INSERT INTO instance_demands VALUES(?,?,?,'Nexus','','pending',?,?,?)",
                params![
                    g,
                    instance,
                    "Nexus",
                    f.state.now(),
                    f.state.now() + 15.,
                    f.state.now()
                ],
            )
            .unwrap();
        }
        tx.commit().unwrap();
    }
    f.write_status(&f.status(&instance, "Nexus", 7777, 0));
    assert_eq!(
        f.call("N2SpaceLoading", &[&guid, OWNER]),
        format!("{guid}#false")
    );
    assert_eq!(
        f.state
            .connection()
            .unwrap()
            .query_row(
                "SELECT expires_at FROM instance_demands WHERE requester_guid=?",
                [&guid],
                |r| r.get::<_, f64>(0)
            )
            .unwrap(),
        f.state.now() - 1.
    );
}
