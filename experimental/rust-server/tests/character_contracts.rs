//! Offline persistence and Python-handler conformance. These tests do not run a
//! native client and cannot establish native acceptance of the replacement.
use nebula_preserved_server::{
    character,
    state::State,
    wire::{session_guid, Request},
};
use rusqlite::params;
use serde_json::{json, Value};
use std::{fs, path::PathBuf};
use tempfile::TempDir;

const ACCOUNT: &str = "76561198000000001";
struct Fixture {
    _dir: TempDir,
    root: PathBuf,
    protocol: PathBuf,
    state: State,
}
impl Fixture {
    fn new() -> Self {
        let base = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("test-state");
        fs::create_dir_all(&base).unwrap();
        let dir = tempfile::Builder::new()
            .prefix("character-")
            .tempdir_in(&base)
            .unwrap();
        let root = dir.path().to_path_buf();
        let protocol = root.join("protocol");
        fs::create_dir(&protocol).unwrap();
        let fixtures: Value =
            serde_json::from_str(include_str!("character_catalog_fixtures.json")).unwrap();
        for (name, body) in fixtures.as_object().unwrap() {
            fs::write(protocol.join(name), serde_json::to_vec(body).unwrap()).unwrap();
        }
        let mut state = State::open(&root.join("state"), &protocol).unwrap();
        state.fixed_time = Some(1_700_000_000.0);
        Self {
            _dir: dir,
            root,
            protocol,
            state,
        }
    }
    fn reopen(&mut self) {
        let mut state = State::open(&self.root.join("state"), &self.protocol).unwrap();
        state.fixed_time = self.state.fixed_time;
        self.state = state;
    }
    fn req(&self, route: &str, fields: &[&str]) -> String {
        character::handle(&self.state, route, &request(fields))
            .unwrap()
            .unwrap()
    }
    fn login(&self) -> String {
        self.req(
            "N2UserExist",
            &["Test persona", "version", "false", ACCOUNT, "45"],
        );
        let hash = "ab".repeat(32);
        self.req("ChannelGUIDServlet", &[ACCOUNT, &hash]);
        session_guid(ACCOUNT, &hash)
    }
    fn count(&self, table: &str) -> i64 {
        self.state
            .connection()
            .unwrap()
            .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0))
            .unwrap()
    }
}
fn request(fields: &[&str]) -> Request {
    Request {
        fields: fields.iter().map(|s| s.to_string()).collect(),
        platform: "StandaloneWindows".into(),
    }
}
fn status(state: &State, route: &str, fields: &[&str]) -> u16 {
    character::handle(state, route, &request(fields))
        .unwrap_err()
        .status
}
fn decoded_fields(text: &str) -> Vec<Value> {
    text.split('#')
        .map(|t| serde_json::from_str::<Value>(t).unwrap_or_else(|_| json!(t)))
        .collect()
}

#[test]
fn real_python_vectors_match_offline_handlers() {
    let fixture = Fixture::new();
    let document: Value =
        serde_json::from_str(include_str!("character_python_vectors.json")).unwrap();
    for (i, v) in document["vectors"].as_array().unwrap().iter().enumerate() {
        let r = Request {
            fields: v["fields"]
                .as_array()
                .unwrap()
                .iter()
                .map(|s| s.as_str().unwrap().to_string())
                .collect(),
            platform: v["platform"].as_str().unwrap().to_string(),
        };
        let route = v["route"].as_str().unwrap();
        let result = character::handle(&fixture.state, route, &r);
        if v["status"] == 200 {
            let actual = result
                .unwrap_or_else(|e| panic!("vector {i} {route}: {e}"))
                .unwrap();
            assert_eq!(
                decoded_fields(&actual),
                decoded_fields(v["response"].as_str().unwrap()),
                "vector {i} {route}"
            );
        } else {
            assert_eq!(
                result.unwrap_err().status as u64,
                v["status"].as_u64().unwrap(),
                "vector {i} {route}"
            );
        }
    }
}

