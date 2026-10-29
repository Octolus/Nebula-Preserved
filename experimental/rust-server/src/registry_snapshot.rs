//! Trusted interaction/housing publication from authored protocol metadata.
//! Port of backend/interaction_registry.py and HousingService.export_bindings.
//! This module never opens game assets, starts a process, or invents runtime IDs.
use crate::{
    error::{Error, Result},
    state::State,
};
use rusqlite::OptionalExtension;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    sync::{Arc, Mutex, OnceLock},
    time::SystemTime,
};
const PUBLIC: &[&str] = &["Nexus", "LeafPark", "Beach", "Cinema"];
const PERSONAL: &[&str] = &[
    "Home",
    "Greenhouse",
    "Waterfall",
    "StarCrawlers",
    "BlueWaveHideout",
    "DressingRoom",
    "CutteridgeEstate",
    "TheMoonlightRoom",
    "LeChalet",
    "LakeApartment",
    "SereneGarden",
    "WoodlandClearing",
    "TheNebulian",
    "SorcerersEyrie",
    "ZeroDistrictDen",
    "CampSilverLake",
    "FlyingDevice",
    "Deadquarters",
    "HollyridgeEstate",
    "WinterSnowGlobe",
    "TokyoApartment",
    "NebuHouse",
    "WestValleyApartment",
    "WhisperingHillsMansion",
    "CliffApartment",
    "TheCrypt",
    "ForgottenStation",
    "GreekSummerHouse",
    "MountainHideout",
    "GingerbreadHouse",
    "WindMillFarmHouse",
];
const DYNAMIC: &[&str] = &["CampSilverLake", "CutteridgeEstate", "SorcerersEyrie1"];
#[derive(Clone)]
struct Binding {
    instance: String,
    scene: String,
    owner: String,
    logical: String,
}
#[derive(Clone)]
struct Profile {
    available: bool,
    bundle: String,
    entries: Vec<Value>,
}
struct Manifests {
    bridge_hash: String,
    static_hash: String,
    furniture_hash: String,
    anchored: bool,
    profiles: BTreeMap<String, Profile>,
    furniture: BTreeMap<String, Value>,
}
struct ManifestCache {
    stamps: Vec<Option<(u64, SystemTime)>>,
    value: Arc<Manifests>,
}
static MANIFESTS: OnceLock<Mutex<BTreeMap<PathBuf, ManifestCache>>> = OnceLock::new();
struct InstanceCache {
    fingerprint: String,
    value: Value,
}
static INSTANCES: OnceLock<Mutex<BTreeMap<(PathBuf, String), InstanceCache>>> = OnceLock::new();
fn safe_instance(v: &str) -> bool {
    !v.is_empty()
        && v.len() <= 128
        && v.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn string<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap_or("")
}
fn hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
fn small(path: &Path, max: u64) -> Result<Vec<u8>> {
    if path.symlink_metadata()?.file_type().is_symlink() {
        return Err(Error::bad("linked_registry_snapshot_path"));
    }
    let m = path.metadata()?;
    if m.len() == 0 || m.len() > max {
        return Err(Error::bad("registry_snapshot_size"));
    }
    Ok(fs::read(path)?)
}
fn ascii_quote(v: &str, out: &mut String) {
    use std::fmt::Write;
    out.push('"');
    for c in v.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{0008}' => out.push_str("\\b"),
            '\u{000c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c < ' ' || c >= '\u{007f}' => {
                let mut units = [0; 2];
                for unit in c.encode_utf16(&mut units) {
                    let _ = write!(out, "\\u{unit:04x}");
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}
// _digest uses Python ensure_ascii/separators/sort_keys. Unlike HTTP wire JSON,
// a literal '#' is not escaped. Float spelling reuses the verified wire codec.
fn canonical(v: &Value) -> Result<String> {
    fn encode(v: &Value, out: &mut String) -> Result<()> {
        match v {
            Value::Null => out.push_str("null"),
            Value::Bool(v) => out.push_str(if *v { "true" } else { "false" }),
            Value::Number(_) => out.push_str(&crate::wire::json_field(v)?),
            Value::String(v) => ascii_quote(v, out),
            Value::Array(v) => {
                out.push('[');
                for (i, e) in v.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    encode(e, out)?;
                }
                out.push(']');
            }
            Value::Object(v) => {
                out.push('{');
                let sorted: BTreeMap<_, _> = v.iter().collect();
                for (i, (k, e)) in sorted.into_iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    ascii_quote(k, out);
                    out.push(':');
                    encode(e, out)?;
                }
                out.push('}');
            }
        }
        Ok(())
    }
    let mut out = String::new();
    encode(v, &mut out)?;
    Ok(out)
}
fn digest(v: &Value) -> Result<String> {
    Ok(hash(canonical(v)?.as_bytes()))
}
fn valid_path(v: &Value) -> bool {
    v.as_array()
        .is_some_and(|p| p.iter().all(|n| n.as_i64().is_some_and(|n| n >= 0)))
}
fn entry_sort(a: &Value, b: &Value) -> std::cmp::Ordering {
    let path = |v: &Value| {
        v["path"]
            .as_array()
            .map(|p| {
                p.iter()
                    .map(|n| n.as_i64().unwrap_or(-1))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default()
    };
    (
        string(a, "kind"),
        string(a, "anchor"),
        path(a),
        string(a, "class"),
        a["slot"].as_i64().unwrap_or(-1),
    )
        .cmp(&(
            string(b, "kind"),
            string(b, "anchor"),
            path(b),
            string(b, "class"),
            b["slot"].as_i64().unwrap_or(-1),
        ))
}
fn load(state: &State) -> Result<Arc<Manifests>> {
    let names = [
        "interaction-mapping-bridge.json",
        "housing-interaction-manifest.json",
        "static-interaction-manifest.json",
    ];
    let stamps = names
        .iter()
        .map(|name| {
            let path = state.protocol.join(name);
            match path.symlink_metadata() {
                Ok(m) => {
                    if m.file_type().is_symlink() {
                        return Err(Error::bad("linked_interaction_manifest"));
                    }
                    Ok(Some((m.len(), m.modified()?)))
                }
                Err(e)
                    if *name == "static-interaction-manifest.json"
                        && e.kind() == std::io::ErrorKind::NotFound =>
                {
                    Ok(None)
                }
                Err(e) => Err(e.into()),
            }
        })
        .collect::<Result<Vec<_>>>()?;
    let cache = MANIFESTS.get_or_init(|| Mutex::new(BTreeMap::new()));
    let key = state.protocol.as_ref().clone();
    if let Some(value) = cache
        .lock()
        .map_err(|_| Error::bad("registry_manifest_cache_unavailable"))?
        .get(&key)
        .filter(|v| v.stamps == stamps)
        .map(|v| v.value.clone())
    {
        return Ok(value);
    }
    let value = Arc::new(load_uncached(state)?);
    cache
        .lock()
        .map_err(|_| Error::bad("registry_manifest_cache_unavailable"))?
        .insert(
            key,
            ManifestCache {
                stamps,
                value: value.clone(),
            },
        );
    Ok(value)
}
fn load_uncached(state: &State) -> Result<Manifests> {
    let bridge = small(
        &state.protocol.join("interaction-mapping-bridge.json"),
        8 * 1024 * 1024,
    )?;
    let furniture_bytes = small(
        &state.protocol.join("housing-interaction-manifest.json"),
        16 * 1024 * 1024,
    )?;
    let furniture_doc: Value = serde_json::from_slice(&furniture_bytes)?;
    if furniture_doc["format_version"] != 1 || furniture_doc["effective_ground_item_count"] != 1035
    {
        return Err(Error::bad("unsupported_housing_interaction_manifest"));
    }
    let mut furniture = BTreeMap::new();
    for row in furniture_doc["items"]
        .as_array()
        .ok_or_else(|| Error::bad("housing_interaction_items_missing"))?
    {
        let id = row["item_id"]
            .as_str()
            .ok_or_else(|| Error::bad("housing_interaction_item_id"))?;
        furniture.insert(id.to_owned(), row.clone());
    }
    let static_path = state.protocol.join("static-interaction-manifest.json");
    let mut profiles = BTreeMap::new();
    let anchored = static_path.exists();
    let mut static_hash = String::new();
    if anchored {
        let bytes = small(&static_path, 32 * 1024 * 1024)?;
        static_hash = hash(&bytes);
        let doc: Value = serde_json::from_slice(&bytes)?;
        if doc["format_version"] != 1
            || doc["path_convention"] != "anchor_relative_excludes_root_v1"
        {
            return Err(Error::bad("unsupported_static_interaction_manifest"));
        }
        for scene in doc["scenes"]
            .as_array()
            .ok_or_else(|| Error::bad("static_interaction_scenes_missing"))?
        {
            let name = scene["scene"]
                .as_str()
                .ok_or_else(|| Error::bad("invalid_static_scene_row"))?;
            let entries = scene["entries"].as_array();
            let anchors = scene["active_anchor_counts"].as_object();
            let mut complete = matches!(
                string(scene, "status"),
                "complete_verified" | "verified_empty"
            ) && scene["unresolved"] == json!([])
                && entries.is_some()
                && anchors.is_some_and(|a| {
                    a.iter()
                        .all(|(k, v)| !k.is_empty() && v.as_i64() == Some(1))
                })
                && (scene["status"] != "verified_empty" || entries.is_some_and(|e| e.is_empty()));
            let mut converted = vec![];
            if complete {
                for e in entries.unwrap() {
                    if !e.is_object()
                        || !anchors.unwrap().contains_key(string(e, "root"))
                        || !matches!(string(e, "kind"), "generic" | "occupable")
                        || !matches!(string(e, "source"), "geometry" | "logic" | "event")
                        || !matches!(
                            string(e, "classification"),
                            "ordinary" | "deferred_minigame" | "separate_protocol"
                        )
                        || !valid_path(&e["path"])
                        || string(e, "class").is_empty()
                        || e["slot"].as_i64().is_none_or(|n| n < 0)
                        || e["extension_arity"]
                            .as_i64()
                            .is_none_or(|n| !(0..=32).contains(&n))
                    {
                        complete = false;
                        break;
                    }
                    converted.push(json!({"kind":e["kind"],"anchor":e["root"],"path":e["path"],"class":e["class"],"slot":e["slot"],"ground_index":-1,"item_id":"","classification":e["classification"],"extension_arity":e["extension_arity"]}));
                }
            }
            if complete {
                converted.sort_by(entry_sort);
            } else {
                converted.clear();
            }
            profiles.insert(
                name.into(),
                Profile {
                    available: complete,
                    bundle: string(scene, "bundle_sha256").into(),
                    entries: converted,
                },
            );
        }
    } else {
        let doc: Value = serde_json::from_slice(&bridge)?;
        for row in doc["static_registry"]["profiles"]
            .as_array()
            .ok_or_else(|| Error::bad("bridge_static_profiles_missing"))?
        {
            let scene = string(row, "scene");
            if !DYNAMIC.contains(&scene) {
                return Err(Error::bad("unknown_reviewed_static_scene"));
            }
            // Legacy relative keys have an unresolved dynamic root and cannot
            // authorize any semantic runtime registration.
            profiles.insert(
                scene.into(),
                Profile {
                    available: false,
                    bundle: string(row, "bundle_sha256").into(),
                    entries: vec![],
                },
            );
        }
    }
    Ok(Manifests {
        bridge_hash: hash(&bridge),
        static_hash,
        furniture_hash: hash(&furniture_bytes),
        anchored,
        profiles,
        furniture,
    })
}
fn bindings(state: &State) -> Result<Vec<Binding>> {
    let db = state.connection()?;
    let mut q=db.prepare("SELECT h.instance_id,h.psidglobal,h.owner_ps4_id,h.logical_space_key,p.ps4_id FROM housing_spaces h LEFT JOIN profiles p ON p.ps4_id=h.owner_ps4_id ORDER BY h.instance_id")?;
    let rows = q
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, Option<String>>(4)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    rows.into_iter()
        .map(|(instance, scene, owner, logical, known)| {
            if known.is_none() {
                return Err(Error::new(
                    409,
                    "Housing binding owner has no local account",
                ));
            }
            let expected = if logical == "SorcerersEyrie" {
                "SorcerersEyrie1"
            } else {
                logical.as_str()
            };
            if !safe_instance(&instance)
                || !PERSONAL.contains(&logical.as_str())
                || scene != expected
            {
                return Err(Error::new(
                    409,
                    "Housing binding is not a case-exact shipped scene",
                ));
            }
            Ok(Binding {
                instance,
                scene,
                owner,
                logical,
            })
        })
        .collect()
}
fn instance(state: &State, m: &Manifests, b: &Binding) -> Result<Value> {
    let row: Option<(String, f64)> = {
        let db = state.connection()?;
        db.query_row(
            "SELECT layout_json,updated_at FROM housing_layouts WHERE instance_id=?",
            [&b.instance],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?
    };
    let fingerprint = digest(&json!([
        m.bridge_hash,
        m.static_hash,
        m.furniture_hash,
        b.scene,
        b.owner,
        row.as_ref().map(|r| &r.0),
        row.as_ref().map(|r| r.1)
    ]))?;
    let cache = INSTANCES.get_or_init(|| Mutex::new(BTreeMap::new()));
    let key = (state.state_dir.as_ref().clone(), b.instance.clone());
    if let Some(value) = cache
        .lock()
        .map_err(|_| Error::bad("registry_instance_cache_unavailable"))?
        .get(&key)
        .filter(|v| v.fingerprint == fingerprint)
        .map(|v| v.value.clone())
    {
        return Ok(value);
    }
    let value = build_instance(state, m, b, row)?;
    let mut cache = cache
        .lock()
        .map_err(|_| Error::bad("registry_instance_cache_unavailable"))?;
    if cache.len() >= 4096 && !cache.contains_key(&key) {
        return Err(Error::new(503, "registry_instance_cache_capacity"));
    }
    cache.insert(
        key,
        InstanceCache {
            fingerprint,
            value: value.clone(),
        },
    );
    Ok(value)
}
fn build_instance(
    _state: &State,
    m: &Manifests,
    b: &Binding,
    row: Option<(String, f64)>,
) -> Result<Value> {
    let profile = m.profiles.get(&b.scene);
    let dynamic = !m.anchored && DYNAMIC.contains(&b.scene.as_str());
    let available = profile.is_some_and(|p| p.available) && !dynamic;
    let static_entries = if available {
        profile.unwrap().entries.clone()
    } else {
        vec![]
    };
    let (layout, updated) = if let Some((text, t)) = row {
        if !t.is_finite() {
            return Err(Error::bad("invalid_layout_timestamp"));
        }
        (serde_json::from_str::<Value>(&text)?, t)
    } else {
        (Value::Null, 0.0)
    };
    let mut ground = vec![];
    let mut furniture = vec![];
    let mut errors = BTreeSet::new();
    if dynamic {
        errors.insert("static_dynamic_root_normalization_unresolved");
    } else if !available {
        errors.insert(if m.anchored {
            "static_interaction_manifest_unresolved"
        } else {
            "static_interaction_manifest_unavailable"
        });
    }
    let truthy = match &layout {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
        Value::String(v) => !v.is_empty(),
        Value::Number(n) => n.as_f64() != Some(0.0),
    };
    if truthy {
        if !layout.is_object() {
            return Err(Error::bad("invalid_housing_layout_object"));
        }
        let keys = [
            "aidasset",
            "aidasset_tx",
            "aidasset_ty",
            "aidasset_tz",
            "aidasset_r",
        ];
        if keys.iter().any(|k| !layout[*k].is_array()) {
            errors.insert("layout_arrays_missing");
        } else {
            let len = layout[keys[0]].as_array().unwrap().len();
            if keys
                .iter()
                .any(|k| layout[*k].as_array().unwrap().len() != len)
            {
                errors.insert("layout_arrays_mismatched");
            } else {
                let mut compact = 0;
                for source in 0..len {
                    let item = &layout["aidasset"][source];
                    if item == "null" {
                        continue;
                    }
                    let values: Vec<_> = keys[1..]
                        .iter()
                        .map(|k| layout[*k][source].as_f64())
                        .collect();
                    let known = item.as_str().and_then(|id| m.furniture.get(id));
                    if known.is_none() || values.iter().any(|v| v.is_none_or(|n| !n.is_finite())) {
                        errors.insert("untrusted_ground_item_or_transform");
                        compact += 1;
                        continue;
                    }
                    let known = known.unwrap();
                    let mut narrowed = [0.0; 4];
                    for (i, v) in values.iter().enumerate() {
                        let n = v.unwrap() as f32;
                        if !n.is_finite() {
                            return Err(Error::bad("ground_transform_float32_overflow"));
                        }
                        narrowed[i] = if n == 0.0 { 0.0 } else { n as f64 };
                    }
                    ground.push(json!({"item_id":item,"index":compact,"tx":narrowed[0],"ty":narrowed[1],"tz":narrowed[2],"r":narrowed[3]}));
                    if known["status"] == "interactive_verified" {
                        for component in known["interactions"]
                            .as_array()
                            .ok_or_else(|| Error::bad("furniture_interactions_missing"))?
                        {
                            if component["admission"] != "allow" {
                                continue;
                            }
                            furniture.push(json!({"kind":component["registry_kind"],"anchor":"","path":component["sibling_index_chain"],"class":component["class"],"slot":component["component_slot"],"ground_index":compact,"item_id":item,"classification":component["classification"],"extension_arity":component["extension_arity"]}));
                        }
                    } else if known["status"] != "noninteractive_verified_empty" {
                        errors.insert("layout_contains_unresolved_interaction_item");
                    }
                    compact += 1;
                }
            }
        }
    }
    let epoch = digest(
        &json!({"scene":b.scene,"static":static_entries,"ground_sig":ground,"furniture":furniture}),
    )?;
    Ok(
        json!({"instance_id":b.instance,"scene":b.scene,"owner_ps4_id":b.owner,"trusted":errors.is_empty(),"errors":errors.into_iter().collect::<Vec<_>>(),
        "static_profile_available":available,"static_bundle_sha256":profile.map_or("",|p|p.bundle.as_str()),"static_entries":static_entries,"ground_sig":ground,
        "furniture_entries":furniture,"layout_updated_at":updated,"epoch":epoch}),
    )
}
fn atomic(state: &State, name: &str, value: &Value) -> Result<()> {
    use std::io::Write;
    let root = state.state_dir.as_ref();
    if root.symlink_metadata()?.file_type().is_symlink() {
        return Err(Error::bad("linked_registry_root"));
    }
    let temp = root.join(format!(".{name}.{}.tmp", uuid::Uuid::new_v4().simple()));
    let mut f = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp)?;
    f.write_all(canonical(value)?.as_bytes())?;
    f.sync_all()?;
    drop(f);
    let result = replace(&temp, &root.join(name));
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}
/// Publish independent ownership and trusted semantic snapshots. Publication is
/// derived only from reviewed JSON metadata, durable layouts and actual status
/// descriptors. Invalid ownership/manifests fail without replacing authority.
pub fn publish(state: &State) -> Result<()> {
    let m = load(state)?;
    let houses = bindings(state)?;
    let binding_values:Vec<_>=houses.iter().map(|b|json!({"instance_id":b.instance,"psidglobal":b.scene,"owner_ps4_id":b.owner,"logical_space_key":b.logical})).collect();
    let mut rows: BTreeMap<String, Binding> = houses
        .into_iter()
        .map(|b| (b.instance.clone(), b))
        .collect();
    let root = state.state_dir.join("instances");
    if root.is_dir() {
        for entry in fs::read_dir(&root)?.flatten() {
            let path = entry.path();
            let id = entry.file_name().to_string_lossy().into_owned();
            if !safe_instance(&id)
                || !path.is_dir()
                || path.symlink_metadata()?.file_type().is_symlink()
                || rows.contains_key(&id)
            {
                continue;
            }
            let status = small(&path.join("instance-status.json"), 65536)
                .ok()
                .and_then(|bytes| {
                    let bytes = bytes.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(&bytes);
                    serde_json::from_slice::<Value>(bytes).ok()
                });
            if let Some(status) = status {
                let scene = string(&status, "psidglobal");
                if status["format_version"] == 1
                    && status["instance_id"] == id
                    && PUBLIC.contains(&scene)
                {
                    rows.insert(
                        id.clone(),
                        Binding {
                            instance: id,
                            scene: scene.into(),
                            owner: String::new(),
                            logical: String::new(),
                        },
                    );
                }
            }
        }
    }
    let mut instances = vec![];
    for b in rows.values() {
        instances.push(instance(state, &m, b)?);
    }
    let interactions = json!({"format_version":1,"generation":state.now(),"bridge_manifest_sha256":m.bridge_hash,"static_manifest_sha256":m.static_hash,"furniture_manifest_sha256":m.furniture_hash,"instances":instances});
    atomic(
        state,
        "instance-housing.json",
        &json!({"format_version":1,"generation":state.now(),"bindings":binding_values}),
    )?;
    atomic(state, "instance-interactions.json", &interactions)
}
fn snapshot(state: &State, name: &str, max: u64) -> Result<Value> {
    let bytes = small(&state.state_dir.join(name), max)?;
    let v: Value = serde_json::from_slice(&bytes)?;
    let age = state.now() - v["generation"].as_f64().unwrap_or(f64::NEG_INFINITY);
    if v["format_version"] != 1 || !(0.0..=15.0).contains(&age) {
        return Err(Error::bad("registry_snapshot_not_fresh"));
    }
    Ok(v)
}
fn valid_semantic_entries(entries: &Value, initial: bool) -> bool {
    let Some(entries) = entries.as_array() else {
        return false;
    };
    if entries.len() > 4096 {
        return false;
    }
    let mut keys = BTreeSet::new();
    for e in entries {
        if !matches!(string(e, "kind"), "generic" | "occupable")
            || e["anchor"].as_str().is_none_or(|v| initial == v.is_empty())
            || !valid_path(&e["path"])
            || string(e, "class").is_empty()
            || e["slot"].as_i64().is_none_or(|v| v < 0)
            || e["ground_index"].as_i64().is_none_or(|v| v < -1)
            || !e["item_id"].is_string()
            || e["extension_arity"]
                .as_i64()
                .is_none_or(|v| !(0..=32).contains(&v))
            || !matches!(
                string(e, "classification"),
                "ordinary" | "deferred_minigame" | "separate_protocol"
            )
        {
            return false;
        }
        let key = json!([
            e["kind"],
            e["anchor"],
            e["path"],
            e["class"],
            e["slot"],
            e["ground_index"],
            e["item_id"]
        ]);
        let Ok(key) = canonical(&key) else {
            return false;
        };
        if !keys.insert(key) {
            return false;
        }
    }
    true
}
/// Fields for the actual listener's status. They do not assert listening,
/// complete protocol parity, or a native UI test. `core_test_eligible` remains
/// false unless current DB ownership, metadata and fresh snapshots all agree.
pub fn descriptor_fields(state: &State, id: &str, space: &str) -> Result<Value> {
    if !safe_instance(id) {
        return Err(Error::bad("invalid_registry_instance"));
    }
    let mut out = json!({"scene_registry_verified":false,"interaction_bridge_required":state.readiness_profile.as_deref()==Some("nonmini-semantic-v1"),
        "interaction_registry_trusted":false,"housing_bound":false,"housing_owner":"","core_test_eligible":false});
    let m = load(state)?;
    let houses = bindings(state)?;
    let binding = houses.into_iter().find(|b| b.instance == id);
    let public = PUBLIC.contains(&space);
    let b = if let Some(b) = binding {
        if b.scene != space {
            return Err(Error::bad("housing_descriptor_scene_mismatch"));
        }
        b
    } else if public {
        Binding {
            instance: id.into(),
            scene: space.into(),
            owner: String::new(),
            logical: String::new(),
        }
    } else {
        return Ok(out);
    };
    let expected = instance(state, &m, &b)?;
    let root = match snapshot(state, "instance-interactions.json", 32 * 1024 * 1024) {
        Ok(v) => v,
        Err(_) => return Ok(out),
    };
    if root["bridge_manifest_sha256"] != m.bridge_hash
        || root["static_manifest_sha256"] != m.static_hash
        || root["furniture_manifest_sha256"] != m.furniture_hash
    {
        return Ok(out);
    }
    let Some(rows) = root["instances"].as_array() else {
        return Ok(out);
    };
    let matches: Vec<_> = rows.iter().filter(|v| v["instance_id"] == id).collect();
    if matches.len() != 1
        || *matches[0] != expected
        || expected["trusted"] != true
        || expected["static_profile_available"] != true
        || !valid_semantic_entries(&expected["static_entries"], true)
        || !valid_semantic_entries(&expected["furniture_entries"], false)
    {
        return Ok(out);
    }
    let entries = expected["static_entries"]
        .as_array()
        .ok_or_else(|| Error::bad("registry_static_entries_invalid"))?;
    let counts = (
        entries.len(),
        entries
            .iter()
            .filter(|v| v["classification"] == "ordinary")
            .count(),
        entries
            .iter()
            .filter(|v| v["classification"] == "deferred_minigame")
            .count(),
    );
    let mixed = match space {
        "CampSilverLake" => Some((9, 8, 1)),
        "CutteridgeEstate" => Some((5, 4, 1)),
        "SorcerersEyrie1" => Some((12, 1, 11)),
        _ => None,
    };
    if mixed.is_some_and(|v| v != counts) {
        return Ok(out);
    }
    if !public {
        let housing = match snapshot(state, "instance-housing.json", 4 * 1024 * 1024) {
            Ok(v) => v,
            Err(_) => return Ok(out),
        };
        let Some(rows) = housing["bindings"].as_array() else {
            return Ok(out);
        };
        let matches: Vec<_> = rows.iter().filter(|v| v["instance_id"] == id).collect();
        let value = json!({"instance_id":b.instance,"psidglobal":b.scene,"owner_ps4_id":b.owner,"logical_space_key":b.logical});
        if matches.len() != 1 || *matches[0] != value {
            return Ok(out);
        }
        out["housing_bound"] = json!(true);
        out["housing_owner"] = json!(b.owner);
    }
    out["scene_registry_verified"] = json!(true);
    out["interaction_registry_trusted"] = json!(true);
    out["registry_epoch"] = expected["epoch"].clone();
    out["registry_static_entries"] = json!(counts.0);
    out["registry_ordinary_entries"] = json!(counts.1);
    out["registry_deferred_entries"] = json!(counts.2);
    out["registry_furniture_entries"] =
        json!(expected["furniture_entries"].as_array().map_or(0, Vec::len));
    out["core_test_eligible"] = json!(match state.readiness_profile.as_deref() {
        Some("nonmini-semantic-v1") => true,
        Some("nonmini-core-v1") => mixed.is_none(),
        Some("nexus-core-v1") => space == "Nexus",
        _ => false,
    });
    Ok(out)
}
#[cfg(windows)]
fn replace(source: &Path, target: &Path) -> Result<()> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(old: *const u16, new: *const u16, flags: u32) -> i32;
    }
    let a: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let b: Vec<u16> = target.as_os_str().encode_wide().chain(Some(0)).collect();
    for attempt in 0..=6 {
        if unsafe { MoveFileExW(a.as_ptr(), b.as_ptr(), 1 | 8) } != 0 {
            return Ok(());
        }
        let error = std::io::Error::last_os_error();
        if attempt == 6 || !matches!(error.raw_os_error(), Some(5 | 32 | 33)) {
            return Err(error.into());
        }
        std::thread::sleep(std::time::Duration::from_millis(10 << attempt));
    }
    Err(Error::new(500, "Registry atomic publication failed"))
}
#[cfg(not(windows))]
fn replace(source: &Path, target: &Path) -> Result<()> {
    fs::rename(source, target)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn canonical_digest_matches_python_empty_epoch() {
        let v = json!({"scene":"Home","static":[],"ground_sig":[],"furniture":[]});
        assert_eq!(
            canonical(&v).unwrap(),
            "{\"furniture\":[],\"ground_sig\":[],\"scene\":\"Home\",\"static\":[]}"
        );
    }
    #[test]
    fn canonical_keeps_hash_and_escapes_unicode_without_aliasing_backslash() {
        assert_eq!(
            canonical(&json!({"z":"#é","a":"\\u0023"})).unwrap(),
            "{\"a\":\"\\\\u0023\",\"z\":\"#\\u00e9\"}"
        );
    }
}
