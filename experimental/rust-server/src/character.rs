//! Account, settings and avatar contracts. These are local preservation policies,
//! not a claim that the retired service or an unmodified native client accepts them.
use crate::{
    error::{Error, Result},
    state::State,
    wire::Request,
};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde_json::{json, Map, Value};
use std::collections::{BTreeSet, HashSet};

pub const ROUTES: &[&str] = &[
    "STMGetUserInfo",
    "CheckerServlet",
    "CheckServerStatusServlet",
    "N2UserExist",
    "UserExistsServlet",
    "N2AddUser",
    "ChannelGUIDServlet",
    "GetIinitInfosNeededServlet",
    "GetPlayerPrefsServlet",
    "PlayerPrefsServlet",
    "GetCinemaFilmsServlet",
    "GetPurchases",
    "SavePlayerPref",
    "SetPlayerPrefsServlet",
    "InfoServlet",
    "N2AddUserOnline",
    "N2UpdateUserOnline",
    "GetLastUsedPreset",
    "GetLoadPresetByName",
    "GetPresetGameServlet",
    "PlayerLabelInfoServlet",
    "Send_CheckIsInWardrobeServlet",
    "SetUserInWardrobe",
    "GetAllInWardrobe",
    "N2SavePreset",
    "ShowPresetsServlet",
    "RemovePresetServlet",
    "RenamePresetServlet",
    "GetInfoServlet",
    "WardrobeOptionItemServlet",
    "ResetDefaultPresetServlet",
    "GetCompanionsServlet",
    "GetLocomotionsServlet",
    "InWardrobeCheckerServlet",
    "RemoveInWardrobeServlet",
    "GetrefusernameServlet",
];

