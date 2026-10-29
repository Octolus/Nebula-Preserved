//! Fresh descriptor admission and durable instance demand. Runtime journals
//! express intent only; they cannot confer protocol readiness or home ownership.
use crate::{
    character,
    error::{Error, Result},
    services::{js, n, one, presence as raw_presence, rows, s},
    state::State,
    wire::Request,
};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde_json::{json, Value};
use std::{collections::HashMap, fs, io::Write, net::Ipv4Addr, path::Path};
pub const ROUTES: &[&str] = &["N2LoadSpace", "N2SpaceLoading", "spaceExistServlet"];
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
fn text(v: &str, max: usize) -> bool {
    !v.is_empty() && v.chars().count() <= max && !v.contains(['#', '\0', '/', '\\'])
}
fn instance_id(v: &str) -> bool {
    !v.is_empty()
        && v.len() <= 128
        && v.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn ipv4(v: &str, wildcard: bool) -> bool {
    v.parse::<Ipv4Addr>().is_ok_and(|a| {
        a.to_string() == v
            && ((wildcard && a.is_unspecified()) || (a.octets()[0] > 0 && a.octets()[0] < 224))
    })
}
fn small(path: &Path, max: u64) -> Option<Value> {
    let meta = fs::metadata(path).ok()?;
    if meta.len() > max {
        return None;
    }
    let b = fs::read(path).ok()?;
    let t = std::str::from_utf8(&b).ok()?.trim_start_matches('\u{feff}');
    serde_json::from_str(t).ok()
}
fn snapshot(state: &State, file: &str, key: &str, max: u64) -> Option<Value> {
    let doc = small(&state.state_dir.join(file), max)?;
    let t = doc["generation"].as_f64()?;
    if doc["format_version"] != 1
        || !(0.0..=15.0).contains(&(state.now() - t))
        || !doc[key].is_array()
    {
        return None;
    }
    Some(doc)
}
fn housing_descriptor(state: &State, value: &Value) -> bool {
    let Some(doc) = snapshot(state, "instance-housing.json", "bindings", 4 * 1024 * 1024) else {
        return false;
    };
    let matches: Vec<_> = doc["bindings"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|r| r["instance_id"] == value["instance_id"])
        .collect();
    if matches.len() != 1 {
        return false;
    }
    let b = matches[0];
    value["housing_bound"] == true
        && text(s(b, "owner_ps4_id"), 256)
        && value["housing_owner"] == b["owner_ps4_id"]
        && b["psidglobal"] == value["psidglobal"]
        && PERSONAL.contains(&s(b, "logical_space_key"))
}
fn semantic_registry(state: &State, value: &Value) -> bool {
    let Some(doc) = snapshot(
        state,
        "instance-interactions.json",
        "instances",
        32 * 1024 * 1024,
    ) else {
        return false;
    };
    let matches: Vec<_> = doc["instances"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|r| r["instance_id"] == value["instance_id"])
        .collect();
    if matches.len() != 1 {
        return false;
    }
    let r = matches[0];
    if r["scene"] != value["psidglobal"]
        || r["trusted"] != true
        || r["static_profile_available"] != true
        || s(r, "epoch").is_empty()
        || !r["static_entries"].is_array()
        || !r["furniture_entries"].is_array()
        || !r["ground_sig"].is_array()
    {
        return false;
    }
    let expected = match s(r, "scene") {
        "CampSilverLake" => Some((9, 8, 1)),
        "CutteridgeEstate" => Some((5, 4, 1)),
        "SorcerersEyrie1" => Some((12, 1, 11)),
        _ => None,
    };
    expected.is_none_or(|(total, ordinary, deferred)| {
        let entries = r["static_entries"].as_array().unwrap();
        entries.len() == total
            && entries
                .iter()
                .filter(|e| e["classification"] == "ordinary")
                .count()
                == ordinary
            && entries
                .iter()
                .filter(|e| e["classification"] == "deferred_minigame")
                .count()
                == deferred
    })
}
fn scope_matches(state: &State, v: &Value) -> bool {
    let scene = s(v, "psidglobal");
    match state.readiness_profile.as_deref() {
        Some("nexus-core-v1") => scene == "Nexus",
        Some(profile @ ("nonmini-core-v1" | "nonmini-semantic-v1")) => {
            if v["scene_registry_verified"] != true {
                return false;
            }
            if profile == "nonmini-semantic-v1"
                && (v["interaction_bridge_required"] != true
                    || v["interaction_registry_trusted"] != true
                    || !semantic_registry(state, v))
            {
                return false;
            }
            if PUBLIC.contains(&scene) {
                return v["housing_bound"] == false && v["housing_owner"] == "";
            }
            let permitted = if profile == "nonmini-core-v1" {
                PERSONAL.contains(&scene)
                    && !["CampSilverLake", "CutteridgeEstate", "SorcerersEyrie"].contains(&scene)
            } else {
                (PERSONAL.contains(&scene) && scene != "SorcerersEyrie")
                    || scene == "SorcerersEyrie1"
            };
            permitted && housing_descriptor(state, v)
        }
        _ => false,
    }
}
fn read_status(state: &State, path: &Path, expected: Option<&str>) -> Option<Value> {
    let v = small(path, 65536)?;
    if v["format_version"] != 1 || v["listening"] != true {
        return None;
    }
    let complete = v["protocol_complete"] == true
        && (v.get("game_ready").is_none() || v["game_ready"] == true);
    let core = scope_matches(state, &v)
        && state.readiness_profile.as_deref() == v["readiness_scope"].as_str()
        && state.readiness_profile.is_some()
        && v["core_test_eligible"] == true
        && v["listener_bound"] == true
        && v["game_ready"] == false
        && v["protocol_complete"] == false
        && v["networking_parity"] == "unproven"
        && ["board_tables", "darts_tables"]
            .iter()
            .all(|k| v[*k].as_i64() == Some(0));
    if !complete && !core {
        return None;
    }
    let heartbeat = v["heartbeat"].as_f64()?;
    if !(0.0..=15.0).contains(&(state.now() - heartbeat))
        || s(&v, "ip") != state.advertised_ip
        || !ipv4(s(&v, "ip"), false)
        || v["port"].as_u64().is_none_or(|p| p == 0 || p > 65535)
        || v.get("bind")
            .is_some_and(|b| !b.as_str().is_some_and(|s| ipv4(s, true)))
        || !instance_id(s(&v, "instance_id"))
        || expected.is_some_and(|id| id != s(&v, "instance_id"))
        || !text(s(&v, "psidglobal"), 128)
        || v["maxusers"].as_i64() != Some(32)
        || v["players"].as_i64().is_none_or(|p| !(0..=32).contains(&p))
    {
        return None;
    }
    Some(v)
}
pub(crate) fn all_ready(state: &State) -> Vec<Value> {
    let mut values = Vec::new();
    if let Some(v) = read_status(state, &state.state_dir.join("instance-status.json"), None) {
        values.push(v);
    }
    let registry = state.state_dir.join("instances");
    if let Ok(entries) = fs::read_dir(&registry) {
        let parent = registry.canonicalize().ok();
        let mut paths: Vec<_> = entries
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.is_dir())
            .collect();
        paths.sort();
        for path in paths {
            let Some(id) = path.file_name().and_then(|n| n.to_str()) else {
                continue;
            };
            if !instance_id(id)
                || path
                    .canonicalize()
                    .ok()
                    .and_then(|p| p.parent().map(Path::to_path_buf))
                    != parent
            {
                continue;
            }
            if let Some(v) = read_status(state, &path.join("instance-status.json"), Some(id)) {
                values.push(v);
            }
        }
    }
    let mut ids = HashMap::new();
    let mut endpoints = HashMap::new();
    for v in &values {
        *ids.entry(s(v, "instance_id").to_string()).or_insert(0) += 1;
        *endpoints
            .entry((s(v, "ip").to_string(), n(v, "port")))
            .or_insert(0) += 1;
    }
    values.retain(|v| {
        ids.get(s(v, "instance_id")) == Some(&1)
            && endpoints.get(&(s(v, "ip").to_string(), n(v, "port"))) == Some(&1)
    });
    values.sort_by(|a, b| {
        (n(a, "players"), s(a, "instance_id")).cmp(&(n(b, "players"), s(b, "instance_id")))
    });
    values
}
pub(crate) fn ready(
    state: &State,
    scene: Option<&str>,
    instance: Option<&str>,
    exclude: Option<&str>,
) -> Option<Value> {
    all_ready(state).into_iter().find(|v| {
        scene.is_none_or(|s_| s_ == s(v, "psidglobal"))
            && instance.is_none_or(|i| i == s(v, "instance_id"))
            && exclude.is_none_or(|i| i != s(v, "instance_id"))
    })
}

