//! Recovered business wire contracts backed by the shared SQLite authority.
use crate::{
    error::{Error, Result},
    state::State,
    wire::Request,
};
use rusqlite::{types::ValueRef, Connection, OptionalExtension, Params};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
mod gathering;
mod housing;
mod ipc;
mod rewards;
mod shop;

pub const ROUTES: &[&str] = &[
    "N2AddBlock",
    "N2AddSilenced",
    "N2RemoveBlock",
    "N2RemoveSilenced",
    "N2RemoveFriend",
    "N2ToggleFavorite",
    "N2GetSocialList",
    "GetSocialList",
    "N2GetRelationship",
    "N2GetPsidglobalAndGuidByUsernamePlatform",
    "checkStateNPFriendsServlet",
    "GetNewsServlet",
    "ReportServlet",
    "checkerToServerDownMaintenanceServlet",
    "GetSpaceEventServlet",
    "GetPersonalSpacesServlet",
    "GetHousingTypeServlet",
    "HousingReadPresetServlet",
    "N2HousingReadPreset",
    "HousingSavePresetServletParts",
    "N2GetUserTypeSpace",
    "GetFeaturesServlet",
    "GetGenderDataShopServlet",
    "GetItemAssetsDataServlet",
    "GetShopDataShopServlet",
    "GetShopInfoPlayerShop",
    "GetShopTypeDataShopServlet",
    "NPShopBundleItemsServlet",
    "NPShopBuyItemServlet",
    "NPShopGiftItemServlet",
    "NPShopIsItemPurchasedServlet",
    "NPShopSyncCrystalsServlet",
    "CheckOwnGenericReward",
    "GenericReward",
    "RewardClothServlet",
    "RewardConsumeServlet",
    "SKLPromoServlet",
    "SKLPromoTriggerServlet",
    "checkRewardAvailableServlet",
    "CinemaInteractionNPServlet",
    "CheckIfSpaceStillExistServlet",
    "GetConsumableServlet",
    "GetConsumablePriceServlet",
    "Get_GatherConsume",
    "Get_GatherConsumeReward",
    "Get_GatherMedievalVillage",
    "Get_GatherPhaseGame",
    "Get_GatherStatus",
    "Get_npGather",
    "Get_npGatherChristmas",
    "Get_npGatherProcessItem",
    "Send_GatherInitInSpace",
    "Send_GatherMedievalVillageConsume",
];
pub fn handle(state: &State, route: &str, req: &Request) -> Result<Option<String>> {
    handle_as(state, route, req, None)
}
pub fn handle_as(
    state: &State,
    route: &str,
    req: &Request,
    actor: Option<&str>,
) -> Result<Option<String>> {
    if !ROUTES.contains(&route) {
        return Ok(None);
    }
    let mut db = state.connection()?;
    {
        let imported = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        ipc::import_events(state, &imported)?;
        imported.commit()?;
    }
    let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let result = if shop::ROUTES.contains(&route) {
        shop::handle(state, &tx, route, req, actor)
    } else if housing::ROUTES.contains(&route) {
        housing::handle(state, &tx, route, req, actor)
    } else if rewards::ROUTES.contains(&route) {
        rewards::handle(state, &tx, route, req, actor)
    } else if gathering::ROUTES.contains(&route) {
        gathering::handle(state, &tx, route, req, actor)
    } else {
        social(state, &tx, route, req, actor)
    };
    // A conflicting native housing batch is quarantined durably, even though
    // the client receives a protocol rejection. No layout write is performed.
    match result {
        Ok(value) => {
            tx.commit()?;
            drop(db);
            if route == "GetConsumableServlet" {
                rewards::publish_consumable(state, &value)?;
            }
            Ok(Some(value))
        }
        Err(err) if housing::is_durable_rejection(&err) => {
            tx.commit()?;
            Err(err)
        }
        // Gathering's _event initializes durable progress before read/consume
        // validation; the reward route deliberately wraps that in its grant
        // transaction. Preserve this distinction without committing SQL faults.
        Err(err)
            if gathering::ROUTES.contains(&route)
                && route != "Get_GatherConsumeReward"
                && err.status < 500 =>
        {
            tx.commit()?;
            Err(err)
        }
        Err(err) => Err(err),
    }
}

