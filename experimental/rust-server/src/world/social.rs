use super::accounts::Account;
use crate::{
    error::{Error, Result},
    state::State,
};
use rusqlite::{params, OptionalExtension};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, path::PathBuf};

#[derive(Clone, Copy, Default, Debug, PartialEq, Eq)]
pub(super) struct Relation {
    pub friend: bool,
    pub favorite: bool,
    pub ignored: bool,
    pub silent_by: bool,
    pub blocked: bool,
    pub blocked_by: bool,
}
impl Relation {
    pub fn codes(self) -> Vec<i32> {
        if self.blocked {
            return vec![5];
        }
        if self.blocked_by {
            return vec![6];
        }
        let mut v = Vec::new();
        if self.ignored {
            v.push(3);
        } else if self.silent_by {
            v.push(4);
        }
        if self.friend {
            v.push(1);
        }
        if self.favorite {
            v.push(2);
        }
        if v.is_empty() {
            v.push(0);
        }
        v
    }
    pub fn transition(self, next: Self) -> (bool, Vec<i32>) {
        let reseed = ((self.blocked || self.blocked_by) && !(next.blocked || next.blocked_by))
            || (self.favorite && !next.favorite);
        let mut codes = next.codes();
        if !reseed
            && ((self.friend && !next.friend)
                || (self.ignored && !next.ignored)
                || (self.silent_by && !next.silent_by)
                || (self.blocked && !next.blocked)
                || (self.blocked_by && !next.blocked_by))
            && codes != [0]
        {
            codes.insert(0, 0);
        }
        (reseed, codes)
    }
}
pub(super) fn relation(s: &State, a: &Account, b: &Account) -> Result<Relation> {
    let db = s.connection()?;
    let mut stmt =
        db.prepare("SELECT kind FROM relations WHERE ps4_id=? AND target=? AND target_platform=?")?;
    let forward: Vec<String> = stmt
        .query_map(params![a.id, b.username, b.platform], |r| r.get(0))?
        .collect::<std::result::Result<_, _>>()?;
    let reverse: Vec<String> = stmt
        .query_map(params![b.id, a.username, a.platform], |r| r.get(0))?
        .collect::<std::result::Result<_, _>>()?;
    let has = |v: &Vec<String>, k: &str| v.iter().any(|s| s == k);
    Ok(Relation {
        friend: has(&forward, "friend"),
        favorite: has(&forward, "favorite"),
        ignored: has(&forward, "silenced"),
        silent_by: has(&reverse, "silenced"),
        blocked: has(&forward, "block"),
        blocked_by: has(&reverse, "block"),
    })
}
pub(super) fn can_receive(s: &State, recipient: &Account, sender: &Account) -> Result<bool> {
    if recipient.id == sender.id {
        return Ok(true);
    }
    let r = relation(s, recipient, sender)?;
    Ok(!r.blocked && !r.blocked_by && !r.ignored)
}
fn pair(a: &str, b: &str) -> String {
    if a < b {
        format!("{a}\0{b}")
    } else {
        format!("{b}\0{a}")
    }
}
fn digest(v: &str) -> String {
    hex::encode(Sha256::digest(v.as_bytes()))
}
fn pending_path(s: &State, source: &str, target: &str, t: i32) -> PathBuf {
    s.state_dir.join("social-requests").join(format!(
        "{}.json",
        digest(&format!("{source}\0{target}\0{t}"))
    ))
}
fn grant_path(s: &State, a: &str, b: &str) -> PathBuf {
    s.state_dir
        .join("social-chat-grants")
        .join(format!("{}.json", digest(&pair(a, b))))
}
#[derive(serde::Serialize, serde::Deserialize)]
struct Pending {
    format_version: i32,
    source_guid: String,
    target_guid: String,
    source_account: String,
    target_account: String,
    #[serde(rename = "type")]
    kind: i32,
    expires_at: f64,
}
#[derive(serde::Serialize, serde::Deserialize)]
struct Grant {
    format_version: i32,
    a: String,
    b: String,
    expires_at: f64,
}
fn read_small<T: serde::de::DeserializeOwned>(p: &std::path::Path) -> Option<T> {
    let m = fs::metadata(p).ok()?;
    if m.len() > 8192 || m.len() == 0 {
        return None;
    }
    serde_json::from_slice(&fs::read(p).ok()?).ok()
}
fn write_new<T: serde::Serialize>(p: &std::path::Path, v: &T) -> Result<()> {
    use std::io::Write;
    fs::create_dir_all(
        p.parent()
            .ok_or_else(|| Error::bad("invalid_social_path"))?,
    )?;
    let mut f = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(p)
        .map_err(|_| Error::bad("notification_already_pending"))?;
    f.write_all(&serde_json::to_vec(v)?)?;
    f.sync_all()?;
    Ok(())
}
pub(super) fn can_private(s: &State, a: &Account, b: &Account) -> Result<bool> {
    if !can_receive(s, a, b)? || !can_receive(s, b, a)? {
        return Ok(false);
    }
    if relation(s, a, b)?.friend || relation(s, b, a)?.friend {
        return Ok(true);
    }
    let grant: Option<Grant> = read_small(&grant_path(s, &a.guid, &b.guid));
    Ok(grant.is_some_and(|g| {
        g.format_version == 1
            && g.expires_at > s.now()
            && pair(&g.a, &g.b) == pair(&a.guid, &b.guid)
    }))
}
pub(super) fn request(s: &State, a: &Account, b: &Account, kind: i32) -> Result<()> {
    if a.id == b.id {
        return Err(Error::bad("notification_to_self"));
    }
    if !matches!(kind, 0 | 1 | 6) {
        return Err(Error::bad("unsupported_notification_type"));
    }
    if !can_receive(s, b, a)? {
        return Err(Error::bad("notification_relation_denied"));
    }
    expire(s, None)?;
    let dir = s.state_dir.join("social-requests");
    if dir.is_dir() && fs::read_dir(&dir)?.take(257).count() >= 256 {
        return Err(Error::bad("notification_capacity"));
    }
    write_new(
        &pending_path(s, &a.guid, &b.guid, kind),
        &Pending {
            format_version: 1,
            source_guid: a.guid.clone(),
            target_guid: b.guid.clone(),
            source_account: a.id.clone(),
            target_account: b.id.clone(),
            kind,
            expires_at: s.now() + 300.0,
        },
    )
}
pub(super) fn cancel(s: &State, a: &Account, b: &Account, kind: i32) {
    let _ = fs::remove_file(pending_path(s, &a.guid, &b.guid, kind));
}
pub(super) fn accept(s: &State, acceptor: &Account, requester: &Account, kind: i32) -> Result<()> {
    if !matches!(kind, 0 | 1) {
        return Err(Error::bad("unsupported_notification_acceptance"));
    }
    let path = pending_path(s, &requester.guid, &acceptor.guid, kind);
    let p: Pending =
        read_small(&path).ok_or_else(|| Error::bad("uncorrelated_notification_acceptance"))?;
    if p.format_version != 1
        || p.expires_at <= s.now()
        || p.kind != kind
        || p.source_guid != requester.guid
        || p.target_guid != acceptor.guid
        || p.source_account != requester.id
        || p.target_account != acceptor.id
    {
        return Err(Error::bad("uncorrelated_notification_acceptance"));
    }
    if !can_receive(s, acceptor, requester)? || !can_receive(s, requester, acceptor)? {
        return Err(Error::bad("notification_relation_denied"));
    }
    let claim = path.with_extension(format!("claim.{}", uuid::Uuid::new_v4().simple()));
    fs::rename(&path, &claim).map_err(|_| Error::bad("uncorrelated_notification_acceptance"))?;
    let result = if kind == 1 {
        friendship(s, acceptor, requester, true)
    } else {
        let target = grant_path(s, &acceptor.guid, &requester.guid);
        let _ = fs::remove_file(&target);
        write_new(
            &target,
            &Grant {
                format_version: 1,
                a: acceptor.guid.clone(),
                b: requester.guid.clone(),
                expires_at: s.now() + 86400.0,
            },
        )
    };
    if result.is_err() {
        let _ = fs::rename(&claim, &path);
    } else {
        let _ = fs::remove_file(claim);
    }
    result
}
pub(super) fn friendship(s: &State, a: &Account, b: &Account, enable: bool) -> Result<()> {
    if a.id == b.id {
        return Err(Error::bad("social_target_is_self"));
    }
    let mut db = s.connection()?;
    let tx = db.transaction()?;
    for (owner, target) in [(a, b), (b, a)] {
        if enable {
            tx.execute(
                "INSERT OR IGNORE INTO relations VALUES(?,?,?,'friend')",
                params![owner.id, target.username, target.platform],
            )?;
        } else {
            tx.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind IN ('friend','favorite')",params![owner.id,target.username,target.platform])?;
        }
    }
    let event = uuid::Uuid::new_v4().simple().to_string();
    tx.execute(
        "INSERT INTO friend_events VALUES(?,?,?,?,?,?)",
        params![
            event,
            if enable {
                "accept_friendship"
            } else {
                "remove_friendship"
            },
            a.id,
            b.id,
            s.now(),
            s.now()
        ],
    )?;
    tx.commit()?;
    Ok(())
}
// 22..25 are post-HTTP publications. The authoritative value must already match;
// a forged callback cannot persist a relationship mutation.
pub(super) fn validate_refresh(s: &State, a: &Account, b: &Account, opcode: i32) -> Result<()> {
    let r = relation(s, a, b)?;
    let valid = match opcode {
        22 => !r.ignored,
        23 => r.ignored,
        24 => r.blocked,
        25 => !r.blocked,
        _ => false,
    };
    if valid {
        Ok(())
    } else {
        Err(Error::bad("relationship_http_state_mismatch"))
    }
}
pub(super) fn expire(s: &State, disconnected: Option<&str>) -> Result<()> {
    for folder in ["social-requests", "social-chat-grants"] {
        let dir = s.state_dir.join(folder);
        if !dir.is_dir() {
            continue;
        }
        for entry in fs::read_dir(dir)?.take(4096).flatten() {
            let p = entry.path();
            if p.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let remove = if folder == "social-requests" {
                match read_small::<Pending>(&p) {
                    Some(v) => {
                        v.format_version != 1
                            || v.expires_at <= s.now()
                            || disconnected
                                .is_some_and(|g| g == v.source_guid || g == v.target_guid)
                    }
                    None => true,
                }
            } else {
                match read_small::<Grant>(&p) {
                    Some(v) => {
                        v.format_version != 1
                            || v.expires_at <= s.now()
                            || disconnected.is_some_and(|g| g == v.a || g == v.b)
                    }
                    None => true,
                }
            };
            if remove {
                let _ = fs::remove_file(p);
            }
        }
    }
    Ok(())
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub(super) struct Relay {
    pub format_version: i32,
    pub event_id: String,
    pub kind: String,
    pub source_guid: String,
    pub target_guid: String,
    pub source_account: String,
    pub target_account: String,
    pub source_instance: String,
    pub target_instance: String,
    pub value: i32,
    pub text: String,
    pub created_at: f64,
    pub expires_at: f64,
}
pub(super) fn enqueue(
    s: &State,
    source: &Account,
    target: &Account,
    instance: &str,
    kind: &str,
    value: i32,
    text: &str,
) -> Result<()> {
    let event = uuid::Uuid::new_v4().simple().to_string();
    let p = s
        .state_dir
        .join("social-relay")
        .join(&target.instance)
        .join(format!("{event}.json"));
    write_new(
        &p,
        &Relay {
            format_version: 1,
            event_id: event,
            kind: kind.into(),
            source_guid: source.guid.clone(),
            target_guid: target.guid.clone(),
            source_account: source.id.clone(),
            target_account: target.id.clone(),
            source_instance: instance.into(),
            target_instance: target.instance.clone(),
            value,
            text: text.into(),
            created_at: s.now(),
            expires_at: s.now() + 15.0,
        },
    )
}
pub(super) fn drain(s: &State, instance: &str) -> Result<Vec<Relay>> {
    let dir = s.state_dir.join("social-relay").join(instance);
    if !dir.is_dir() {
        return Ok(vec![]);
    }
    let mut entries: BTreeMap<String, PathBuf> = BTreeMap::new();
    for entry in fs::read_dir(dir)?.take(4096).flatten() {
        let p = entry.path();
        if p.extension().and_then(|s| s.to_str()) == Some("json") {
            entries.insert(entry.file_name().to_string_lossy().into_owned(), p);
        }
    }
    let mut out = Vec::new();
    for (_, p) in entries.into_iter().take(128) {
        let data: Option<Relay> = read_small(&p);
        let claim = p.with_extension("processing");
        if fs::rename(&p, &claim).is_err() {
            continue;
        }
        if let Some(v) = data {
            if v.format_version == 1
                && v.target_instance == instance
                && v.created_at <= s.now() + 5.0
                && v.expires_at > s.now()
                && v.expires_at - v.created_at <= 15.0
                && v.text.len() <= 4096
            {
                out.push(v);
            }
        }
        let _ = fs::remove_file(claim);
    }
    Ok(out)
}

pub(super) fn notification_rows(
    s: &State,
    target: &Account,
) -> Result<Vec<(String, String, i32, i32, String, i64)>> {
    let db = s.connection()?;
    let mut q=db.prepare("SELECT event_id,source_username,source_platform,notification_type,arguments,ticks FROM notification_outbox WHERE target_ps4_id=? AND accepted_at IS NULL ORDER BY created_at,event_id LIMIT 128")?;
    let v = q
        .query_map([&target.id], |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
                r.get(5)?,
            ))
        })?
        .collect::<std::result::Result<_, _>>()?;
    Ok(v)
}
pub(super) fn accept_gift(
    s: &State,
    a: &Account,
    name: &str,
    kind: i32,
    platform: i32,
    delivered: &std::collections::BTreeSet<String>,
) -> Result<()> {
    let mut db = s.connection()?;
    let tx = db.transaction()?;
    let event:Option<String>=tx.query_row("SELECT event_id FROM notification_outbox WHERE target_ps4_id=? AND source_username=? AND source_platform=? AND notification_type=? AND accepted_at IS NULL ORDER BY created_at,event_id LIMIT 1",params![a.id,name,platform,kind],|r|r.get(0)).optional()?;
    let event = event
        .filter(|e| delivered.contains(e))
        .ok_or_else(|| Error::bad("uncorrelated_gift_notification_acceptance"))?;
    tx.execute(
        "UPDATE notification_outbox SET accepted_at=? WHERE event_id=? AND accepted_at IS NULL",
        params![s.now(), event],
    )?;
    tx.commit()?;
    Ok(())
}
