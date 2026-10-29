//! Semantic interaction IDs are per-client namespaces. Trusted descriptors bind
//! them to scene/furniture keys before any occupancy or generic relay is sent.
use crate::error::{Error, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use std::collections::{BTreeMap, BTreeSet};
type Delivery = (String, String);
#[derive(Clone, Debug, serde::Deserialize, PartialEq)]
pub(super) struct Entry {
    kind: String,
    anchor: String,
    #[serde(rename = "class")]
    class_name: String,
    item_id: String,
    path: Vec<i32>,
    slot: i32,
    ground_index: i32,
    #[serde(default)]
    classification: String,
    #[serde(default)]
    extension_arity: i32,
    #[serde(default)]
    send_id: i32,
    #[serde(default)]
    receive_id: i32,
}
#[derive(Clone, Debug, serde::Deserialize, PartialEq)]
struct Ground {
    item_id: String,
    index: i32,
    tx: f32,
    ty: f32,
    tz: f32,
    r: f32,
}
#[derive(Clone, Debug, serde::Deserialize)]
struct Trusted {
    instance_id: String,
    scene: String,
    epoch: String,
    trusted: bool,
    static_profile_available: bool,
    static_entries: Vec<Entry>,
    furniture_entries: Vec<Entry>,
    ground_sig: Vec<Ground>,
}
#[derive(serde::Deserialize)]
struct Root {
    format_version: i32,
    instances: Vec<Trusted>,
}
#[derive(Clone, serde::Deserialize)]
struct Document {
    v: i32,
    source: String,
    scene: String,
    seq: i64,
    entries: Vec<Entry>,
    ground_sig: Vec<Ground>,
}
#[derive(Clone)]
struct Bound {
    key: String,
    kind: String,
    send: i32,
    receive: i32,
}
#[derive(Default)]
struct Peer {
    opted: bool,
    static_ready: bool,
    furniture_ready: bool,
    seq: i64,
    initial: Vec<Bound>,
    furniture: Vec<Bound>,
    queued: Vec<(i32, Vec<String>)>,
    pending: Option<(String, f64)>,
    chunks: Option<Chunks>,
}
struct Chunks {
    seq: i64,
    parts: i32,
    next: i32,
    until: f64,
    bytes: Vec<u8>,
}
#[derive(Default)]
pub(super) struct Registry {
    trusted: Option<Trusted>,
    peers: BTreeMap<String, Peer>,
    generic: BTreeMap<String, (bool, String, Vec<String>)>,
    occupants: BTreeMap<String, String>,
}
impl Registry {
    pub fn require(&mut self, g: &str) {
        self.peer(g).opted = true;
    }
    pub fn opted(&self, g: &str) -> bool {
        self.peers.get(g).is_some_and(|p| p.opted)
    }
    pub fn ready(&self, g: &str) -> bool {
        self.trusted.is_some()
            && self
                .peers
                .get(g)
                .is_some_and(|p| p.static_ready && p.furniture_ready)
    }
    pub fn trusted(&self) -> bool {
        self.trusted.is_some()
    }
    fn peer(&mut self, g: &str) -> &mut Peer {
        self.peers.entry(g.into()).or_insert_with(|| Peer {
            seq: -1,
            ..Peer::default()
        })
    }
    fn invalidate(&mut self) {
        self.trusted = None;
        self.generic.clear();
        self.occupants.clear();
        for p in self.peers.values_mut() {
            p.static_ready = false;
            p.furniture_ready = false;
            p.initial.clear();
            p.furniture.clear();
            p.pending = None;
        }
    }
    pub fn refresh(&mut self, json: &[u8], instance: &str, scene: &str) -> Result<Vec<String>> {
        let result = (|| {
            if json.len() > 32 * 1024 * 1024 {
                return Err(Error::bad("registry_trust_snapshot_invalid"));
            }
            let root: Root = serde_json::from_slice(json)?;
            if root.format_version != 1 {
                return Err(Error::bad("registry_trust_snapshot_invalid"));
            }
            let mut matches = root
                .instances
                .into_iter()
                .filter(|t| t.instance_id == instance);
            let t = matches
                .next()
                .ok_or_else(|| Error::bad("registry_instance_not_trusted"))?;
            if matches.next().is_some()
                || t.scene != scene
                || !t.trusted
                || !t.static_profile_available
                || t.epoch.is_empty()
            {
                return Err(Error::bad("registry_instance_not_trusted"));
            }
            validate_trusted(&t.static_entries, "initial")?;
            validate_trusted(&t.furniture_entries, "furniture")?;
            if t.ground_sig.len() > 4096
                || t.ground_sig
                    .iter()
                    .any(|g| ![g.tx, g.ty, g.tz, g.r].iter().all(|v| v.is_finite()))
            {
                return Err(Error::bad("registry_ground_invalid"));
            }
            Ok(t)
        })();
        let next = match result {
            Ok(t) => t,
            Err(e) => {
                self.invalidate();
                return Err(e);
            }
        };
        if let Some(old) = &self.trusted {
            if old.epoch == next.epoch {
                if !trusted_equal(&old.static_entries, &next.static_entries, "initial")
                    || !trusted_equal(&old.furniture_entries, &next.furniture_entries, "furniture")
                    || old.ground_sig != next.ground_sig
                {
                    self.invalidate();
                    return Err(Error::bad("registry_epoch_content_mismatch"));
                }
                self.trusted = Some(next);
                return Ok(vec![]);
            }
        }
        let changed = self
            .trusted
            .as_ref()
            .is_some_and(|o| !trusted_equal(&o.static_entries, &next.static_entries, "initial"));
        self.trusted = Some(next);
        self.generic.clear();
        self.occupants.clear();
        let mut invalid = vec![];
        for (g, p) in &mut self.peers {
            if p.furniture_ready || (changed && p.static_ready) {
                invalid.push(g.clone());
            }
            p.furniture_ready = false;
            p.furniture.clear();
            if changed {
                p.static_ready = false;
                p.initial.clear();
            }
        }
        Ok(invalid)
    }
    pub fn clear_trust(&mut self) {
        self.invalidate();
    }
    pub fn chunk(
        &mut self,
        g: &str,
        seq: i64,
        part: i32,
        parts: i32,
        encoded: &str,
        now: f64,
    ) -> Result<Option<String>> {
        let p = self.peer(g);
        p.opted = true;
        if seq < 0
            || !(1..=256).contains(&parts)
            || part < 0
            || part >= parts
            || encoded.is_empty()
            || encoded.len() > 6000
            || !encoded
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        {
            return Err(Error::bad("registry_chunk_invalid"));
        }
        if p.chunks.is_none() {
            if part != 0 || seq <= p.seq {
                return Err(Error::bad("registry_chunk_order"));
            }
            p.chunks = Some(Chunks {
                seq,
                parts,
                next: 0,
                until: now + 10.0,
                bytes: vec![],
            });
        }
        let c = p.chunks.as_mut().unwrap();
        if now > c.until {
            p.chunks = None;
            return Err(Error::bad("registry_chunk_timeout"));
        }
        if c.seq != seq || c.parts != parts || c.next != part {
            return Err(Error::bad("registry_chunk_order"));
        }
        let b = URL_SAFE_NO_PAD
            .decode(encoded)
            .map_err(|_| Error::bad("registry_chunk_base64url_invalid"))?;
        if b.len() > 4096 {
            return Err(Error::bad("registry_chunk_too_large"));
        }
        if c.bytes.len() + b.len() > 1024 * 1024 {
            p.chunks = None;
            return Err(Error::bad("registry_json_too_large"));
        }
        c.bytes.extend(b);
        c.next += 1;
        if c.next != parts {
            return Ok(None);
        }
        let c = p.chunks.take().unwrap();
        String::from_utf8(c.bytes)
            .map(Some)
            .map_err(|_| Error::bad("registry_utf8_invalid"))
    }
    pub fn register(
        &mut self,
        g: &str,
        json: &str,
        scene: &str,
        now: f64,
        targets: &[String],
    ) -> Result<(i64, bool, Vec<Delivery>)> {
        if json.is_empty() || json.len() > 1024 * 1024 {
            return Err(Error::bad("registry_message_invalid"));
        }
        self.peer(g).opted = true;
        let doc: Document = serde_json::from_str(json)?;
        let p = &self.peers[g];
        if doc.v != 1
            || doc.scene != scene
            || doc.seq <= p.seq
            || !matches!(doc.source.as_str(), "initial" | "load" | "save")
        {
            return Err(Error::bad("registry_message_invalid"));
        }
        let t = self
            .trusted
            .as_ref()
            .ok_or_else(|| Error::bad("registry_trust_not_loaded"))?;
        let initial = doc.source == "initial";
        if initial && !doc.ground_sig.is_empty() {
            return Err(Error::bad("registry_initial_has_ground_signature"));
        }
        if !initial && doc.ground_sig != t.ground_sig {
            if doc.source == "save" {
                let p = self.peer(g);
                p.furniture_ready = false;
                p.furniture.clear();
                let deadline = p
                    .pending
                    .as_ref()
                    .filter(|(old, _)| old == json)
                    .map_or(now + 10.0, |(_, until)| *until);
                p.pending = Some((json.into(), deadline));
                self.generic.clear();
                self.occupants.clear();
                return Ok((doc.seq, false, vec![]));
            }
            return Err(Error::bad("registry_ground_signature_mismatch"));
        }
        let ns = if initial { "initial" } else { "furniture" };
        let expected = if initial {
            &t.static_entries
        } else {
            &t.furniture_entries
        };
        let bound = bind(&doc.entries, expected, ns)?;
        let other = if initial { &p.furniture } else { &p.initial };
        let mut send = BTreeSet::new();
        let mut receive = BTreeSet::new();
        for b in bound.iter().chain(other) {
            if !send.insert((b.kind.clone(), b.send))
                || !receive.insert((b.kind.clone(), b.receive))
            {
                return Err(Error::bad("registry_source_namespace_collision"));
            }
        }
        let p = self.peer(g);
        if initial {
            p.initial = bound;
            p.static_ready = true;
        } else {
            p.furniture = bound;
            p.furniture_ready = true;
        }
        p.seq = doc.seq;
        p.pending = None;
        let mut out = vec![];
        if self.ready(g) {
            let queued = std::mem::take(&mut self.peer(g).queued);
            for (op, args) in queued {
                if let Ok(v) = self.handle(g, op, &args, targets) {
                    out.extend(v);
                }
            }
            for (key, (state, actor, extra)) in &self.generic {
                if let Ok(id) = self.receive(g, key, "generic") {
                    let mut f = vec![actor.clone(), id.to_string(), boolean(*state).into()];
                    f.extend(extra.clone());
                    out.push((g.into(), format!("94#{}", f.join("#"))));
                }
            }
        }
        Ok((doc.seq, true, out))
    }
    pub fn pending(&self) -> Vec<(String, String, f64)> {
        self.peers
            .iter()
            .filter_map(|(g, p)| p.pending.as_ref().map(|(j, t)| (g.clone(), j.clone(), *t)))
            .collect()
    }
    pub fn handle(
        &mut self,
        g: &str,
        op: i32,
        args: &[String],
        targets: &[String],
    ) -> Result<Vec<Delivery>> {
        if !self.opted(g) {
            return Err(Error::bad("registry_peer_not_opted_in"));
        }
        if !self.ready(g) {
            if !matches!(op, 8 | 94) {
                return Err(Error::bad("registry_not_ready"));
            }
            let p = self.peer(g);
            if p.queued.len() >= 64 {
                return Err(Error::bad("registry_queue_limit"));
            }
            p.queued.push((op, args.to_vec()));
            return Ok(vec![]);
        }
        if args.len() < 2 || args[0] != g {
            return Err(Error::bad("registry_session_not_owned"));
        }
        let id = args[1]
            .trim()
            .parse::<i32>()
            .ok()
            .filter(|n| *n >= 0)
            .ok_or_else(|| Error::bad("registry_id_invalid"))?;
        let kind = if op == 94 { "generic" } else { "occupable" };
        let key = self.resolve(g, id, kind)?;
        let t = self.trusted.as_ref().unwrap();
        let rules = if key.starts_with("initial|") {
            &t.static_entries
        } else {
            &t.furniture_entries
        };
        let ns = if key.starts_with("initial|") {
            "initial"
        } else {
            "furniture"
        };
        let rule = rules
            .iter()
            .find(|e| key_for(ns, e) == key)
            .ok_or_else(|| Error::bad("registry_rule_missing"))?;
        if rule.classification != "ordinary" {
            return Err(Error::bad("registry_semantic_key_denied"));
        }
        if op == 8 {
            if args.len() != 2 {
                return Err(Error::bad("registry_field_count"));
            }
            let id = self.receive(g, &key, kind)?;
            return Ok(vec![(
                g.into(),
                match self.occupants.get(&key) {
                    Some(o) => format!("9#{g}#{id}#{o}"),
                    None => format!("10##{id}"),
                },
            )]);
        }
        if op == 9 {
            if args.len() != 2 {
                return Err(Error::bad("registry_field_count"));
            }
            if self.occupants.get(&key).is_some_and(|o| o != g) {
                return Err(Error::bad("registry_occupable_claim_conflict"));
            }
            self.occupants.insert(key.clone(), g.into());
        } else if op == 10 {
            if args.len() != 2 || self.occupants.get(&key).is_none_or(|o| o != g) {
                return Err(Error::bad("registry_occupable_not_owned"));
            }
            self.occupants.remove(&key);
        } else {
            if op != 94 || args.len() < 3 || (args.len() - 3) as i32 != rule.extension_arity {
                return Err(Error::bad("registry_generic_arity"));
            }
            let state = parse_bool(&args[2])?;
            if args[3..]
                .iter()
                .any(|v| v.len() > 512 || v.contains(['#', '\0']))
            {
                return Err(Error::bad("registry_extension_invalid"));
            }
            if self.generic.get(&key).is_some_and(|(s, _, _)| *s == state) {
                return Ok(vec![]);
            }
            self.generic
                .insert(key.clone(), (state, g.into(), args[3..].to_vec()));
        }
        let mut out = vec![];
        for target in targets.iter().filter(|s| self.ready(s)) {
            let id = self.receive(target, &key, kind)?;
            let payload = match op {
                9 => format!("9#{g}#{id}#{g}"),
                10 => format!("10#{g}#{id}"),
                _ => {
                    let mut f = vec![
                        g.into(),
                        id.to_string(),
                        boolean(parse_bool(&args[2])?).into(),
                    ];
                    f.extend_from_slice(&args[3..]);
                    format!("94#{}", f.join("#"))
                }
            };
            out.push((target.clone(), payload));
        }
        Ok(out)
    }
    fn resolve(&self, g: &str, id: i32, kind: &str) -> Result<String> {
        let p = self
            .peers
            .get(g)
            .ok_or_else(|| Error::bad("registry_send_id_unbound"))?;
        let mut v = p
            .initial
            .iter()
            .chain(&p.furniture)
            .filter(|b| b.kind == kind && b.send == id);
        let b = v
            .next()
            .ok_or_else(|| Error::bad("registry_send_id_unbound"))?;
        if v.next().is_some() {
            return Err(Error::bad("registry_send_id_unbound"));
        }
        Ok(b.key.clone())
    }
    fn receive(&self, g: &str, key: &str, kind: &str) -> Result<i32> {
        let p = self
            .peers
            .get(g)
            .ok_or_else(|| Error::bad("registry_receive_id_unbound"))?;
        let mut v = p
            .initial
            .iter()
            .chain(&p.furniture)
            .filter(|b| b.kind == kind && b.key == key);
        let b = v
            .next()
            .ok_or_else(|| Error::bad("registry_receive_id_unbound"))?;
        if v.next().is_some() {
            return Err(Error::bad("registry_receive_id_unbound"));
        }
        Ok(b.receive)
    }
    pub fn disconnect(&mut self, g: &str, targets: &[String]) -> Vec<Delivery> {
        let keys: Vec<_> = self
            .occupants
            .iter()
            .filter(|(_, a)| *a == g)
            .map(|(k, _)| k.clone())
            .collect();
        let mut out = vec![];
        for k in keys {
            self.occupants.remove(&k);
            for target in targets.iter().filter(|t| self.ready(t)) {
                if let Ok(id) = self.receive(target, &k, "occupable") {
                    out.push((target.clone(), format!("10#{g}#{id}")));
                }
            }
        }
        self.peers.remove(g);
        out
    }
}
fn boolean(v: bool) -> &'static str {
    if v {
        "True"
    } else {
        "False"
    }
}
fn parse_bool(v: &str) -> Result<bool> {
    match v.trim().to_ascii_lowercase().as_str() {
        "true" => Ok(true),
        "false" => Ok(false),
        _ => Err(Error::bad("registry_bool_invalid")),
    }
}
fn key_for(ns: &str, e: &Entry) -> String {
    format!(
        "{}|{}|{}|{}|{}|{}|{}|{}",
        ns,
        e.kind,
        e.anchor,
        e.path
            .iter()
            .map(i32::to_string)
            .collect::<Vec<_>>()
            .join("/"),
        e.class_name,
        e.slot,
        e.ground_index,
        e.item_id
    )
}
fn validate_trusted(entries: &[Entry], ns: &str) -> Result<()> {
    if entries.len() > 4096 {
        return Err(Error::bad("registry_trust_entries_invalid"));
    }
    let mut keys = BTreeSet::new();
    for e in entries {
        if !matches!(e.kind.as_str(), "generic" | "occupable")
            || (ns == "initial") == e.anchor.is_empty()
            || e.path.iter().any(|v| *v < 0)
            || e.slot < 0
            || e.ground_index < -1
            || e.class_name.is_empty()
            || !(0..=32).contains(&e.extension_arity)
            || !matches!(
                e.classification.as_str(),
                "ordinary" | "deferred_minigame" | "separate_protocol"
            )
            || !keys.insert(key_for(ns, e))
        {
            return Err(Error::bad("registry_trust_entry_invalid"));
        }
    }
    Ok(())
}
fn trusted_equal(a: &[Entry], b: &[Entry], ns: &str) -> bool {
    let map = |v: &[Entry]| {
        v.iter()
            .map(|e| {
                (
                    key_for(ns, e),
                    (e.classification.clone(), e.extension_arity),
                )
            })
            .collect::<BTreeMap<_, _>>()
    };
    map(a) == map(b)
}
fn bind(supplied: &[Entry], expected: &[Entry], ns: &str) -> Result<Vec<Bound>> {
    if supplied.len() != expected.len() || supplied.len() > 4096 {
        return Err(Error::bad("registry_incomplete"));
    }
    let rules: BTreeSet<_> = expected.iter().map(|e| key_for(ns, e)).collect();
    let mut keys = BTreeSet::new();
    let mut out = vec![];
    for e in supplied {
        if !matches!(e.kind.as_str(), "generic" | "occupable")
            || e.send_id < 0
            || e.receive_id < 0
            || (ns == "initial") == e.anchor.is_empty()
            || e.path.iter().any(|v| *v < 0)
            || e.slot < 0
            || (e.kind == "generic" && e.send_id != e.receive_id)
        {
            return Err(Error::bad("registry_entry_invalid"));
        }
        let k = key_for(ns, e);
        if !rules.contains(&k) || !keys.insert(k.clone()) {
            return Err(Error::bad("registry_unknown_or_duplicate_key"));
        }
        out.push(Bound {
            key: k,
            kind: e.kind.clone(),
            send: e.send_id,
            receive: e.receive_id,
        });
    }
    Ok(out)
}