#[test]
fn fresh_bootstrap_save_and_reopen_preserves_accounts_settings_and_selection() {
    let mut fixture = Fixture::new();
    let guid = fixture.login();
    assert_eq!(fixture.count("profiles"), 1);
    assert_eq!(fixture.count("presets"), 2);
    assert!(fixture.count("entitlements") > 0);
    fixture.req(
        "SavePlayerPref",
        &[
            &guid,
            "NameColorSelectedIndex",
            r#"{"x":0.125,"y":0.25,"z":0.5}"#,
        ],
    );
    fixture.req(
        "SavePlayerPref",
        &[&guid, "status", "literal # and rocket 🚀"],
    );
    fixture.req("SavePlayerPref", &[&guid, "PlatformOnly", "1"]);
    fixture.req(
        "ResetDefaultPresetServlet",
        &[&guid, ACCOUNT, "Second", "0"],
    );
    fixture.req(
        "RenamePresetServlet",
        &[&guid, ACCOUNT, "Second", "Persisted", "0"],
    );
    fixture.reopen();
    let prefs = fixture.req("GetPlayerPrefsServlet", &[&guid, ACCOUNT]);
    assert_eq!(prefs.split('#').count(), 5);
    assert!(prefs.contains("\\u0023"));
    assert!(prefs.contains("\\ud83d\\ude80"));
    let tokens: Vec<_> = prefs.split('#').collect();
    let data: Value = serde_json::from_str(tokens[2]).unwrap();
    assert_eq!(data["status"], "literal # and rocket 🚀");
    assert_eq!(data["NameColorSelectedIndex_g"], 0.25);
    assert_eq!(tokens[4], "1");
    let response = fixture.req("GetLastUsedPreset", &[&guid, ACCOUNT, &guid, "0"]);
    let fields: Vec<_> = response.split('#').collect();
    let preset: Value = serde_json::from_str(fields[3]).unwrap();
    assert_eq!(preset["presetname"], "Persisted");
    assert_eq!(preset["iduser"], ACCOUNT);
}

#[test]
fn malformed_json_and_mid_write_failure_leave_color_atomic() {
    let fixture = Fixture::new();
    let guid = fixture.login();
    for value in [
        "{",
        r#"{"x":1,"y":2}"#,
        r#"{"x":1,"y":2,"z":false}"#,
        r#"{"x":1,"y":2,"z":3,"w":4}"#,
        r#"{"x":1,"y":2,"z":1e99}"#,
    ] {
        assert_eq!(
            status(
                &fixture.state,
                "SavePlayerPref",
                &[&guid, "NameColorSelectedIndex", value]
            ),
            400
        );
    }
    assert_eq!(fixture.count("preferences"), 0);
    fixture.state.connection().unwrap().execute_batch("CREATE TRIGGER reject_green BEFORE INSERT ON preferences WHEN NEW.key='NameColorSelectedIndex_g' BEGIN SELECT RAISE(ABORT,'test interruption'); END;").unwrap();
    assert_eq!(
        status(
            &fixture.state,
            "SavePlayerPref",
            &[
                &guid,
                "NameColorSelectedIndex",
                r#"{"x":0.1,"y":0.2,"z":0.3}"#
            ]
        ),
        500
    );
    assert_eq!(
        fixture.count("preferences"),
        0,
        "red must roll back when green fails"
    );
}

#[test]
fn failed_bootstrap_rolls_back_profile_grants_and_both_gender_presets() {
    let fixture = Fixture::new();
    let mut doc: Value = serde_json::from_slice(
        &fs::read(fixture.protocol.join("avatar-asset-catalog.json")).unwrap(),
    )
    .unwrap();
    doc["items"]
        .as_array_mut()
        .unwrap()
        .retain(|v| v["gender"] != "FEMALE");
    fs::write(
        fixture.protocol.join("avatar-asset-catalog.json"),
        serde_json::to_vec(&doc).unwrap(),
    )
    .unwrap();
    assert_eq!(
        status(
            &fixture.state,
            "N2UserExist",
            &["Persona", "v", "false", ACCOUNT, "0"]
        ),
        404
    );
    for table in [
        "profiles",
        "profile_state",
        "entitlements",
        "presets",
        "preset_selection",
    ] {
        assert_eq!(fixture.count(table), 0, "failed bootstrap leaked {table}");
    }
}

#[test]
fn actor_platform_reserved_and_historical_writes_fail_closed() {
    let mut fixture = Fixture::new();
    let guid = fixture.login();
    let req = request(&[&guid, "status", "cross-account"]);
    assert_eq!(
        character::handle_as(
            &fixture.state,
            "SavePlayerPref",
            &req,
            Some("76561198000000002")
        )
        .unwrap_err()
        .status,
        403
    );
    let mut wrong_platform = request(&[&guid, ACCOUNT]);
    wrong_platform.platform = "PS4".into();
    assert_eq!(
        character::handle(&fixture.state, "GetPlayerPrefsServlet", &wrong_platform)
            .unwrap_err()
            .status,
        403
    );
    for (id, name) in [
        ("LOCAL-PRESERVATION-TEST-1", "Person"),
        (ACCOUNT, "[test] Preservation Client 1"),
    ] {
        assert_eq!(
            status(
                &fixture.state,
                "N2UserExist",
                &[name, "v", "false", id, "0"]
            ),
            403
        );
    }
    fixture.state.fixed_time = Some(1_700_000_001.0);
    fixture.req("ChannelGUIDServlet", &[ACCOUNT, &"cd".repeat(32)]);
    assert_eq!(
        status(&fixture.state, "SavePlayerPref", &[&guid, "status", "old"]),
        403
    );
    fixture.req("GetPlayerPrefsServlet", &[&guid, ACCOUNT]);
    assert_eq!(fixture.count("preferences"), 0);
}