pub(crate) fn rows<P: Params>(db: &Connection, sql: &str, args: P) -> Result<Vec<Value>> {
    let mut stmt = db.prepare(sql)?;
    let names: Vec<String> = stmt.column_names().iter().map(|s| s.to_string()).collect();
    let values = stmt
        .query_map(args, |r| {
            let mut result = serde_json::Map::new();
            for (i, name) in names.iter().enumerate() {
                let v = match r.get_ref(i)? {
                    ValueRef::Null => Value::Null,
                    ValueRef::Integer(v) => json!(v),
                    ValueRef::Real(v) => json!(v),
                    ValueRef::Text(v) => Value::String(String::from_utf8_lossy(v).into_owned()),
                    ValueRef::Blob(_) => Value::Null,
                };
                result.insert(name.clone(), v);
            }
            Ok(Value::Object(result))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(values)
}
pub(crate) fn one<P: Params>(db: &Connection, sql: &str, args: P) -> Result<Option<Value>> {
    Ok(rows(db, sql, args)?.into_iter().next())
}
pub(crate) fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
pub(crate) fn n(v: &Value, k: &str) -> i64 {
    v[k].as_i64().unwrap_or(0)
}
pub(crate) fn flag(v: &Value, k: &str) -> bool {
    v[k].as_bool().unwrap_or_else(|| n(v, k) != 0)
}
pub(crate) fn js(v: &Value) -> String {
    crate::wire::json_field(v).expect("JSON Value is serializable")
}
pub(crate) fn ascii_json(v: &Value) -> String {
    // Canonical digests use Python's ensure_ascii JSON without the outer-wire
    // '#' escape. Walk escape pairs so a literal "\\u0023" stays literal.
    let encoded = js(v);
    let mut chars = encoded.chars().peekable();
    let mut out = String::new();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        let Some(next) = chars.next() else {
            out.push(c);
            break;
        };
        if next == 'u' {
            let hex: String = chars.by_ref().take(4).collect();
            if hex == "0023" {
                out.push('#');
            } else {
                out.push('\\');
                out.push('u');
                out.push_str(&hex);
            }
        } else {
            out.push('\\');
            out.push(next);
        }
    }
    out
}
pub(crate) fn hash(v: &str) -> String {
    format!("{:x}", Sha256::digest(v.as_bytes()))
}
pub(crate) fn uuid() -> String {
    uuid::Uuid::new_v4().simple().to_string()
}
pub(crate) fn token<'a>(v: &'a str, label: &str, max: usize, empty: bool) -> Result<&'a str> {
    if (!empty && v.is_empty())
        || v.chars().count() > max
        || v.chars().any(|c| c == '#' || c.is_control())
    {
        return Err(Error::bad(format!("Invalid {label}")));
    }
    Ok(v)
}
pub(crate) fn uint(v: &str, label: &str, max: i64) -> Result<i64> {
    let val = v
        .parse::<i64>()
        .ok()
        .filter(|x| *x >= 0 && *x <= max)
        .ok_or_else(|| Error::bad(format!("Invalid {label}")))?;
    Ok(val)
}
pub(crate) fn canonical_uint(v: &str, label: &str, max: i64) -> Result<i64> {
    let num = uint(v, label, max)?;
    if num.to_string() != v {
        return Err(Error::bad(format!("Invalid {label}")));
    }
    Ok(num)
}
pub(crate) fn platform(v: &str) -> Result<&'static str> {
    match v {
        "0" | "PS4" => Ok("PS4"),
        "1" | "StandaloneWindows" => Ok("StandaloneWindows"),
        _ => Err(Error::bad("Unsupported platform")),
    }
}
pub(crate) fn platform_num(v: &str) -> Result<i64> {
    Ok(if platform(v)? == "PS4" { 0 } else { 1 })
}
pub(crate) fn current(db: &Connection, id: &str, guid: &str) -> Result<bool> {
    let value: Option<String> = db
        .query_row(
            "SELECT guid FROM sessions WHERE ps4_id=? ORDER BY created_at DESC,guid DESC LIMIT 1",
            [id],
            |r| r.get(0),
        )
        .optional()?;
    Ok(value.as_deref() == Some(guid))
}
pub(crate) fn identity(
    state: &State,
    db: &Connection,
    req: &Request,
    count: usize,
    id_index: Option<usize>,
    actor: Option<&str>,
    writer: bool,
) -> Result<Value> {
    req.require(count)?;
    let p = session(state, db, &req.fields[0])?;
    if id_index.is_some_and(|i| req.fields[i] != s(&p, "ps4_id"))
        || actor.is_some_and(|a| a != s(&p, "ps4_id"))
    {
        return Err(Error::new(403, "Unknown or mismatched local session"));
    }
    if writer && !current(db, s(&p, "ps4_id"), &req.fields[0])? {
        return Err(Error::new(
            403,
            "Historical session cannot change current account state",
        ));
    }
    Ok(p)
}
pub(crate) fn session(state: &State, db: &Connection, guid: &str) -> Result<Value> {
    let p = one(
        db,
        "SELECT p.* FROM sessions s JOIN profiles p USING(ps4_id) WHERE s.guid=?",
        [guid],
    )?
    .ok_or_else(|| Error::new(403, "Unknown or mismatched local session"))?;
    let banned: bool = db.query_row("SELECT EXISTS(SELECT 1 FROM moderation_accounts WHERE ps4_id=? AND ban_enabled=1 AND (ban_expires_at IS NULL OR ban_expires_at>?))",rusqlite::params![s(&p,"ps4_id"),state.now()],|r|r.get(0))?;
    let revoked: bool = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM moderation_revoked_sessions WHERE guid=?)",
        [guid],
        |r| r.get(0),
    )?;
    if banned || revoked {
        return Err(Error::new(403, "Account or session is not permitted"));
    }
    Ok(p)
}
pub(crate) fn find_user(db: &Connection, name: &str, plat: &str) -> Result<Option<Value>> {
    token(name, "username", 128, false)?;
    let r = rows(
        db,
        "SELECT * FROM profiles WHERE username=? AND platform=?",
        rusqlite::params![name, platform(plat)?],
    )?;
    if r.len() > 1 {
        return Err(Error::new(409, "Local username/platform is ambiguous"));
    }
    Ok(r.into_iter().next())
}
pub(crate) fn relation(
    db: &Connection,
    id: &str,
    target: &str,
    plat: &str,
    kind: &str,
) -> Result<bool> {
    Ok(db.query_row("SELECT EXISTS(SELECT 1 FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind=?)",rusqlite::params![id,target,platform(plat)?,kind],|r|r.get(0))?)
}
pub(crate) fn entry(values: &[String]) -> Result<String> {
    let mut out = String::new();
    for value in values {
        if value.contains('#') {
            return Err(Error::bad(
                "Value cannot be represented in legacy EntryData framing",
            ));
        }
        let count = value.encode_utf16().count() + 0x24;
        let c = u32::try_from(count)
            .ok()
            .and_then(char::from_u32)
            .filter(|_| count <= 0xffff)
            .ok_or_else(|| Error::bad("EntryData value exceeds length prefix"))?;
        out.push(c);
        out.push_str(value);
    }
    Ok(out)
}
pub(crate) fn reply(f: &[String], vals: &[String]) -> String {
    [
        vec!["true".into(), f[0].clone(), f[1].clone()],
        vals.to_vec(),
    ]
    .concat()
    .join("#")
}

