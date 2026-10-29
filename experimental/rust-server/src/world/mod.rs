//! Deterministic Mirror/Nebula world engine. Socket framing and clocks are
//! supplied by the host; all game-facing bytes use the shipped Mirror schema.
mod accounts;
mod interactions;
mod social;
use crate::{
    error::{Error, Result},
    mirror::{message_id, stable_hash, Reader, Writer},
    state::State,
    wire,
};
use accounts::{Account, Pose};
use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    fs,
};

pub const IMPLEMENTED_OPCODES: &[i32] = &[
    1, 2, 3, 4, 6, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 29, 30,
    31, 44, 46, 92, 94, 97,
];
/// Directional and excluded opcodes are rejected explicitly, never relayed.
pub const EXCLUDED_MINIGAME_OPCODES: &[i32] = &[
    32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59,
    60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83,
    84, 85, 86, 87, 88, 89, 90, 91,
];
pub const CLIENTBOUND_ONLY_OPCODES: &[i32] = &[0, 5, 7, 14, 27, 28, 45, 47, 93, 96];
pub const MAX_ACTIONS: usize = 8192;
pub const MAX_ACTION_BYTES: usize = 8 * 1024 * 1024;
const PLAYER_ASSET: &str = "86041873b099ede4687c67606e379683";
const SPEED: &str =
    "System.Void Assets.Scripts.NebulaPlayers.NebulaPlayerSyncVars::SetSpeed(System.Single)";
const SYNC:&str="System.Void Mirror.NetworkTransformBase::CmdClientToServerSync(System.Nullable`1<UnityEngine.Vector3>,System.Nullable`1<UnityEngine.Quaternion>,System.Nullable`1<UnityEngine.Vector3>)";
const TELEPORT: &str = "System.Void Mirror.NetworkTransformBase::CmdTeleport(UnityEngine.Vector3)";
const TELEPORT_ROT:&str="System.Void Mirror.NetworkTransformBase::CmdTeleport(UnityEngine.Vector3,UnityEngine.Quaternion)";
const LEGACY_TELEPORT:&str="System.Void Mirror.NetworkTransformBase::CmdTeleportAndRotate(UnityEngine.Vector3,UnityEngine.Quaternion)";
const SYNC_RPC:&str="System.Void Mirror.NetworkTransformBase::RpcServerToClientSync(System.Nullable`1<UnityEngine.Vector3>,System.Nullable`1<UnityEngine.Quaternion>,System.Nullable`1<UnityEngine.Vector3>)";
const TELEPORT_RPC: &str =
    "System.Void Mirror.NetworkTransformBase::RpcTeleport(UnityEngine.Vector3)";
const TELEPORT_ROT_RPC:&str="System.Void Mirror.NetworkTransformBase::RpcTeleport(UnityEngine.Vector3,UnityEngine.Quaternion)";