#[test]
fn account_rename_collision_and_session_hash_checks_are_atomic() {
    let fixture = Fixture::new();
    fixture.login();
    fixture.req(
        "N2UserExist",
        &["Occupied", "v", "false", "76561198000000002", "0"],
    );
    assert_eq!(
        status(
            &fixture.state,
            "N2UserExist",
            &["Occupied", "v", "false", ACCOUNT, "0"]
        ),
        409
    );
    assert_eq!(
        fixture
            .state
            .connection()
            .unwrap()
            .query_row(
                "SELECT username FROM profiles WHERE ps4_id=?",
                [ACCOUNT],
                |r| r.get::<_, String>(0)
            )
            .unwrap(),
        "Test persona"
    );
    for hash in ["x".repeat(64), "AB".repeat(32), "a".repeat(63)] {
        assert_eq!(
            status(&fixture.state, "ChannelGUIDServlet", &[ACCOUNT, &hash]),
            400
        );
    }
    assert_eq!(fixture.count("sessions"), 1);
}

#[test]
fn wardrobe_allocation_validation_and_mutations_are_owned() {
    let fixture = Fixture::new();
    let guid = fixture.login();
    assert_eq!(
        status(
            &fixture.state,
            "SetUserInWardrobe",
            &[
                &guid,
                "unallocated",
                "1",
                "FEMALE",
                "unused",
                "status",
                "mood",
                "1",
                "1",
                "1",
                "2",
                "3",
                "4"
            ]
        ),
        403
    );
    assert_eq!(fixture.count("positions"), 0);
    assert_eq!(fixture.count("preferences"), 0);
    let db = fixture.state.connection().unwrap();
    db.execute(
        "INSERT INTO allocations VALUES(?,?,?,?,?,?)",
        params![
            guid,
            "local-instance",
            "local-space",
            "127.0.0.1",
            7777,
            fixture.state.now()
        ],
    )
    .unwrap();
    drop(db);
    fixture.req(
        "SetUserInWardrobe",
        &[
            &guid,
            "local-instance",
            "1",
            "FEMALE",
            "unused",
            "status",
            "mood",
            "0.1",
            "0.2",
            "0.3",
            "2",
            "3",
            "4",
        ],
    );
    assert!(fixture
        .req("Send_CheckIsInWardrobeServlet", &[&guid, ACCOUNT, &guid])
        .contains("#true#"));
    assert_eq!(
        status(
            &fixture.state,
            "WardrobeOptionItemServlet",
            &[&guid, ACCOUNT, "not-owned", "2"]
        ),
        404
    );
    let item: String = fixture
        .state
        .connection()
        .unwrap()
        .query_row(
            "SELECT item_id FROM entitlements WHERE ps4_id=? LIMIT 1",
            [ACCOUNT],
            |r| r.get(0),
        )
        .unwrap();
    fixture.req("WardrobeOptionItemServlet", &[&guid, ACCOUNT, &item, "2"]);
    fixture.req("RemoveInWardrobeServlet", &[&guid, ACCOUNT, "unused"]);
    assert!(fixture
        .req("Send_CheckIsInWardrobeServlet", &[&guid, ACCOUNT, &guid])
        .contains("#false#"));
}

#[test]
fn entrydata_save_requires_entitlements_and_rejects_truncation() {
    let fixture = Fixture::new();
    let guid = fixture.login();
    let vectors: Value =
        serde_json::from_str(include_str!("character_python_vectors.json")).unwrap();
    let v = vectors["vectors"]
        .as_array()
        .unwrap()
        .iter()
        .find(|v| v["route"] == "N2SavePreset")
        .unwrap();
    let payload = v["fields"][4].as_str().unwrap();
    assert_eq!(
        status(
            &fixture.state,
            "N2SavePreset",
            &[&guid, ACCOUNT, "Broken", "1", &payload[..payload.len() - 1]]
        ),
        400
    );
    fixture
        .state
        .connection()
        .unwrap()
        .execute(
            "DELETE FROM entitlements WHERE ps4_id=? AND gender='FEMALE'",
            [ACCOUNT],
        )
        .unwrap();
    assert_eq!(
        status(
            &fixture.state,
            "N2SavePreset",
            &[&guid, ACCOUNT, "Denied", "1", payload]
        ),
        403
    );
    assert_eq!(fixture.count("presets"), 2);
    let response = fixture.req("ShowPresetsServlet", &[&guid, ACCOUNT, "1"]);
    assert!(!response.contains("Denied"));
}