pub(crate) fn presence(state: &State, db: &Connection) -> HashMap<String, i64> {
    let mut result = HashMap::new();
    let mut paths = vec![state.state_dir.join("instance-presence.json")];
    if let Ok(entries) = std::fs::read_dir(state.state_dir.join("instances")) {
        for e in entries.flatten() {
            if e.path().is_dir() {
                paths.push(e.path().join("instance-presence.json"));
            }
        }
    }
    for path in paths {
        if path
            .symlink_metadata()
            .map(|m| m.file_type().is_symlink() || m.len() > 65536)
            .unwrap_or(true)
        {
            continue;
        }
        let Ok(bytes) = std::fs::read(&path) else {
            continue;
        };
        let Ok(doc) = serde_json::from_slice::<Value>(&bytes) else {
            continue;
        };
        let age = state.now() - doc["generation"].as_f64().unwrap_or(-1.0);
        if doc["format_version"] != 1 || !(0.0..=15.0).contains(&age) {
            continue;
        }
        let Some(players) = doc["players"].as_array() else {
            continue;
        };
        let mut seen = HashSet::new();
        let mut additions = Vec::new();
        let mut invalid = false;
        for p in players {
            let guid = s(p, "guid");
            let status = n(p, "status");
            if guid.len() != 32
                || !guid
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
                || p["status"].as_i64().is_none()
                || ![0, 1, 3].contains(&status)
                || !seen.insert(guid)
            {
                invalid = true;
                break;
            }
            let Ok(Some(account)) = one(db, "SELECT ps4_id FROM sessions WHERE guid=?", [guid])
            else {
                continue;
            };
            if !current(db, s(&account, "ps4_id"), guid).unwrap_or(false) {
                continue;
            }
            if path.parent() != Some(state.state_dir.as_path()) {
                let Ok(Some(a)) = one(
                    db,
                    "SELECT instance_id,psidglobal FROM allocations WHERE guid=?",
                    [guid],
                ) else {
                    continue;
                };
                if a["instance_id"] != doc["instance_id"] || a["psidglobal"] != doc["psidglobal"] {
                    continue;
                }
            }
            additions.push((guid.to_string(), status));
        }
        if !invalid {
            result.extend(additions);
        }
    }
    result
}
pub(crate) fn ready(state: &State, instance: &str, scene: &str) -> bool {
    crate::lifecycle::ready(state, Some(scene), Some(instance), None).is_some()
}
fn social(
    state: &State,
    db: &Connection,
    route: &str,
    req: &Request,
    actor: Option<&str>,
) -> Result<String> {
    let f = &req.fields;
    if route == "GetNewsServlet" {
        req.require(1)?;
        if f[0].is_empty()
            || !f[0].bytes().all(|b| b.is_ascii_digit())
            || uint(&f[0], "native news random value", 99).is_err()
        {
            return Err(Error::bad("Invalid native news random value"));
        }
        let rows=rows(db,"SELECT date_label,text FROM moderation_news WHERE active=1 AND (expires_at IS NULL OR expires_at>?) ORDER BY created_at DESC,news_id DESC LIMIT 100",[state.now()])?;
        if rows.is_empty() {
            return Ok("1#Local preservation#This is a local preservation service. Original online news is unavailable.".into());
        }
        let mut out = vec![rows.len().to_string()];
        for r in rows {
            out.extend([s(&r, "date_label").into(), s(&r, "text").into()]);
        }
        return Ok(out.join("#"));
    }
    if [
        "N2AddBlock",
        "N2AddSilenced",
        "N2RemoveBlock",
        "N2RemoveSilenced",
        "N2RemoveFriend",
        "N2ToggleFavorite",
    ]
    .contains(&route)
    {
        let p = identity(state, db, req, 3, None, actor, true)?;
        if !["0", "1"].contains(&f[2].as_str()) {
            return Err(Error::bad("Unsupported relation platform"));
        }
        token(&f[1], "relation username", 128, false)?;
        let plat = platform(&f[2])?;
        let kind = if route.contains("Block") {
            "block"
        } else if route.contains("Silenced") {
            "silenced"
        } else if route == "N2RemoveFriend" {
            "friend"
        } else {
            "favorite"
        };
        if kind == "friend" {
            db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind IN ('friend','favorite')",rusqlite::params![s(&p,"ps4_id"),f[1],plat])?;
            if let Some(target) = find_user(db, &f[1], plat)? {
                if s(&target, "ps4_id") == s(&p, "ps4_id") {
                    return Err(Error::bad(
                        "Friendship requires two distinct local accounts",
                    ));
                }
                db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind IN ('friend','favorite')",rusqlite::params![s(&target,"ps4_id"),s(&p,"username"),s(&p,"platform")])?;
                db.execute(
                    "INSERT INTO friend_events VALUES(?,?,?,?,?,?)",
                    rusqlite::params![
                        uuid(),
                        "remove_friendship",
                        s(&p, "ps4_id"),
                        s(&target, "ps4_id"),
                        state.now(),
                        state.now()
                    ],
                )?;
            }
        } else if route.starts_with("N2Remove")
            || (kind == "favorite" && relation(db, s(&p, "ps4_id"), &f[1], plat, kind)?)
        {
            db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind=?",rusqlite::params![s(&p,"ps4_id"),f[1],plat,kind])?;
        } else {
            db.execute(
                "INSERT OR IGNORE INTO relations VALUES(?,?,?,?)",
                rusqlite::params![s(&p, "ps4_id"), f[1], plat, kind],
            )?;
        }
        return Ok("OK#true".into());
    }
    match route {
        "N2GetSocialList" | "GetSocialList" => {
            let is_n2 = route == "N2GetSocialList";
            let p = identity(
                state,
                db,
                req,
                if is_n2 { 4 } else { 2 },
                if is_n2 { Some(1) } else { None },
                actor,
                false,
            )?;
            let kind_index = if is_n2 { 2 } else { 1 };
            let index = canonical_uint(&f[kind_index], "social list", 2)
                .map_err(|_| Error::new(501, "Social list selection has not been reconstructed"))?
                as usize;
            if is_n2 && !["0", "1"].contains(&f[3].as_str()) {
                return Err(Error::new(501, "Unknown legacy social UI selector"));
            }
            let pres = presence(state, db);
            let mut entries = Vec::new();
            for r in rows(db,"SELECT target,target_platform FROM relations WHERE ps4_id=? AND kind=? ORDER BY target,target_platform",rusqlite::params![s(&p,"ps4_id"),["friend","silenced","block"][index]])? {
                let mut statuses=HashSet::new();if let Some(target)=find_user(db,s(&r,"target"),s(&r,"target_platform"))? {for g in rows(db,"SELECT guid FROM sessions WHERE ps4_id=?",[s(&target,"ps4_id")])? {if let Some(v)=pres.get(s(&g,"guid")){statuses.insert(*v);}}}
                let status=if statuses.contains(&3){3}else if statuses.contains(&0){0}else if statuses.contains(&1){1}else{2};
                let fav=relation(db,s(&p,"ps4_id"),s(&r,"target"),s(&r,"target_platform"),"favorite")?;
                entries.push((!fav,status==2,s(&r,"target").to_string(),platform_num(s(&r,"target_platform"))?,status,fav));
            }
            entries.sort();
            if !is_n2 {
                return Ok(format!(
                    "OK#{}",
                    js(
                        &json!({"lUsernames":entries.iter().map(|r|r.2.clone()).collect::<Vec<_>>()})
                    )
                ));
            }
            let mut out = vec![
                "true".into(),
                f[0].clone(),
                f[3].clone(),
                entries.len().to_string(),
            ];
            for e in entries {
                out.push(entry(&[
                    if e.5 { "True" } else { "False" }.into(),
                    ["Online", "Away", "Offline", "Wardrobe"][e.4 as usize].into(),
                    e.2,
                    e.3.to_string(),
                    ["Friends", "Silenced", "Blocked"][index].into(),
                ])?);
            }
            Ok(out.join("#"))
        }
        "N2GetRelationship" => {
            let p = identity(state, db, req, 3, Some(1), actor, false)?;
            let t = session(state, db, &f[2])?;
            let own = |kind| {
                relation(
                    db,
                    s(&p, "ps4_id"),
                    s(&t, "username"),
                    s(&t, "platform"),
                    kind,
                )
            };
            let rev = |kind| {
                relation(
                    db,
                    s(&t, "ps4_id"),
                    s(&p, "username"),
                    s(&p, "platform"),
                    kind,
                )
            };
            let code = if own("block")? {
                5
            } else if rev("block")? {
                6
            } else if own("silenced")? {
                3
            } else if rev("silenced")? {
                4
            } else if own("favorite")? {
                2
            } else if own("friend")? {
                1
            } else {
                0
            };
            Ok(format!("OK####{code}"))
        }
        "N2GetPsidglobalAndGuidByUsernamePlatform" => {
            identity(state, db, req, 3, None, actor, false)?;
            if !["0", "1"].contains(&f[2].as_str()) {
                return Err(Error::bad("Unsupported lookup platform"));
            }
            if let Some(t) = find_user(db, &f[1], &f[2])? {
                let pres = presence(state, db);
                for a in rows(db,"SELECT a.* FROM allocations a JOIN sessions s USING(guid) WHERE s.ps4_id=? ORDER BY allocated_at DESC",[s(&t,"ps4_id")])? {if pres.contains_key(s(&a,"guid")) && ready(state,s(&a,"instance_id"),s(&a,"psidglobal")){return Ok(format!("OK#{}#{}",s(&a,"psidglobal"),s(&a,"guid")));}}
            }
            Ok("OK##".into())
        }
        "checkStateNPFriendsServlet" => {
            if f.len() < 2 {
                return Err(Error::bad("Missing external-friend identity"));
            }
            identity(state, db, req, f.len(), Some(1), actor, false)?;
            Ok(format!("true#{}", f[0]))
        }
        "GetSpaceEventServlet" => {
            identity(state, db, req, 3, Some(1), actor, false)?;
            Ok(format!("true#{}#false", f[0]))
        }
        "checkerToServerDownMaintenanceServlet" => {
            identity(state, db, req, 2, Some(1), actor, false)?;
            let end: Option<i64> = db
                .query_row(
                    "SELECT end_at FROM moderation_maintenance WHERE singleton=1",
                    [],
                    |r| r.get(0),
                )
                .optional()?;
            let mins = end
                .map(|v| ((v as f64 - state.now()) / 60.).ceil().max(0.) as i64)
                .unwrap_or(0);
            Ok(reply(f, &[mins.to_string()]))
        }
        "ReportServlet" => {
            identity(state, db, req, 5, Some(1), actor, true)?;
            let opt = uint(&f[2], "report option", 2)?;
            token(&f[3], "report target", 128, false)?;
            token(&f[4], "report text", 512, true)?;
            if f[0].len() != 32
                || !f[0]
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                || f[3].trim().is_empty()
            {
                return Err(Error::bad("Invalid report session or target"));
            }
            let accepted = db.execute(
                "INSERT OR IGNORE INTO local_reports VALUES(?,?,?,?,?)",
                rusqlite::params![f[0], f[3], opt, f[4], state.now()],
            )? == 1;
            let rid = hash(&ascii_json(&json!([f[0], f[3], opt])));
            db.execute(
                "INSERT OR IGNORE INTO moderation_report_index VALUES(?,?,?,?)",
                rusqlite::params![rid, f[0], f[3], opt],
            )?;
            let indexed = one(
                db,
                "SELECT guid,target,option FROM moderation_report_index WHERE report_id=?",
                [&rid],
            )?
            .ok_or_else(|| Error::new(409, "Report identity collision"))?;
            if s(&indexed, "guid") != f[0]
                || s(&indexed, "target") != f[3]
                || n(&indexed, "option") != opt
            {
                return Err(Error::new(409, "Report identity collision"));
            }
            Ok(reply(f, &[accepted.to_string()]))
        }
        _ => Err(Error::new(501, "Business route has not been reconstructed")),
    }
}
pub use ipc::{process_resource_selection, pump, resource_selection_snapshot};
pub(crate) fn import_events(state: &State, db: &Connection) -> Result<()> {
    ipc::import_events(state, db)
}
pub(crate) fn housing_binding(db: &Connection, instance: &str) -> Result<Option<Value>> {
    housing::binding(db, instance)
}
pub(crate) fn admin_resolve_asset(
    state: &State,
    kind: &str,
    item: &str,
    gender: Option<&str>,
    category: Option<&str>,
) -> Result<Value> {
    shop::asset(state, kind, item, gender, category)
}
pub(crate) fn admin_account(db: &Connection, account: &str) -> Result<()> {
    let profile = one(
        db,
        "SELECT username FROM profiles WHERE ps4_id=?",
        [account],
    )?
    .ok_or_else(|| Error::new(404, "Account not found"))?;
    crate::character::identity(account, Some(s(&profile, "username")))
}
pub(crate) fn admin_grant_asset(
    state: &State,
    db: &Connection,
    account: &str,
    kind: &str,
    item: &str,
    gender: Option<&str>,
    category: Option<&str>,
) -> Result<()> {
    admin_account(db, account)?;
    shop::grant(state, db, account, kind, item, gender, category, None)
}
pub(crate) fn admin_offer_owned(db: &Connection, account: &str, offer: &Value) -> Result<bool> {
    shop::owned(db, account, offer, &mut HashSet::new())
}
pub(crate) fn admin_grant_offer(
    state: &State,
    db: &Connection,
    account: &str,
    offer: &Value,
    operator: &str,
) -> Result<bool> {
    if admin_offer_owned(db, account, offer)? {
        return Ok(false);
    }
    admin_account(db, account)?;
    db.execute(
        "INSERT OR IGNORE INTO profile_state(ps4_id) VALUES(?)",
        [account],
    )?;
    shop::grant_offer(state, db, account, offer, &mut HashSet::new())?;
    db.execute(
        "INSERT OR IGNORE INTO shop_owned VALUES(?,?,'admin',?,?)",
        rusqlite::params![account, s(offer, "offer_id"), operator, state.now()],
    )?;
    Ok(true)
}
pub(crate) fn admin_asset_catalog(state: &State, kind: &str) -> Result<Vec<Value>> {
    match kind {
        "companions" | "locomotions" => Ok(shop::resource_catalog(state)?
            .into_iter()
            .filter(|((k, _), _)| k == kind)
            .map(|(_, v)| v)
            .collect()),
        "housing" => Ok(housing::catalog(state)?.into_values().collect()),
        "wardrobe" => {
            let catalog = state.catalog("avatar-asset-catalog.json")?;
            let mut result = HashMap::new();
            for row in catalog["items"]
                .as_array()
                .ok_or_else(|| Error::new(500, "Missing wardrobe catalog"))?
            {
                if ["MALE", "FEMALE"].contains(&s(row, "gender"))
                    && s(row, "category") != "UNKNOWN"
                    && !flag(row, "category_conflict")
                {
                    result.insert(
                        (
                            s(row, "item_id").to_string(),
                            s(row, "gender").to_string(),
                            s(row, "category").to_string(),
                        ),
                        row.clone(),
                    );
                }
            }
            Ok(result.into_values().collect())
        }
        _ => Err(Error::bad("Unsupported grant kind")),
    }
}
