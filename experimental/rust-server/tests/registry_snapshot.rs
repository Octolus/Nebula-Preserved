use nebula_preserved_server::{registry_snapshot, state::State};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};
const NOW: f64 = 1_800_000_000.0;
fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}
fn write(path: &Path, v: &Value) {
    if let Some(p) = path.parent() {
        fs::create_dir_all(p).unwrap();
    }
    fs::write(path, serde_json::to_vec(v).unwrap()).unwrap();
}
fn read(state: &State, name: &str) -> Value {
    serde_json::from_slice(&fs::read(state.state_dir.join(name)).unwrap()).unwrap()
}
fn synthetic_protocol(dir: &Path) {
    fs::create_dir_all(dir).unwrap();
    write(
        &dir.join("interaction-mapping-bridge.json"),
        &json!({"static_registry":{"profiles":[]}}),
    );
    write(
        &dir.join("static-interaction-manifest.json"),
        &json!({"format_version":1,"path_convention":"anchor_relative_excludes_root_v1","scenes":[
        {"scene":"Home","status":"verified_empty","unresolved":[],"active_anchor_counts":{},"entries":[],"bundle_sha256":"home-reviewed"},
        {"scene":"Nexus","status":"verified_empty","unresolved":[],"active_anchor_counts":{},"entries":[],"bundle_sha256":"nexus-reviewed"},
        {"scene":"SorcerersEyrie1","status":"complete_verified","unresolved":[],"active_anchor_counts":{"logic":1},"entries":[],"bundle_sha256":"eyrie-reviewed"}]}),
    );
    write(
        &dir.join("housing-interaction-manifest.json"),
        &json!({"format_version":1,"effective_ground_item_count":1035,"items":[
        {"item_id":"chair","status":"interactive_verified","interactions":[{"admission":"allow","registry_kind":"occupable","sibling_index_chain":[1,0],"class":"NebulaSeat","component_slot":3,"classification":"ordinary","extension_arity":0}]},
        {"item_id":"table","status":"noninteractive_verified_empty","interactions":[]},
        {"item_id":"unknown","status":"unresolved","interactions":[]}]}),
    );
}
fn fixture(real: bool) -> (tempfile::TempDir, State) {
    let dir = tempfile::tempdir().unwrap();
    let protocol = if real {
        std::env::var_os("NEBULA_REFERENCE_PROTOCOL_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| root().join("../../protocol"))
    } else {
        let p = dir.path().join("protocol");
        synthetic_protocol(&p);
        p
    };
    let mut s = State::open(dir.path(), &protocol).unwrap();
    s.fixed_time = Some(NOW);
    s.readiness_profile = Some("nonmini-semantic-v1".into());
    s.connection().unwrap().execute("INSERT INTO profiles VALUES('registry-owner','Registry Owner','StandaloneWindows','MALE',?)",[NOW]).unwrap();
    (dir, s)
}
fn bind(s: &State, id: &str, logical: &str, scene: &str) {
    s.connection()
        .unwrap()
        .execute(
            "INSERT INTO housing_spaces VALUES(?,?,?,'registry-owner',?)",
            rusqlite::params![id, logical, scene, NOW],
        )
        .unwrap();
}
fn layout(s: &State, id: &str, v: &Value, updated: f64) {
    s.connection().unwrap().execute("INSERT INTO housing_layouts VALUES(?,?,?)ON CONFLICT(instance_id)DO UPDATE SET layout_json=excluded.layout_json,updated_at=excluded.updated_at",rusqlite::params![id,serde_json::to_string(v).unwrap(),updated]).unwrap();
}
fn row(s: &State, id: &str) -> Value {
    read(s, "instance-interactions.json")["instances"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["instance_id"] == id)
        .unwrap()
        .clone()
}

#[test]
fn empty_housing_binding_and_epoch_match_canonical_source_schema() {
    let (_dir, s) = fixture(false);
    bind(&s, "home-one", "Home", "Home");
    registry_snapshot::publish(&s).unwrap();
    assert_eq!(
        read(&s, "instance-housing.json"),
        json!({"format_version":1,"generation":NOW,"bindings":[{"instance_id":"home-one","psidglobal":"Home","owner_ps4_id":"registry-owner","logical_space_key":"Home"}]})
    );
    let r = row(&s, "home-one");
    assert_eq!(r["trusted"], true);
    assert_eq!(r["static_profile_available"], true);
    assert_eq!(r["ground_sig"], json!([]));
    assert_eq!(r["furniture_entries"], json!([]));
    let expected = hex::encode(Sha256::digest(
        b"{\"furniture\":[],\"ground_sig\":[],\"scene\":\"Home\",\"static\":[]}",
    ));
    assert_eq!(r["epoch"], expected);
    let d = registry_snapshot::descriptor_fields(&s, "home-one", "Home").unwrap();
    assert_eq!(d["core_test_eligible"], true);
    assert_eq!(d["housing_bound"], true);
    assert_eq!(d["housing_owner"], "registry-owner");
}

#[test]
fn ground_compaction_float32_and_duplicate_furniture_preserve_native_semantics() {
    let (_dir, s) = fixture(false);
    bind(&s, "home-one", "Home", "Home");
    layout(
        &s,
        "home-one",
        &json!({"aidasset":["null","chair","table","chair"],"aidasset_tx":[0,0.1,-0.0,4],"aidasset_ty":[0,2,0,5],"aidasset_tz":[0,3,0,6],"aidasset_r":[0,90,0,180]}),
        NOW - 1.0,
    );
    registry_snapshot::publish(&s).unwrap();
    let r = row(&s, "home-one");
    assert_eq!(r["trusted"], true);
    assert_eq!(r["ground_sig"].as_array().unwrap().len(), 3);
    assert_eq!(r["ground_sig"][0]["index"], 0);
    assert_eq!(r["ground_sig"][0]["tx"].as_f64().unwrap(), 0.1f32 as f64);
    assert_eq!(
        r["ground_sig"][1]["tx"].as_f64().unwrap().to_bits(),
        0.0f64.to_bits()
    );
    assert_eq!(r["furniture_entries"].as_array().unwrap().len(), 2);
    assert_eq!(r["furniture_entries"][0]["ground_index"], 0);
    assert_eq!(r["furniture_entries"][1]["ground_index"], 2);
    assert_eq!(r["furniture_entries"][0]["path"], json!([1, 0]));
    assert_eq!(r["furniture_entries"][0]["anchor"], "");
    let epoch = r["epoch"].clone();
    registry_snapshot::publish(&s).unwrap();
    assert_eq!(row(&s, "home-one")["epoch"], epoch);
    layout(
        &s,
        "home-one",
        &json!({"aidasset":["chair"],"aidasset_tx":[1],"aidasset_ty":[0],"aidasset_tz":[0],"aidasset_r":[0]}),
        NOW,
    );
    assert_eq!(
        registry_snapshot::descriptor_fields(&s, "home-one", "Home").unwrap()["core_test_eligible"],
        false
    );
    registry_snapshot::publish(&s).unwrap();
    assert_ne!(row(&s, "home-one")["epoch"], epoch);
}

#[test]
fn invalid_ground_layouts_publish_closed_reasons() {
    let (_dir, s) = fixture(false);
    bind(&s, "home-one", "Home", "Home");
    for (value, reason) in [
        (json!({"aidasset":[]}), "layout_arrays_missing"),
        (
            json!({"aidasset":["chair"],"aidasset_tx":[],"aidasset_ty":[],"aidasset_tz":[],"aidasset_r":[]}),
            "layout_arrays_mismatched",
        ),
        (
            json!({"aidasset":["forged"],"aidasset_tx":[0],"aidasset_ty":[0],"aidasset_tz":[0],"aidasset_r":[0]}),
            "untrusted_ground_item_or_transform",
        ),
        (
            json!({"aidasset":["unknown"],"aidasset_tx":[0],"aidasset_ty":[0],"aidasset_tz":[0],"aidasset_r":[0]}),
            "layout_contains_unresolved_interaction_item",
        ),
    ] {
        layout(&s, "home-one", &value, NOW);
        registry_snapshot::publish(&s).unwrap();
        let r = row(&s, "home-one");
        assert_eq!(r["trusted"], false);
        assert!(r["errors"].as_array().unwrap().iter().any(|r| r == reason));
        assert_eq!(
            registry_snapshot::descriptor_fields(&s, "home-one", "Home").unwrap()
                ["core_test_eligible"],
            false
        );
    }
}

#[test]
fn public_status_discovery_requires_exact_supported_scene_and_id() {
    let (_dir, s) = fixture(false);
    for (id, scene) in [
        ("public-one", "Nexus"),
        ("wrong-case", "nexus"),
        ("unsupported", "SteamPunk"),
    ] {
        write(
            &s.state_dir
                .join("instances")
                .join(id)
                .join("instance-status.json"),
            &json!({"format_version":1,"instance_id":id,"psidglobal":scene}),
        );
    }
    registry_snapshot::publish(&s).unwrap();
    let rows = read(&s, "instance-interactions.json");
    assert_eq!(rows["instances"].as_array().unwrap().len(), 1);
    assert_eq!(row(&s, "public-one")["owner_ps4_id"], "");
    let d = registry_snapshot::descriptor_fields(&s, "public-one", "Nexus").unwrap();
    assert_eq!(d["core_test_eligible"], true);
    assert_eq!(d["housing_bound"], false);
    assert_eq!(d["housing_owner"], "");
}

#[test]
fn changed_or_stale_snapshots_do_not_grant_readiness() {
    let (_dir, s) = fixture(false);
    bind(&s, "home-one", "Home", "Home");
    registry_snapshot::publish(&s).unwrap();
    let mut v = read(&s, "instance-interactions.json");
    v["instances"][0]["epoch"] = json!("forged");
    write(&s.state_dir.join("instance-interactions.json"), &v);
    assert_eq!(
        registry_snapshot::descriptor_fields(&s, "home-one", "Home").unwrap()["core_test_eligible"],
        false
    );
    registry_snapshot::publish(&s).unwrap();
    let mut v = read(&s, "instance-interactions.json");
    v["generation"] = json!(NOW - 16.0);
    write(&s.state_dir.join("instance-interactions.json"), &v);
    assert_eq!(
        registry_snapshot::descriptor_fields(&s, "home-one", "Home").unwrap()["core_test_eligible"],
        false
    );
    registry_snapshot::publish(&s).unwrap();
    let mut v = read(&s, "instance-housing.json");
    v["bindings"][0]["owner_ps4_id"] = json!("someone-else");
    write(&s.state_dir.join("instance-housing.json"), &v);
    assert_eq!(
        registry_snapshot::descriptor_fields(&s, "home-one", "Home").unwrap()["core_test_eligible"],
        false
    );
}

#[test]
fn ownership_scene_aliases_are_exact_and_mixed_counts_are_independent() {
    let (_dir, s) = fixture(false);
    bind(&s, "eyrie-one", "SorcerersEyrie", "SorcerersEyrie1");
    registry_snapshot::publish(&s).unwrap();
    let b = read(&s, "instance-housing.json");
    assert_eq!(b["bindings"][0]["logical_space_key"], "SorcerersEyrie");
    assert_eq!(b["bindings"][0]["psidglobal"], "SorcerersEyrie1");
    assert_eq!(row(&s, "eyrie-one")["trusted"], true);
    assert_eq!(
        registry_snapshot::descriptor_fields(&s, "eyrie-one", "SorcerersEyrie1").unwrap()
            ["core_test_eligible"],
        false
    );
    s.connection()
        .unwrap()
        .execute("UPDATE housing_spaces SET psidglobal='SorcerersEyrie'", [])
        .unwrap();
    assert!(registry_snapshot::publish(&s).is_err());
}

#[test]
fn actual_authored_metadata_admits_all_46_reviewed_scenes_with_exact_mixed_counts() {
    let (_dir, s) = fixture(true);
    let static_doc = s.catalog("static-interaction-manifest.json").unwrap();
    let scenes = static_doc["scenes"].as_array().unwrap();
    assert_eq!(scenes.len(), 46);
    for (i, scene) in scenes.iter().enumerate() {
        let name = scene["scene"].as_str().unwrap();
        let id = format!("reviewed-{i}");
        if [
            "Nexus",
            "LeafPark",
            "Beach",
            "Cinema",
            "Bowling",
            "Dome",
            "StoneLakeCastle",
            "Cube",
            "GhostTown",
            "TheNebulianOpenHouse",
            "ZeroDistrict",
            "NebuHouseOpenHouse",
            "WestValleyApartmentOpenHouse",
            "MedievalVillage",
            "SKL",
        ]
        .contains(&name)
        {
            write(
                &s.state_dir
                    .join("instances")
                    .join(&id)
                    .join("instance-status.json"),
                &json!({"format_version":1,"instance_id":id,"psidglobal":name}),
            );
        } else {
            bind(
                &s,
                &id,
                if name == "SorcerersEyrie1" {
                    "SorcerersEyrie"
                } else {
                    name
                },
                name,
            );
        }
    }
    registry_snapshot::publish(&s).unwrap();
    let doc = read(&s, "instance-interactions.json");
    assert_eq!(doc["instances"].as_array().unwrap().len(), 46);
    for (i, scene) in scenes.iter().enumerate() {
        let id = format!("reviewed-{i}");
        let name = scene["scene"].as_str().unwrap();
        let d = registry_snapshot::descriptor_fields(&s, &id, name).unwrap();
        assert_eq!(d["interaction_registry_trusted"], true, "{name}");
        assert_eq!(d["core_test_eligible"], true, "{name}");
        if name == "CampSilverLake" {
            assert_eq!(d["registry_static_entries"], 9);
            assert_eq!(d["registry_ordinary_entries"], 8);
            assert_eq!(d["registry_deferred_entries"], 1);
        }
        if name == "CutteridgeEstate" {
            assert_eq!(d["registry_static_entries"], 5);
            assert_eq!(d["registry_ordinary_entries"], 4);
            assert_eq!(d["registry_deferred_entries"], 1);
        }
        if name == "SorcerersEyrie1" {
            assert_eq!(d["registry_static_entries"], 12);
            assert_eq!(d["registry_ordinary_entries"], 1);
            assert_eq!(d["registry_deferred_entries"], 11);
        }
    }
}

#[test]
fn unavailable_static_manifest_cannot_fall_back_to_dynamic_guesses() {
    let (_dir, s) = fixture(false);
    let path = s.protocol.join("static-interaction-manifest.json");
    fs::remove_file(path).unwrap();
    write(
        &s.protocol.join("interaction-mapping-bridge.json"),
        &json!({"static_registry":{"profiles":[{"scene":"CampSilverLake","bundle_sha256":"legacy"}]}}),
    );
    bind(&s, "camp-one", "CampSilverLake", "CampSilverLake");
    registry_snapshot::publish(&s).unwrap();
    let r = row(&s, "camp-one");
    assert_eq!(r["static_profile_available"], false);
    assert_eq!(r["trusted"], false);
    assert_eq!(
        r["errors"],
        json!(["static_dynamic_root_normalization_unresolved"])
    );
}

#[test]
fn complete_snapshots_and_dynamic_epochs_match_actual_python_publishers() {
    let oracle: Value =
        serde_json::from_str(include_str!("registry_snapshot_oracle.json")).unwrap();
    assert_eq!(oracle["format_version"], 1);
    assert_eq!(oracle["fixed_time"], NOW);
    for case in oracle["cases"].as_array().unwrap() {
        let (_dir, s) = fixture(true);
        let name = case["name"].as_str().unwrap();
        for b in case["bindings"].as_array().unwrap() {
            bind(
                &s,
                b["instance_id"].as_str().unwrap(),
                b["logical_space_key"].as_str().unwrap(),
                b["psidglobal"].as_str().unwrap(),
            );
        }
        for (id, record) in case["layouts"].as_object().unwrap() {
            layout(
                &s,
                id,
                &record["layout"],
                record["updated_at"].as_f64().unwrap(),
            );
        }
        for status in case["public_statuses"].as_array().unwrap() {
            write(
                &s.state_dir
                    .join("instances")
                    .join(status["instance_id"].as_str().unwrap())
                    .join("instance-status.json"),
                status,
            );
        }
        registry_snapshot::publish(&s).unwrap();
        assert_eq!(
            read(&s, "instance-housing.json"),
            case["housing"],
            "{name}: complete housing snapshot"
        );
        let actual = read(&s, "instance-interactions.json");
        let expected = &case["interactions"];
        for key in [
            "format_version",
            "generation",
            "bridge_manifest_sha256",
            "static_manifest_sha256",
            "furniture_manifest_sha256",
        ] {
            assert_eq!(actual[key], expected[key], "{name}: root {key}");
        }
        let actual = actual["instances"].as_array().unwrap();
        let expected = expected["instances"].as_array().unwrap();
        assert_eq!(actual.len(), expected.len(), "{name}: instance count");
        for (actual, expected) in actual.iter().zip(expected) {
            assert_eq!(
                actual, expected,
                "{name}: complete instance row {}",
                expected["instance_id"]
            );
        }
    }
}