#[derive(Clone, Debug)]
pub struct Profile {
    pub ps4_id: String,
    pub username: String,
    pub platform: String,
    pub gender: String,
}
pub fn canonical_platform(value: &str) -> Result<&'static str> {
    match value {
        "0" | "PS4" => Ok("PS4"),
        "1" | "StandaloneWindows" => Ok("StandaloneWindows"),
        _ => Err(Error::bad("Unsupported relation platform")),
    }
}
pub(crate) fn identity(id: &str, name: Option<&str>) -> Result<()> {
    if id.is_empty() || id.chars().count() > 128 || id.contains(['#', '\0']) {
        return Err(Error::bad("Invalid local account identifier"));
    }
    if id.to_lowercase().starts_with("local-preservation-test-")
        || name.is_some_and(|s| s.to_lowercase().starts_with("[test] preservation client "))
    {
        return Err(Error::new(403, "Local test identities are disabled"));
    }
    Ok(())
}
fn actor_matches(actor: Option<&str>, id: &str) -> Result<()> {
    if actor.is_some_and(|a| a != id) {
        return Err(Error::new(
            403,
            "Authenticated account differs from request identity",
        ));
    }
    Ok(())
}
fn profile(db: &Connection, id: &str) -> Result<Option<Profile>> {
    let p = db
        .query_row(
            "SELECT ps4_id,username,platform,gender FROM profiles WHERE ps4_id=?",
            [id],
            |r| {
                Ok(Profile {
                    ps4_id: r.get(0)?,
                    username: r.get(1)?,
                    platform: r.get(2)?,
                    gender: r.get(3)?,
                })
            },
        )
        .optional()?;
    if let Some(ref p) = p {
        identity(&p.ps4_id, Some(&p.username))?;
        canonical_platform(&p.platform)?;
    }
    Ok(p)
}
pub fn current_guid(db: &Connection, id: &str) -> Result<Option<String>> {
    Ok(db
        .query_row(
            "SELECT guid FROM sessions WHERE ps4_id=? ORDER BY created_at DESC,guid DESC LIMIT 1",
            [id],
            |r| r.get(0),
        )
        .optional()?)
}
pub fn ensure_allowed(db: &Connection, id: &str, guid: Option<&str>, now: f64) -> Result<()> {
    identity(id, None)?;
    let banned:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM moderation_accounts WHERE ps4_id=? AND ban_enabled=1 AND (ban_expires_at IS NULL OR ban_expires_at>?))",params![id,now],|r|r.get(0))?;
    if banned {
        return Err(Error::new(403, "Account is banned"));
    }
    if let Some(g) = guid {
        if g.len() != 32
            || !g
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        {
            return Err(Error::new(403, "Invalid session identifier"));
        }
        let revoked: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM moderation_revoked_sessions WHERE guid=?)",
            [g],
            |r| r.get(0),
        )?;
        if revoked {
            return Err(Error::new(403, "Session has been revoked"));
        }
    }
    Ok(())
}
pub(crate) fn session_db(
    db: &Connection,
    guid: &str,
    id: Option<&str>,
    platform: Option<&str>,
    now: f64,
) -> Result<Profile> {
    let owner: Option<String> = db
        .query_row("SELECT ps4_id FROM sessions WHERE guid=?", [guid], |r| {
            r.get(0)
        })
        .optional()?;
    let owner = owner.ok_or_else(|| Error::new(403, "Unknown or mismatched local session"))?;
    if id.is_some_and(|i| i != owner) {
        return Err(Error::new(403, "Unknown or mismatched local session"));
    }
    ensure_allowed(db, &owner, Some(guid), now)?;
    let p = profile(db, &owner)?.ok_or_else(|| Error::new(403, "Unknown local session profile"))?;
    if let Some(platform) = platform {
        if canonical_platform(platform)? != canonical_platform(&p.platform)? {
            return Err(Error::new(403, "Mismatched session platform"));
        }
    }
    Ok(p)
}
pub fn session(
    state: &State,
    guid: &str,
    id: Option<&str>,
    platform: Option<&str>,
) -> Result<Profile> {
    let conn = state.connection()?;
    session_db(&conn, guid, id, platform, state.now())
}
pub(crate) fn identify(
    db: &Connection,
    r: &Request,
    count: usize,
    id_index: Option<usize>,
    actor: Option<&str>,
    current: bool,
    now: f64,
) -> Result<Profile> {
    fields(r, count)?;
    let p = session_db(
        db,
        &r.fields[0],
        id_index.map(|i| r.fields[i].as_str()),
        Some(&r.platform),
        now,
    )?;
    actor_matches(actor, &p.ps4_id)?;
    if current && current_guid(db, &p.ps4_id)?.as_deref() != Some(r.fields[0].as_str()) {
        return Err(Error::new(
            403,
            "Historical session cannot change current account state",
        ));
    }
    Ok(p)
}
fn fields(r: &Request, count: usize) -> Result<&[String]> {
    if r.fields.len() != count {
        return Err(Error::bad(format!(
            "Expected {count} request fields, got {}",
            r.fields.len()
        )));
    }
    Ok(&r.fields)
}
fn numeric_gender(text: &str) -> Result<&'static str> {
    match text {
        "0" => Ok("MALE"),
        "1" => Ok("FEMALE"),
        _ => Err(Error::bad("Invalid numeric gender")),
    }
}
fn number(text: &str) -> Result<f64> {
    let n = text
        .trim()
        .parse::<f64>()
        .map_err(|_| Error::bad("Invalid invariant-culture number"))?;
    if !n.is_finite() || n.abs() > f32::MAX as f64 {
        return Err(Error::bad("Non-finite number"));
    }
    Ok(n)
}
/// ASCII JSON protects the outer hash framing, including literal hashes in values.
fn json_text(v: &Value) -> Result<String> {
    crate::wire::json_field(v)
}
fn defaults() -> Value {
    json!({"mood":"0","status":"","DisplayOthersName":1,"DisplayOthersStatus":1,"DisplayOthersMood":1,"DisplayMyName":1,"DisplayMyStatus":1,"DisplayMyMood":1,"MasterVolume":1.0,"Music":1.0,"Fx":1.0,"Ambient":1.0,"InvertYAxis":0,"ProfanityFilter":1,"ChatFontSize":20.0,"NameColorSelectedIndex_r":1.0,"NameColorSelectedIndex_g":1.0,"NameColorSelectedIndex_b":1.0,"spaceTutorialPhase":"0","editorTutorialPhase":"0","velocityCam":1.0,"notificationLoginFriend":1})
}
fn preferences(db: &Connection, id: &str) -> Result<Value> {
    let mut v = defaults();
    let mut s = db.prepare("SELECT key,value FROM preferences WHERE ps4_id=?")?;
    for row in s.query_map([id], |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
    })? {
        let (k, t) = row?;
        v[&k] = serde_json::from_str(&t)?;
    }
    Ok(v)
}
fn put_pref(db: &Connection, id: &str, key: &str, v: &Value) -> Result<()> {
    db.execute("INSERT INTO preferences VALUES(?,?,?) ON CONFLICT(ps4_id,key) DO UPDATE SET value=excluded.value",params![id,key,json_text(v)?])?;
    Ok(())
}
fn account(
    db: &Connection,
    id: &str,
    name: Option<&str>,
    platform: &str,
    now: f64,
    actor: Option<&str>,
) -> Result<Profile> {
    actor_matches(actor, id)?;
    identity(id, name)?;
    ensure_allowed(db, id, None, now)?;
    let platform = canonical_platform(platform)?;
    let old = profile(db, id)?;
    if let (Some(old), Some(name)) = (&old, name) {
        if old.username != name || canonical_platform(&old.platform)? != platform {
            let collision:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM profiles WHERE ps4_id<>? AND ((username=? AND platform=?) OR (username=? AND platform=?)))",params![id,old.username,canonical_platform(&old.platform)?,name,platform],|r|r.get(0))?;
            if collision {
                return Err(Error::new(
                    409,
                    "Local username/platform identity is ambiguous",
                ));
            }
            db.execute("INSERT OR IGNORE INTO relations(ps4_id,target,target_platform,kind) SELECT ps4_id,?,?,kind FROM relations WHERE target=? AND target_platform=?",params![name,platform,old.username,canonical_platform(&old.platform)?])?;
            db.execute(
                "DELETE FROM relations WHERE target=? AND target_platform=?",
                params![old.username, canonical_platform(&old.platform)?],
            )?;
        }
    }
    db.execute(
        "INSERT OR IGNORE INTO profiles(ps4_id,username,platform,created_at) VALUES(?,?,?,?)",
        params![id, name.unwrap_or(id), platform, now],
    )?;
    if let Some(name) = name {
        db.execute(
            "UPDATE profiles SET username=?,platform=? WHERE ps4_id=?",
            params![name, platform, id],
        )?;
    }
    db.execute(
        "INSERT OR IGNORE INTO profile_state(ps4_id) VALUES(?)",
        [id],
    )?;
    profile(db, id)?.ok_or_else(|| Error::new(500, "Account was not created"))
}
fn schemas(state: &State, gender: &str) -> Result<Vec<Value>> {
    let name = match gender {
        "MALE" => "JsonClasses.PresetMaleJson",
        "FEMALE" => "JsonClasses.PresetFemaleJson",
        _ => return Err(Error::bad("Unsupported avatar gender")),
    };
    let doc = state.catalog("bootstrap-response-contracts.json")?;
    doc["json_and_enum_declarations"]
        .as_array()
        .and_then(|a| {
            a.iter()
                .find(|r| r["name"] == name || r["full_name"] == name)
        })
        .and_then(|r| r["fields"].as_array())
        .cloned()
        .ok_or_else(|| Error::new(501, "Avatar schema is unavailable"))
}
fn validate_preset(state: &State, v: &Value, gender: &str) -> Result<()> {
    let o = v
        .as_object()
        .ok_or_else(|| Error::bad("Invalid preset type"))?;
    let fields = schemas(state, gender)?;
    if o.len() != fields.len()
        || fields
            .iter()
            .any(|f| !o.contains_key(f["name"].as_str().unwrap_or("")))
    {
        return Err(Error::bad(
            "Preset does not contain every recovered field exactly once",
        ));
    }
    for f in fields {
        let key = f["name"]
            .as_str()
            .ok_or_else(|| Error::new(501, "Invalid avatar schema"))?;
        let kind = f["type_and_modifiers"]
            .as_str()
            .unwrap_or("")
            .trim_start_matches("public ");
        let valid = match kind {
            "string" => v[key].is_null() || v[key].is_string(),
            "float" => v[key]
                .as_f64()
                .is_some_and(|n| n.is_finite() && n.abs() <= f32::MAX as f64),
            _ => return Err(Error::new(501, "Unreconstructed preset field type")),
        };
        if !valid {
            return Err(Error::bad(format!("Invalid preset field {key}")));
        }
    }
    Ok(())
}
fn neutral(state: &State, id: &str, gender: &str, name: &str) -> Result<(Value, Value, Value)> {
    let file = match gender {
        "MALE" => "avatar-neutral-male.json",
        "FEMALE" => "avatar-neutral-female.json",
        _ => return Err(Error::bad("Unsupported avatar gender")),
    };
    let mut preset = state.catalog(file)?;
    preset["iduser"] = json!(id);
    preset["idpreset"] = json!(format!("local-neutral-{}", gender.to_lowercase()));
    preset["presetname"] = json!(name);
    validate_preset(state, &preset, gender)?;
    let doc = state.catalog("avatar-default-catalog.json")?;
    let rows = doc["defaults"][gender]["items"]
        .as_array()
        .ok_or_else(|| Error::new(501, "Default avatar catalog unavailable"))?;
    let tokens: Vec<&str> = rows
        .iter()
        .map(|r| r["item_id"].as_str().unwrap_or(""))
        .chain(rows.iter().map(|r| r["category"].as_str().unwrap_or("")))
        .collect();
    Ok((
        preset,
        json!({"data":tokens.join("!")}),
        json!({"GUID":"","PS4ID":id,"lastPosition_x":0.0,"lastPosition_y":0.0,"lastPosition_z":0.0}),
    ))
}
fn resolve_asset<'a>(
    catalog: &'a Value,
    id: &str,
    gender: &str,
    category: Option<&str>,
) -> Result<&'a Value> {
    let rows = catalog["items"]
        .as_array()
        .ok_or_else(|| Error::new(501, "Avatar asset catalog unavailable"))?;
    let choices: Vec<&Value> = rows
        .iter()
        .filter(|r| {
            r["item_id"] == id
                && r["gender"] == gender
                && r["category"] != "UNKNOWN"
                && r["category_conflict"] != true
                && category.is_none_or(|c| r["category"] == c)
        })
        .collect();
    let cats: BTreeSet<&str> = choices
        .iter()
        .filter_map(|r| r["category"].as_str())
        .collect();
    if cats.len() != 1 {
        return Err(Error::new(
            404,
            "Item has no unambiguous shipped wardrobe asset",
        ));
    }
    Ok(choices[0])
}
fn save_preset(
    db: &Connection,
    id: &str,
    name: &str,
    gender: &str,
    preset: &Value,
    assets: &Value,
    position: &Value,
    now: f64,
) -> Result<()> {
    db.execute("INSERT INTO presets VALUES(?,?,?,?,?,?,?) ON CONFLICT(ps4_id,name,gender) DO UPDATE SET preset_json=excluded.preset_json,assets_json=excluded.assets_json,position_json=excluded.position_json,updated_at=excluded.updated_at",params![id,name,gender,json_text(preset)?,json_text(assets)?,json_text(position)?,now])?;
    db.execute(
        "UPDATE profiles SET gender=? WHERE ps4_id=?",
        params![gender, id],
    )?;
    db.execute("INSERT INTO preset_selection VALUES(?,?,?) ON CONFLICT(ps4_id,gender) DO UPDATE SET name=excluded.name",params![id,gender,name])?;
    Ok(())
}
fn ensure_defaults(db: &Connection, state: &State, p: &Profile, now: f64) -> Result<()> {
    let defaults = state.catalog("avatar-default-catalog.json")?;
    let assets = state.catalog("avatar-asset-catalog.json")?;
    for gender in ["MALE", "FEMALE"] {
        let exists: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM presets WHERE ps4_id=? AND gender=?)",
            params![p.ps4_id, gender],
            |r| r.get(0),
        )?;
        if exists {
            continue;
        }
        let (preset, ids, pos) = neutral(state, &p.ps4_id, gender, "Default")?;
        for item in defaults["defaults"][gender]["items"]
            .as_array()
            .ok_or_else(|| Error::new(501, "Default avatar catalog unavailable"))?
        {
            let id = item["item_id"]
                .as_str()
                .ok_or_else(|| Error::new(501, "Invalid default item"))?;
            let cat = item["category"]
                .as_str()
                .ok_or_else(|| Error::new(501, "Invalid default category"))?;
            let a = resolve_asset(&assets, id, gender, Some(cat))?;
            db.execute("INSERT OR IGNORE INTO entitlements(ps4_id,item_id,gender,category,bundle,display_name,granted_at,item_type) VALUES(?,?,?,?,?,?,?,1)",params![p.ps4_id,id,gender,cat,a["bundle"].as_str().unwrap_or(""),id,now])?;
        }
        save_preset(db, &p.ps4_id, "Default", gender, &preset, &ids, &pos, now)?;
    }
    db.execute(
        "UPDATE profiles SET gender=? WHERE ps4_id=?",
        params![p.gender, p.ps4_id],
    )?;
    if state.managed_instances {
        crate::lifecycle::provision_account_in(state, db, &p.ps4_id)?;
    }
    Ok(())
}
fn preset(
    db: &Connection,
    id: &str,
    gender: &str,
    name: Option<&str>,
) -> Result<(Value, Value, Value)> {
    let selected = if let Some(n) = name {
        Some(n.to_string())
    } else {
        db.query_row("SELECT name FROM preset_selection WHERE ps4_id=? AND gender=?",params![id,gender],|r|r.get::<_,String>(0)).optional()?.or(db.query_row("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY updated_at DESC,name LIMIT 1",params![id,gender],|r|r.get(0)).optional()?)
    };
    let row:Option<(String,String,String)>=db.query_row("SELECT preset_json,assets_json,position_json FROM presets WHERE ps4_id=? AND gender=? AND name=?",params![id,gender,selected],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
    let (a, b, c) =
        row.ok_or_else(|| Error::new(501, "A fully reconstructed avatar preset is not available"))?;
    Ok((
        serde_json::from_str(&a)?,
        serde_json::from_str(&b)?,
        serde_json::from_str(&c)?,
    ))
}
fn instance_documents(state: &State, filename: &str, key: &str, fresh: bool) -> Vec<Value> {
    let mut paths = vec![state.state_dir.join(filename)];
    if let Ok(entries) = std::fs::read_dir(state.state_dir.join("instances")) {
        let mut dirs: Vec<_> = entries
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.is_dir())
            .collect();
        dirs.sort();
        paths.extend(dirs.into_iter().map(|p| p.join(filename)));
    }
    paths
        .into_iter()
        .filter_map(|path| {
            let bytes = std::fs::read(&path).ok()?;
            let text = std::str::from_utf8(&bytes)
                .ok()?
                .trim_start_matches('\u{feff}');
            let v: Value = serde_json::from_str(text).ok()?;
            let generation = v["generation"].as_f64()?;
            if v["format_version"] != 1
                || !generation.is_finite()
                || !v[key].is_array()
                || (fresh && !(0.0..=15.0).contains(&(state.now() - generation)))
            {
                return None;
            }
            if path.parent() != Some(state.state_dir.as_path())
                && v["instance_id"].as_str()
                    != path
                        .parent()
                        .and_then(|p| p.file_name())
                        .and_then(|n| n.to_str())
            {
                return None;
            }
            Some(v)
        })
        .collect()
}
fn position(state: &State, db: &Connection, id: &str) -> Result<(Value, f64)> {
    let mut result = db
        .query_row(
            "SELECT x,y,z,updated_at FROM positions WHERE ps4_id=?",
            [id],
            |r| {
                Ok((
                    json!({"x":r.get::<_,f64>(0)?,"y":r.get::<_,f64>(1)?,"z":r.get::<_,f64>(2)?}),
                    r.get(3)?,
                ))
            },
        )
        .optional()?
        .unwrap_or((json!({"x":0.0,"y":0.0,"z":0.0}), 0.0));
    let guid = current_guid(db, id)?;
    let allocation: Option<(String, String)> = db
        .query_row(
            "SELECT instance_id,psidglobal FROM allocations WHERE guid=?",
            [guid],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((instance, psid)) = allocation {
        for doc in instance_documents(state, "instance-poses.json", "poses", false) {
            if doc["instance_id"] != instance || doc["psidglobal"] != psid {
                continue;
            }
            for row in doc["poses"].as_array().unwrap() {
                if row["ps4_id"] != id {
                    continue;
                }
                let Some(updated) = row["updated_at"].as_f64() else {
                    continue;
                };
                let Some(pos) = row["position"].as_object() else {
                    continue;
                };
                if pos.len() == 3
                    && ["x", "y", "z"].iter().all(|k| {
                        pos.get(*k)
                            .and_then(Value::as_f64)
                            .is_some_and(|n| n.is_finite() && n.abs() <= f32::MAX as f64)
                    })
                    && updated > result.1
                    && updated <= state.now()
                {
                    result = (row["position"].clone(), updated);
                }
            }
        }
    }
    Ok(result)
}
fn player_label(state: &State, db: &Connection, p: &Profile, guid: &str) -> Result<Value> {
    let prefs = preferences(db, &p.ps4_id)?;
    let (pos, _) = position(state, db, &p.ps4_id)?;
    Ok(
        json!({"GUID":guid,"userName":p.username,"status":prefs["status"],"mood":prefs["mood"],"nameColorX":prefs["NameColorSelectedIndex_r"],"nameColorY":prefs["NameColorSelectedIndex_g"],"nameColorZ":prefs["NameColorSelectedIndex_b"],"lastPosX":pos["x"],"lastPosY":pos["y"],"lastPosZ":pos["z"],"gender":p.gender}),
    )
}
fn wardrobe_active(
    db: &Connection,
    id: &str,
    guid: &str,
    instance: Option<&str>,
    now: f64,
) -> Result<bool> {
    let row:Option<(bool,String,f64)>=db.query_row("SELECT in_wardrobe,wardrobe_instance_id,wardrobe_updated_at FROM profile_state WHERE ps4_id=?",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
    Ok(row.is_some_and(|(active, i, t)| {
        active && now - t >= 0.0 && now - t <= 60.0 && instance.is_none_or(|v| v == i)
    }) && current_guid(db, id)?.as_deref() == Some(guid))
}
fn wardrobe_delivery(state: &State, instance: &str, psid: &str) -> bool {
    for doc in instance_documents(state, "instance-avatar-state.json", "avatars", true) {
        if doc["instance_id"] != instance
            || doc["psidglobal"] != psid
            || doc["listening"] != true
            || doc["wardrobe_delivery"] != "mirror_after_avatar_ready_v1"
        {
            continue;
        }
        let rows = doc["avatars"].as_array().unwrap();
        let mut seen = HashSet::new();
        let valid = rows.len() <= 32
            && rows.iter().all(|a| {
                let Some(g) = a["guid"].as_str() else {
                    return false;
                };
                let valid_guid = g.len() == 32
                    && g.bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                    && seen.insert(g.to_string());
                valid_guid
                    && a["ps4_id"].is_string()
                    && a["net_id"]
                        .as_u64()
                        .is_some_and(|n| n > 0 && n <= u32::MAX as u64)
                    && ["connected", "announced", "in_wardrobe"]
                        .iter()
                        .all(|k| a[*k].is_boolean())
                    && [
                        ("position", &["x", "y", "z"][..]),
                        ("rotation", &["x", "y", "z", "w"][..]),
                        ("scale", &["x", "y", "z"][..]),
                    ]
                    .iter()
                    .all(|(key, axes)| {
                        a[*key].as_object().is_some_and(|v| {
                            v.len() == axes.len()
                                && axes.iter().all(|axis| {
                                    v.get(*axis)
                                        .and_then(Value::as_f64)
                                        .is_some_and(f64::is_finite)
                                })
                        })
                    })
            });
        if valid {
            return true;
        }
    }
    false
}
fn encode_preset(state: &State, preset: &Value, gender: &str) -> Result<String> {
    let mut out = String::new();
    for f in schemas(state, gender)? {
        let key = f["name"]
            .as_str()
            .ok_or_else(|| Error::new(501, "Invalid avatar schema"))?;
        let token = if preset[key].is_null() {
            "nulls".into()
        } else if let Some(s) = preset[key].as_str() {
            s.into()
        } else {
            crate::wire::json_field(&preset[key])?
        };
        let len = token.encode_utf16().count() + 0x24;
        if len > u16::MAX as usize {
            return Err(Error::bad("EntryData value too long"));
        }
        let ch = char::from_u32(len as u32)
            .ok_or_else(|| Error::bad("EntryData length is not representable as UTF-8"))?;
        out.push(ch);
        out.push_str(&token);
    }
    Ok(out)
}
fn decode_preset(state: &State, text: &str, gender: &str) -> Result<(Value, Value)> {
    let units: Vec<u16> = text.encode_utf16().collect();
    let mut offset = 0;
    let mut map = Map::new();
    for f in schemas(state, gender)? {
        let key = f["name"]
            .as_str()
            .ok_or_else(|| Error::new(501, "Invalid avatar schema"))?;
        let prefix = *units
            .get(offset)
            .ok_or_else(|| Error::bad("Missing EntryData length prefix"))?;
        offset += 1;
        let len = prefix
            .checked_sub(0x24)
            .ok_or_else(|| Error::bad("Invalid EntryData length prefix"))?
            as usize;
        let slice = units
            .get(offset..offset + len)
            .ok_or_else(|| Error::bad("Truncated EntryData value"))?;
        let token = String::from_utf16(slice).map_err(|_| Error::bad("Invalid EntryData UTF16"))?;
        offset += len;
        let is_float = f["type_and_modifiers"]
            .as_str()
            .unwrap_or("")
            .contains("float");
        let value = if token == "nulls" {
            if is_float {
                return Err(Error::bad("Null float in avatar preset"));
            }
            Value::Null
        } else if is_float {
            json!(number(&token)? as f32 as f64)
        } else {
            json!(token)
        };
        map.insert(key.into(), value);
    }
    if offset != units.len() {
        return Err(Error::bad("Trailing data after final preset field"));
    }
    let mut p = Value::Object(map);
    validate_preset(state, &p, gender)?;
    let catalog = state.catalog("avatar-asset-catalog.json")?;
    let mut ids = Vec::new();
    let mut cats = Vec::new();
    let mut seen = HashSet::new();
    for i in 1..=40 {
        let item = p[format!("item{i}")]
            .as_str()
            .ok_or_else(|| Error::bad("Invalid avatar item slot"))?;
        if item == "null" {
            continue;
        }
        if item.is_empty() || !seen.insert(item.to_string()) {
            return Err(Error::bad("Empty or duplicate avatar item slot"));
        }
        if catalog["items"].as_array().is_some_and(|a| {
            a.iter()
                .any(|r| r["item_id"] == item && r["category_conflict"] == true)
        }) {
            return Err(Error::bad("Conflicting avatar item category"));
        }
        let row = resolve_asset(&catalog, item, gender, None)?;
        let cat = row["category"]
            .as_str()
            .ok_or_else(|| Error::bad("Invalid avatar category"))?;
        if item.contains('!') || cat.contains('!') {
            return Err(Error::bad("Unexpected avatar asset delimiter"));
        }
        ids.push(item.to_string());
        cats.push(cat.to_string());
    }
    // Only this original native ingress uses the observed female field permutation.
    if gender == "FEMALE" {
        for axis in ["x", "y", "z"] {
            let right = format!("f_ch_r_pectoral_jnt_t_{axis}");
            let left = format!("f_ch_l_pectoral_jnt_s_{axis}");
            let a = p[&right].clone();
            p[&right] = p[&left].clone();
            p[&left] = a;
        }
    }
    ids.extend(cats);
    Ok((p, json!({"data":ids.join("!")})))
}

fn sentinels(state: &State) -> Result<Vec<Value>> {
    let doc = state.catalog("wardrobe-removal-sentinels.json")?;
    let policy = &doc["policy"];
    if policy["view"] != "ordinary_only"
        || policy["entitlement"] != false
        || policy["storage_or_deleted_item"] != false
    {
        return Err(Error::new(500, "Unsafe wardrobe removal sentinel policy"));
    }
    let catalog = state.catalog("avatar-asset-catalog.json")?;
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for row in doc["sentinels"]
        .as_array()
        .ok_or_else(|| Error::new(500, "Invalid sentinel catalog"))?
    {
        let mut r = row.clone();
        let id = r["item_id"]
            .as_str()
            .ok_or_else(|| Error::new(500, "Invalid sentinel identifier"))?;
        let gender = r["gender"].as_str().unwrap_or("");
        let cat = r["category"].as_str().unwrap_or("");
        if !seen.insert((gender.to_string(), cat.to_string())) {
            return Err(Error::new(500, "Multiple wardrobe sentinels for category"));
        }
        match r["evidence_kind"].as_str().unwrap_or("wearable_manifest") {
            "wearable_manifest" => {
                let a = resolve_asset(&catalog, id, gender, Some(cat))?;
                if a["bundle"] != r["bundle"] || a["manifest_sha256"] != r["manifest_sha256"] {
                    return Err(Error::new(
                        500,
                        "Wardrobe sentinel evidence differs from shipped catalog",
                    ));
                }
            }
            "thumbnail_control" => {
                let path = format!(
                    "Assets/ResourcesART/Wardrobe_EAB/{gender}/{cat}/{id}/{id}Thumbnail.png"
                );
                let bundle = format!("th/{}thumbnail", id.to_lowercase());
                let digest = r["manifest_sha256"].as_str().unwrap_or("");
                if r["thumbnail_asset_path"] != path
                    || r["bundle"] != bundle
                    || digest.len() != 64
                    || !digest
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                {
                    return Err(Error::new(500, "Invalid thumbnail sentinel evidence"));
                }
            }
            _ => return Err(Error::new(500, "Unknown wardrobe sentinel evidence")),
        }
        for key in ["asset_status", "item_type", "display_name"] {
            r[key] = policy[key].clone();
        }
        out.push(r);
    }
    Ok(out)
}
fn resources(state: &State, db: &Connection, id: &str, kind: Option<&str>) -> Result<Vec<Value>> {
    let catalog = state.catalog("resource-entitlements.json")?;
    if catalog["format_version"] != 1 {
        return Err(Error::new(501, "Unsupported resource catalog"));
    }
    let mut q=db.prepare("SELECT kind,item_id,display_name FROM resource_entitlements WHERE ps4_id=? ORDER BY kind,item_id")?;
    let mut out = Vec::new();
    for row in q.query_map([id], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
        ))
    })? {
        let (k, item, label) = row?;
        if kind.is_some_and(|s| s != k) {
            continue;
        }
        let group: Vec<&Value> = catalog["items"]
            .as_array()
            .ok_or_else(|| Error::new(501, "Invalid resource catalog"))?
            .iter()
            .filter(|r| r["item_id"] == item)
            .collect();
        let table = match k.as_str() {
            "companions" => "COMPANIONS",
            "locomotions" => "LOCOMOTIONS",
            _ => return Err(Error::new(409, "Unsupported stored resource kind")),
        };
        let prefix = if k == "companions" { "02" } else { "03" };
        if group.len() != 1
            || group[0]["kind"] != k
            || group[0]["grantable"] != true
            || group[0]["conflicts"]
                .as_array()
                .is_some_and(|a| !a.is_empty())
            || group[0]["table"] != table
            || group[0]["bundle"] != format!("{prefix}/{}", item.to_lowercase())
            || group[0]["requested_resource_path"] != format!("Wardrobe_EAB/{table}/{item}/{item}")
        {
            return Err(Error::new(404, "Unknown or conflicting shipped resource"));
        }
        if item.contains(['#', '\0']) || item.is_empty() {
            return Err(Error::bad("Invalid resource identifier"));
        }
        out.push(json!({"kind":k,"item_id":item,"display_name":label}));
    }
    Ok(out)
}
fn purchases(state: &State, db: &Connection, id: &str, guid: &str) -> Result<Value> {
    let mut result = json!({"guid":guid});
    for group in [
        "cloths",
        "locomotions",
        "animations",
        "companions",
        "dances",
        "emotes",
        "gestures",
        "poses",
        "personalspaces",
        "profilePictures",
        "housings",
        "bundles",
        "bundlesHousing",
    ] {
        result[group] = json!([]);
        result[format!("{group}Name")] = json!([]);
    }
    let mut q=db.prepare("SELECT item_id,display_name FROM entitlements WHERE ps4_id=? ORDER BY item_id,gender,category")?;
    let mut seen = HashSet::new();
    for row in q.query_map([id], |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
    })? {
        let (item, label) = row?;
        if seen.insert(item.clone()) {
            result["cloths"].as_array_mut().unwrap().push(json!(item));
            result["clothsName"]
                .as_array_mut()
                .unwrap()
                .push(json!(label));
        }
    }
    for row in resources(state, db, id, None)? {
        let k = row["kind"].as_str().unwrap();
        result[k]
            .as_array_mut()
            .unwrap()
            .push(row["item_id"].clone());
        result[format!("{k}Name")]
            .as_array_mut()
            .unwrap()
            .push(row["display_name"].clone());
    }
    let mut q = db.prepare(
        "SELECT item_id,display_name FROM housing_entitlements WHERE ps4_id=? ORDER BY item_id",
    )?;
    let owned_housing = q
        .query_map([id], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let housing_catalog = if owned_housing.is_empty() {
        None
    } else {
        Some((
            state.catalog("http-nonminigame-gap-audit.json")?,
            state.catalog("housing-placement-contracts.json")?,
        ))
    };
    for (item, label) in owned_housing {
        let (doc, placement) = housing_catalog.as_ref().unwrap();
        let valid = doc["housing_catalog"].as_array().is_some_and(|rows| {
            rows.iter().any(|row| {
                if row["item_id"] != item || row["grantable"] != true {
                    return false;
                }
                let table = row["table"].as_str().unwrap_or("");
                let contract = &placement["items"][&item];
                let suffix = format!("ResourcesART/Housing/{table}/{item}/FBX/{item}.prefab");
                [
                    "HOUSING_WALLHANGING",
                    "HOUSING_CHAIR",
                    "HOUSING_FOOTSTOOL",
                    "HOUSING_TABLE",
                    "HOUSING_FLOORING",
                    "HOUSING_ORNAMENT",
                    "HOUSING_LAMP",
                    "HOUSING_LIGHT",
                    "HOUSING_SOFA",
                    "HOUSING_APPLIANCE",
                    "HOUSING_STORAGE",
                ]
                .contains(&table)
                    && row["bundle"] == format!("01/{}", item.to_lowercase())
                    && (row["asset_path"] == format!("Assets/{suffix}")
                        || row["asset_path"] == format!("Assets/ART/{suffix}"))
                    && contract["table"] == table
                    && contract["bundle"] == row["bundle"]
                    && contract["manifest_sha256"] == row["manifest_sha256"]
                    && ["ground", "floor", "wall", "ceiling"]
                        .contains(&contract["behaviour"].as_str().unwrap_or(""))
                    && contract["placement_cost"]
                        .as_i64()
                        .is_some_and(|n| (1..=200).contains(&n))
            })
        });
        if !valid {
            continue;
        }
        result["housings"].as_array_mut().unwrap().push(json!(item));
        result["housingsName"]
            .as_array_mut()
            .unwrap()
            .push(json!(label));
    }
    let mut q=db.prepare("SELECT logical_space_key FROM housing_spaces WHERE owner_ps4_id=? ORDER BY logical_space_key")?;
    for row in q.query_map([id], |r| r.get::<_, String>(0))? {
        let key = row?;
        result["personalspaces"]
            .as_array_mut()
            .unwrap()
            .push(json!(key));
        result["personalspacesName"]
            .as_array_mut()
            .unwrap()
            .push(json!(key));
    }
    Ok(result)
}
fn save_preference(
    db: &Connection,
    r: &Request,
    actor: Option<&str>,
    now: f64,
    key: &str,
    text: &str,
) -> Result<String> {
    let p = identify(db, r, 3, None, actor, true, now)?;
    let key = if key == "NotificationLoginFriend" {
        "notificationLoginFriend"
    } else {
        key
    };
    if key == "NameColorSelectedIndex" {
        let color: Value = serde_json::from_str(text)?;
        let obj = color
            .as_object()
            .ok_or_else(|| Error::bad("Invalid name color JSON"))?;
        if obj.len() != 3 || !["x", "y", "z"].iter().all(|k| obj.contains_key(*k)) {
            return Err(Error::bad("Invalid name color JSON"));
        }
        let mut values = Vec::new();
        for (axis, key) in ["x", "y", "z"].into_iter().zip([
            "NameColorSelectedIndex_r",
            "NameColorSelectedIndex_g",
            "NameColorSelectedIndex_b",
        ]) {
            let n = if let Some(v) = color[axis].as_f64() {
                number(&v.to_string())?
            } else if let Some(s) = color[axis].as_str() {
                number(s)?
            } else {
                return Err(Error::bad("Invalid name color JSON"));
            };
            values.push((key, json!(n)));
        }
        for (k, v) in values {
            put_pref(db, &p.ps4_id, k, &v)?;
        }
    } else {
        let default = defaults();
        let value = if key == "ShowPets" || key == "PlatformOnly" {
            let n = text
                .trim()
                .parse::<i64>()
                .map_err(|_| Error::bad("Invalid Boolean integer preference"))?;
            if n != 0 && n != 1 {
                return Err(Error::bad("Expected Boolean integer preference"));
            }
            json!(n)
        } else if default.get(key).is_none() {
            return Err(Error::bad("Unknown preference key"));
        } else if default[key].is_string() {
            json!(text)
        } else if default[key].is_i64() {
            json!(text
                .trim()
                .parse::<i64>()
                .map_err(|_| Error::bad("Invalid integer preference"))?)
        } else {
            json!(number(text)?)
        };
        put_pref(db, &p.ps4_id, key, &value)?;
    }
    Ok(format!("true#{}", r.fields[0]))
}
fn ban_fields(db: &Connection, id: Option<&str>, now: f64) -> Result<(String, String, String)> {
    if let Some(id) = id {
        identity(id, None)?;
        let row:Option<(bool,Option<i64>,String)>=db.query_row("SELECT ban_enabled,ban_expires_at,ban_reason FROM moderation_accounts WHERE ps4_id=?",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
        if let Some((true, expiry, reason)) = row {
            if expiry.is_none_or(|t| now < t as f64) {
                return Ok((
                    "true".into(),
                    expiry.map(format_utc).unwrap_or_else(|| "null".into()),
                    reason,
                ));
            }
        }
    }
    Ok(("false".into(), String::new(), String::new()))
}
// Gregorian UTC conversion avoids host timezone/locale and an extra date runtime.
fn format_utc(seconds: i64) -> String {
    let days = seconds.div_euclid(86400);
    let rem = seconds.rem_euclid(86400);
    let z = days + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let mut y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = mp + if mp < 10 { 3 } else { -9 };
    y += i64::from(m <= 2);
    format!(
        "{y:04}-{m:02}-{d:02} {:02}:{:02} UTC",
        rem / 3600,
        (rem % 3600) / 60
    )
}

pub fn handle(state: &State, route: &str, r: &Request) -> Result<Option<String>> {
    handle_as(state, route, r, None)
}
/// `actor` is supplied only after the HTTP adapter verifies its account credential.
pub fn handle_as(
    state: &State,
    route: &str,
    r: &Request,
    actor: Option<&str>,
) -> Result<Option<String>> {
    if !ROUTES.contains(&route) {
        return Ok(None);
    }
    canonical_platform(&r.platform)?;
    if state.managed_instances {
        crate::lifecycle::initialize(state)?;
    }
    let mut conn = state.connection()?;
    {
        let imports = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::services::import_events(state, &imports)?;
        imports.commit()?;
    }
    // A single transaction covers identity bootstrap, entitlement checks and every
    // multi-row mutation. Parsing/validation failure rolls all of it back.
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let db = &*tx;
    let now = state.now();
    let f = &r.fields;
    let response = match route {
        "STMGetUserInfo" => {
            fields(r, 2)?;
            account(db, &f[1], None, &r.platform, now, actor)?;
            format!(
                "OK#{}\n",
                json_text(
                    &json!({"response":{"result":"OK","params":{"state":"","country":"US","currency":"USD","status":"Active"}}})
                )?
            )
        }
        "CheckerServlet" => {
            fields(r, 4)?;
            if f[0]
                .to_lowercase()
                .starts_with("[test] preservation client ")
            {
                return Err(Error::new(403, "Invalid fixed local test identity lookup"));
            }
            let id = if let Some(a) = actor {
                Some(a.to_string())
            } else {
                let mut q =
                    db.prepare("SELECT ps4_id FROM profiles WHERE username=? AND platform=?")?;
                let rows = q
                    .query_map(params![f[0], canonical_platform(&r.platform)?], |r| {
                        r.get::<_, String>(0)
                    })?
                    .collect::<std::result::Result<Vec<_>, _>>()?;
                if rows.len() > 1 {
                    return Err(Error::new(409, "Local username/platform is ambiguous"));
                }
                rows.into_iter().next()
            };
            let (b, d, why) = ban_fields(db, id.as_deref(), now)?;
            format!("OK#{}#{b}#{d}#{why}", f[3])
        }
        "CheckServerStatusServlet" => {
            fields(r, 2)?;
            format!("true#{}#{}#1", f[0], f[1])
        }
        "N2UserExist" | "UserExistsServlet" => {
            fields(r, 5)?;
            actor_matches(actor, &f[3])?;
            if route == "UserExistsServlet" && f[0] != f[3] {
                return Err(Error::new(
                    409,
                    "Legacy identity differs from recovered Steam account binding",
                ));
            }
            identity(
                &f[3],
                if route == "N2UserExist" {
                    Some(&f[0])
                } else {
                    None
                },
            )?;
            let (b, d, why) = ban_fields(db, Some(&f[3]), now)?;
            if b == "true" {
                format!("{}##preservation#false#{b}#{d}#{why}", f[3])
            } else {
                let p = account(
                    db,
                    &f[3],
                    if route == "N2UserExist" {
                        Some(&f[0])
                    } else {
                        None
                    },
                    &r.platform,
                    now,
                    actor,
                )?;
                ensure_defaults(db, state, &p, now)?;
                format!("{}##preservation#false#false##", f[3])
            }
        }
        "N2AddUser" => {
            fields(r, 6)?;
            let expected = if r.platform == "PS4" { "0" } else { "1" };
            if f[5] != expected {
                return Err(Error::bad("Mismatched platform"));
            }
            let p = account(db, &f[0], Some(&f[1]), &r.platform, now, actor)?;
            ensure_defaults(db, state, &p, now)?;
            "true#".into()
        }
        "ChannelGUIDServlet" => {
            fields(r, 2)?;
            if f[1].len() != 64
                || !f[1]
                    .bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            {
                return Err(Error::bad("Invalid client-generated session hash"));
            }
            let id = &f[0];
            account(db, id, None, &r.platform, now, actor)?;
            let guid = crate::wire::session_guid(id, &f[1]);
            ensure_allowed(db, id, Some(&guid), now)?;
            let owner: Option<String> = db
                .query_row("SELECT ps4_id FROM sessions WHERE guid=?", [&guid], |r| {
                    r.get(0)
                })
                .optional()?;
            if owner.is_some_and(|o| o != *id) {
                return Err(Error::new(409, "Session identifier is already bound"));
            }
            db.execute(
                "INSERT OR IGNORE INTO sessions VALUES(?,?,?)",
                params![guid, id, now],
            )?;
            "true#".into()
        }
        "GetIinitInfosNeededServlet" => {
            identify(db, r, 2, Some(1), actor, false, now)?;
            format!("{}#true#true#false", f[0])
        }
        "GetPlayerPrefsServlet" => {
            let p = identify(db, r, 2, Some(1), actor, false, now)?;
            let stored = preferences(db, &p.ps4_id)?;
            let platform = stored.get("PlatformOnly").unwrap_or(&Value::Null);
            let platform = if platform.is_null() {
                0
            } else {
                platform
                    .as_i64()
                    .filter(|n| *n == 0 || *n == 1)
                    .ok_or_else(|| Error::new(409, "Invalid stored PlatformOnly preference"))?
            };
            let mut prefs = defaults();
            for key in defaults().as_object().unwrap().keys() {
                prefs[key] = stored[key].clone();
            }
            format!("true#{}#{}#prefs-v1#{platform}", f[0], json_text(&prefs)?)
        }
        "PlayerPrefsServlet" => {
            identify(db, r, 2, Some(1), actor, false, now)?;
            "true#".into()
        }
        "GetCinemaFilmsServlet" => {
            identify(db, r, 2, Some(1), actor, false, now)?;
            let seconds = (now.floor() as i64).rem_euclid(86400);
            format!(
                "{}#{}#{}#{}#0#LOCAL_NO_FILMS#84600",
                f[0],
                seconds / 3600,
                (seconds % 3600) / 60,
                seconds % 60
            )
        }
        "GetPurchases" => {
            let p = identify(db, r, 1, None, actor, false, now)?;
            format!(
                "true#{}#{}",
                f[0],
                json_text(&purchases(state, db, &p.ps4_id, &f[0])?)?
            )
        }
        "SavePlayerPref" => {
            fields(r, 3)?;
            save_preference(db, r, actor, now, &f[1], &f[2])?
        }
        "SetPlayerPrefsServlet" => {
            identify(db, r, 4, Some(1), actor, false, now)?;
            let req = Request {
                fields: vec![f[0].clone(), f[2].clone(), f[3].clone()],
                platform: r.platform.clone(),
            };
            save_preference(db, &req, actor, now, &f[2], &f[3])?
        }
        "InfoServlet" => {
            if f.len() < 3 {
                return Err(Error::bad("Invalid network-info request"));
            }
            let p = session_db(db, &f[0], Some(&f[1]), Some(&r.platform), now)?;
            actor_matches(actor, &p.ps4_id)?;
            "true#".into()
        }
        "N2AddUserOnline" => {
            let p = identify(db, r, 3, Some(1), actor, true, now)?;
            db.execute(
                "UPDATE profile_state SET online=1 WHERE ps4_id=?",
                [&p.ps4_id],
            )?;
            "OK#true".into()
        }
        "N2UpdateUserOnline" => {
            identify(db, r, 2, Some(1), actor, false, now)?;
            "true#".into()
        }
        "GetLastUsedPreset" | "GetLoadPresetByName" | "GetPresetGameServlet" => {
            let count = if route == "GetLastUsedPreset" {
                4
            } else if route == "GetLoadPresetByName" {
                5
            } else {
                3
            };
            identify(db, r, count, Some(1), actor, false, now)?;
            let target = session_db(db, &f[2], None, None, now)?;
            let gender = if count == 3 {
                target.gender.as_str()
            } else {
                numeric_gender(&f[3])?
            };
            let (p, a, mut pos) = preset(
                db,
                &target.ps4_id,
                gender,
                if count == 5 { Some(&f[4]) } else { None },
            )?;
            pos["GUID"] = json!(f[2]);
            pos["PS4ID"] = json!(target.ps4_id);
            let (saved, at) = position(state, db, &target.ps4_id)?;
            if at != 0.0 {
                for axis in ["x", "y", "z"] {
                    pos[format!("lastPosition_{axis}")] = saved[axis].clone();
                }
            }
            format!(
                "true#{}#{gender}#{}#{}#{}",
                f[1],
                json_text(&p)?,
                json_text(&a)?,
                json_text(&pos)?
            )
        }
        "PlayerLabelInfoServlet" => {
            identify(db, r, 3, Some(1), actor, false, now)?;
            let target = session_db(db, &f[2], None, None, now)?;
            let staff: String = db
                .query_row(
                    "SELECT staff_label FROM moderation_accounts WHERE ps4_id=?",
                    [&target.ps4_id],
                    |r| r.get(0),
                )
                .optional()?
                .unwrap_or_default();
            format!(
                "true#{}#{}#{}#{}#{staff}",
                f[0],
                f[1],
                f[2],
                json_text(&player_label(state, db, &target, &f[2])?)?
            )
        }
        "Send_CheckIsInWardrobeServlet" => {
            identify(db, r, 3, Some(1), actor, false, now)?;
            let p = session_db(db, &f[2], None, None, now)?;
            let active = wardrobe_active(db, &p.ps4_id, &f[2], None, now)?;
            format!("OK#{}##{active}#", f[0])
        }
        "SetUserInWardrobe" => {
            let p = identify(db, r, 13, None, actor, true, now)?;
            if f[2] != "0" && f[2] != "1" {
                return Err(Error::bad("Invalid integer wardrobe state"));
            }
            if f[3] != "MALE" && f[3] != "FEMALE" {
                return Err(Error::bad("Unsupported avatar gender"));
            }
            let nums = f[7..13]
                .iter()
                .map(|s| number(s))
                .collect::<Result<Vec<_>>>()?;
            let active = f[2] == "1";
            let instance: Option<String> = db
                .query_row(
                    "SELECT instance_id FROM allocations WHERE guid=?",
                    [&f[0]],
                    |r| r.get(0),
                )
                .optional()?;
            if active && instance.as_deref() != Some(f[1].as_str()) {
                return Err(Error::new(
                    403,
                    "Wardrobe session is not allocated to this instance",
                ));
            }
            db.execute("UPDATE profile_state SET in_wardrobe=?,wardrobe_instance_id=?,wardrobe_updated_at=? WHERE ps4_id=?",params![active,if active{&f[1]}else{""},now,p.ps4_id])?;
            db.execute(
                "UPDATE profiles SET gender=? WHERE ps4_id=?",
                params![f[3], p.ps4_id],
            )?;
            db.execute("INSERT INTO positions VALUES(?,?,?,?,?) ON CONFLICT(ps4_id) DO UPDATE SET x=excluded.x,y=excluded.y,z=excluded.z,updated_at=excluded.updated_at",params![p.ps4_id,nums[3],nums[4],nums[5],now])?;
            for (k, v) in [
                ("status", json!(f[5])),
                ("mood", json!(f[6])),
                ("NameColorSelectedIndex_r", json!(nums[0])),
                ("NameColorSelectedIndex_g", json!(nums[1])),
                ("NameColorSelectedIndex_b", json!(nums[2])),
            ] {
                put_pref(db, &p.ps4_id, k, &v)?;
            }
            "OK#true".into()
        }
        "GetAllInWardrobe" => {
            identify(db, r, 2, None, actor, false, now)?;
            let instance: Option<String> = db
                .query_row(
                    "SELECT instance_id FROM allocations WHERE guid=?",
                    [&f[0]],
                    |r| r.get(0),
                )
                .optional()?;
            if instance.as_deref() != Some(f[1].as_str()) {
                return Err(Error::new(
                    403,
                    "Wardrobe query is not allocated to this instance",
                ));
            }
            let psid: String = db.query_row(
                "SELECT psidglobal FROM allocations WHERE guid=?",
                [&f[0]],
                |r| r.get(0),
            )?;
            if wardrobe_delivery(state, &f[1], &psid) {
                "OK#".into()
            } else {
                let mut q=db.prepare("SELECT s.guid,s.ps4_id FROM sessions s JOIN profile_state p USING(ps4_id) JOIN allocations a ON a.guid=s.guid WHERE p.in_wardrobe=1 AND a.instance_id=? AND s.guid<>? ORDER BY s.guid")?;
                let mut labels = Vec::new();
                for row in q.query_map(params![f[1], f[0]], |r| {
                    Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
                })? {
                    let (g, id) = row?;
                    if wardrobe_active(db, &id, &g, Some(&f[1]), now)? {
                        let p = session_db(db, &g, None, None, now)?;
                        labels.push(json_text(&player_label(state, db, &p, &g)?)?);
                    }
                }
                format!("OK#{}", labels.join("#"))
            }
        }
        "N2SavePreset" => {
            let p = identify(db, r, 5, Some(1), actor, true, now)?;
            let gender = numeric_gender(&f[3])?;
            let (mut value, assets) = decode_preset(state, &f[4], gender)?;
            for i in 1..=40 {
                let item = value[format!("item{i}")]
                    .as_str()
                    .ok_or_else(|| Error::bad("Invalid avatar item slot"))?;
                if item != "null" {
                    let owned:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM entitlements WHERE ps4_id=? AND item_id=? AND gender=?)",params![p.ps4_id,item,gender],|r|r.get(0))?;
                    if !owned {
                        return Err(Error::new(
                            403,
                            "Preset contains an ungranted local wardrobe item",
                        ));
                    }
                }
            }
            value["iduser"] = json!(p.ps4_id);
            value["presetname"] = json!(f[2]);
            let previous:Option<String>=db.query_row("SELECT position_json FROM presets WHERE ps4_id=? AND gender=? ORDER BY updated_at DESC LIMIT 1",params![p.ps4_id,gender],|r|r.get(0)).optional()?;
            let mut pos = if let Some(s) = previous {
                serde_json::from_str(&s)?
            } else {
                json!({"lastPosition_x":0.0,"lastPosition_y":0.0,"lastPosition_z":0.0})
            };
            pos["GUID"] = json!(f[0]);
            pos["PS4ID"] = json!(f[1]);
            save_preset(db, &p.ps4_id, &f[2], gender, &value, &assets, &pos, now)?;
            "true#true".into()
        }
        "ShowPresetsServlet" => {
            let p = identify(db, r, 3, Some(1), actor, false, now)?;
            let gender = numeric_gender(&f[2])?;
            let mut q =
                db.prepare("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY name")?;
            let mut out = vec!["true".to_string(), f[0].clone()];
            for row in q.query_map(params![p.ps4_id, gender], |r| r.get::<_, String>(0))? {
                out.push(row?);
            }
            out.join("#")
        }
        "RemovePresetServlet" => {
            let p = identify(db, r, 5, Some(1), actor, true, now)?;
            let gender = numeric_gender(&f[4])?;
            db.execute(
                "DELETE FROM presets WHERE ps4_id=? AND name=? AND gender=?",
                params![p.ps4_id, f[2], gender],
            )?;
            let selected: Option<String> = db
                .query_row(
                    "SELECT name FROM preset_selection WHERE ps4_id=? AND gender=?",
                    params![p.ps4_id, gender],
                    |r| r.get(0),
                )
                .optional()?;
            if selected.as_deref() == Some(f[2].as_str()) {
                let next:Option<String>=db.query_row("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY updated_at DESC,name LIMIT 1",params![p.ps4_id,gender],|r|r.get(0)).optional()?;
                if let Some(next) = next {
                    db.execute(
                        "UPDATE preset_selection SET name=? WHERE ps4_id=? AND gender=?",
                        params![next, p.ps4_id, gender],
                    )?;
                } else {
                    db.execute(
                        "DELETE FROM preset_selection WHERE ps4_id=? AND gender=?",
                        params![p.ps4_id, gender],
                    )?;
                }
            }
            "true#".into()
        }
        "RenamePresetServlet" => {
            let p = identify(db, r, 5, Some(1), actor, true, now)?;
            let gender = numeric_gender(&f[4])?;
            let (mut value, _, _) = preset(db, &p.ps4_id, gender, Some(&f[2]))?;
            let collision: bool = db.query_row(
                "SELECT EXISTS(SELECT 1 FROM presets WHERE ps4_id=? AND name=? AND gender=?)",
                params![p.ps4_id, f[3], gender],
                |r| r.get(0),
            )?;
            if collision {
                return Err(Error::new(409, "Preset name already exists"));
            }
            value["presetname"] = json!(f[3]);
            db.execute("UPDATE presets SET name=?,preset_json=?,updated_at=? WHERE ps4_id=? AND name=? AND gender=?",params![f[3],json_text(&value)?,now,p.ps4_id,f[2],gender])?;
            db.execute(
                "UPDATE preset_selection SET name=? WHERE ps4_id=? AND gender=? AND name=?",
                params![f[3], p.ps4_id, gender, f[2]],
            )?;
            "true#".into()
        }
        "ResetDefaultPresetServlet" => {
            let p = identify(db, r, 4, Some(1), actor, true, now)?;
            let gender = numeric_gender(&f[3])?;
            let (v, a, pos) = neutral(state, &p.ps4_id, gender, &f[2])?;
            save_preset(db, &p.ps4_id, &f[2], gender, &v, &a, &pos, now)?;
            "true#".into()
        }
        "GetInfoServlet" => legacy_info(state, db, r, actor, now)?,
        "WardrobeOptionItemServlet" => {
            if f.len() != 4 && f.len() != 5 {
                return Err(Error::bad("Invalid wardrobe mutation field count"));
            }
            let p = identify(db, r, f.len(), Some(1), actor, true, now)?;
            if sentinels(state)?.iter().any(|v| v["item_id"] == f[2]) {
                return Err(Error::new(
                    403,
                    "Wardrobe removal controls are not mutable entitlements",
                ));
            }
            if !["0", "1", "2", "3"].contains(&f[3].as_str()) {
                return Err(Error::bad("Invalid wardrobe item status"));
            }
            let changed = db.execute(
                "UPDATE entitlements SET asset_status=? WHERE ps4_id=? AND item_id=?",
                params![f[3].parse::<i64>().unwrap(), p.ps4_id, f[2]],
            )?;
            if changed == 0 {
                return Err(Error::new(404, "Unknown local wardrobe entitlement"));
            }
            format!("true#{}", f[0])
        }
        "GetCompanionsServlet" | "GetLocomotionsServlet" => {
            let p = identify(db, r, 2, Some(1), actor, false, now)?;
            let kind = if route == "GetCompanionsServlet" {
                "companions"
            } else {
                "locomotions"
            };
            let mut parts = vec!["true".to_string(), f[0].clone()];
            for row in resources(state, db, &p.ps4_id, Some(kind))? {
                parts.push(row["item_id"].as_str().unwrap().to_string());
            }
            parts.join("#")
        }
        "InWardrobeCheckerServlet" => {
            let p = identify(db, r, 2, Some(1), actor, false, now)?;
            if current_guid(db, &p.ps4_id)?.as_deref() == Some(f[0].as_str()) {
                db.execute("UPDATE profile_state SET wardrobe_updated_at=? WHERE ps4_id=? AND in_wardrobe=1",params![now,p.ps4_id])?;
            }
            "true#".into()
        }
        "RemoveInWardrobeServlet" => {
            let p = identify(db, r, 3, Some(1), actor, false, now)?;
            if current_guid(db, &p.ps4_id)?.as_deref() == Some(f[0].as_str()) {
                db.execute("UPDATE profile_state SET in_wardrobe=0,wardrobe_instance_id='',wardrobe_updated_at=? WHERE ps4_id=?",params![now,p.ps4_id])?;
            }
            "true#".into()
        }
        "GetrefusernameServlet" => {
            identify(db, r, 3, Some(1), actor, false, now)?;
            if f[2]
                .to_lowercase()
                .starts_with("[test] preservation client ")
            {
                return Err(Error::new(403, "Invalid fixed local test identity lookup"));
            }
            let guid:Option<String>=db.query_row("SELECT s.guid FROM profiles p JOIN sessions s USING(ps4_id) WHERE p.username=? ORDER BY s.created_at DESC,s.guid DESC LIMIT 1",[&f[2]],|r|r.get(0)).optional()?;
            format!("true#{}#{}", f[0], guid.unwrap_or_default())
        }
        _ => return Err(Error::new(500, "Advertised account route has no handler")),
    };
    tx.commit()?;
    Ok(Some(response))
}

