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
    read_bounded(p, 8192)
}
fn read_bounded<T: serde::de::DeserializeOwned>(p: &std::path::Path, max: u64) -> Option<T> {
    use std::io::Read;
    let f = fs::File::open(p).ok()?;
    let m = f.metadata().ok()?;
    if m.len() > max || m.len() == 0 {
        return None;
    }
    let mut bytes = Vec::with_capacity(m.len() as usize);
    f.take(max + 1).read_to_end(&mut bytes).ok()?;
    if bytes.len() > max as usize {
        return None;
    }
    serde_json::from_slice(&bytes).ok()
}
fn write_new<T: serde::Serialize>(p: &std::path::Path, v: &T) -> Result<()> {
    use std::io::Write;
    let folder = p
        .parent()
        .ok_or_else(|| Error::bad("invalid_social_path"))?;
    fs::create_dir_all(folder)?;
    let bytes = serde_json::to_vec(v)?;
    let temporary = folder.join(format!(".{}.tmp", uuid::Uuid::new_v4().simple()));
    let mut f = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
    let result = (|| {
        f.write_all(&bytes)?;
        f.sync_all()?;
        drop(f);
        // Same-volume hard-link publication is atomic and refuses to replace an
        // existing immutable message on both Linux and Windows. Readers never
        // observe the partially written staging file (its suffix is not .json).
        fs::hard_link(&temporary, p).map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                Error::bad("notification_already_pending")
            } else {
                error.into()
            }
        })?;
        Ok(())
    })();
    let _ = fs::remove_file(temporary);
    result
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
fn valid_relay(v: &Relay, now: f64) -> bool {
    let guid = |s: &str| {
        s.len() == 32
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    };
    let token = |s: &str, max: usize| {
        !s.is_empty() && s.encode_utf16().count() <= max && !s.contains(['#', '\0'])
    };
    v.format_version == 1
        && guid(&v.event_id)
        && guid(&v.source_guid)
        && guid(&v.target_guid)
        && v.source_guid != v.target_guid
        && super::safe_instance(&v.source_instance)
        && super::safe_instance(&v.target_instance)
        && token(&v.source_account, 128)
        && token(&v.target_account, 128)
        && v.source_account != v.target_account
        && now.is_finite()
        && now >= 0.0
        && v.created_at.is_finite()
        && v.expires_at.is_finite()
        && v.created_at <= now + 5.0
        && v.expires_at > now
        && v.expires_at > v.created_at
        && v.expires_at - v.created_at <= 30.0
        && match v.kind.as_str() {
            "chat" => v.value == 1 && token(&v.text, 4096),
            "request" => matches!(v.value, 0 | 1 | 6) && v.text.is_empty(),
            "accepted" => matches!(v.value, 0 | 1) && v.text.is_empty(),
            "typing" | "stop_typing" => v.value == 0 && v.text.is_empty(),
            "refresh" => (21..=25).contains(&v.value) && v.text.is_empty(),
            _ => false,
        }
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
    let folder = s.state_dir.join("social-relay").join(&target.instance);
    let entry = Relay {
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
    };
    if !valid_relay(&entry, s.now()) || source.instance != instance {
        return Err(Error::bad("social_relay_invalid_envelope"));
    }
    if folder.is_dir()
        && fs::read_dir(&folder)?
            .flatten()
            .filter(|e| e.path().extension().and_then(|x| x.to_str()) == Some("json"))
            .take(512)
            .count()
            >= 512
    {
        return Err(Error::bad("social_relay_capacity"));
    }
    write_new(&folder.join(format!("{}.json", entry.event_id)), &entry)
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
        let claim = p.with_extension(format!("processing.{}", uuid::Uuid::new_v4().simple()));
        if fs::rename(&p, &claim).is_err() {
            continue;
        }
        // JSON may use six bytes per UTF-16 code unit. Use the same bounded
        // envelope size as the preserved C# mailbox, not the small-request cap.
        let data: Option<Relay> = read_bounded(&claim, 32768);
        if let Some(v) = data {
            if valid_relay(&v, s.now())
                && v.target_instance == instance
                && p.file_stem().and_then(|name| name.to_str()) == Some(&v.event_id)
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    };

    const NOW: f64 = 1_800_000_000.0;

    fn envelope() -> Relay {
        Relay {
            format_version: 1,
            event_id: uuid::Uuid::new_v4().simple().to_string(),
            kind: "chat".into(),
            source_guid: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
            target_guid: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".into(),
            source_account: "source-account".into(),
            target_account: "target-account".into(),
            source_instance: "source-instance".into(),
            target_instance: "target-instance".into(),
            value: 1,
            text: "汉".repeat(4096),
            created_at: NOW,
            expires_at: NOW + 15.0,
        }
    }

    fn state() -> (tempfile::TempDir, State) {
        let dir = tempfile::tempdir().unwrap();
        let protocol = std::env::var_os("NEBULA_REFERENCE_PROTOCOL_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../protocol"));
        let mut state = State::open(dir.path(), &protocol).unwrap();
        state.fixed_time = Some(NOW);
        (dir, state)
    }

    #[test]
    fn relay_text_limit_matches_utf16_and_rejects_invalid_envelopes() {
        let original = envelope();
        assert!(valid_relay(&original, NOW));
        for text in ["😀".repeat(2048), "\u{1}".repeat(4096)] {
            let mut next = original.clone();
            next.text = text;
            assert!(valid_relay(&next, NOW));
        }
        for text in [
            "😀".repeat(2049),
            "x".repeat(4097),
            "bad#field".into(),
            "bad\0field".into(),
            String::new(),
        ] {
            let mut next = original.clone();
            next.text = text;
            assert!(!valid_relay(&next, NOW));
        }
        let mut invalid = vec![];
        let mut next = original.clone();
        next.event_id = "../outside".into();
        invalid.push(next);
        let mut next = original.clone();
        next.source_guid = next.target_guid.clone();
        invalid.push(next);
        let mut next = original.clone();
        next.target_instance = "../outside".into();
        invalid.push(next);
        let mut next = original.clone();
        next.kind = "request".into();
        invalid.push(next);
        let mut next = original.clone();
        next.value = 0;
        invalid.push(next);
        let mut next = original.clone();
        next.expires_at = NOW;
        invalid.push(next);
        let mut next = original.clone();
        next.expires_at = NOW + 31.0;
        invalid.push(next);
        let mut next = original.clone();
        next.created_at = f64::NAN;
        invalid.push(next);
        for next in invalid {
            assert!(!valid_relay(&next, NOW));
        }
    }

    #[test]
    fn concurrent_readers_only_observe_complete_immutable_publications() {
        let dir = tempfile::tempdir().unwrap();
        let reader_dir = dir.path().to_owned();
        let finished = Arc::new(AtomicBool::new(false));
        let done = finished.clone();
        let reader = std::thread::spawn(move || {
            let mut seen = std::collections::BTreeSet::new();
            loop {
                let final_pass = done.load(Ordering::Acquire);
                for file in fs::read_dir(&reader_dir).unwrap().flatten() {
                    let path = file.path();
                    if path.extension().and_then(|s| s.to_str()) == Some("json") {
                        let value: serde_json::Value =
                            read_bounded(&path, 32768).expect("published JSON was incomplete");
                        assert_eq!(value["text"].as_str().unwrap().len(), 16384);
                        seen.insert(path);
                    }
                }
                if final_pass {
                    break;
                }
                std::thread::yield_now();
            }
            seen.len()
        });
        for i in 0..64 {
            let path = dir.path().join(format!("{i:032x}.json"));
            write_new(&path, &serde_json::json!({"text":"x".repeat(16384)})).unwrap();
            assert!(write_new(&path, &serde_json::json!({"text":"replacement"})).is_err());
        }
        finished.store(true, Ordering::Release);
        assert_eq!(reader.join().unwrap(), 64);
        assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 64);
    }

    #[test]
    fn drain_claims_unicode_payloads_once_and_discards_bad_or_misnamed_files() {
        let (_dir, state) = state();
        let folder = state.state_dir.join("social-relay/target-instance");
        fs::create_dir_all(&folder).unwrap();
        let good = envelope();
        write_new(&folder.join(format!("{}.json", good.event_id)), &good).unwrap();
        let mut bad = envelope();
        bad.value = 0;
        write_new(&folder.join(format!("{}.json", bad.event_id)), &bad).unwrap();
        let wrong_name = envelope();
        write_new(&folder.join("wrong-name.json"), &wrong_name).unwrap();
        fs::write(folder.join("oversized.json"), vec![b' '; 32769]).unwrap();
        fs::write(folder.join("partial.json"), b"{\"text\":").unwrap();
        let values = drain(&state, "target-instance").unwrap();
        assert_eq!(values.len(), 1);
        assert_eq!(values[0].event_id, good.event_id);
        assert_eq!(values[0].text, good.text);
        assert!(drain(&state, "target-instance").unwrap().is_empty());
        assert_eq!(fs::read_dir(&folder).unwrap().count(), 0);
    }

    #[test]
    fn a_full_mailbox_rejects_new_messages_before_creating_more_state() {
        let (_dir, state) = state();
        let folder = state.state_dir.join("social-relay/target-instance");
        fs::create_dir_all(&folder).unwrap();
        for i in 0..512 {
            fs::write(folder.join(format!("{i:032x}.json")), b"{}").unwrap();
        }
        let account = |guid: &str, id: &str, instance: &str| Account {
            guid: guid.into(),
            id: id.into(),
            username: id.into(),
            platform: "StandaloneWindows".into(),
            instance: instance.into(),
            selected_companion: String::new(),
            selected_locomotion: String::new(),
            companion_revision: 0,
            locomotion_revision: 0,
            wardrobe_active: false,
            wardrobe_instance: String::new(),
            wardrobe_updated: 0.0,
            position: super::super::Vector3::default(),
            position_updated: 0.0,
            muted: false,
        };
        let source = account(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "source",
            "source-instance",
        );
        let target = account(
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "target",
            "target-instance",
        );
        assert_eq!(
            enqueue(
                &state,
                &source,
                &target,
                "source-instance",
                "chat",
                1,
                "hello"
            )
            .unwrap_err()
            .message,
            "social_relay_capacity"
        );
        assert_eq!(fs::read_dir(&folder).unwrap().count(), 512);
        let mut unsafe_target = target;
        unsafe_target.instance = "../outside".into();
        assert_eq!(
            enqueue(
                &state,
                &source,
                &unsafe_target,
                "source-instance",
                "chat",
                1,
                "hello"
            )
            .unwrap_err()
            .message,
            "social_relay_invalid_envelope"
        );
        assert!(!state.state_dir.join("outside").exists());
    }
}