#[derive(Clone, Debug)]
pub struct Config {
    pub instance_id: String,
    pub space_id: String,
    pub max_peers: usize,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            instance_id: "local-nexus".into(),
            space_id: "Nexus".into(),
            max_peers: 32,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Outbound {
    Send {
        peer: u64,
        reliable: bool,
        message: Vec<u8>,
    },
    Disconnect {
        peer: u64,
        reason: String,
    },
}
#[derive(Clone, Debug, Serialize)]
pub struct Event {
    pub peer: u64,
    pub opcode: i32,
    pub kind: String,
    pub detail: String,
}
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq)]
pub(super) struct Vector3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}
impl Vector3 {
    fn valid(self) -> bool {
        self.x.is_finite() && self.y.is_finite() && self.z.is_finite()
    }
    fn array(self) -> [f32; 3] {
        [self.x, self.y, self.z]
    }
}
impl From<[f32; 3]> for Vector3 {
    fn from(v: [f32; 3]) -> Self {
        Self {
            x: v[0],
            y: v[1],
            z: v[2],
        }
    }
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq)]
pub(super) struct Quaternion {
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub w: f32,
}
impl Default for Quaternion {
    fn default() -> Self {
        Self {
            x: 0.0,
            y: 0.0,
            z: 0.0,
            w: 1.0,
        }
    }
}
impl Quaternion {
    fn valid(self) -> bool {
        [self.x, self.y, self.z, self.w]
            .iter()
            .all(|v| v.is_finite())
            && [self.x, self.y, self.z, self.w]
                .iter()
                .map(|v| (*v as f64).powi(2))
                .sum::<f64>()
                > 0.000001
    }
    fn array(self) -> [f32; 4] {
        [self.x, self.y, self.z, self.w]
    }
}
impl From<[f32; 4]> for Quaternion {
    fn from(v: [f32; 4]) -> Self {
        Self {
            x: v[0],
            y: v[1],
            z: v[2],
            w: v[3],
        }
    }
}
#[derive(Serialize, Deserialize)]
struct Transform {
    position: Vector3,
    rotation: Quaternion,
}
#[derive(Clone)]
struct Peer {
    id: u64,
    ready: bool,
    spawned: bool,
    announced: bool,
    net_id: u32,
    account: Option<Account>,
    in_wardrobe: bool,
    position: Vector3,
    rotation: Quaternion,
    scale: Vector3,
    position_updated: f64,
    speed: f32,
    companion: String,
    locomotion: String,
    companion_revision: i64,
    locomotion_revision: i64,
    animation: Option<String>,
    visible: BTreeSet<u32>,
    loaded: BTreeSet<u32>,
    wardrobe_shown: BTreeSet<u32>,
    typing_public: bool,
    typing_target: Option<String>,
    delivered_notifications: BTreeSet<String>,
    informational: BTreeMap<(String, i32), f64>,
    retired: BTreeMap<String, u64>,
}
impl Peer {
    fn new(id: u64) -> Self {
        Self {
            id,
            ready: false,
            spawned: false,
            announced: false,
            net_id: 0,
            account: None,
            in_wardrobe: false,
            position: Vector3::default(),
            rotation: Quaternion::default(),
            scale: Vector3 {
                x: 1.0,
                y: 1.0,
                z: 1.0,
            },
            position_updated: 0.0,
            speed: 0.0,
            companion: String::new(),
            locomotion: String::new(),
            companion_revision: 0,
            locomotion_revision: 0,
            animation: None,
            visible: BTreeSet::new(),
            loaded: BTreeSet::new(),
            wardrobe_shown: BTreeSet::new(),
            typing_public: false,
            typing_target: None,
            delivered_notifications: BTreeSet::new(),
            informational: BTreeMap::new(),
            retired: BTreeMap::new(),
        }
    }
}
#[derive(Clone)]
struct Reseed {
    actor: u32,
    viewer: u64,
    actor_guid: String,
    viewer_guid: String,
    frame: u64,
    codes: Vec<i32>,
}
#[derive(Default)]
struct WorldState {
    boats: BTreeMap<String, i32>,
    boat_seen: BTreeMap<String, BTreeSet<String>>,
    generic: BTreeMap<i32, (bool, String)>,
    history: Vec<String>,
    scene_seen: BTreeSet<String>,
}
pub struct Engine {
    config: Config,
    state: State,
    peers: BTreeMap<u64, Peer>,
    wardrobe: BTreeMap<String, Peer>,
    next_net_id: u32,
    occupables: BTreeMap<i32, String>,
    poses: BTreeMap<String, Pose>,
    relations: BTreeMap<(String, String), social::Relation>,
    reseeds: Vec<Reseed>,
    registry: interactions::Registry,
    world: WorldState,
    is_day: Option<bool>,
    frame: u64,
    events: VecDeque<Event>,
    listening: bool,
    last_publish: f64,
    trust_bytes: Vec<u8>,
    relay_seen: BTreeMap<String, f64>,
    rebind_deadlines: BTreeMap<String, f64>,
}
impl Engine {
    pub fn new(config: Config, state: State) -> Result<Self> {
        if !safe_instance(&config.instance_id)
            || config.space_id.is_empty()
            || config.space_id.len() > 128
            || config.space_id.contains(['#', '\0'])
            || config.max_peers == 0
            || config.max_peers > 256
        {
            return Err(Error::bad("invalid_world_config"));
        }
        let mut e = Self {
            config,
            state,
            peers: BTreeMap::new(),
            wardrobe: BTreeMap::new(),
            next_net_id: 1,
            occupables: BTreeMap::new(),
            poses: BTreeMap::new(),
            relations: BTreeMap::new(),
            reseeds: vec![],
            registry: Default::default(),
            world: Default::default(),
            is_day: None,
            frame: 0,
            events: VecDeque::new(),
            listening: false,
            last_publish: f64::NEG_INFINITY,
            trust_bytes: vec![],
            relay_seen: BTreeMap::new(),
            rebind_deadlines: BTreeMap::new(),
        };
        e.load_poses()?;
        let _ = e.refresh_trust(&mut vec![]);
        e.recover_wardrobe()?;
        Ok(e)
    }
    pub fn config(&self) -> &Config {
        &self.config
    }
    pub fn peer_count(&self) -> usize {
        self.peers.len()
    }
    pub fn registry_trusted(&self) -> bool {
        self.registry.trusted()
    }
    pub fn scene_inventory_verified(&self) -> bool {
        inventory(&self.config.space_id).0
    }
    pub fn drain_events(&mut self) -> Vec<Event> {
        self.events.drain(..).collect()
    }
    pub fn set_listening(&mut self, value: bool) -> Result<()> {
        self.listening = value;
        self.publish()
    }
    pub fn connect(&mut self, id: u64) -> Result<Vec<Outbound>> {
        if self.peers.contains_key(&id) {
            return Err(Error::bad("duplicate_transport_peer"));
        }
        if self.peers.len() >= self.config.max_peers {
            return Ok(vec![Outbound::Disconnect {
                peer: id,
                reason: "instance_full".into(),
            }]);
        }
        self.peers.insert(id, Peer::new(id));
        self.event(id, -1, "connected", "transport_only");
        Ok(vec![])
    }
    pub fn receive(&mut self, id: u64, packet: &[u8]) -> Result<Vec<Outbound>> {
        let mut p = self
            .peers
            .remove(&id)
            .ok_or_else(|| Error::bad("unknown_transport_peer"))?;
        let mut out = vec![];
        let mut opcode = -1;
        let result = (|| {
            if packet.len() > 65536 {
                return Err(Error::bad("mirror_message_too_large"));
            }
            let mut r = Reader::new(packet);
            let msg = r.read_u16()?;
            if msg == message_id("Mirror.ReadyMessage") {
                r.finish()?;
                if !p.ready {
                    p.ready = true;
                }
                return Ok(());
            }
            if msg == message_id("Mirror.AddPlayerMessage") {
                r.finish()?;
                return self.add_player(&mut p, &mut out);
            }
            if msg == message_id("Mirror.NetworkPingMessage") {
                let t = r.read_f64()?;
                r.finish()?;
                if !t.is_finite() {
                    return Err(Error::bad("invalid_ping_time"));
                }
                let mut w = message("Mirror.NetworkPongMessage");
                w.write_f64(t);
                w.write_f64(self.state.now());
                return push(&mut out, id, true, w.into_inner());
            }
            if msg == message_id("Mirror.CommandMessage") {
                let net = r.read_u32()?;
                let component = r.read_u8()?;
                let hash = r.read_i32()?;
                let data = r
                    .read_bytes_and_size()?
                    .ok_or_else(|| Error::bad("missing_command_payload"))?;
                r.finish()?;
                return self.command(&mut p, net, component, hash, &data, &mut out);
            }
            if msg != message_id("NebulaMessage") {
                return Err(Error::bad(format!("unsupported_mirror_message:{msg}")));
            }
            if !p.spawned {
                return Err(Error::bad("application_before_spawn"));
            }
            let cipher = r
                .read_string()?
                .ok_or_else(|| Error::bad("missing_application_ciphertext"))?;
            r.finish()?;
            let plain = wire::decrypt_client(&cipher)?;
            if plain.contains('\0') {
                return Err(Error::bad("invalid_application_token"));
            }
            let tokens: Vec<String> = plain.split('#').map(str::to_owned).collect();
            if tokens.len() < 2 {
                return Err(Error::bad("invalid_opcode"));
            }
            opcode = int(&tokens[0])?;
            let platform = &tokens[tokens.len() - 1];
            if !matches!(platform.as_str(), "PS4" | "StandaloneWindows") {
                return Err(Error::bad("invalid_platform_trailer"));
            }
            if p.account.as_ref().is_some_and(|a| a.platform != *platform) {
                return Err(Error::bad("platform_mismatch"));
            }
            self.dispatch(
                &mut p,
                opcode,
                &tokens[1..tokens.len() - 1],
                platform,
                &mut out,
            )
        })();
        if let Err(e) = &result {
            self.event(id, opcode, "rejected", &e.message);
            if opcode == 9
                && p.account
                    .as_ref()
                    .is_some_and(|a| self.registry.opted(&a.guid))
            {
                out.push(Outbound::Disconnect {
                    peer: id,
                    reason: "rejected_semantic_claim_requires_reload".into(),
                });
                self.peers.insert(id, p);
                return bounded(out);
            }
        }
        self.peers.insert(id, p);
        // The Unity handler queues trusted restoration/snapshot replies before
        // recording a later validation failure. Preserve those replies while
        // exposing the rejection through the bounded audit event queue.
        if result.is_err() && !out.is_empty() {
            return bounded(out);
        }
        result?;
        bounded(out)
    }
    fn add_player(&mut self, p: &mut Peer, out: &mut Vec<Outbound>) -> Result<()> {
        if p.spawned || !p.ready {
            return Err(Error::bad("invalid_add_player_state"));
        }
        p.net_id = self.allocate_net_id()?;
        p.spawned = true;
        push(
            out,
            p.id,
            true,
            message("Mirror.ObjectSpawnStartedMessage").into_inner(),
        )?;
        let entity = p.clone();
        self.spawn(&entity, p, true, out)?;
        push(
            out,
            p.id,
            true,
            message("Mirror.ObjectSpawnFinishedMessage").into_inner(),
        )?;
        send(out, p.id, "0")?;
        Ok(())
    }
    fn allocate_net_id(&mut self) -> Result<u32> {
        let id = self.next_net_id;
        if id == 0 {
            return Err(Error::bad("netid_exhausted"));
        }
        self.next_net_id = id.checked_add(1).unwrap_or(0);
        Ok(id)
    }
    fn spawn(
        &self,
        actor: &Peer,
        viewer: &mut Peer,
        local: bool,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        if !viewer.visible.insert(actor.net_id) {
            return Ok(());
        }
        let mut initial = Writer::new();
        initial.write_u8(0);
        initial.write_i32(28);
        initial.write_vector3(actor.position.array());
        initial.write_quaternion(actor.rotation.array());
        initial.write_u8(1);
        initial.write_i32(4);
        initial.write_f32(actor.speed);
        let mut w = message("Mirror.SpawnMessage");
        w.write_u32(actor.net_id);
        w.write_bool(local);
        w.write_bool(local);
        w.write_u64(0);
        w.write_guid(
            uuid::Uuid::parse_str(PLAYER_ASSET)
                .map_err(|_| Error::bad("invalid_player_asset_id"))?
                .to_bytes_le(),
        );
        w.write_vector3(actor.position.array());
        w.write_quaternion(actor.rotation.array());
        w.write_vector3(actor.scale.array());
        w.write_bytes_and_size(Some(initial.as_slice()))?;
        push(out, viewer.id, true, w.into_inner())
    }
    fn seed(&mut self, actor: &Peer, viewer: &mut Peer, out: &mut Vec<Outbound>) -> Result<()> {
        let (Some(a), Some(v)) = (&actor.account, &viewer.account) else {
            return Ok(());
        };
        if a.id == v.id
            || viewer.visible.contains(&actor.net_id)
            || self
                .reseeds
                .iter()
                .any(|r| r.actor == actor.net_id && r.viewer == viewer.id)
        {
            return Ok(());
        }
        if let Some(frame) = viewer.retired.get(&a.id).filter(|f| **f > self.frame) {
            self.reseeds.push(Reseed {
                actor: actor.net_id,
                viewer: viewer.id,
                actor_guid: a.guid.clone(),
                viewer_guid: v.guid.clone(),
                frame: *frame,
                codes: vec![],
            });
            return Ok(());
        }
        viewer.retired.remove(&a.id);
        self.spawn(actor, viewer, false, out)?;
        send(out, viewer.id, &joined(actor)?)
    }
    fn entities(&self) -> Vec<Peer> {
        self.peers
            .values()
            .filter(|p| p.announced && p.account.is_some())
            .chain(self.wardrobe.values())
            .cloned()
            .collect()
    }
    fn seed_remotes(&mut self, p: &mut Peer, out: &mut Vec<Outbound>) -> Result<()> {
        let mut entities = self.entities();
        entities.sort_by_key(|e| e.net_id);
        for actor in entities {
            self.seed(&actor, p, out)?;
        }
        Ok(())
    }
    fn own(
        &mut self,
        p: &mut Peer,
        guid: &str,
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        let a = accounts::find(&self.state, guid)?;
        if a.platform != platform {
            return Err(Error::bad("unknown_session"));
        }
        if a.instance != self.config.instance_id {
            return Err(Error::bad("session_not_allocated_to_instance"));
        }
        if p.account
            .as_ref()
            .is_some_and(|old| old.guid != guid || old.id != a.id)
        {
            return Err(Error::bad("session_not_owned"));
        }
        for old in self
            .peers
            .values()
            .filter(|other| other.account.as_ref().is_some_and(|old| old.id == a.id))
            .cloned()
            .collect::<Vec<_>>()
        {
            if accounts::find(&self.state, &old.account.as_ref().unwrap().guid).is_ok() {
                return Err(Error::bad("account_already_connected"));
            }
            out.extend(self.disconnect(old.id)?);
            out.push(Outbound::Disconnect {
                peer: old.id,
                reason: "session_superseded".into(),
            });
        }
        let first = p.account.is_none();
        p.account = Some(a.clone());
        if first {
            if self.state.readiness_profile.as_deref() == Some("nonmini-semantic-v1") {
                self.registry.require(&a.guid);
            }
            if let Some(retained) = self.wardrobe.remove(&a.id) {
                self.remember_pose(&retained);
                self.retire_all(&retained, out)?;
            }
            p.companion = a.selected_companion.clone();
            p.locomotion = a.selected_locomotion.clone();
            p.companion_revision = a.companion_revision;
            p.locomotion_revision = a.locomotion_revision;
            self.restore_pose(p);
            self.seed_remotes(p, out)?;
        }
        Ok(())
    }
    fn bound(&self, p: &mut Peer) -> Result<()> {
        let old = p
            .account
            .as_ref()
            .ok_or_else(|| Error::bad("identity_not_bound"))?;
        let a = accounts::find(&self.state, &old.guid)?;
        if a.id != old.id || a.platform != old.platform || a.instance != self.config.instance_id {
            return Err(Error::bad("session_not_current"));
        }
        p.account = Some(a);
        Ok(())
    }
    fn dispatch(
        &mut self,
        p: &mut Peer,
        op: i32,
        f: &[String],
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        if matches!(op, 8 | 9 | 10 | 31 | 44 | 45 | 46 | 47 | 93 | 94 | 97) {
            if f.is_empty() {
                return Err(Error::bad("missing_world_identity"));
            }
            self.own(p, &f[0], platform, out)?;
            if op == 97 {
                return self.registration(p, f, out);
            }
            if p.in_wardrobe {
                return Err(Error::bad("world_interaction_while_in_wardrobe"));
            }
            if matches!(op, 8 | 9 | 10 | 94) && self.registry.opted(&f[0]) {
                let targets = self.ready_guids(Some(p));
                let deliveries = self.registry.handle(&f[0], op, f, &targets)?;
                return self.deliver_interactions(deliveries, Some(p), out);
            }
            if matches!(op, 31 | 44 | 45 | 46 | 47 | 93 | 94) {
                return self.world(p, op, f, out);
            }
        }
        match op {
            1 => self.announce(p, f, platform, out),
            2 => {
                count(f, 2)?;
                self.bound(p)?;
                if unsigned(&f[0])? != p.net_id {
                    return Err(Error::bad("netid_not_owned"));
                }
                if p.in_wardrobe {
                    return Err(Error::bad("movement_while_in_wardrobe"));
                }
                let t: Transform = serde_json::from_str(&f[1])?;
                if !t.position.valid() || !t.rotation.valid() {
                    return Err(Error::bad("invalid_transform"));
                }
                p.position = t.position;
                p.rotation = t.rotation;
                self.observe_pose(p);
                self.broadcast(&transform_reply(p)?, Some(p), out)
            }
            3 | 6 | 16 | 20 => self.query(p, op, f, platform, out),
            4 => {
                if f.len() < 6 {
                    return Err(Error::bad("invalid_animation_fields"));
                }
                self.own(p, &f[0], platform, out)?;
                let reply = animation(f, p.net_id)?;
                p.animation = Some(reply.clone());
                self.broadcast(&reply, Some(p), out)
            }
            8 | 9 => {
                count(f, 2)?;
                let id = int(&f[1])?;
                if id < 0 {
                    return Err(Error::bad("invalid_occupable_id"));
                }
                let guid = &f[0];
                if op == 9 && self.occupables.get(&id).is_none_or(|g| g == guid) {
                    self.occupables.insert(id, guid.clone());
                    self.broadcast_legacy(&format!("9#{guid}#{id}#{guid}"), Some(p), out)
                } else {
                    let reply = match self.occupables.get(&id) {
                        Some(g) => format!("9#{guid}#{id}#{g}"),
                        None => format!("10##{id}"),
                    };
                    send(out, p.id, &reply)
                }
            }
            10 => {
                count(f, 2)?;
                let id = int(&f[1])?;
                if self.occupables.get(&id).is_none_or(|g| g != &f[0]) {
                    return Err(Error::bad("occupable_not_owned"));
                }
                self.occupables.remove(&id);
                self.broadcast_legacy(&join(op, f), Some(p), out)
            }
            11 => self.start_typing(p, f, platform, out),
            12 => {
                count(f, 1)?;
                self.own(p, &f[0], platform, out)?;
                self.stop_typing(p, out)
            }
            13 => self.chat(p, f, platform, out),
            15 | 17 => {
                count(f, 2)?;
                self.own(p, &f[0], platform, out)?;
                self.select_resource(p, op, &f[1], out)
            }
            18 => {
                count(f, 3)?;
                self.own(p, &f[0], platform, out)?;
                if !matches!(int(&f[1])?, 0 | 1 | 2 | 3 | 4 | 15 | 21) {
                    return Err(Error::bad("unsupported_preference_replication"));
                }
                self.broadcast(&join(op, f), Some(p), out)
            }
            19 => self.notification(p, f, out),
            21..=25 => self.social_refresh(p, op, f, platform, out),
            26 => self.accept_notification(p, f, platform, out),
            29 => self.enter_wardrobe(p, f, platform, out),
            30 => {
                count(f, 1)?;
                self.bound(p)?;
                let day = boolean(&f[0])?;
                self.is_day = Some(day);
                let reply = format!("30##{}", bool_text(day));
                self.broadcast(&reply, None, out)?;
                send(out, p.id, &reply)
            }
            92 => {
                count(f, 4)?;
                self.own(p, &f[0], platform, out)?;
                match int(&f[2])? {
                    1 => {
                        float(&f[3])?;
                    }
                    3 => {
                        int(&f[3])?;
                    }
                    4 => {
                        boolean(&f[3])?;
                    }
                    9 => {}
                    _ => return Err(Error::bad("invalid_animator_parameter_type")),
                }
                self.broadcast(&join(op, f), Some(p), out)
            }
            95 => {
                count(f, 4)?;
                self.own(p, &f[0], platform, out)?;
                announced(p)?;
                if !matches!(int(&f[3])?, 10 | 12) {
                    return Err(Error::bad("unsupported_notification_decline_type"));
                }
                Err(Error::bad("uncorrelated_game_notification_decline"))
            }
            _ if EXCLUDED_MINIGAME_OPCODES.contains(&op) => {
                Err(Error::bad(format!("excluded_minigame_opcode:{op}")))
            }
            _ if CLIENTBOUND_ONLY_OPCODES.contains(&op) => {
                Err(Error::bad(format!("clientbound_only_opcode:{op}")))
            }
            _ => {
                self.event(
                    p.id,
                    op,
                    "unsupported_opcode",
                    "no_reconstructed_transition",
                );
                Err(Error::bad(format!("unsupported_opcode:{op}")))
            }
        }
    }
    fn announce(
        &mut self,
        p: &mut Peer,
        f: &[String],
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        count(f, 4)?;
        if unsigned(&f[0])? != p.net_id {
            return Err(Error::bad("netid_not_owned"));
        }
        self.own(p, &f[1], platform, out)?;
        let a = p.account.as_ref().unwrap();
        if f[2] != a.username || int(&f[3])? != a.platform_number() {
            return Err(Error::bad("identity_claim_mismatch"));
        }
        if p.announced {
            return Ok(());
        }
        let ids: Vec<_> = self
            .peers
            .iter()
            .filter(|(_, v)| v.spawned && v.account.is_some())
            .map(|(id, _)| *id)
            .collect();
        for id in ids {
            let mut viewer = self.peers.remove(&id).unwrap();
            let r = self.seed(p, &mut viewer, out);
            self.peers.insert(id, viewer);
            r?;
        }
        send(out, p.id, &format!("17#{}#{}", a.guid, p.companion))?;
        send(out, p.id, &format!("15#{}#{}", a.guid, p.locomotion))?;
        if !self.registry.opted(&a.guid) && self.world.scene_seen.insert(a.guid.clone()) {
            if inventory(&self.config.space_id).4 {
                for reply in &self.world.history {
                    send(out, p.id, reply)?;
                }
            } else {
                for (_, reply) in self.world.generic.values() {
                    send(out, p.id, reply)?;
                }
            }
        }
        if let Some(day) = self.is_day {
            send(out, p.id, &format!("30##{}", bool_text(day)))?;
        }
        for other in self
            .peers
            .values()
            .filter(|v| v.announced)
            .cloned()
            .collect::<Vec<_>>()
        {
            self.relation_pair(p, &other, out)?;
        }
        p.announced = true;
        self.event(p.id, 1, "announced", "current_db_identity_bound");
        Ok(())
    }
    fn query(
        &mut self,
        p: &mut Peer,
        op: i32,
        f: &[String],
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        count(f, 2)?;
        self.own(p, &f[0], platform, out)?;
        let target = self
            .entities()
            .into_iter()
            .find(|t| t.account.as_ref().is_some_and(|a| a.guid == f[1]))
            .ok_or_else(|| Error::bad("target_not_present"))?;
        if target.net_id == p.net_id || !p.visible.contains(&target.net_id) {
            return Err(Error::bad("query_target_not_spawned_for_peer"));
        }
        let a = target.account.as_ref().unwrap();
        match op {
            20 => send(out, p.id, &transform_reply(&target)?)?,
            16 => send(out, p.id, &format!("15#{}#{}", a.guid, target.locomotion))?,
            6 => send(out, p.id, &format!("17#{}#{}", a.guid, target.companion))?,
            _ => {
                if let Some(reply) = &target.animation {
                    send(out, p.id, reply)?;
                }
            }
        }
        if op == 3 {
            if p.loaded.insert(target.net_id) && !target.in_wardrobe {
                if let Some(token) = self.world.boats.get(&a.guid) {
                    let own = &p.account.as_ref().unwrap().guid;
                    if self
                        .world
                        .boat_seen
                        .entry(own.clone())
                        .or_default()
                        .insert(a.guid.clone())
                    {
                        send(out, p.id, &format!("31#{}#True#{token}", a.guid))?;
                    }
                }
            }
            self.show_wardrobe(&target, p, out)?;
        }
        Ok(())
    }
    fn select_resource(
        &mut self,
        p: &mut Peer,
        op: i32,
        item: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        self.bound(p)?;
        let a = p.account.as_ref().unwrap();
        let (kind, revision) = if op == 17 {
            ("companions", p.companion_revision)
        } else {
            ("locomotions", p.locomotion_revision)
        };
        let next = match accounts::select_resource(&self.state, a, kind, item, revision) {
            Ok(v) => v,
            Err(e) => {
                send(
                    out,
                    p.id,
                    &format!(
                        "{op}#{}#{}",
                        a.guid,
                        if op == 17 {
                            &a.selected_companion
                        } else {
                            &a.selected_locomotion
                        }
                    ),
                )?;
                return Err(e);
            }
        };
        if op == 17 {
            p.companion = item.into();
            p.companion_revision = next;
        } else {
            p.locomotion = item.into();
            p.locomotion_revision = next;
        }
        let reply = format!("{op}#{}#{item}", a.guid);
        self.broadcast(&reply, Some(p), out)?;
        send(out, p.id, &reply)
    }
    fn command(
        &mut self,
        p: &mut Peer,
        net: u32,
        component: u8,
        hash: i32,
        data: &[u8],
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        if !p.ready || !p.spawned {
            return Err(Error::bad("mirror_command_before_ready_player"));
        }
        self.bound(p)?;
        if net != p.net_id {
            return Err(Error::bad("mirror_command_netid_not_owned"));
        }
        if p.in_wardrobe {
            return Err(Error::bad("mirror_command_while_in_wardrobe"));
        }
        let mut r = Reader::new(data);
        if component == 1 && hash == stable_hash(SPEED) {
            let speed = r.read_f32()?;
            r.finish()?;
            if !speed.is_finite() {
                return Err(Error::bad("invalid_speed_command"));
            }
            p.speed = speed;
            if p.announced {
                let mut delta = Writer::new();
                delta.write_u8(1);
                delta.write_i32(12);
                delta.write_u64(1);
                delta.write_f32(speed);
                let mut w = message("Mirror.EntityStateMessage");
                w.write_u32(net);
                w.write_bytes_and_size(Some(delta.as_slice()))?;
                let bytes = w.into_inner();
                for viewer in self
                    .peers
                    .values()
                    .filter(|v| v.spawned && v.visible.contains(&net))
                {
                    push(out, viewer.id, true, bytes.clone())?;
                }
            }
            return Ok(());
        }
        if component != 0
            || ![SYNC, TELEPORT, TELEPORT_ROT, LEGACY_TELEPORT]
                .iter()
                .any(|s| stable_hash(s) == hash)
        {
            self.event(
                p.id,
                -1,
                "unsupported_mirror_command",
                &format!("component={component};hash={hash}"),
            );
            return Err(Error::bad(format!(
                "unsupported_mirror_command:{component}:{hash}"
            )));
        }
        let (position, rotation, scale, rpc, reliable) = if hash == stable_hash(SYNC) {
            let pos = if present(&mut r)? {
                Some(Vector3::from(r.read_vector3()?))
            } else {
                None
            };
            let rot = if present(&mut r)? {
                Some(Quaternion::from(r.read_quaternion()?))
            } else {
                None
            };
            let scale = if present(&mut r)? {
                Some(Vector3::from(r.read_vector3()?))
            } else {
                None
            };
            (pos, rot, scale, SYNC_RPC, false)
        } else {
            let pos = Some(Vector3::from(r.read_vector3()?));
            let rot = if hash != stable_hash(TELEPORT) {
                Some(Quaternion::from(r.read_quaternion()?))
            } else {
                None
            };
            (
                pos,
                rot,
                None,
                if rot.is_some() {
                    TELEPORT_ROT_RPC
                } else {
                    TELEPORT_RPC
                },
                true,
            )
        };
        r.finish()?;
        if position.is_some_and(|v| !v.valid())
            || rotation.is_some_and(|q| !q.valid())
            || scale.is_some_and(|v| !v.valid())
        {
            return Err(Error::bad("invalid_mirror_transform_command"));
        }
        if let Some(v) = position {
            p.position = v;
        }
        if let Some(q) = rotation {
            p.rotation = q;
        }
        if let Some(v) = scale {
            p.scale = v;
        }
        if position.is_some() || p.position_updated > 0.0 {
            self.observe_pose(p);
        }
        if p.announced {
            let mut w = message("Mirror.RpcMessage");
            w.write_u32(net);
            w.write_u8(0);
            w.write_i32(stable_hash(rpc));
            w.write_bytes_and_size(Some(data))?;
            let bytes = w.into_inner();
            for viewer in self
                .peers
                .values()
                .filter(|v| v.spawned && v.visible.contains(&net))
            {
                push(out, viewer.id, reliable, bytes.clone())?;
            }
            if p.visible.contains(&net) {
                push(out, p.id, reliable, bytes)?;
            }
        }
        Ok(())
    }
    fn broadcast(&self, text: &str, except: Option<&Peer>, out: &mut Vec<Outbound>) -> Result<()> {
        for viewer in self
            .peers
            .values()
            .filter(|v| v.spawned && except.is_none_or(|a| v.visible.contains(&a.net_id)))
        {
            send(out, viewer.id, text)?;
        }
        Ok(())
    }
    fn broadcast_legacy(
        &self,
        text: &str,
        caller: Option<&Peer>,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        for v in self.peers.values().chain(caller.into_iter()).filter(|v| {
            v.spawned
                && v.account
                    .as_ref()
                    .is_none_or(|a| !self.registry.opted(&a.guid))
        }) {
            send(out, v.id, text)?;
        }
        Ok(())
    }
    fn event(&mut self, peer: u64, opcode: i32, kind: &str, detail: &str) {
        if self.events.len() == 1024 {
            self.events.pop_front();
        }
        self.events.push_back(Event {
            peer,
            opcode,
            kind: kind.into(),
            detail: detail.chars().take(256).collect(),
        });
    }
}
fn message(name: &str) -> Writer {
    let mut w = Writer::new();
    w.write_u16(message_id(name));
    w
}
fn push(out: &mut Vec<Outbound>, peer: u64, reliable: bool, bytes: Vec<u8>) -> Result<()> {
    if out.len() >= MAX_ACTIONS {
        return Err(Error::new(503, "world_action_capacity"));
    }
    let size: usize = out
        .iter()
        .map(|a| {
            if let Outbound::Send { message, .. } = a {
                message.len()
            } else {
                0
            }
        })
        .sum();
    if size + bytes.len() > MAX_ACTION_BYTES {
        return Err(Error::new(503, "world_action_bytes_capacity"));
    }
    out.push(Outbound::Send {
        peer,
        reliable,
        message: bytes,
    });
    Ok(())
}
fn bounded(out: Vec<Outbound>) -> Result<Vec<Outbound>> {
    if out.len() > MAX_ACTIONS {
        Err(Error::new(503, "world_action_capacity"))
    } else {
        Ok(out)
    }
}
fn send(out: &mut Vec<Outbound>, peer: u64, text: &str) -> Result<()> {
    let encrypted = wire::encrypt(text)?;
    let mut w = message("NebulaMessage");
    w.write_string(Some(&encrypted))?;
    push(out, peer, true, w.into_inner())
}
fn joined(p: &Peer) -> Result<String> {
    let a = p
        .account
        .as_ref()
        .ok_or_else(|| Error::bad("identity_not_bound"))?;
    Ok(format!(
        "1#{}#{}#{}#{}",
        p.net_id,
        a.guid,
        a.username,
        a.platform_number()
    ))
}
fn transform_reply(p: &Peer) -> Result<String> {
    Ok(format!(
        "2#{}#{}",
        p.net_id,
        serde_json::to_string(&Transform {
            position: p.position,
            rotation: p.rotation
        })?
    ))
}
fn join(op: i32, f: &[String]) -> String {
    format!("{op}#{}", f.join("#"))
}
fn count(f: &[String], n: usize) -> Result<()> {
    if f.len() == n {
        Ok(())
    } else {
        Err(Error::bad("wrong_field_count"))
    }
}
fn int(v: &str) -> Result<i32> {
    v.trim().parse().map_err(|_| Error::bad("invalid_int32"))
}
fn unsigned(v: &str) -> Result<u32> {
    if !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit()) {
        v.parse().map_err(|_| Error::bad("invalid_uint32"))
    } else {
        Err(Error::bad("invalid_uint32"))
    }
}
fn float(v: &str) -> Result<f32> {
    v.trim()
        .parse::<f32>()
        .ok()
        .filter(|v| v.is_finite())
        .ok_or_else(|| Error::bad("invalid_float32"))
}
fn boolean(v: &str) -> Result<bool> {
    match v.trim().to_ascii_lowercase().as_str() {
        "true" => Ok(true),
        "false" => Ok(false),
        _ => Err(Error::bad("invalid_boolean")),
    }
}
fn bool_text(v: bool) -> &'static str {
    if v {
        "True"
    } else {
        "False"
    }
}
fn present(r: &mut Reader<'_>) -> Result<bool> {
    match r.read_u8()? {
        0 => Ok(false),
        1 => Ok(true),
        _ => Err(Error::bad("invalid_nullable_flag")),
    }
}
fn announced(p: &Peer) -> Result<()> {
    if p.announced {
        Ok(())
    } else {
        Err(Error::bad("social_before_player_announcement"))
    }
}
fn chat_allowed(p: &Peer) -> Result<()> {
    if p.account.as_ref().is_some_and(|a| !a.muted) {
        Ok(())
    } else {
        Err(Error::bad("chat_restricted"))
    }
}
fn safe_instance(v: &str) -> bool {
    !v.is_empty()
        && v.len() <= 128
        && v.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn animation(f: &[String], net: u32) -> Result<String> {
    let id = int(&f[1])?;
    let kind = int(&f[2])?;
    let cycle = int(&f[3])?;
    let n = int(&f[5])?;
    if id != -1 && id != net as i32 {
        return Err(Error::bad("invalid_animation_netid_sentinel"));
    }
    if !(0..=7).contains(&kind)
        || !(0..=2).contains(&cycle)
        || !(0..=128).contains(&n)
        || (if n == 0 {
            f.len() != 7 || !f[6].is_empty()
        } else {
            f.len() != 6 + n as usize
        })
    {
        return Err(Error::bad("invalid_animation_count_or_enum"));
    }
    let mut fields = vec![
        f[0].clone(),
        f[2].clone(),
        f[3].clone(),
        f[4].clone(),
        f[5].clone(),
    ];
    fields.extend_from_slice(&f[6..]);
    Ok(format!("5#{}", fields.join("#")))
}

impl Engine {
    fn local_guid(&self, guid: &str, announced: bool) -> Option<Peer> {
        self.peers
            .values()
            .find(|p| {
                p.spawned
                    && (!announced || p.announced)
                    && p.account.as_ref().is_some_and(|a| a.guid == guid)
            })
            .cloned()
    }
    fn online(&self, a: &Account, caller: Option<&Peer>) -> bool {
        if !safe_instance(&a.instance) {
            return false;
        }
        if a.instance == self.config.instance_id {
            return self.peers.values().chain(caller.into_iter()).any(|p| {
                p.announced
                    && p.account
                        .as_ref()
                        .is_some_and(|b| b.guid == a.guid && b.id == a.id)
            });
        }
        let dir = self.state.state_dir.join("instances").join(&a.instance);
        let read = |name: &str| -> Option<Value> {
            let p = dir.join(name);
            if fs::metadata(&p).ok()?.len() > 16 * 1024 * 1024 {
                return None;
            }
            serde_json::from_slice(&fs::read(p).ok()?).ok()
        };
        let (Some(status), Some(avatars)) = (
            read("instance-status.json"),
            read("instance-avatar-state.json"),
        ) else {
            return false;
        };
        let fresh = |v: &Value, k: &str| {
            v[k].as_f64().is_some_and(|t| {
                t.is_finite() && self.state.now() >= t && self.state.now() - t <= 15.0
            })
        };
        status["format_version"] == 1
            && status["instance_id"] == a.instance
            && status["listening"] == true
            && status["listener_bound"] == true
            && fresh(&status, "heartbeat")
            && avatars["format_version"] == 1
            && avatars["instance_id"] == a.instance
            && avatars["psidglobal"] == status["psidglobal"]
            && avatars["listening"] == true
            && fresh(&avatars, "generation")
            && avatars["avatars"].as_array().is_some_and(|rows| {
                rows.iter()
                    .filter(|r| {
                        r["guid"] == a.guid
                            && r["ps4_id"] == a.id
                            && r["connected"] == true
                            && r["announced"] == true
                    })
                    .count()
                    == 1
            })
    }
    fn named(
        &self,
        name: &str,
        platform: i32,
        online: bool,
        caller: Option<&Peer>,
    ) -> Result<Account> {
        if !(-1..=1).contains(&platform) {
            return Err(Error::bad("invalid_target_platform"));
        }
        let mut matches = accounts::all(&self.state)?
            .into_iter()
            .filter(|a| a.username == name && (platform == -1 || a.platform_number() == platform));
        let target = matches.next().ok_or_else(|| Error::bad("target_unknown"))?;
        if matches.next().is_some() {
            return Err(Error::bad("ambiguous_target_identity"));
        }
        if online && !self.online(&target, caller) {
            return Err(Error::bad("target_not_present"));
        }
        Ok(target)
    }
    fn relay(
        &self,
        a: &Account,
        b: &Account,
        kind: &str,
        value: i32,
        text: &str,
        caller: Option<&Peer>,
    ) -> Result<()> {
        if !self.online(b, caller) {
            return Err(Error::bad("social_relay_target_not_present"));
        }
        social::enqueue(
            &self.state,
            a,
            b,
            &self.config.instance_id,
            kind,
            value,
            text,
        )
    }
    fn chat(
        &mut self,
        p: &mut Peer,
        f: &[String],
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        count(f, 5)?;
        self.own(p, &f[0], platform, out)?;
        chat_allowed(p)?;
        announced(p)?;
        let target_platform = int(&f[2])?;
        let kind = int(&f[4])?;
        if !(-1..=1).contains(&target_platform) {
            return Err(Error::bad("invalid_chat_platform"));
        }
        if f[1].is_empty() || f[3].is_empty() || f[3].encode_utf16().count() > 4096 {
            return Err(Error::bad("invalid_chat"));
        }
        let a = p.account.as_ref().unwrap();
        if kind == 0 {
            if f[1] != "Public" {
                return Err(Error::bad("unsupported_space_chat_group"));
            }
            let reply = join(13, f);
            for recipient in self
                .peers
                .values()
                .chain(std::iter::once(&*p))
                .filter(|v| v.announced)
            {
                if let Some(b) = &recipient.account {
                    if social::can_receive(&self.state, b, a)? {
                        send(out, recipient.id, &reply)?;
                    }
                }
            }
            Ok(())
        } else if kind == 1 {
            let b = self.named(&f[1], target_platform, true, Some(p))?;
            if a.guid == b.guid || !social::can_private(&self.state, a, &b)? {
                return Err(Error::bad("private_chat_not_authorized"));
            }
            private(out, p.id, &b, &a.guid, &f[3])?;
            if let Some(target) = self.local_guid(&b.guid, true) {
                private(out, target.id, a, &a.guid, &f[3])
            } else {
                self.relay(a, &b, "chat", 1, &f[3], Some(p))
            }
        } else {
            Err(Error::bad("unsupported_chat_type"))
        }
    }
    fn start_typing(
        &mut self,
        p: &mut Peer,
        f: &[String],
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        count(f, 2)?;
        self.own(p, &f[0], platform, out)?;
        chat_allowed(p)?;
        announced(p)?;
        self.stop_typing(p, out)?;
        let a = p.account.as_ref().unwrap();
        if f[1] == "Public" {
            p.typing_public = true;
            for recipient in self.peers.values().filter(|v| v.announced) {
                if recipient
                    .account
                    .as_ref()
                    .is_some_and(|b| social::can_receive(&self.state, b, a).unwrap_or(false))
                {
                    send(out, recipient.id, &join(11, f))?;
                }
            }
            Ok(())
        } else {
            let b = self.named(&f[1], -1, true, Some(p))?;
            if a.guid == b.guid || !social::can_private(&self.state, a, &b)? {
                return Err(Error::bad("private_typing_not_authorized"));
            }
            p.typing_target = Some(b.guid.clone());
            if let Some(target) = self.local_guid(&b.guid, true) {
                send(out, target.id, &format!("11#{}#{}", a.guid, a.username))
            } else {
                self.relay(a, &b, "typing", 0, "", Some(p))
            }
        }
    }
    fn stop_typing(&mut self, p: &mut Peer, out: &mut Vec<Outbound>) -> Result<()> {
        let Some(a) = p.account.as_ref() else {
            return Ok(());
        };
        if p.typing_public {
            for viewer in self.peers.values().filter(|v| v.announced) {
                send(out, viewer.id, &format!("12#{}", a.guid))?;
            }
        }
        if let Some(guid) = &p.typing_target {
            if let Some(target) = self.local_guid(guid, true) {
                send(out, target.id, &format!("12#{}", a.guid))?;
            } else if let Ok(b) = accounts::find(&self.state, guid) {
                if self.online(&b, Some(p)) {
                    self.relay(a, &b, "stop_typing", 0, "", Some(p))?;
                }
            }
        }
        p.typing_public = false;
        p.typing_target = None;
        Ok(())
    }
    fn notification(&mut self, p: &mut Peer, f: &[String], out: &mut Vec<Outbound>) -> Result<()> {
        count(f, 4)?;
        self.bound(p)?;
        announced(p)?;
        let a = p.account.as_ref().unwrap();
        if f[0] != a.username {
            return Err(Error::bad("notification_sender_mismatch"));
        }
        let kind = int(&f[2])?;
        let b = self.named(&f[1], int(&f[3])?, true, Some(p))?;
        social::request(&self.state, a, &b, kind)?;
        let result = if let Some(target) = self.local_guid(&b.guid, true) {
            self.send_notification(target.id, a, kind, "", out)
        } else {
            self.relay(a, &b, "request", kind, "", Some(p))
        };
        if result.is_err() {
            social::cancel(&self.state, a, &b, kind);
        }
        result
    }
    fn send_notification(
        &mut self,
        recipient: u64,
        a: &Account,
        kind: i32,
        arguments: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        let ticks = 621_355_968_000_000_000i64 + (self.state.now() * 10_000_000.0) as i64;
        send(
            out,
            recipient,
            &format!(
                "19#{}#{}#{kind}#{arguments}#{ticks}",
                a.username,
                a.platform_number()
            ),
        )?;
        if kind == 5 {
            if let Some(p) = self.peers.get_mut(&recipient) {
                p.informational.insert(
                    (a.username.clone(), a.platform_number()),
                    self.state.now() + 300.0,
                );
            }
        }
        Ok(())
    }
    fn accept_notification(
        &mut self,
        p: &mut Peer,
        f: &[String],
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        if f.len() != 3 && f.len() != 4 {
            return Err(Error::bad("wrong_field_count"));
        }
        self.own(p, &f[0], platform, out)?;
        announced(p)?;
        let a = p.account.as_ref().unwrap().clone();
        let kind = int(&f[2])?;
        if f.len() == 3 {
            return Err(Error::bad(if kind == 11 {
                "space_game_notification_not_reconstructed"
            } else {
                "invalid_platform_omitting_acceptance"
            }));
        }
        let target_platform = int(&f[3])?;
        if !matches!(target_platform, 0 | 1) {
            return Err(Error::bad("invalid_target_platform"));
        }
        if matches!(kind, 3 | 4) {
            return social::accept_gift(
                &self.state,
                &a,
                &f[1],
                kind,
                target_platform,
                &p.delivered_notifications,
            );
        }
        if kind == 5 {
            let k = (f[1].clone(), target_platform);
            if p.informational
                .remove(&k)
                .is_some_and(|t| t > self.state.now())
            {
                return Ok(());
            }
            return Err(Error::bad("uncorrelated_informational_acceptance"));
        }
        let b = self.named(&f[1], target_platform, true, Some(p))?;
        social::accept(&self.state, &a, &b, kind)?;
        if kind == 1 {
            if let Some(target) = self.local_guid(&b.guid, true) {
                self.send_notification(target.id, &a, 5, "", out)?;
                self.relation_pair(p, &target, out)
            } else {
                self.relay(&a, &b, "accepted", 1, "", Some(p))?;
                self.relation_external(p, &b, out)
            }
        } else {
            if let Some(target) = self.local_guid(&b.guid, true) {
                private(out, target.id, &a, &b.guid, "Private chat connected.")?;
                private(out, p.id, &b, &b.guid, "Private chat connected.")
            } else {
                self.relay(&a, &b, "accepted", 0, "", Some(p))?;
                private(out, p.id, &b, &b.guid, "Private chat connected.")
            }
        }
    }
    fn social_refresh(
        &mut self,
        p: &mut Peer,
        op: i32,
        f: &[String],
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        if f.len() != 3 && !(op == 21 && f.len() == 2) {
            return Err(Error::bad("wrong_field_count"));
        }
        self.own(p, &f[0], platform, out)?;
        announced(p)?;
        let a = p.account.as_ref().unwrap().clone();
        let b = self.named(
            &f[1],
            if f.len() == 3 { int(&f[2])? } else { -1 },
            false,
            Some(p),
        )?;
        if a.id == b.id {
            return Err(Error::bad("social_target_is_self"));
        }
        if op == 21 {
            social::friendship(&self.state, &a, &b, false)?;
        } else {
            social::validate_refresh(&self.state, &a, &b, op)?;
        }
        send(
            out,
            p.id,
            &format!("{op}#{}#{}", b.username, b.platform_number()),
        )?;
        if let Some(target) = self.local_guid(&b.guid, true) {
            self.relation_pair(p, &target, out)?;
            send(
                out,
                target.id,
                &format!("{op}#{}#{}", a.username, a.platform_number()),
            )?;
        } else {
            self.relation_external(p, &b, out)?;
            if self.online(&b, Some(p)) {
                self.relay(&a, &b, "refresh", op, "", Some(p))?;
            }
        }
        Ok(())
    }
    fn relation_external(
        &mut self,
        viewer: &Peer,
        target: &Account,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        let Some(a) = &viewer.account else {
            return Err(Error::bad("identity_not_bound"));
        };
        let next = social::relation(&self.state, a, target)?;
        self.relations
            .insert((a.guid.clone(), target.guid.clone()), next);
        for code in next.codes() {
            send(out, viewer.id, &format!("28#{}#{code}", target.guid))?;
        }
        Ok(())
    }
    fn relation_pair(&mut self, a: &mut Peer, b: &Peer, out: &mut Vec<Outbound>) -> Result<()> {
        self.relation_snapshot(a, b, out)?;
        let mut b = b.clone();
        self.relation_snapshot(&mut b, a, out)?;
        if self.peers.contains_key(&b.id) {
            self.peers.insert(b.id, b);
        }
        Ok(())
    }
    fn relation_snapshot(
        &mut self,
        viewer: &mut Peer,
        target: &Peer,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        let (Some(a), Some(b)) = (viewer.account.clone(), target.account.clone()) else {
            return Err(Error::bad("identity_not_bound"));
        };
        let next = social::relation(&self.state, &a, &b)?;
        let key = (a.guid.clone(), b.guid.clone());
        let (reseed, codes) = self
            .relations
            .insert(key, next)
            .map_or((false, next.codes()), |old| old.transition(next));
        if reseed && self.retire_for(target, viewer, out)? {
            self.reseeds.push(Reseed {
                actor: target.net_id,
                viewer: viewer.id,
                actor_guid: b.guid.clone(),
                viewer_guid: a.guid.clone(),
                frame: self.frame + 2,
                codes,
            });
        } else {
            for code in codes {
                send(out, viewer.id, &format!("28#{}#{code}", b.guid))?;
            }
        }
        Ok(())
    }
    fn pump_relay(&mut self, out: &mut Vec<Outbound>) -> Result<()> {
        self.relay_seen.retain(|_, until| *until > self.state.now());
        for entry in social::drain(&self.state, &self.config.instance_id)? {
            let result = (|| {
                if self.relay_seen.len() >= 4096
                    || self
                        .relay_seen
                        .insert(entry.event_id.clone(), entry.expires_at)
                        .is_some()
                {
                    return Err(Error::bad("social_relay_duplicate_or_capacity"));
                }
                let source = accounts::find(&self.state, &entry.source_guid)?;
                let target = accounts::find(&self.state, &entry.target_guid)?;
                let recipient = self
                    .local_guid(&target.guid, true)
                    .ok_or_else(|| Error::bad("social_relay_target_not_present"))?;
                if source.id != entry.source_account
                    || target.id != entry.target_account
                    || target.instance != self.config.instance_id
                    || (entry.kind != "stop_typing"
                        && (source.instance != entry.source_instance
                            || !self.online(&source, None)))
                {
                    return Err(Error::bad("social_relay_session_not_current_or_present"));
                }
                if matches!(entry.kind.as_str(), "chat" | "typing") && source.muted {
                    return Err(Error::bad("chat_restricted"));
                }
                if !matches!(entry.kind.as_str(), "refresh" | "stop_typing")
                    && !social::can_receive(&self.state, &target, &source)?
                {
                    return Err(Error::bad("social_relay_relation_denied"));
                }
                match entry.kind.as_str() {
                    "request" => {
                        self.send_notification(recipient.id, &source, entry.value, "", out)
                    }
                    "chat" => {
                        if !social::can_private(&self.state, &source, &target)? {
                            return Err(Error::bad("private_chat_not_authorized"));
                        }
                        private(out, recipient.id, &source, &source.guid, &entry.text)
                    }
                    "typing" => {
                        if !social::can_private(&self.state, &source, &target)? {
                            return Err(Error::bad("private_typing_not_authorized"));
                        }
                        send(
                            out,
                            recipient.id,
                            &format!("11#{}#{}", source.guid, source.username),
                        )
                    }
                    "stop_typing" => send(out, recipient.id, &format!("12#{}", source.guid)),
                    "accepted" => {
                        if entry.value == 1 {
                            if !social::relation(&self.state, &source, &target)?.friend {
                                return Err(Error::bad("friendship_not_committed"));
                            }
                            self.send_notification(recipient.id, &source, 5, "", out)?;
                            self.relation_external(&recipient, &source, out)
                        } else {
                            if !social::can_private(&self.state, &source, &target)? {
                                return Err(Error::bad("private_chat_not_authorized"));
                            }
                            private(
                                out,
                                recipient.id,
                                &source,
                                &target.guid,
                                "Private chat connected.",
                            )
                        }
                    }
                    "refresh" => {
                        if entry.value != 21 {
                            social::validate_refresh(&self.state, &source, &target, entry.value)?;
                        }
                        send(
                            out,
                            recipient.id,
                            &format!(
                                "{}#{}#{}",
                                entry.value,
                                source.username,
                                source.platform_number()
                            ),
                        )?;
                        self.relation_external(&recipient, &source, out)
                    }
                    _ => Err(Error::bad("social_relay_invalid_kind")),
                }
            })();
            if let Err(e) = result {
                self.event(0, -1, "social_relay_rejected", &e.message);
            }
        }
        Ok(())
    }
}
fn private(
    out: &mut Vec<Outbound>,
    recipient: u64,
    partner: &Account,
    author: &str,
    text: &str,
) -> Result<()> {
    send(
        out,
        recipient,
        &format!(
            "13#{author}#{}#{}#{text}#1",
            partner.username,
            partner.platform_number()
        ),
    )
}

impl Engine {
    fn ready_guids(&self, caller: Option<&Peer>) -> Vec<String> {
        self.peers
            .values()
            .chain(caller.into_iter())
            .filter(|p| p.spawned && !p.in_wardrobe)
            .filter_map(|p| p.account.as_ref().map(|a| a.guid.clone()))
            .collect()
    }
    fn deliver_interactions(
        &self,
        deliveries: Vec<(String, String)>,
        caller: Option<&Peer>,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        for (guid, text) in deliveries {
            if let Some(p) = self.peers.values().chain(caller.into_iter()).find(|p| {
                p.spawned && !p.in_wardrobe && p.account.as_ref().is_some_and(|a| a.guid == guid)
            }) {
                send(out, p.id, &text)?;
            }
        }
        Ok(())
    }
    fn registration(&mut self, p: &mut Peer, f: &[String], out: &mut Vec<Outbound>) -> Result<()> {
        count(f, 5)?;
        let seq = f[1]
            .parse::<i64>()
            .ok()
            .filter(|v| *v >= 0)
            .ok_or_else(|| Error::bad("interaction_registry_seq_invalid"))?;
        let result = (|| {
            let complete = self.registry.chunk(
                &f[0],
                seq,
                int(&f[2])?,
                int(&f[3])?,
                &f[4],
                self.state.now(),
            )?;
            let Some(json) = complete else {
                return Ok(());
            };
            let doc: Value = serde_json::from_str(&json)?;
            if doc["seq"].as_i64() != Some(seq) {
                return Err(Error::bad("registry_embedded_seq_mismatch"));
            }
            let targets = self.ready_guids(Some(p));
            let (_, accepted, deliveries) = self.registry.register(
                &f[0],
                &json,
                &self.config.space_id,
                self.state.now(),
                &targets,
            )?;
            if accepted {
                self.rebind_deadlines.remove(&f[0]);
            }
            self.deliver_interactions(deliveries, Some(p), out)?;
            send(
                out,
                p.id,
                &format!(
                    "97#{}#{seq}#{}#{}",
                    f[0],
                    if accepted { 1 } else { 0 },
                    if accepted {
                        "accepted"
                    } else {
                        "awaiting_authoritative_ground_signature"
                    }
                ),
            )
        })();
        if let Err(e) = &result {
            send(
                out,
                p.id,
                &format!("97#{}#{seq}#0#{}", f[0], e.message.replace('#', "_")),
            )?;
        }
        result
    }
    fn refresh_trust(&mut self, out: &mut Vec<Outbound>) -> Result<()> {
        let path = self.state.state_dir.join("instance-interactions.json");
        if !path.exists() {
            self.registry.clear_trust();
            self.trust_bytes.clear();
            return Ok(());
        }
        if fs::metadata(&path)?.len() > 32 * 1024 * 1024 {
            self.registry.clear_trust();
            return Err(Error::bad("interaction_registry_snapshot_size"));
        }
        let bytes = fs::read(path)?;
        let invalidated = if bytes == self.trust_bytes {
            vec![]
        } else {
            let r =
                self.registry
                    .refresh(&bytes, &self.config.instance_id, &self.config.space_id)?;
            self.trust_bytes = bytes;
            r
        };
        let mut retained = BTreeSet::new();
        let targets = self.ready_guids(None);
        for (guid, json, until) in self.registry.pending() {
            if self.state.now() > until {
                if let Some(p) = self.local_guid(&guid, false) {
                    out.push(Outbound::Disconnect {
                        peer: p.id,
                        reason: "registry_pending_timeout".into(),
                    });
                }
                continue;
            }
            match self.registry.register(
                &guid,
                &json,
                &self.config.space_id,
                self.state.now(),
                &targets,
            ) {
                Ok((seq, true, deliveries)) => {
                    retained.insert(guid.clone());
                    self.rebind_deadlines.remove(&guid);
                    self.deliver_interactions(deliveries, None, out)?;
                    if let Some(p) = self.local_guid(&guid, false) {
                        send(out, p.id, &format!("97#{guid}#{seq}#1#accepted"))?;
                    }
                }
                Ok(_) => {}
                Err(e) => self.event(0, 97, "registry_pending_rejected", &e.message),
            }
        }
        let owner: Option<String> = {
            let db = self.state.connection()?;
            db.query_row(
                "SELECT owner_ps4_id FROM housing_spaces WHERE instance_id=? AND psidglobal=?",
                params![self.config.instance_id, self.config.space_id],
                |r| r.get(0),
            )
            .optional()?
        };
        for guid in invalidated.into_iter().filter(|g| !retained.contains(g)) {
            if let Some(p) = self.local_guid(&guid, false) {
                if p.account
                    .as_ref()
                    .is_some_and(|a| owner.as_ref() == Some(&a.id))
                {
                    self.rebind_deadlines.insert(guid, self.state.now() + 10.0);
                } else {
                    out.push(Outbound::Disconnect {
                        peer: p.id,
                        reason: "interaction_registry_epoch_changed_reload".into(),
                    });
                }
            }
        }
        for guid in self
            .rebind_deadlines
            .iter()
            .filter(|(_, until)| self.state.now() > **until)
            .map(|(g, _)| g.clone())
            .collect::<Vec<_>>()
        {
            self.rebind_deadlines.remove(&guid);
            if !self.registry.ready(&guid) {
                if let Some(p) = self.local_guid(&guid, false) {
                    out.push(Outbound::Disconnect {
                        peer: p.id,
                        reason: "interaction_registry_owner_rebind_timeout".into(),
                    });
                }
            }
        }
        Ok(())
    }
    fn world(
        &mut self,
        p: &mut Peer,
        op: i32,
        f: &[String],
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        if matches!(op, 45 | 47 | 93) {
            return Err(Error::bad("world_clientbound_only_opcode"));
        }
        let (verified, boats, consumables, generic, history) = inventory(&self.config.space_id);
        let a = p.account.as_ref().unwrap();
        if op == 31 {
            count(f, 3)?;
            let entering = boolean(&f[1])?;
            let token = int(&f[2])?;
            if !verified || !boats.contains(&token) {
                return Err(Error::bad("boat_token_not_in_scene"));
            }
            if !entering {
                if self
                    .world
                    .boats
                    .get(&a.guid)
                    .is_some_and(|old| *old != token)
                {
                    return Err(Error::bad("boat_release_token_mismatch"));
                }
                let had = self.world.boats.remove(&a.guid).is_some();
                for seen in self.world.boat_seen.values_mut() {
                    seen.remove(&a.guid);
                }
                if had {
                    p.animation = None;
                    self.refresh_vehicle_exit(p, out)?;
                }
                return Ok(());
            }
            if let Some(old) = self.world.boats.get(&a.guid) {
                if *old != token {
                    return Err(Error::bad("boat_change_requires_exit"));
                }
                return Ok(());
            }
            self.world.boats.insert(a.guid.clone(), token);
            for seen in self.world.boat_seen.values_mut() {
                seen.remove(&a.guid);
            }
            let reply = format!("31#{}#True#{token}", a.guid);
            for target in self.peers.values().filter(|t| t.announced) {
                send(out, target.id, &reply)?;
            }
            return Ok(());
        }
        if op == 94 {
            if f.len() < 3 {
                return Err(Error::bad("world_wrong_field_count"));
            }
            let id = int(&f[1])?;
            let state = boolean(&f[2])?;
            if !verified
                || id < 0
                || id >= generic
                || (if history { f.len() > 4 } else { f.len() != 3 })
            {
                return Err(Error::bad("generic_interactable_not_in_scene"));
            }
            if f[3..]
                .iter()
                .any(|v| v.encode_utf16().count() > 512 || v.contains('\0'))
            {
                return Err(Error::bad("world_invalid_token"));
            }
            if self.world.generic.get(&id).map_or(false, |(v, _)| *v) == state {
                return Ok(());
            }
            if history && self.world.history.len() >= 4096 {
                return Err(Error::bad("generic_scene_history_limit"));
            }
            let mut fields = vec![a.guid.clone(), id.to_string(), bool_text(state).into()];
            fields.extend_from_slice(&f[3..]);
            let reply = join(94, &fields);
            self.world.generic.insert(id, (state, reply.clone()));
            if history {
                self.world.history.push(reply.clone());
            }
            return self.broadcast_legacy(&reply, Some(p), out);
        }
        count(f, 3)?;
        let tag = if op == 44 { "coffee" } else { "oktoberfest" };
        if f[1] != tag || !verified || !consumables.contains(&tag) {
            return Err(Error::bad("consumable_not_in_scene"));
        }
        if f[2].len() != 32
            || !f[2]
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(Error::bad("consumable_http_receipt_required"));
        }
        let uses = {
            let mut db = self.state.connection()?;
            let tx = db.transaction()?;
            let uses:Option<i32>=tx.query_row("SELECT use_count FROM consumable_receipts WHERE receipt_id=? AND guid=? AND ps4_id=? AND kind=? AND status='pending' AND table_id=0 AND use_count>0 AND reward_index>=0 AND issued_at>0 AND issued_at<=? AND expires_at>? AND expires_at>issued_at",params![f[2],a.guid,a.id,tag,self.state.now(),self.state.now()],|r|r.get(0)).optional()?;
            let uses = uses.ok_or_else(|| Error::bad("consumable_receipt_not_authorized"))?;
            if tx.execute("UPDATE consumable_receipts SET status='claimed',claimed_at=? WHERE receipt_id=? AND status='pending'",params![self.state.now(),f[2]])?!=1{return Err(Error::bad("consumable_receipt_already_claimed"));}
            // Retire the immutable legacy handoff before committing so a
            // surviving Unity instance cannot claim a Rust-consumed receipt.
            let pending = self
                .state
                .state_dir
                .join("consumable-receipts")
                .join(format!("{}.json", f[2]));
            if pending.exists() {
                let claims = self.state.state_dir.join("consumable-claims");
                fs::create_dir_all(&claims)?;
                let claimed = claims.join(format!("{}.json", f[2]));
                if claimed.exists() {
                    return Err(Error::bad("consumable_receipt_already_claimed"));
                }
                fs::rename(pending, claimed)?;
            }
            tx.commit()?;
            uses
        };
        send(out, p.id, &format!("{op}#{}##{tag}#{uses}", a.guid))?;
        let reply = if op == 44 {
            format!("45#{}##{tag}#{uses}", a.guid)
        } else {
            format!("47#{}#{tag}#{uses}", a.guid)
        };
        for target in self.peers.values().filter(|v| v.announced) {
            send(out, target.id, &reply)?;
        }
        Ok(())
    }
    fn refresh_vehicle_exit(&mut self, actor: &Peer, out: &mut Vec<Outbound>) -> Result<()> {
        let ids: Vec<_> = self
            .peers
            .values()
            .filter(|v| v.spawned && v.account.is_some() && v.loaded.contains(&actor.net_id))
            .map(|v| v.id)
            .collect();
        for id in ids {
            let mut viewer = self.peers.remove(&id).unwrap();
            if self.retire_for(actor, &mut viewer, out)? {
                self.reseeds.push(Reseed {
                    actor: actor.net_id,
                    viewer: id,
                    actor_guid: actor.account.as_ref().unwrap().guid.clone(),
                    viewer_guid: viewer.account.as_ref().unwrap().guid.clone(),
                    frame: self.frame + 2,
                    codes: vec![],
                });
            }
            self.peers.insert(id, viewer);
        }
        Ok(())
    }
    fn retire_for(
        &mut self,
        actor: &Peer,
        viewer: &mut Peer,
        out: &mut Vec<Outbound>,
    ) -> Result<bool> {
        viewer.loaded.remove(&actor.net_id);
        viewer.wardrobe_shown.remove(&actor.net_id);
        if !viewer.visible.remove(&actor.net_id) {
            return Ok(false);
        }
        let a = actor
            .account
            .as_ref()
            .ok_or_else(|| Error::bad("retire_unbound_entity"))?;
        viewer.retired.insert(a.id.clone(), self.frame + 2);
        send(out, viewer.id, &format!("14#{}", a.guid))?;
        let mut w = message("Mirror.ObjectDestroyMessage");
        w.write_u32(actor.net_id);
        push(out, viewer.id, true, w.into_inner())?;
        Ok(true)
    }
    fn retire_all(&mut self, actor: &Peer, out: &mut Vec<Outbound>) -> Result<()> {
        self.reseeds.retain(|r| r.actor != actor.net_id);
        let ids: Vec<_> = self.peers.keys().copied().collect();
        for id in ids {
            let mut viewer = self.peers.remove(&id).unwrap();
            let result = self.retire_for(actor, &mut viewer, out);
            self.peers.insert(id, viewer);
            result?;
        }
        Ok(())
    }
    fn show_wardrobe(
        &self,
        actor: &Peer,
        viewer: &mut Peer,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        if actor.in_wardrobe
            && viewer.account.is_some()
            && viewer.loaded.contains(&actor.net_id)
            && viewer.visible.contains(&actor.net_id)
            && viewer.wardrobe_shown.insert(actor.net_id)
        {
            send(
                out,
                viewer.id,
                &format!("29#{}", actor.account.as_ref().unwrap().guid),
            )?;
        }
        Ok(())
    }
    fn enter_wardrobe(
        &mut self,
        p: &mut Peer,
        f: &[String],
        platform: &str,
        out: &mut Vec<Outbound>,
    ) -> Result<()> {
        count(f, 1)?;
        self.own(p, &f[0], platform, out)?;
        announced(p)?;
        if p.in_wardrobe {
            return Ok(());
        }
        let a = p.account.as_ref().unwrap();
        if !a.wardrobe_lease(&self.config.instance_id, self.state.now()) {
            return Err(Error::bad("wardrobe_requires_fresh_http_lease"));
        }
        if a.position_updated > p.position_updated {
            p.position = a.position;
            p.position_updated = a.position_updated;
        }
        self.remember_pose(p);
        self.stop_typing(p, out)?;
        p.in_wardrobe = true;
        send(out, p.id, &format!("29#{}", f[0]))?;
        let ids: Vec<_> = self.peers.keys().copied().collect();
        for id in ids {
            let mut viewer = self.peers.remove(&id).unwrap();
            let result = self.show_wardrobe(p, &mut viewer, out);
            self.peers.insert(id, viewer);
            result?;
        }
        Ok(())
    }
    fn restore_pose(&self, p: &mut Peer) {
        let Some(a) = &p.account else {
            return;
        };
        if let Some(pose) = self.poses.get(&a.id) {
            p.position = pose.position;
            p.rotation = pose.rotation;
            p.scale = pose.scale;
            p.position_updated = pose.updated_at;
        }
        if a.position_updated > p.position_updated {
            p.position = a.position;
            p.position_updated = a.position_updated;
        }
    }
    fn observe_pose(&mut self, p: &mut Peer) {
        p.position_updated = self.state.now();
        self.remember_pose(p);
    }
    fn remember_pose(&mut self, p: &Peer) {
        let Some(a) = &p.account else {
            return;
        };
        if p.position_updated <= 0.0
            || self
                .poses
                .get(&a.id)
                .is_some_and(|v| v.updated_at > p.position_updated)
        {
            return;
        }
        self.poses.insert(
            a.id.clone(),
            Pose {
                ps4_id: a.id.clone(),
                position: p.position,
                rotation: p.rotation,
                scale: p.scale,
                updated_at: p.position_updated,
            },
        );
    }
    fn load_poses(&mut self) -> Result<()> {
        let path = self.instance_dir().join("instance-poses.json");
        if !path.exists() {
            return Ok(());
        }
        if fs::metadata(&path)?.len() > 16 * 1024 * 1024 {
            return Err(Error::bad("pose_snapshot_too_large"));
        }
        let value: Value = serde_json::from_slice(&fs::read(path)?)?;
        if value["format_version"] != 1
            || value["instance_id"] != self.config.instance_id
            || value["psidglobal"] != self.config.space_id
        {
            return Ok(());
        }
        if let Some(rows) = value["poses"].as_array() {
            for row in rows.iter().take(16384) {
                if let Ok(p) = serde_json::from_value::<Pose>(row.clone()) {
                    if !p.ps4_id.is_empty()
                        && p.ps4_id.len() <= 128
                        && p.position.valid()
                        && p.rotation.valid()
                        && p.scale.valid()
                        && p.updated_at.is_finite()
                        && p.updated_at > 0.0
                        && p.updated_at <= self.state.now() + 5.0
                        && !self.poses.contains_key(&p.ps4_id)
                    {
                        self.poses.insert(p.ps4_id.clone(), p);
                    }
                }
            }
        }
        Ok(())
    }
    fn recover_wardrobe(&mut self) -> Result<()> {
        for a in accounts::all(&self.state)? {
            if a.instance != self.config.instance_id
                || !a.wardrobe_lease(&self.config.instance_id, self.state.now())
                || self.wardrobe.contains_key(&a.id)
                || self
                    .peers
                    .values()
                    .any(|p| p.account.as_ref().is_some_and(|b| b.id == a.id))
            {
                continue;
            }
            let mut p = Peer::new(0);
            p.net_id = self.allocate_net_id()?;
            p.ready = true;
            p.spawned = true;
            p.announced = true;
            p.in_wardrobe = true;
            p.companion = a.selected_companion.clone();
            p.locomotion = a.selected_locomotion.clone();
            p.companion_revision = a.companion_revision;
            p.locomotion_revision = a.locomotion_revision;
            p.account = Some(a.clone());
            self.restore_pose(&mut p);
            self.wardrobe.insert(a.id.clone(), p);
        }
        Ok(())
    }
    fn instance_dir(&self) -> std::path::PathBuf {
        self.state
            .state_dir
            .join("instances")
            .join(&self.config.instance_id)
    }
    fn atomic(&self, name: &str, value: &Value) -> Result<()> {
        let dir = self.instance_dir();
        fs::create_dir_all(&dir)?;
        let temp = dir.join(format!(
            ".{name}.rust.{}.tmp",
            uuid::Uuid::new_v4().simple()
        ));
        fs::write(&temp, serde_json::to_vec(value)?)?;
        let target = dir.join(name);
        // Windows rename does not replace files, use a write-through same-volume
        // replacement primitive exposed by MoveFileExW via the existing runtime.
        replace_file(&temp, &target)?;
        Ok(())
    }
    fn publish(&mut self) -> Result<()> {
        let now = self.state.now();
        let entities = if self.listening {
            self.entities()
        } else {
            vec![]
        };
        for p in &entities {
            self.remember_pose(p);
        }
        let players: Vec<_> = entities
            .iter()
            .filter_map(|p| {
                p.account
                    .as_ref()
                    .map(|a| json!({"guid":a.guid,"status":if p.in_wardrobe{3}else{0}}))
            })
            .collect();
        self.atomic("instance-presence.json",&json!({"format_version":1,"instance_id":self.config.instance_id,"psidglobal":self.config.space_id,"generation":now,"players":players}))?;
        let avatars:Vec<_>=entities.iter().filter_map(|p|p.account.as_ref().map(|a|json!({"guid":a.guid,"ps4_id":a.id,"net_id":p.net_id,"connected":self.peers.contains_key(&p.id)&&p.id!=0,"announced":p.announced,"in_wardrobe":p.in_wardrobe,"position":p.position,"rotation":p.rotation,"scale":p.scale,"position_updated_at":p.position_updated}))).collect();
        self.atomic("instance-avatar-state.json",&json!({"format_version":1,"instance_id":self.config.instance_id,"psidglobal":self.config.space_id,"generation":now,"listening":self.listening,"wardrobe_delivery":"mirror_after_avatar_ready_v1","avatars":avatars}))?;
        self.atomic("instance-poses.json",&json!({"format_version":1,"instance_id":self.config.instance_id,"psidglobal":self.config.space_id,"generation":now,"poses":self.poses.values().collect::<Vec<_>>()}))?;
        self.last_publish = now;
        Ok(())
    }
    pub fn disconnect(&mut self, id: u64) -> Result<Vec<Outbound>> {
        let Some(mut p) = self.peers.remove(&id) else {
            return Ok(vec![]);
        };
        let mut out = vec![];
        let _ = self.stop_typing(&mut p, &mut out);
        self.reseeds
            .retain(|r| r.actor != p.net_id && r.viewer != id);
        if let Some(a) = &p.account {
            let a = a.clone();
            self.rebind_deadlines.remove(&a.guid);
            self.relations
                .retain(|(x, y), _| x != &a.guid && y != &a.guid);
            let targets = self.ready_guids(None);
            let deliveries = self.registry.disconnect(&a.guid, &targets);
            self.deliver_interactions(deliveries, None, &mut out)?;
            self.remember_pose(&p);
            if accounts::find(&self.state, &a.guid).is_err() {
                let _ = social::expire(&self.state, Some(&a.guid));
            }
            self.world.boats.remove(&a.guid);
            self.world.boat_seen.remove(&a.guid);
            self.world.scene_seen.remove(&a.guid);
            for seen in self.world.boat_seen.values_mut() {
                seen.remove(&a.guid);
            }
            let seats: Vec<_> = self
                .occupables
                .iter()
                .filter(|(_, g)| *g == &a.guid)
                .map(|(id, _)| *id)
                .collect();
            for seat in seats {
                self.occupables.remove(&seat);
                self.broadcast_legacy(&format!("10#{}#{seat}", a.guid), None, &mut out)?;
            }
            let current = accounts::find(&self.state, &a.guid).ok();
            if p.announced
                && p.in_wardrobe
                && current.as_ref().is_some_and(|c| {
                    c.id == a.id
                        && c.instance == self.config.instance_id
                        && c.wardrobe_lease(&self.config.instance_id, self.state.now())
                })
            {
                p.account = current;
                self.wardrobe.insert(a.id, p);
            } else if p.spawned {
                self.retire_all(&p, &mut out)?;
            }
        }
        self.event(id, -1, "disconnected", "local_presence_removed");
        bounded(out)
    }
    pub fn tick(&mut self) -> Result<Vec<Outbound>> {
        self.frame = self.frame.saturating_add(1);
        let mut out = vec![];
        // A failed/changed authority cannot keep an idle player connected.
        for id in self.peers.keys().copied().collect::<Vec<_>>() {
            let mut p = self.peers.remove(&id).unwrap();
            let result = if p.account.is_some() {
                self.bound(&mut p)
            } else {
                Ok(())
            };
            let lease_ok = p.account.as_ref().is_none_or(|a| {
                !p.in_wardrobe || a.wardrobe_lease(&self.config.instance_id, self.state.now())
            });
            if let Err(e) = result {
                self.peers.insert(id, p);
                out.extend(self.disconnect(id)?);
                out.push(Outbound::Disconnect {
                    peer: id,
                    reason: e.message,
                });
                continue;
            }
            if !lease_ok {
                self.peers.insert(id, p);
                out.extend(self.disconnect(id)?);
                out.push(Outbound::Disconnect {
                    peer: id,
                    reason: "wardrobe_lease_expired".into(),
                });
                continue;
            }
            if p.account.as_ref().is_some_and(|a| a.muted)
                && (p.typing_public || p.typing_target.is_some())
            {
                self.stop_typing(&mut p, &mut out)?;
            }
            if let Some(a) = &p.account {
                let a = a.clone();
                for (op, item, revision, old) in [
                    (
                        17,
                        a.selected_companion.clone(),
                        a.companion_revision,
                        p.companion_revision,
                    ),
                    (
                        15,
                        a.selected_locomotion.clone(),
                        a.locomotion_revision,
                        p.locomotion_revision,
                    ),
                ] {
                    if revision > old {
                        if op == 17 {
                            p.companion = item.clone();
                            p.companion_revision = revision;
                        } else {
                            p.locomotion = item.clone();
                            p.locomotion_revision = revision;
                        }
                        let reply = format!("{op}#{}#{item}", a.guid);
                        self.broadcast(&reply, Some(&p), &mut out)?;
                        send(&mut out, id, &reply)?;
                    }
                }
                if p.announced {
                    for (event, name, platform, kind, args, ticks) in
                        social::notification_rows(&self.state, &a)?
                    {
                        if p.delivered_notifications.insert(event) {
                            send(
                                &mut out,
                                id,
                                &format!("19#{name}#{platform}#{kind}#{args}#{ticks}"),
                            )?;
                        }
                    }
                }
            }
            p.informational.retain(|_, t| *t > self.state.now());
            self.peers.insert(id, p);
        }
        for key in self.wardrobe.keys().cloned().collect::<Vec<_>>() {
            let p = self.wardrobe.get(&key).unwrap();
            let a = p.account.as_ref().unwrap();
            if accounts::find(&self.state, &a.guid).is_ok_and(|c| {
                c.id == a.id
                    && c.instance == self.config.instance_id
                    && c.wardrobe_lease(&self.config.instance_id, self.state.now())
            }) {
                continue;
            }
            let p = self.wardrobe.remove(&key).unwrap();
            self.retire_all(&p, &mut out)?;
        }
        self.recover_wardrobe()?;
        if let Err(e) = self.refresh_trust(&mut out) {
            self.event(0, 97, "interaction_registry_refresh_rejected", &e.message);
        }
        self.process_reseeds(&mut out)?;
        self.pump_relay(&mut out)?;
        social::expire(&self.state, None)?;
        if self.state.now() - self.last_publish >= 1.0 {
            self.publish()?;
        }
        bounded(out)
    }
    fn process_reseeds(&mut self, out: &mut Vec<Outbound>) -> Result<()> {
        let pending = std::mem::take(&mut self.reseeds);
        for item in pending {
            if item.frame > self.frame {
                self.reseeds.push(item);
                continue;
            }
            let actor = self.entities().into_iter().find(|p| {
                p.net_id == item.actor
                    && p.account
                        .as_ref()
                        .is_some_and(|a| a.guid == item.actor_guid)
            });
            let Some(actor) = actor else {
                continue;
            };
            let Some(mut viewer) = self.peers.remove(&item.viewer) else {
                continue;
            };
            let valid = viewer
                .account
                .as_ref()
                .is_some_and(|a| a.guid == item.viewer_guid)
                && self.bound(&mut viewer).is_ok();
            if valid {
                if let Some(frame) = viewer
                    .retired
                    .get(&actor.account.as_ref().unwrap().id)
                    .filter(|f| **f > self.frame)
                {
                    let mut item = item;
                    item.frame = *frame;
                    self.reseeds.push(item);
                } else {
                    viewer.retired.remove(&actor.account.as_ref().unwrap().id);
                    self.spawn(&actor, &mut viewer, false, out)?;
                    send(out, viewer.id, &joined(&actor)?)?;
                    for code in item.codes {
                        send(out, viewer.id, &format!("28#{}#{code}", item.actor_guid))?;
                    }
                }
            }
            self.peers.insert(viewer.id, viewer);
        }
        Ok(())
    }
}