const MANAGED_SCHEMA:&str="CREATE TABLE IF NOT EXISTS managed_lifecycle_config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS managed_account_policy(ps4_id TEXT PRIMARY KEY REFERENCES profiles,default_home INTEGER NOT NULL CHECK(default_home IN (0,1)),policy_source TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS managed_instances(instance_id TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('public','personal')),psidglobal TEXT NOT NULL,owner_ps4_id TEXT REFERENCES profiles,logical_space_key TEXT,desired_state TEXT NOT NULL CHECK(desired_state IN ('running','stopped')),adopted_existing INTEGER NOT NULL CHECK(adopted_existing IN (0,1)),created_at REAL NOT NULL,updated_at REAL NOT NULL,CHECK((kind='public' AND owner_ps4_id IS NULL AND logical_space_key IS NULL) OR (kind='personal' AND owner_ps4_id IS NOT NULL AND logical_space_key IS NOT NULL)),UNIQUE(owner_ps4_id,logical_space_key));
CREATE TABLE IF NOT EXISTS instance_demands(requester_guid TEXT PRIMARY KEY REFERENCES sessions,instance_id TEXT NOT NULL REFERENCES managed_instances,psidglobal TEXT NOT NULL,requested_key TEXT NOT NULL,desired_owner_guid TEXT NOT NULL DEFAULT '',state TEXT NOT NULL CHECK(state IN ('pending','allocated','cancelled')),reserved_at REAL NOT NULL,expires_at REAL NOT NULL,updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS instance_demands_instance_state ON instance_demands(instance_id,state,expires_at);";
pub fn initialize(state: &State) -> Result<()> {
    if !state.managed_instances {
        return Ok(());
    }
    if state.readiness_profile.as_deref() != Some("nonmini-semantic-v1") {
        return Err(Error::bad(
            "Managed instances require nonmini-semantic-v1 readiness",
        ));
    }
    let db = state.connection()?;
    db.execute_batch(MANAGED_SCHEMA)?;
    db.execute(
        "INSERT OR IGNORE INTO managed_lifecycle_config VALUES('enabled_at',?)",
        [state.now().to_string()],
    )?;
    Ok(())
}
fn ensure_instance(
    state: &State,
    db: &Connection,
    id: &str,
    kind: &str,
    scene: &str,
    owner: Option<&str>,
    key: Option<&str>,
    adopted: bool,
) -> Result<()> {
    if !instance_id(id) || !text(scene, 128) {
        return Err(Error::bad("Invalid managed instance identity"));
    }
    if let Some(row) = one(
        db,
        "SELECT * FROM managed_instances WHERE instance_id=?",
        [id],
    )? {
        if s(&row, "kind") != kind
            || s(&row, "psidglobal") != scene
            || row["owner_ps4_id"].as_str() != owner
            || row["logical_space_key"].as_str() != key
        {
            return Err(Error::new(
                409,
                "Managed instance identity conflicts with stored authority",
            ));
        }
        return Ok(());
    }
    db.execute(
        "INSERT INTO managed_instances VALUES(?,?,?,?,?,'running',?,?,?)",
        params![
            id,
            kind,
            scene,
            owner,
            key,
            adopted,
            state.now(),
            state.now()
        ],
    )?;
    Ok(())
}
pub(crate) fn provision_account_in(state: &State, db: &Connection, id: &str) -> Result<()> {
    if !state.managed_instances {
        return Ok(());
    }
    let created: f64 = db.query_row(
        "SELECT created_at FROM profiles WHERE ps4_id=?",
        [id],
        |r| r.get(0),
    )?;
    let enabled: String = db.query_row(
        "SELECT value FROM managed_lifecycle_config WHERE key='enabled_at'",
        [],
        |r| r.get(0),
    )?;
    let enabled = enabled
        .parse::<f64>()
        .map_err(|_| Error::new(409, "Invalid lifecycle epoch"))?;
    let policy = one(
        db,
        "SELECT * FROM managed_account_policy WHERE ps4_id=?",
        [id],
    )?;
    let grant = policy
        .as_ref()
        .map(|p| n(p, "default_home") == 1)
        .unwrap_or(created >= enabled);
    if grant {
        let binding = one(
            db,
            "SELECT * FROM housing_spaces WHERE owner_ps4_id=? AND logical_space_key='Home'",
            [id],
        )?;
        let instance = if let Some(b) = binding {
            s(&b, "instance_id").to_string()
        } else {
            let instance = format!("apt-{}", uuid::Uuid::new_v4().simple());
            db.execute(
                "INSERT INTO housing_spaces VALUES(?,'Home','Home',?,?)",
                params![instance, id, state.now()],
            )?;
            instance
        };
        let binding = crate::services::housing_binding(db, &instance)?
            .ok_or_else(|| Error::new(409, "Default Home binding missing"))?;
        ensure_instance(
            state,
            db,
            &instance,
            "personal",
            s(&binding, "psidglobal"),
            Some(id),
            Some("Home"),
            !opaque_personal(&instance),
        )?;
    }
    if policy.is_none() {
        db.execute(
            "INSERT INTO managed_account_policy VALUES(?,?,?,?)",
            params![
                id,
                grant,
                if grant {
                    "managed_default_home_v1"
                } else {
                    "preexisting_before_managed_mode"
                },
                state.now()
            ],
        )?;
    }
    Ok(())
}
fn opaque_personal(id: &str) -> bool {
    id.strip_prefix("apt-").is_some_and(|s| {
        s.len() == 32
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}
fn exact(db: &Connection, guid: &str, instance: &str, scene: &str) -> Result<bool> {
    Ok(db.query_row(
        "SELECT EXISTS(SELECT 1 FROM allocations WHERE guid=? AND instance_id=? AND psidglobal=?)",
        params![guid, instance, scene],
        |r| r.get(0),
    )?)
}
fn presence(state: &State, db: &Connection) -> HashMap<String, i64> {
    let mut values = raw_presence(state, db);
    values.retain(|guid, _| character::session_db(db, guid, None, None, state.now()).is_ok());
    values
}
fn is_current(db: &Connection, guid: &str, now: f64) -> Result<bool> {
    let owner: Option<String> = db
        .query_row("SELECT ps4_id FROM sessions WHERE guid=?", [guid], |r| {
            r.get(0)
        })
        .optional()?;
    Ok(match owner {
        Some(id) => {
            character::ensure_allowed(db, &id, Some(guid), now).is_ok()
                && character::current_guid(db, &id)?.as_deref() == Some(guid)
        }
        None => false,
    })
}
fn resolve_binding(
    state: &State,
    db: &Connection,
    id: &str,
    key: &str,
    owner_guid: &str,
    pres: &HashMap<String, i64>,
) -> Result<Option<Value>> {
    if !owner_guid.is_empty() {
        let allocation=one(db,"SELECT a.instance_id,s.ps4_id FROM allocations a JOIN sessions s USING(guid) WHERE a.guid=?",[owner_guid])?;
        let b = if let Some(a) = allocation {
            let b = crate::services::housing_binding(db, s(&a, "instance_id"))?;
            if b.as_ref().is_some_and(|b| b["owner_ps4_id"] != a["ps4_id"]) {
                return Err(Error::new(
                    403,
                    "Invite target is not the personal-space owner",
                ));
            }
            b
        } else {
            None
        };
        let b =
            b.ok_or_else(|| Error::new(403, "Invite target is not the personal-space owner"))?;
        if !is_current(db, owner_guid, state.now())? || !pres.contains_key(owner_guid) {
            return Err(Error::new(
                503,
                "Invite target has no fresh current-session presence",
            ));
        }
        if key != s(&b, "logical_space_key") && key != s(&b, "psidglobal") {
            return Err(Error::new(
                409,
                "Invite target differs from requested personal space",
            ));
        }
        return Ok(Some(b));
    }
    let matches=rows(db,"SELECT instance_id FROM housing_spaces WHERE owner_ps4_id=? AND (logical_space_key=? OR psidglobal=?)",params![id,key,key])?;
    if matches.len() > 1 {
        return Err(Error::new(409, "Personal-space selection is ambiguous"));
    }
    if let Some(row) = matches.first() {
        return crate::services::housing_binding(db, s(row, "instance_id"));
    }
    if PERSONAL.contains(&key) {
        return Err(Error::new(
            403,
            "Personal space has no explicit local ownership binding",
        ));
    }
    let _ = state;
    Ok(None)
}
fn upsert_allocation(state: &State, db: &Connection, guid: &str, v: &Value) -> Result<()> {
    db.execute("INSERT INTO allocations VALUES(?,?,?,?,?,?) ON CONFLICT(guid) DO UPDATE SET instance_id=excluded.instance_id,psidglobal=excluded.psidglobal,ip=excluded.ip,port=excluded.port,allocated_at=excluded.allocated_at",params![guid,s(v,"instance_id"),s(v,"psidglobal"),s(v,"ip"),n(v,"port"),state.now()])?;
    Ok(())
}

pub fn handle(state: &State, route: &str, r: &Request) -> Result<Option<String>> {
    handle_as(state, route, r, None)
}
pub fn handle_as(
    state: &State,
    route: &str,
    r: &Request,
    actor: Option<&str>,
) -> Result<Option<String>> {
    if !ROUTES.contains(&route) {
        return Ok(None);
    }
    if state.managed_instances {
        initialize(state)?;
    }
    let mut conn = state.connection()?;
    {
        let imports = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::services::import_events(state, &imports)?;
        imports.commit()?;
    }
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let db = &*tx;
    let f = &r.fields;
    if route == "N2LoadSpace" {
        r.require(6)?;
        let username: Option<String> = db
            .query_row(
                "SELECT username FROM profiles WHERE ps4_id=?",
                [&f[1]],
                |r| r.get(0),
            )
            .optional()?;
        character::identity(&f[1], username.as_deref())?;
        if actor.is_some_and(|a| a != f[1]) {
            return Err(Error::new(
                403,
                "Authenticated account differs from request identity",
            ));
        }
        let bound: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM sessions WHERE guid=? AND ps4_id=?)",
            params![f[0], f[1]],
            |r| r.get(0),
        )?;
        let banned:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM moderation_accounts WHERE ps4_id=? AND ban_enabled=1 AND (ban_expires_at IS NULL OR ban_expires_at>?))",params![f[1],state.now()],|r|r.get(0))?;
        if bound && banned {
            tx.commit()?;
            return Ok(Some(format!("{}#true#false", f[0])));
        }
    }
    let count = if route == "N2LoadSpace" {
        6
    } else if route == "N2SpaceLoading" {
        2
    } else {
        5
    };
    let profile = character::identify(
        db,
        r,
        count,
        Some(1),
        actor,
        state.managed_instances || route == "N2LoadSpace",
        state.now(),
    )?;
    let result = if state.managed_instances {
        managed_handle(state, db, route, r, &profile)?
    } else {
        match route {
            "N2LoadSpace" => {
                let pres = presence(state, db);
                let b = resolve_binding(state, db, &profile.ps4_id, &f[2], &f[5], &pres)?;
                let scene = b
                    .as_ref()
                    .map(|b| s(b, "psidglobal"))
                    .unwrap_or(if f[2] == "Login" { "Nexus" } else { &f[2] });
                let mut forced = b.as_ref().map(|b| s(b, "instance_id").to_string());
                if !f[5].is_empty() {
                    let target = one(
                        db,
                        "SELECT instance_id,psidglobal FROM allocations WHERE guid=?",
                        [&f[5]],
                    )?
                    .ok_or_else(|| {
                        Error::new(503, "Requested player has no ready local instance")
                    })?;
                    if s(&target, "psidglobal") != scene
                        || forced
                            .as_ref()
                            .is_some_and(|id| id != s(&target, "instance_id"))
                    {
                        return Err(Error::new(
                            503,
                            "Requested player has no ready local instance",
                        ));
                    }
                    forced = Some(s(&target, "instance_id").to_string());
                }
                let v = ready(
                    state,
                    Some(scene),
                    forced.as_deref(),
                    if f[4].is_empty() { None } else { Some(&f[4]) },
                )
                .ok_or_else(|| {
                    Error::new(
                        503,
                        "No instance eligible for the configured readiness scope is registered",
                    )
                })?;
                if n(&v, "players") >= n(&v, "maxusers") {
                    format!("{}#false#true", f[0])
                } else {
                    upsert_allocation(state, db, &f[0], &v)?;
                    format!("{}#false#false", f[0])
                }
            }
            "N2SpaceLoading" => {
                let a = one(db, "SELECT * FROM allocations WHERE guid=?", [&f[0]])?;
                if let Some(v) = a.as_ref().and_then(|a| {
                    ready(
                        state,
                        Some(s(a, "psidglobal")),
                        Some(s(a, "instance_id")),
                        None,
                    )
                }) {
                    format!(
                        "{}#true#{}#{}#{}#{}",
                        f[0],
                        s(&v, "instance_id"),
                        s(&v, "psidglobal"),
                        s(&v, "ip"),
                        n(&v, "port")
                    )
                } else {
                    format!("{}#false", f[0])
                }
            }
            "spaceExistServlet" => space_exists(state, db, r)?,
            _ => unreachable!(),
        }
    };
    tx.commit()?;
    drop(conn);
    if state.managed_instances {
        export_desired(state)?;
    }
    Ok(Some(result))
}
fn space_exists(state: &State, db: &Connection, r: &Request) -> Result<String> {
    let f = &r.fields;
    let a = one(
        db,
        "SELECT instance_id FROM allocations WHERE guid=?",
        [&f[0]],
    )?;
    let v = a
        .as_ref()
        .and_then(|a| ready(state, Some(&f[4]), Some(s(a, "instance_id")), None));
    let exists = v
        .as_ref()
        .is_some_and(|v| f[2] == s(v, "ip") && f[3] == n(v, "port").to_string());
    Ok(format!("true#{}#{exists}", f[0]))
}