fn legacy_info(
    state: &State,
    db: &Connection,
    r: &Request,
    actor: Option<&str>,
    now: f64,
) -> Result<String> {
    let f = &r.fields;
    if f.is_empty() {
        return Err(Error::bad("Missing legacy preset mode"));
    }
    if f[0] != "0" {
        let count = match f[0].as_str() {
            "1" => 3,
            "2" => 4,
            "3" => 5,
            _ => return Err(Error::bad("Unknown legacy preset mode")),
        };
        fields(r, count)?;
        let p = session_db(db, &f[1], Some(&f[2]), Some(&r.platform), now)?;
        actor_matches(actor, &p.ps4_id)?;
        let gender = if f[0] == "1" {
            p.gender.as_str()
        } else {
            numeric_gender(&f[3])?
        };
        let (value, assets, _) = preset(
            db,
            &p.ps4_id,
            gender,
            if f[0] == "3" { Some(&f[4]) } else { None },
        )?;
        if f[0] == "3" {
            return Ok(format!(
                "true#{}#{}#{}",
                f[1],
                json_text(&value)?,
                json_text(&assets)?
            ));
        }
        let serial = encode_preset(state, &value, gender)?;
        if serial.contains('#') {
            return Err(Error::new(
                409,
                "Legacy preset is not representable in outer framing",
            ));
        }
        return Ok(if f[0] == "1" {
            format!("true#{}##{serial}#{gender}", f[1])
        } else {
            format!("true#{}#{serial}#{}", f[1], f[3])
        });
    }
    fields(r, 6)?;
    let p = session_db(db, &f[1], Some(&f[2]), Some(&r.platform), now)?;
    actor_matches(actor, &p.ps4_id)?;
    let gender = numeric_gender(&f[3])?;
    let statuses: &[i64] = match f[5].as_str() {
        "0" => &[0, 1],
        "1" => &[2],
        "2" => &[3],
        _ => return Err(Error::bad("Invalid wardrobe view")),
    };
    let sentinels = sentinels(state)?;
    let mut q=db.prepare("SELECT item_id,display_name,asset_status,item_type FROM entitlements WHERE ps4_id=? AND gender=? AND category=? ORDER BY item_id,gender,category")?;
    let mut items = Vec::new();
    for row in q.query_map(params![p.ps4_id, gender, f[4]], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, i64>(2)?,
            r.get::<_, i64>(3)?,
        ))
    })? {
        let (id, name, status, kind) = row?;
        if statuses.contains(&status) && !sentinels.iter().any(|s| s["item_id"] == id) {
            items.push((id, name, status, kind));
        }
    }
    if f[5] == "0" {
        if let Some(s) = sentinels
            .iter()
            .find(|s| s["gender"] == gender && s["category"] == f[4])
        {
            items.push((
                s["item_id"].as_str().unwrap().into(),
                s["display_name"].as_str().unwrap().into(),
                s["asset_status"].as_i64().unwrap(),
                s["item_type"].as_i64().unwrap(),
            ));
        }
    }
    let ids = items
        .iter()
        .map(|r| r.0.as_str())
        .collect::<Vec<_>>()
        .join("#");
    let names = items
        .iter()
        .map(|r| {
            if r.1.contains(['#', '!']) {
                r.0.as_str()
            } else {
                r.1.as_str()
            }
        })
        .collect::<Vec<_>>()
        .join("#");
    let status = items
        .iter()
        .map(|r| r.2.to_string())
        .collect::<Vec<_>>()
        .join("#");
    let kinds = items
        .iter()
        .map(|r| r.3.to_string())
        .collect::<Vec<_>>()
        .join("#");
    Ok(format!(
        "true!{}!{ids}!{status}!{names}!{kinds}!{gender}",
        f[1]
    ))
}