// Scene inventory is taken from NebulaWorldState.SceneInventory.ForSpace.
// Return verified, boats, consumables, generic count, replay history.
fn inventory(space: &str) -> (bool, Vec<i32>, Vec<&'static str>, i32, bool) {
    match space.to_ascii_lowercase().as_str() {
        "leafpark" => (true, vec![0, 1, 2], vec!["coffee"], 0, false),
        "beach" | "bluewavehideout" | "greenhouse" => (true, vec![0], vec![], 0, false),
        "thenebulian" => (true, vec![0], vec![], 1, false),
        "greeksummerhouse" | "nebuhouse" | "nebuhouseopenhouse" | "serenegarden"
        | "woodlandclearing" => (true, vec![], vec![], 1, false),
        "westvalleyapartment" | "westvalleyapartmentopenhouse" | "wintersnowglobe" => {
            (true, vec![], vec![], 2, false)
        }
        "tokyoapartment" => (true, vec![], vec![], 3, false),
        "lechalet" | "whisperinghillsmansion" => (true, vec![], vec![], 4, false),
        "lakeapartment" => (true, vec![], vec![], 6, false),
        "waterfall" => (true, vec![], vec![], 9, false),
        "hollyridgeestate" => (true, vec![], vec![], 4, true),
        "nexus"
        | "cinema"
        | "cliffapartment"
        | "cube"
        | "deadquarters"
        | "dome"
        | "dressingroom"
        | "flyingdevice"
        | "forgottenstation"
        | "ghosttown"
        | "gingerbreadhouse"
        | "home"
        | "medievalvillage"
        | "mountainhideout"
        | "skl"
        | "starcrawlers"
        | "steampunk"
        | "stonelakecastle"
        | "thecrypt"
        | "themoonlightroom"
        | "tokyoapartmentopenhouse"
        | "windmillfarmhouse"
        | "zerodistrict"
        | "zerodistrictden"
        | "bowling"
        | "thenebulianopenhouse" => (true, vec![], vec![], 0, false),
        _ => (false, vec![], vec![], 0, false),
    }
}

#[cfg(windows)]
fn replace_file(source: &std::path::Path, target: &std::path::Path) -> Result<()> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(existing: *const u16, new: *const u16, flags: u32) -> i32;
    }
    let a: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let b: Vec<u16> = target.as_os_str().encode_wide().chain(Some(0)).collect();
    if unsafe { MoveFileExW(a.as_ptr(), b.as_ptr(), 1 | 8) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}
#[cfg(not(windows))]
fn replace_file(source: &std::path::Path, target: &std::path::Path) -> Result<()> {
    fs::rename(source, target)?;
    Ok(())
}