fn reservation_count(
    db: &Connection,
    instance: &str,
    now: f64,
    pres: &HashMap<String, i64>,
    exclude: Option<&str>,
) -> Result<usize> {
    let mut total = 0;
    for row in rows(db,"SELECT requester_guid,state,expires_at FROM instance_demands WHERE instance_id=? AND state IN ('pending','allocated')",[instance])?{let guid=s(&row,"requester_guid");if exclude==Some(guid)||row["expires_at"].as_f64().unwrap_or(0.)<=now||!is_current(db,guid,now)?{continue;}if s(&row,"state")=="pending"||!pres.contains_key(guid){total+=1;}}
    Ok(total)
}
fn present_count(
    db: &Connection,
    instance: &str,
    scene: &str,
    pres: &HashMap<String, i64>,
    exclude: Option<&str>,
) -> Result<usize> {
    let mut total = 0;
    for guid in pres.keys() {
        if exclude != Some(guid.as_str()) && exact(db, guid, instance, scene)? {
            total += 1;
        }
    }
    Ok(total)
}
fn poll_capacity(
    state: &State,
    db: &Connection,
    d: &Value,
    pres: &HashMap<String, i64>,
) -> Result<bool> {
    let guid = s(d, "requester_guid");
    let instance = s(d, "instance_id");
    let scene = s(d, "psidglobal");
    let reservations = reservation_count(db, instance, state.now(), pres, Some(guid))?;
    let present = present_count(db, instance, scene, pres, Some(guid))?;
    if let Some(v) = ready(state, Some(scene), Some(instance), None) {
        let self_present = pres.contains_key(guid) && exact(db, guid, instance, scene)?;
        Ok((n(&v, "players") - i64::from(self_present))
            .max(0)
            .max(present as i64)
            + (reservations as i64)
            < n(&v, "maxusers"))
    } else {
        Ok(present + reservations < 32)
    }
}
fn visitor_valid(
    state: &State,
    db: &Connection,
    d: &Value,
    id: &str,
    pres: &HashMap<String, i64>,
) -> Result<bool> {
    let b = crate::services::housing_binding(db, s(d, "instance_id"))?;
    let Some(b) = b else {
        return Ok(s(d, "desired_owner_guid").is_empty());
    };
    let owner = s(&b, "owner_ps4_id");
    let owner_guid = s(d, "desired_owner_guid");
    if owner_guid.is_empty() {
        return Ok(owner == id);
    }
    if character::current_guid(db, owner)?.as_deref() != Some(owner_guid)
        || !is_current(db, owner_guid, state.now())?
        || !pres.contains_key(owner_guid)
        || !exact(db, owner_guid, s(d, "instance_id"), s(d, "psidglobal"))?
    {
        return Ok(false);
    }
    // The managed access policy rechecks both block directions before using
    // an existing friendship or a correlated native invitation.
    let requester = one(
        db,
        "SELECT username,platform FROM profiles WHERE ps4_id=?",
        [id],
    )?
    .ok_or_else(|| Error::new(403, "Unknown visitor account"))?;
    let owner_profile = one(
        db,
        "SELECT username,platform FROM profiles WHERE ps4_id=?",
        [owner],
    )?
    .ok_or_else(|| Error::new(403, "Unknown home owner"))?;
    let blocked:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM relations WHERE kind='block' AND ((ps4_id=? AND target=? AND target_platform=?) OR (ps4_id=? AND target=? AND target_platform=?)))",params![id,s(&owner_profile,"username"),s(&owner_profile,"platform"),owner,s(&requester,"username"),s(&requester,"platform")],|r|r.get(0))?;
    if blocked {
        return Ok(false);
    }
    // Read-only invitation correlation is deliberately retained through demand
    // renewal; the world transport expires/clears its source request normally.
    let friends:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM relations WHERE kind='friend' AND ((ps4_id=? AND target=? AND target_platform=?) OR (ps4_id=? AND target=? AND target_platform=?)))",params![id,s(&owner_profile,"username"),s(&owner_profile,"platform"),owner,s(&requester,"username"),s(&requester,"platform")],|r|r.get(0))?;
    let guid = s(d, "requester_guid");
    let digest = crate::services::hash(&format!("{owner_guid}\0{guid}\06"));
    let pending = small(
        &state
            .state_dir
            .join("social-requests")
            .join(format!("{digest}.json")),
        8192,
    );
    let correlated = pending.as_ref().is_some_and(|p| {
        p["format_version"] == 1
            && p["source_guid"] == owner_guid
            && p["target_guid"] == guid
            && p["source_account"] == owner
            && p["target_account"] == id
            && p["type"] == 6
            && p["expires_at"].as_f64().is_some_and(|t| t > state.now())
    });
    Ok(friends || correlated)
}
fn upsert_demand(
    state: &State,
    db: &Connection,
    guid: &str,
    instance: &str,
    scene: &str,
    key: &str,
    owner_guid: &str,
) -> Result<()> {
    let now = state.now();
    db.execute("INSERT INTO instance_demands VALUES(?,?,?,?,?,'pending',?,?,?) ON CONFLICT(requester_guid) DO UPDATE SET instance_id=excluded.instance_id,psidglobal=excluded.psidglobal,requested_key=excluded.requested_key,desired_owner_guid=excluded.desired_owner_guid,state='pending',reserved_at=excluded.reserved_at,expires_at=excluded.expires_at,updated_at=excluded.updated_at",params![guid,instance,scene,key,owner_guid,now,now+15.,now])?;
    db.execute(
        "UPDATE managed_instances SET desired_state='running',updated_at=? WHERE instance_id=?",
        params![now, instance],
    )?;
    Ok(())
}
fn managed_handle(
    state: &State,
    db: &Connection,
    route: &str,
    r: &Request,
    p: &character::Profile,
) -> Result<String> {
    let f = &r.fields;
    let guid = &f[0];
    let now = state.now();
    let pres = presence(state, db);
    if route == "spaceExistServlet" {
        return space_exists(state, db, r);
    }
    if route == "N2SpaceLoading" {
        let Some(d) = one(
            db,
            "SELECT * FROM instance_demands WHERE requester_guid=?",
            [guid],
        )?
        else {
            return Ok(format!("{guid}#false"));
        };
        if s(&d, "state") == "cancelled" {
            return Ok(format!("{guid}#false"));
        }
        if !visitor_valid(state, db, &d, &p.ps4_id, &pres)? {
            db.execute(
                "UPDATE instance_demands SET expires_at=?,updated_at=? WHERE requester_guid=?",
                params![now, now, guid],
            )?;
            return Ok(format!("{guid}#false"));
        }
        if d["expires_at"].as_f64().unwrap_or(0.) <= now && !poll_capacity(state, db, &d, &pres)? {
            return Ok(format!("{guid}#false"));
        }
        db.execute(
            "UPDATE instance_demands SET expires_at=?,updated_at=? WHERE requester_guid=?",
            params![now + 15., now, guid],
        )?;
        let Some(v) = ready(
            state,
            Some(s(&d, "psidglobal")),
            Some(s(&d, "instance_id")),
            None,
        ) else {
            return Ok(format!("{guid}#false"));
        };
        if !poll_capacity(state, db, &d, &pres)? {
            return Ok(format!("{guid}#false"));
        }
        upsert_allocation(state, db, guid, &v)?;
        db.execute("UPDATE instance_demands SET state='allocated',expires_at=?,updated_at=? WHERE requester_guid=?",params![now+30.,now,guid])?;
        return Ok(format!(
            "{guid}#true#{}#{}#{}#{}",
            s(&v, "instance_id"),
            s(&v, "psidglobal"),
            s(&v, "ip"),
            n(&v, "port")
        ));
    }
    let b = resolve_binding(state, db, &p.ps4_id, &f[2], &f[5], &pres)?;
    let scene = b
        .as_ref()
        .map(|b| s(b, "psidglobal"))
        .unwrap_or(if f[2] == "Login" { "Nexus" } else { &f[2] });
    if b.is_none() && !PUBLIC.contains(&scene) {
        return Err(Error::new(
            404,
            "Scene is outside managed non-mini readiness",
        ));
    }
    let previous=one(db,"SELECT * FROM instance_demands WHERE requester_guid=? AND state IN ('pending','allocated')",[guid])?;
    let previous_live = previous
        .as_ref()
        .is_some_and(|d| d["expires_at"].as_f64().unwrap_or(0.) > now);
    let instance = if let Some(b) = b.as_ref() {
        let id = s(b, "instance_id");
        if !f[4].is_empty() && id == f[4] {
            return Err(Error::new(
                503,
                "Exact personal instance was excluded by the request",
            ));
        }
        ensure_instance(
            state,
            db,
            id,
            "personal",
            scene,
            Some(s(b, "owner_ps4_id")),
            Some(s(b, "logical_space_key")),
            !opaque_personal(id),
        )?;
        let admission = json!({"requester_guid":guid,"instance_id":id,"psidglobal":scene,"desired_owner_guid":f[5]});
        if !visitor_valid(state, db, &admission, &p.ps4_id, &pres)? {
            return Err(Error::new(
                403,
                "Personal-space visitor has no current invitation or friendship",
            ));
        }
        let same = previous_live
            && previous.as_ref().is_some_and(|d| {
                s(d, "instance_id") == id
                    && s(d, "psidglobal") == scene
                    && s(d, "desired_owner_guid") == f[5]
            });
        let players = if let Some(v) = ready(state, Some(scene), Some(id), None) {
            n(&v, "players").max(present_count(db, id, scene, &pres, None)? as i64)
        } else {
            0
        };
        let reserved = reservation_count(db, id, now, &pres, Some(guid))?;
        if !same && players + reserved as i64 >= 32 {
            return Ok(format!("{guid}#false#true"));
        }
        id.to_string()
    } else {
        let mut chosen = None;
        if previous_live {
            if let Some(d) = previous.as_ref() {
                if s(d,"psidglobal")==scene&&s(d,"desired_owner_guid").is_empty()&&s(d,"instance_id")!=f[4]&&one(db,"SELECT instance_id FROM managed_instances WHERE instance_id=? AND kind='public' AND psidglobal=?",params![s(d,"instance_id"),scene])?.is_some(){chosen=Some(s(d,"instance_id").to_string());}
            }
        }
        let ready_rows: Vec<_> = all_ready(state)
            .into_iter()
            .filter(|v| s(v, "psidglobal") == scene && s(v, "instance_id") != f[4])
            .collect();
        if chosen.is_none() {
            for v in &ready_rows {
                let id = s(v, "instance_id");
                let reservations = reservation_count(db, id, now, &pres, Some(guid))?;
                let present = present_count(db, id, scene, &pres, None)?;
                if n(v, "players").max(present as i64) + (reservations as i64) < n(v, "maxusers") {
                    ensure_instance(state, db, id, "public", scene, None, None, true)?;
                    chosen = Some(id.to_string());
                    break;
                }
            }
        }
        if chosen.is_none() {
            for row in rows(db,"SELECT * FROM managed_instances WHERE kind='public' AND psidglobal=? AND instance_id<>? ORDER BY instance_id",params![scene,f[4]])?{let id=s(&row,"instance_id");let v=ready_rows.iter().find(|v|s(v,"instance_id")==id);let reservations=reservation_count(db,id,now,&pres,Some(guid))?;let players=if let Some(v)=v{n(v,"players").max(present_count(db,id,scene,&pres,None)? as i64)}else{0};if players+(reservations as i64)<v.map(|v|n(v,"maxusers")).unwrap_or(32){chosen=Some(id.to_string());break;}}
        }
        if let Some(id) = chosen {
            id
        } else {
            let id = format!("pub-{}", uuid::Uuid::new_v4().simple());
            ensure_instance(state, db, &id, "public", scene, None, None, false)?;
            id
        }
    };
    upsert_demand(state, db, guid, &instance, scene, &f[2], &f[5])?;
    Ok(format!("{guid}#false#false"))
}
fn publish(path: &Path, v: &Value) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| Error::new(500, "Invalid snapshot path"))?;
    fs::create_dir_all(parent)?;
    let tmp = parent.join(format!(
        ".{}.{}.tmp",
        path.file_name().unwrap().to_string_lossy(),
        uuid::Uuid::new_v4().simple()
    ));
    let result = (|| {
        let mut f = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&tmp)?;
        f.write_all(js(v).as_bytes())?;
        f.sync_all()?;
        drop(f);
        fs::rename(&tmp, path)?;
        Ok(())
    })();
    if tmp.exists() {
        let _ = fs::remove_file(&tmp);
    }
    result
}
/// Main's supervisor consumes only this desired-state document. Its listener
/// publishes a separate instance-status.json once actual engine readiness holds.
pub fn export_desired(state: &State) -> Result<Value> {
    if !state.managed_instances {
        return Err(Error::bad("Managed instance lifecycle is disabled"));
    }
    initialize(state)?;
    let mut conn = state.connection()?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let db = &*tx;
    let now = state.now();
    let pres = presence(state, db);
    for d in rows(
        db,
        "SELECT * FROM instance_demands WHERE state IN ('pending','allocated')",
        [],
    )? {
        let guid = s(&d, "requester_guid");
        if !is_current(db, guid, now)?
            || (s(&d, "state") == "allocated"
                && !exact(db, guid, s(&d, "instance_id"), s(&d, "psidglobal"))?)
        {
            db.execute("UPDATE instance_demands SET state='cancelled',expires_at=?,updated_at=? WHERE requester_guid=?",params![now,now,guid])?;
        } else if s(&d, "state") == "allocated" && pres.contains_key(guid) {
            db.execute(
                "UPDATE instance_demands SET expires_at=?,updated_at=? WHERE requester_guid=?",
                params![now + 30., now, guid],
            )?;
        }
    }
    let mut values = Vec::new();
    for m in rows(
        db,
        "SELECT * FROM managed_instances ORDER BY instance_id",
        [],
    )? {
        let id = s(&m, "instance_id");
        let mut active = 0;
        let mut pending = 0;
        for d in rows(db,"SELECT requester_guid,state,expires_at FROM instance_demands WHERE instance_id=? AND state IN ('pending','allocated')",[id])?{let guid=s(&d,"requester_guid");if d["expires_at"].as_f64().unwrap_or(0.)>now&&is_current(db,guid,now)?{active+=1;if s(&d,"state")=="pending"||!pres.contains_key(guid){pending+=1;}}}
        let allocations = present_count(db, id, s(&m, "psidglobal"), &pres, None)?;
        let desired = if active > 0 || allocations > 0 {
            "running"
        } else {
            "stopped"
        };
        db.execute(
            "UPDATE managed_instances SET desired_state=?,updated_at=? WHERE instance_id=?",
            params![desired, now, id],
        )?;
        values.push(json!({"instance_id":id,"kind":m["kind"],"psidglobal":m["psidglobal"],"owner_ps4_id":s(&m,"owner_ps4_id"),"logical_space_key":s(&m,"logical_space_key"),"desired_state":desired,"active_demands":active,"pending_reservations":pending,"active_allocations":allocations,"adopted_existing":n(&m,"adopted_existing")!=0,"readiness_profile":"nonmini-semantic-v1"}));
    }
    let v = json!({"format_version":1,"generation":now,"managed":true,"instances":values});
    tx.commit()?;
    drop(conn);
    publish(&state.state_dir.join("desired-instances.json"), &v)?;
    Ok(v)
}
