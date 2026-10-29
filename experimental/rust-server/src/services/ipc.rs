use super::*;
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
const MAX_REVISION: i64 = 9_007_199_254_740_990;
fn hex32(v: &str) -> bool {
    v.len() == 32
        && v.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn instance_id(v: &str) -> bool {
    !v.is_empty()
        && v.len() <= 128
        && v.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn safe_chain(path: &Path) -> bool {
    path.ancestors().all(|p| {
        p.symlink_metadata()
            .map(|m| !m.file_type().is_symlink())
            .unwrap_or(true)
    })
}
fn read(path: &Path, max: u64) -> Option<Value> {
    if !safe_chain(path) {
        return None;
    }
    let m = path.metadata().ok()?;
    if m.len() == 0 || m.len() > max {
        return None;
    }
    let bytes = fs::read(path).ok()?;
    let b = bytes.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(&bytes);
    serde_json::from_slice(b).ok()
}
fn files(root: &Path) -> Vec<PathBuf> {
    let mut out: Vec<_> = fs::read_dir(root)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .collect();
    out.sort();
    out
}
pub(super) fn publish(path: &Path, value: &Value, replace: bool) -> Result<()> {
    if !safe_chain(path) {
        return Err(Error::new(403, "Linked state path is not permitted"));
    }
    let parent = path
        .parent()
        .ok_or_else(|| Error::bad("Invalid publication path"))?;
    fs::create_dir_all(parent)?;
    let temp = parent.join(format!(".{}.tmp", uuid()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    let bytes = js(value);
    file.write_all(bytes.as_bytes())?;
    file.sync_all()?;
    drop(file);
    // A hard link installs one immutable handoff file without overwrite. The
    // temporary and final names are on the same volume and contain no secrets.
    let result = if replace {
        fs::rename(&temp, path)
    } else {
        fs::hard_link(&temp, path)
    };
    let _ = fs::remove_file(&temp);
    result?;
    Ok(())
}
pub(super) fn enqueue(
    state: &State,
    db: &Connection,
    target: &str,
    source: &Value,
    kind: i64,
    args: &str,
    dedupe: &str,
) -> Result<String> {
    token(
        s(source, "username"),
        "notification source name",
        512,
        false,
    )?;
    token(args, "notification arguments", 512, true)?;
    token(dedupe, "notification dedupe key", 2048, false)?;
    let plat = platform_num(s(source, "platform"))?;
    if let Some(old) = one(
        db,
        "SELECT * FROM notification_outbox WHERE target_ps4_id=? AND dedupe_key=?",
        rusqlite::params![target, dedupe],
    )? {
        if s(&old, "source_username") != s(source, "username")
            || n(&old, "source_platform") != plat
            || n(&old, "notification_type") != kind
            || s(&old, "arguments") != args
        {
            return Err(Error::new(
                409,
                "Notification dedupe key has a different payload",
            ));
        }
        return Ok(s(&old, "event_id").into());
    }
    let now = state.now();
    let ticks = 621_355_968_000_000_000_i64 + (now * 10_000_000.) as i64;
    if !(0..=3_155_378_975_999_999_999).contains(&ticks) {
        return Err(Error::bad(
            "Notification timestamp is outside native DateTime range",
        ));
    }
    let id = uuid();
    db.execute(
        "INSERT INTO notification_outbox VALUES(?,?,?,?,?,?,?,?,?,NULL)",
        rusqlite::params![
            id,
            target,
            s(source, "username"),
            plat,
            kind,
            args,
            ticks,
            dedupe,
            now
        ],
    )?;
    Ok(id)
}
fn selected(db: &Connection, id: &str, kind: &str) -> Result<(String, i64)> {
    let r = one(
        db,
        "SELECT item_id,revision FROM resource_selections WHERE ps4_id=? AND kind=?",
        rusqlite::params![id, kind],
    )?;
    Ok(r.map(|r| (s(&r, "item_id").into(), n(&r, "revision")))
        .unwrap_or_default())
}
fn owned(state: &State, db: &Connection, id: &str, kind: &str, item: &str) -> Result<bool> {
    if item.is_empty() {
        return Ok(true);
    }
    if let Err(e) = shop::asset(state, kind, item, None, None) {
        if [400, 404, 409].contains(&e.status) {
            return Ok(false);
        }
        return Err(e);
    }
    Ok(db.query_row("SELECT EXISTS(SELECT 1 FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?)",rusqlite::params![id,kind,item],|r|r.get(0))?)
}
fn selection_snapshot(state: &State, db: &Connection, id: &str) -> Result<Value> {
    let mut result = json!({});
    for (kind, stem) in [("companions", "companion"), ("locomotions", "locomotion")] {
        let (mut item, mut rev) = selected(db, id, kind)?;
        if !item.is_empty() && !owned(state, db, id, kind, &item)? {
            if rev >= MAX_REVISION {
                return Err(Error::new(409, "resource_selection_revision_exhausted"));
            }
            rev += 1;
            item.clear();
            db.execute("UPDATE resource_selections SET item_id='',revision=?,updated_at=? WHERE ps4_id=? AND kind=?",rusqlite::params![rev,state.now(),id,kind])?;
        }
        result[format!("selected_{stem}")] = json!(item);
        result[format!("{stem}_revision")] = json!(rev);
    }
    Ok(result)
}
pub fn resource_selection_snapshot(state: &State, actor: &str) -> Result<Value> {
    let mut db = state.connection()?;
    let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let out = selection_snapshot(state, &tx, actor)?;
    tx.commit()?;
    Ok(out)
}
fn normalize_selections(state: &State, db: &Connection) -> Result<()> {
    let selections=rows(db,"SELECT r.*,EXISTS(SELECT 1 FROM resource_entitlements e WHERE e.ps4_id=r.ps4_id AND e.kind=r.kind AND e.item_id=r.item_id) AS owned FROM resource_selections r WHERE r.item_id!=''",[])?;
    if selections.is_empty() {
        return Ok(());
    }
    let catalog = shop::resource_catalog(state)?;
    for r in selections {
        if flag(&r, "owned")
            && catalog.contains_key(&(s(&r, "kind").into(), s(&r, "item_id").into()))
        {
            continue;
        }
        let revision = n(&r, "revision");
        if revision >= MAX_REVISION {
            return Err(Error::new(409, "resource_selection_revision_exhausted"));
        }
        db.execute("UPDATE resource_selections SET item_id='',revision=?,updated_at=? WHERE ps4_id=? AND kind=?",rusqlite::params![revision+1,state.now(),s(&r,"ps4_id"),s(&r,"kind")])?;
    }
    Ok(())
}
fn validate_selection(v: &Value, instance: &str) -> Result<()> {
    let keys = [
        "format_version",
        "request_id",
        "guid",
        "instance_id",
        "instance_owner",
        "kind",
        "item_id",
        "expected_revision",
        "created_at",
        "expires_at",
    ];
    if v.as_object()
        .is_none_or(|m| m.len() != keys.len() || !keys.iter().all(|k| m.contains_key(*k)))
    {
        return Err(Error::bad("resource_selection_schema"));
    }
    if v["format_version"] != 1
        || !hex32(s(v, "request_id"))
        || !hex32(s(v, "guid"))
        || !hex32(s(v, "instance_owner"))
        || !instance_id(instance)
        || s(v, "instance_id") != instance
        || !["companions", "locomotions"].contains(&s(v, "kind"))
        || !v["item_id"].is_string()
        || (!s(v, "item_id").is_empty()
            && (s(v, "item_id").len() > 128
                || !s(v, "item_id").bytes().all(|b| b.is_ascii_alphanumeric())))
        || v["expected_revision"]
            .as_i64()
            .is_none_or(|r| r < 0 || r >= MAX_REVISION)
    {
        return Err(Error::bad("resource_selection_fields"));
    }
    let created = v["created_at"]
        .as_f64()
        .filter(|v| v.is_finite() && *v >= 0.)
        .ok_or_else(|| Error::bad("resource_selection_clock"))?;
    let expires = v["expires_at"]
        .as_f64()
        .filter(|v| v.is_finite() && *v >= 0.)
        .ok_or_else(|| Error::bad("resource_selection_clock"))?;
    if expires <= created || expires - created > 15. {
        return Err(Error::bad("resource_selection_lifetime"));
    }
    Ok(())
}
fn process_selection(
    state: &State,
    db: &Connection,
    v: &Value,
    instance: &str,
    now: f64,
) -> Result<Value> {
    validate_selection(v, instance)?;
    let digest = hash(&ascii_json(v));
    if let Some(old) = one(
        db,
        "SELECT digest,response_json FROM resource_selection_receipts WHERE request_id=?",
        [s(v, "request_id")],
    )? {
        if s(&old, "digest") != digest {
            return Err(Error::new(409, "resource_selection_replay_conflict"));
        }
        return Ok(serde_json::from_str(s(&old, "response_json"))?);
    }
    let mut out = json!({"format_version":1,"request_id":v["request_id"],"guid":v["guid"],"instance_id":instance,"instance_owner":v["instance_owner"],"kind":v["kind"],"item_id":v["item_id"],"expected_revision":v["expected_revision"],"revision":v["expected_revision"],"status":"rejected","reason":"session_or_allocation_stale"});
    let actor=one(db,"SELECT s.ps4_id,a.psidglobal FROM sessions s JOIN allocations a USING(guid) WHERE s.guid=? AND a.instance_id=? AND NOT EXISTS(SELECT 1 FROM sessions n WHERE n.ps4_id=s.ps4_id AND (n.created_at>s.created_at OR(n.created_at=s.created_at AND n.guid>s.guid)))",rusqlite::params![s(v,"guid"),instance])?;
    if !(v["created_at"].as_f64().unwrap() <= now && now < v["expires_at"].as_f64().unwrap()) {
        out["reason"] = json!("request_expired_or_future");
    } else if let Some(actor) = actor {
        let path = state
            .state_dir
            .join("instances")
            .join(instance)
            .join("instance-status.json");
        let lease = read(&path, 65536).is_some_and(|lease| {
            let age = now - lease["heartbeat"].as_f64().unwrap_or(-1.);
            s(&lease, "instance_id") == instance
                && lease["owner"] == v["instance_owner"]
                && s(&lease, "psidglobal") == s(&actor, "psidglobal")
                && lease["listening"] == true
                && lease["listener_bound"] == true
                && (0.0..=15.).contains(&age)
        });
        if !lease {
            out["reason"] = json!("instance_lease_not_current");
        } else {
            let id = s(&actor, "ps4_id");
            let (_, rev) = selected(db, id, s(v, "kind"))?;
            out["revision"] = json!(rev);
            if rev != n(v, "expected_revision") {
                out["reason"] = json!("revision_conflict");
            } else if !owned(state, db, id, s(v, "kind"), s(v, "item_id"))? {
                out["reason"] = json!("resource_not_owned");
            } else {
                db.execute("INSERT INTO resource_selections VALUES(?,?,?,?,?) ON CONFLICT(ps4_id,kind) DO UPDATE SET item_id=excluded.item_id,revision=excluded.revision,updated_at=excluded.updated_at",rusqlite::params![id,s(v,"kind"),s(v,"item_id"),rev+1,now])?;
                out["status"] = json!("committed");
                out["reason"] = json!("");
                out["revision"] = json!(rev + 1);
            }
        }
    }
    db.execute(
        "INSERT INTO resource_selection_receipts VALUES(?,?,?,?)",
        rusqlite::params![s(v, "request_id"), digest, ascii_json(&out), now],
    )?;
    Ok(out)
}
pub fn process_resource_selection(
    state: &State,
    value: &Value,
    instance: &str,
    now: Option<f64>,
) -> Result<Value> {
    let mut db = state.connection()?;
    let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let out = process_selection(
        state,
        &tx,
        value,
        instance,
        now.unwrap_or_else(|| state.now()),
    )?;
    tx.commit()?;
    Ok(out)
}
pub(super) fn import_events(state: &State, db: &Connection) -> Result<()> {
    // Readers ignore invalid IPC documents; only fully correlated receipts may
    // move authority. Per-document savepoints isolate malformed peers.
    import_friends(state, db)?;
    for path in files(&state.state_dir.join("consumable-claims")) {
        let Some(v) = read(&path, 16384) else {
            continue;
        };
        let id = s(&v, "receipt_id");
        if !hex32(id)
            || path.file_name().and_then(|s| s.to_str()) != Some(&format!("{id}.json"))
            || v["format_version"] != 1
            || v["policy"] != "local_consumable_receipt_v1"
        {
            continue;
        }
        let Some(row) = one(
            db,
            "SELECT * FROM consumable_receipts WHERE receipt_id=?",
            [id],
        )?
        else {
            continue;
        };
        let keys = [
            "ps4_id",
            "guid",
            "kind",
            "table_id",
            "use_count",
            "reward_index",
            "issued_at",
            "expires_at",
        ];
        if !keys.iter().all(|key| row[*key] == v[*key])
            || !["prepared", "pending", "claimed"].contains(&s(&row, "status"))
        {
            continue;
        }
        db.execute("UPDATE consumable_receipts SET status='claimed',claimed_at=COALESCE(claimed_at,?) WHERE receipt_id=?",rusqlite::params![state.now(),id])?;
    }
    for path in files(&state.state_dir.join("notification-acks")) {
        let Some(v) = read(&path, 16384) else {
            continue;
        };
        let id = s(&v, "event_id");
        let guid = s(&v, "guid");
        let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("");
        if !hex32(id)
            || !(stem == id || stem == format!("{id}-{guid}"))
            || v["format_version"] != 1
            || v.as_object().is_none_or(|m| m.len() != 8)
        {
            continue;
        }
        let Some(at) = v["accepted_at"]
            .as_f64()
            .filter(|v| v.is_finite() && *v >= 0. && *v <= state.now() + 30.)
        else {
            continue;
        };
        if !current(db, s(&v, "target_ps4_id"), guid)? {
            continue;
        }
        let Some(row) = one(
            db,
            "SELECT * FROM notification_outbox WHERE event_id=?",
            [id],
        )?
        else {
            continue;
        };
        if ![
            "target_ps4_id",
            "source_username",
            "source_platform",
            "notification_type",
        ]
        .iter()
        .all(|k| row[*k] == v[*k])
        {
            continue;
        }
        db.execute(
            "UPDATE notification_outbox SET accepted_at=COALESCE(accepted_at,?) WHERE event_id=?",
            rusqlite::params![at, id],
        )?;
    }
    Ok(())
}
fn import_friends(state: &State, db: &Connection) -> Result<()> {
    let mut pending = Vec::new();
    for path in files(&state.state_dir.join("friend-events")) {
        let Some(mut v) = read(&path, 16384) else {
            continue;
        };
        let supplied = s(&v, "event_id");
        let Ok(id) = uuid::Uuid::parse_str(supplied) else {
            continue;
        };
        let id = id.hyphenated().to_string();
        if supplied != id && supplied != id.replace('-', "") {
            continue;
        }
        if path.file_name().and_then(|s| s.to_str()) != Some(&format!("{supplied}.json"))
            || v["format_version"] != 1
            || v["policy"] != "correlated_online_request_v1"
            || !["accept_friendship", "remove_friendship"].contains(&s(&v, "operation"))
            || v["created_at"]
                .as_f64()
                .is_none_or(|x| !x.is_finite() || x < 0.)
            || !v["actor_ps4_id"].is_string()
            || !v["other_ps4_id"].is_string()
        {
            continue;
        }
        if one(db, "SELECT 1 FROM friend_events WHERE event_id=?", [&id])?.is_some() {
            continue;
        }
        v["event_id"] = json!(id);
        pending.push(v);
        if pending.len() >= 4096 {
            break;
        }
    }
    pending.sort_by(|a, b| {
        a["created_at"]
            .as_f64()
            .unwrap()
            .total_cmp(&b["created_at"].as_f64().unwrap())
            .then(
                (s(a, "operation") == "remove_friendship")
                    .cmp(&(s(b, "operation") == "remove_friendship")),
            )
            .then(s(a, "event_id").cmp(s(b, "event_id")))
    });
    for v in pending {
        let id = s(&v, "event_id");
        if one(db, "SELECT 1 FROM friend_events WHERE event_id=?", [id])?.is_some() {
            continue;
        }
        let actor = s(&v, "actor_ps4_id");
        let other = s(&v, "other_ps4_id");
        if actor == other {
            continue;
        }
        let Some(a) = one(db, "SELECT * FROM profiles WHERE ps4_id=?", [actor])? else {
            continue;
        };
        let Some(b) = one(db, "SELECT * FROM profiles WHERE ps4_id=?", [other])? else {
            continue;
        };
        let latest=one(db,"SELECT created_at,operation,event_id FROM friend_events WHERE(actor_ps4_id=? AND other_ps4_id=?)OR(actor_ps4_id=? AND other_ps4_id=?) ORDER BY created_at DESC,(operation='remove_friendship') DESC,event_id DESC LIMIT 1",rusqlite::params![actor,other,other,actor])?;
        let key = |x: &Value| {
            (
                x["created_at"].as_f64().unwrap_or(0.),
                s(x, "operation") == "remove_friendship",
                s(x, "event_id").to_string(),
            )
        };
        let newer = latest.is_none_or(|x| key(&v) > key(&x));
        if newer {
            for (owner, target) in [(&a, &b), (&b, &a)] {
                if s(&v, "operation") == "remove_friendship" {
                    db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind IN('friend','favorite')",rusqlite::params![s(owner,"ps4_id"),s(target,"username"),platform(s(target,"platform"))?])?;
                } else {
                    db.execute(
                        "INSERT OR IGNORE INTO relations VALUES(?,?,?,'friend')",
                        rusqlite::params![
                            s(owner, "ps4_id"),
                            s(target, "username"),
                            platform(s(target, "platform"))?
                        ],
                    )?;
                }
            }
        }
        db.execute(
            "INSERT INTO friend_events VALUES(?,?,?,?,?,?)",
            rusqlite::params![
                id,
                s(&v, "operation"),
                actor,
                other,
                v["created_at"].as_f64().unwrap(),
                state.now()
            ],
        )?;
    }
    Ok(())
}
/// Called periodically by runtime; commits selections before publishing acks.
pub fn pump(state: &State) -> Result<usize> {
    if !safe_chain(&state.state_dir) || !safe_chain(&state.state_dir.join("instances")) {
        return Err(Error::bad("linked_resource_selection_root"));
    }
    {
        let mut db = state.connection()?;
        let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        import_events(state, &tx)?;
        normalize_selections(state, &tx)?;
        tx.commit()?;
    }
    let mut count = 0;
    let mut folders: Vec<_> = fs::read_dir(state.state_dir.join("instances"))
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .collect();
    folders.sort();
    'folders: for folder in folders {
        let Some(instance) = folder.file_name().and_then(|v| v.to_str()) else {
            continue;
        };
        if !instance_id(instance) {
            continue;
        }
        let selections = folder.join("resource-selections");
        for path in files(&selections)
            .into_iter()
            .filter(|p| {
                p.file_name()
                    .is_some_and(|n| n.to_string_lossy().ends_with(".request.json"))
            })
            .take(128)
        {
            if count >= 512 {
                break 'folders;
            }
            count += 1;
            let Some(v) = read(&path, 4096) else {
                continue;
            };
            if path.file_name().and_then(|p| p.to_str())
                != Some(&format!("{}.request.json", s(&v, "request_id")))
            {
                continue;
            }
            if let Ok(response) = process_resource_selection(state, &v, instance, None) {
                let ack = selections.join(format!("{}.ack.json", s(&v, "request_id")));
                publish(&ack, &response, true)?;
                if state.now() > v["expires_at"].as_f64().unwrap_or(f64::MAX) + 30. {
                    let _ = fs::remove_file(&path);
                    let _ = fs::remove_file(ack);
                }
            }
        }
    }
    let entries = {
        let db = state.connection()?;
        rows(&db,"SELECT event_id,target_ps4_id,source_username,source_platform,notification_type,arguments,ticks FROM notification_outbox WHERE accepted_at IS NULL ORDER BY created_at,event_id",[])?
    };
    if entries.len() > 10000 {
        return Err(Error::new(
            503,
            "Notification snapshot exceeds local capacity",
        ));
    }
    publish(
        &state.state_dir.join("instance-notifications.json"),
        &json!({"format_version":1,"generation":state.now(),"entries":entries}),
        true,
    )?;
    Ok(count)
}