#[test]
fn bans_and_revocations_are_checked() {
    let mut fixture = Fixture::new();
    let guid = fixture.login();
    let db = fixture.state.connection().unwrap();
    db.execute("INSERT INTO moderation_accounts(ps4_id,ban_enabled,ban_expires_at,ban_reason) VALUES(?,1,?,?)",params![ACCOUNT,1_700_000_100i64,"Local ban"]).unwrap();
    drop(db);
    assert_eq!(
        status(&fixture.state, "GetPlayerPrefsServlet", &[&guid, ACCOUNT]),
        403
    );
    let login = fixture.req("N2UserExist", &["Test persona", "v", "false", ACCOUNT, "0"]);
    assert!(login.contains("#true#2023-11-14 22:15 UTC#Local ban"));
    fixture.state.fixed_time = Some(1_700_000_101.0);
    fixture.req("GetPlayerPrefsServlet", &[&guid, ACCOUNT]);
    fixture
        .state
        .connection()
        .unwrap()
        .execute(
            "INSERT INTO moderation_revoked_sessions VALUES(?,?,?,?,?)",
            params![
                guid,
                ACCOUNT,
                "test-revoke",
                1_700_000_101i64,
                "Local revoke"
            ],
        )
        .unwrap();
    assert_eq!(
        status(&fixture.state, "GetPlayerPrefsServlet", &[&guid, ACCOUNT]),
        403
    );
}

#[test]
fn mirror_wardrobe_suppression_requires_fresh_valid_snapshot_and_poses_match_allocation() {
    let fixture = Fixture::new();
    let guid = fixture.login();
    let other_id = "76561198000000002";
    fixture.req(
        "N2UserExist",
        &["Other player", "v", "false", other_id, "0"],
    );
    let hash = "ef".repeat(32);
    fixture.req("ChannelGUIDServlet", &[other_id, &hash]);
    let other_guid = session_guid(other_id, &hash);
    {
        let db = fixture.state.connection().unwrap();
        for g in [&guid, &other_guid] {
            db.execute(
                "INSERT INTO allocations VALUES(?,?,?,?,?,?)",
                params![
                    g,
                    "instance-one",
                    "space-one",
                    "127.0.0.1",
                    7777,
                    fixture.state.now()
                ],
            )
            .unwrap();
        }
    }
    fixture.req(
        "SetUserInWardrobe",
        &[
            &other_guid,
            "instance-one",
            "1",
            "MALE",
            "unused",
            "status",
            "mood",
            "1",
            "1",
            "1",
            "2",
            "3",
            "4",
        ],
    );
    assert!(fixture
        .req("GetAllInWardrobe", &[&guid, "instance-one"])
        .contains("Other player"));
    let path = fixture.state.state_dir.join("instance-avatar-state.json");
    let mut snapshot = json!({"format_version":1,"generation":fixture.state.now(),"instance_id":"instance-one","psidglobal":"space-one","listening":true,"wardrobe_delivery":"mirror_after_avatar_ready_v1","avatars":[]});
    fs::write(&path, serde_json::to_vec(&snapshot).unwrap()).unwrap();
    assert_eq!(
        fixture.req("GetAllInWardrobe", &[&guid, "instance-one"]),
        "OK#"
    );
    snapshot["generation"] = json!(fixture.state.now() - 16.0);
    fs::write(&path, serde_json::to_vec(&snapshot).unwrap()).unwrap();
    assert!(fixture
        .req("GetAllInWardrobe", &[&guid, "instance-one"])
        .contains("Other player"));
    fs::write(fixture.state.state_dir.join("instance-poses.json"),serde_json::to_vec(&json!({"format_version":1,"generation":fixture.state.now(),"instance_id":"instance-one","psidglobal":"space-one","poses":[{"ps4_id":other_id,"updated_at":fixture.state.now()+1.0,"position":{"x":99.0,"y":3.0,"z":4.0}},{"ps4_id":other_id,"updated_at":fixture.state.now(),"position":{"x":42.0,"y":3.0,"z":4.0}}]})).unwrap()).unwrap();
    // Existing position has the same timestamp, so an older/equal observation
    // cannot displace it. Move persisted time back before testing a new pose.
    fixture
        .state
        .connection()
        .unwrap()
        .execute(
            "UPDATE positions SET updated_at=updated_at-1 WHERE ps4_id=?",
            [other_id],
        )
        .unwrap();
    let response = fixture.req("GetPresetGameServlet", &[&guid, ACCOUNT, &other_guid]);
    let fields: Vec<_> = response.split('#').collect();
    let pos: Value = serde_json::from_str(fields[5]).unwrap();
    assert_eq!(pos["lastPosition_x"], 42.0);
}
