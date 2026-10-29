use nebula_preserved_server::{
    mirror::{message_id, stable_hash, Reader, Writer},
    state::State,
    wire,
    world::{Config, Engine, Outbound, CLIENTBOUND_ONLY_OPCODES, EXCLUDED_MINIGAME_OPCODES},
};
use serde_json::{json, Value};
use std::{fs, path::PathBuf};
const A: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const B: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const NOW: f64 = 1_800_000_000.0;
fn fixture(space: &str) -> (tempfile::TempDir, State, Engine) {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dir = tempfile::tempdir().unwrap();
    let protocol = std::env::var_os("NEBULA_REFERENCE_PROTOCOL_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("../../protocol"));
    let mut state = State::open(dir.path(), &protocol).unwrap();
    state.fixed_time = Some(NOW);
    {
        let db = state.connection().unwrap();
        for (g, id, name) in [
            (A, "world-test-account-a", "World Alpha"),
            (B, "world-test-account-b", "World Beta"),
        ] {
            db.execute(
                "INSERT INTO profiles VALUES(?,?,'StandaloneWindows','MALE',?)",
                rusqlite::params![id, name, NOW],
            )
            .unwrap();
            db.execute("INSERT INTO profile_state(ps4_id)VALUES(?)", [id])
                .unwrap();
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                rusqlite::params![g, id, NOW],
            )
            .unwrap();
            db.execute(
                "INSERT INTO allocations VALUES(?,'world-test',?,'127.0.0.1',28000,?)",
                rusqlite::params![g, space, NOW],
            )
            .unwrap();
        }
    }
    let engine = Engine::new(
        Config {
            instance_id: "world-test".into(),
            space_id: space.into(),
            max_peers: 32,
        },
        state.clone(),
    )
    .unwrap();
    let path = dir.path().join("instances/world-test");
    fs::create_dir_all(&path).unwrap();
    fs::write(path.join("instance-status.json"),serde_json::to_vec(&json!({"format_version":1,"instance_id":"world-test","psidglobal":space,"owner":"cccccccccccccccccccccccccccccccc","listening":true,"listener_bound":true,"heartbeat":NOW})).unwrap()).unwrap();
    (dir, state, engine)
}
fn empty(name: &str) -> Vec<u8> {
    let mut w = Writer::new();
    w.write_u16(message_id(name));
    w.into_inner()
}
fn app(text: &str) -> Vec<u8> {
    let mut w = Writer::new();
    w.write_u16(message_id("NebulaMessage"));
    w.write_string(Some(
        &wire::encrypt(&format!("{text}#StandaloneWindows")).unwrap(),
    ))
    .unwrap();
    w.into_inner()
}
fn send(e: &mut Engine, id: u64, text: &str) -> Vec<Outbound> {
    e.receive(id, &app(text)).unwrap()
}
fn texts(out: &[Outbound]) -> Vec<(u64, String)> {
    out.iter()
        .filter_map(|o| {
            let Outbound::Send { peer, message, .. } = o else {
                return None;
            };
            let mut r = Reader::new(message);
            if r.read_u16().ok() != Some(message_id("NebulaMessage")) {
                return None;
            }
            Some((
                *peer,
                wire::decrypt(&r.read_string().unwrap().unwrap()).unwrap(),
            ))
        })
        .collect()
}
fn spawn(e: &mut Engine, id: u64) -> (u32, Vec<Outbound>) {
    e.connect(id).unwrap();
    e.receive(id, &empty("Mirror.ReadyMessage")).unwrap();
    let out = e.receive(id, &empty("Mirror.AddPlayerMessage")).unwrap();
    let net = out
        .iter()
        .find_map(|o| {
            let Outbound::Send { message, .. } = o else {
                return None;
            };
            let mut r = Reader::new(message);
            (r.read_u16().ok() == Some(message_id("Mirror.SpawnMessage")))
                .then(|| r.read_u32().unwrap())
        })
        .unwrap();
    (net, out)
}
fn announce(e: &mut Engine, id: u64, guid: &str, name: &str) -> u32 {
    let (net, _) = spawn(e, id);
    send(e, id, &format!("1#{net}#{guid}#{name}#1"));
    net
}
fn two(e: &mut Engine) -> (u32, u32) {
    let a = announce(e, 1, A, "World Alpha");
    let b = announce(e, 2, B, "World Beta");
    (a, b)
}
fn command(net: u32, component: u8, signature: &str, payload: &[u8]) -> Vec<u8> {
    let mut w = Writer::new();
    w.write_u16(message_id("Mirror.CommandMessage"));
    w.write_u32(net);
    w.write_u8(component);
    w.write_i32(stable_hash(signature));
    w.write_bytes_and_size(Some(payload)).unwrap();
    w.into_inner()
}

#[test]
fn local_spawn_matches_prefab_and_mirror66_layout() {
    let (_dir, _s, mut e) = fixture("Nexus");
    let (net, out) = spawn(&mut e, 1);
    assert_eq!(net, 1);
    assert_eq!(out.len(), 4);
    assert_eq!(texts(&out), vec![(1, "0".into())]);
    let Outbound::Send { message, .. } = &out[1] else {
        panic!()
    };
    let mut r = Reader::new(message);
    assert_eq!(r.read_u16().unwrap(), message_id("Mirror.SpawnMessage"));
    assert_eq!(r.read_u32().unwrap(), 1);
    assert!(r.read_bool().unwrap());
    assert!(r.read_bool().unwrap());
    assert_eq!(r.read_u64().unwrap(), 0);
    assert_eq!(
        r.read_uuid().unwrap(),
        uuid::Uuid::parse_str("86041873b099ede4687c67606e379683").unwrap()
    );
    assert_eq!(r.read_vector3().unwrap(), [0.0; 3]);
    assert_eq!(r.read_quaternion().unwrap(), [0.0, 0.0, 0.0, 1.0]);
    assert_eq!(r.read_vector3().unwrap(), [1.0; 3]);
    let data = r.read_bytes_and_size().unwrap().unwrap();
    r.finish().unwrap();
    let mut s = Reader::new(&data);
    assert_eq!(s.read_u8().unwrap(), 0);
    assert_eq!(s.read_i32().unwrap(), 28);
    assert_eq!(s.read_vector3().unwrap(), [0.0; 3]);
    assert_eq!(s.read_quaternion().unwrap(), [0.0, 0.0, 0.0, 1.0]);
    assert_eq!(s.read_u8().unwrap(), 1);
    assert_eq!(s.read_i32().unwrap(), 4);
    assert_eq!(s.read_f32().unwrap(), 0.0);
    s.finish().unwrap();
}

#[test]
fn application_requires_ready_spawn_and_current_allocation() {
    let (_dir, s, mut e) = fixture("Nexus");
    e.connect(1).unwrap();
    assert!(e
        .receive(1, &app(&format!("1#1#{A}#World Alpha#1")))
        .is_err());
    assert!(e.receive(1, &empty("Mirror.AddPlayerMessage")).is_err());
    e.receive(1, &empty("Mirror.ReadyMessage")).unwrap();
    e.receive(1, &empty("Mirror.AddPlayerMessage")).unwrap();
    s.connection()
        .unwrap()
        .execute(
            "UPDATE allocations SET instance_id='different'WHERE guid=?",
            [A],
        )
        .unwrap();
    assert!(e
        .receive(1, &app(&format!("1#1#{A}#World Alpha#1")))
        .is_err());
    assert!(e
        .receive(
            1,
            &app("1#1#00000000000000000000000000000000#World Alpha#1")
        )
        .is_err());
}

#[test]
fn announce_seeds_remotes_once_and_queries_require_visibility() {
    let (_dir, _s, mut e) = fixture("Nexus");
    let anet = announce(&mut e, 1, A, "World Alpha");
    let (bnet, _) = spawn(&mut e, 2);
    let out = send(&mut e, 2, &format!("1#{bnet}#{B}#World Beta#1"));
    let t = texts(&out);
    assert!(t.contains(&(2, format!("1#{anet}#{A}#World Alpha#1"))));
    assert!(t.contains(&(1, format!("1#{bnet}#{B}#World Beta#1"))));
    assert!(texts(&send(&mut e, 2, &format!("1#{bnet}#{B}#World Beta#1"))).is_empty());
    assert_eq!(
        texts(&send(&mut e, 1, &format!("16#{A}#{B}"))),
        vec![(1, format!("15#{B}#"))]
    );
    assert!(e.receive(1, &app(&format!("20#{A}#{A}"))).is_err());
}

#[test]
fn animation_translates_sentinel_and_retains_only_valid_frame() {
    let (_dir, _s, mut e) = fixture("Nexus");
    two(&mut e);
    let out = send(&mut e, 1, &format!("4#{A}#-1#2#1#Wave#1#WaveClip"));
    assert_eq!(texts(&out), vec![(2, format!("5#{A}#2#1#Wave#1#WaveClip"))]);
    assert!(e
        .receive(1, &app(&format!("4#{A}#999#2#1#Wave#1#WaveClip")))
        .is_err());
    assert!(e
        .receive(1, &app(&format!("4#{A}#-1#2#1#Wave#2#WaveClip")))
        .is_err());
    assert_eq!(
        texts(&send(&mut e, 2, &format!("3#{B}#{A}"))),
        vec![(2, format!("5#{A}#2#1#Wave#1#WaveClip"))]
    );
}

#[test]
fn native_speed_and_transform_commands_replicate_exact_components() {
    let (_dir, _s, mut e) = fixture("Nexus");
    let (a, _) = two(&mut e);
    let out=e.receive(1,&command(a,1,"System.Void Assets.Scripts.NebulaPlayers.NebulaPlayerSyncVars::SetSpeed(System.Single)",&3.5f32.to_le_bytes())).unwrap();
    assert_eq!(out.len(), 1);
    let Outbound::Send {
        peer,
        message,
        reliable,
    } = &out[0]
    else {
        panic!()
    };
    assert_eq!(*peer, 2);
    assert!(*reliable);
    let mut r = Reader::new(message);
    assert_eq!(
        r.read_u16().unwrap(),
        message_id("Mirror.EntityStateMessage")
    );
    assert_eq!(r.read_u32().unwrap(), a);
    let data = r.read_bytes_and_size().unwrap().unwrap();
    let mut r = Reader::new(&data);
    assert_eq!(r.read_u8().unwrap(), 1);
    assert_eq!(r.read_i32().unwrap(), 12);
    assert_eq!(r.read_u64().unwrap(), 1);
    assert_eq!(r.read_f32().unwrap(), 3.5);
    r.finish().unwrap();
    let signature="System.Void Mirror.NetworkTransformBase::CmdClientToServerSync(System.Nullable`1<UnityEngine.Vector3>,System.Nullable`1<UnityEngine.Quaternion>,System.Nullable`1<UnityEngine.Vector3>)";
    let mut payload = Writer::new();
    payload.write_u8(1);
    payload.write_vector3([1.0, 2.0, 3.0]);
    payload.write_u8(0);
    payload.write_u8(0);
    let out = e
        .receive(1, &command(a, 0, signature, payload.as_slice()))
        .unwrap();
    assert_eq!(out.len(), 2);
    assert!(out.iter().all(|o| matches!(
        o,
        Outbound::Send {
            reliable: false,
            ..
        }
    )));
    assert!(e
        .receive(1, &command(a + 1, 0, signature, payload.as_slice()))
        .is_err());
    assert!(e.receive(1, &command(a, 0, signature, &[2, 0, 0])).is_err());
    let t = texts(&send(&mut e, 2, &format!("20#{B}#{A}")));
    let parts: Vec<_> = t[0].1.splitn(3, '#').collect();
    let v: Value = serde_json::from_str(parts[2]).unwrap();
    assert_eq!(v["position"], json!({"x":1.0,"y":2.0,"z":3.0}));
}

#[test]
fn public_private_friend_and_invite_are_correlated() {
    let (dir, s, mut e) = fixture("Nexus");
    two(&mut e);
    assert!(e
        .receive(1, &app(&format!("13#{A}#World Beta#1#Before consent#1")))
        .is_err());
    let out = send(&mut e, 1, "19#World Alpha#World Beta#1#1");
    assert!(texts(&out)
        .iter()
        .any(|(p, t)| *p == 2 && t.starts_with("19#World Alpha#1#1##")));
    let out = send(&mut e, 2, &format!("26#{B}#World Alpha#1#1"));
    assert!(texts(&out)
        .iter()
        .any(|(p, t)| *p == 1 && t.starts_with("19#World Beta#1#5##")));
    let friends: i64 = s
        .connection()
        .unwrap()
        .query_row(
            "SELECT COUNT(*)FROM relations WHERE kind='friend'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(friends, 2);
    assert_eq!(
        texts(&send(&mut e, 1, &format!("13#{A}#World Beta#1#Hello#1"))).len(),
        2
    );
    send(&mut e, 1, "19#World Alpha#World Beta#6#1");
    let requests = fs::read_dir(dir.path().join("social-requests"))
        .unwrap()
        .count();
    assert_eq!(requests, 1);
    assert!(e
        .receive(2, &app(&format!("26#{B}#World Alpha#6#1")))
        .is_err());
    assert_eq!(
        texts(&send(
            &mut e,
            1,
            &format!("13#{A}#Public#-1#Public hello#0")
        ))
        .len(),
        2
    );
}

#[test]
fn mute_block_silence_and_revocation_apply_without_reconnect() {
    let (_dir, s, mut e) = fixture("Nexus");
    two(&mut e);
    s.connection().unwrap().execute("INSERT INTO relations VALUES('world-test-account-b','World Alpha','StandaloneWindows','silenced')",[]).unwrap();
    let out = send(&mut e, 1, &format!("13#{A}#Public#-1#Hidden#0"));
    assert_eq!(texts(&out).len(), 1);
    assert_eq!(texts(&out)[0].0, 1);
    s.connection()
        .unwrap()
        .execute(
            "INSERT INTO moderation_accounts(ps4_id,mute_enabled)VALUES('world-test-account-a',1)",
            [],
        )
        .unwrap();
    assert!(e
        .receive(1, &app(&format!("13#{A}#Public#-1#Muted#0")))
        .is_err());
    s.connection().unwrap().execute("INSERT INTO sessions VALUES('ffffffffffffffffffffffffffffffff','world-test-account-a',?)",[NOW+1.0]).unwrap();
    let out = e.tick().unwrap();
    assert!(out
        .iter()
        .any(|o| matches!(o, Outbound::Disconnect { peer: 1, .. })));
    assert_eq!(e.peer_count(), 1);
}

#[test]
fn resource_clear_uses_shared_durable_authority() {
    let (_dir, s, mut e) = fixture("Nexus");
    two(&mut e);
    let out = send(&mut e, 1, &format!("17#{A}#"));
    assert_eq!(texts(&out).len(), 2);
    let revision:i64=s.connection().unwrap().query_row("SELECT revision FROM resource_selections WHERE ps4_id='world-test-account-a'AND kind='companions'",[],|r|r.get(0)).unwrap();
    assert_eq!(revision, 1);
    let receipts: i64 = s
        .connection()
        .unwrap()
        .query_row("SELECT COUNT(*)FROM resource_selection_receipts", [], |r| {
            r.get(0)
        })
        .unwrap();
    assert_eq!(receipts, 1);
    let out = send(&mut e, 1, &format!("17#{A}#forgedasset"));
    assert_eq!(texts(&out), vec![(1, format!("17#{A}#"))]);
    assert!(e.drain_events().iter().any(|v| v.kind == "rejected"));
}

#[test]
fn boat_exit_reseeds_after_two_ticks_and_consumable_receipts_claim_once() {
    let (dir, s, mut e) = fixture("LeafPark");
    two(&mut e);
    send(&mut e, 2, &format!("3#{B}#{A}"));
    assert_eq!(
        texts(&send(&mut e, 1, &format!("31#{A}#True#1"))),
        vec![(2, format!("31#{A}#True#1"))]
    );
    let out = send(&mut e, 1, &format!("31#{A}#False#1"));
    assert!(texts(&out).contains(&(2, format!("14#{A}"))));
    assert!(!e.tick().unwrap().iter().any(|o|matches!(o,Outbound::Send{message,..}if message.starts_with(&message_id("Mirror.SpawnMessage").to_le_bytes()))));
    let out = e.tick().unwrap();
    assert!(texts(&out)
        .iter()
        .any(|(p, t)| *p == 2 && t.starts_with("1#")));
    let receipt = "dddddddddddddddddddddddddddddddd";
    s.connection().unwrap().execute("INSERT INTO consumable_receipts VALUES(?,'world-test-account-a',?,'coffee',0,5,0,?,?,'pending',NULL)",rusqlite::params![receipt,A,NOW-1.0,NOW+30.0]).unwrap();
    let pending = dir.path().join("consumable-receipts");
    fs::create_dir_all(&pending).unwrap();
    fs::write(pending.join(format!("{receipt}.json")), "{}").unwrap();
    let out = send(&mut e, 1, &format!("44#{A}#coffee#{receipt}"));
    assert!(texts(&out).contains(&(1, format!("44#{A}##coffee#5"))));
    assert!(texts(&out).contains(&(2, format!("45#{A}##coffee#5"))));
    assert!(dir
        .path()
        .join(format!("consumable-claims/{receipt}.json"))
        .exists());
    assert!(e
        .receive(1, &app(&format!("44#{A}#coffee#{receipt}")))
        .is_err());
}

#[test]
fn generic_history_and_unknown_scene_fail_closed() {
    let (_dir, _s, mut e) = fixture("HollyridgeEstate");
    two(&mut e);
    assert_eq!(
        texts(&send(&mut e, 1, &format!("94#{A}#1#True#extra"))).len(),
        2
    );
    assert!(texts(&send(&mut e, 1, &format!("94#{A}#1#True#extra"))).is_empty());
    assert!(e.receive(1, &app(&format!("94#{A}#4#True"))).is_err());
    let (_dir, _s, mut e) = fixture("UnknownScene");
    announce(&mut e, 1, A, "World Alpha");
    assert!(!e.scene_inventory_verified());
    assert!(e.receive(1, &app(&format!("94#{A}#0#True"))).is_err());
}

#[test]
fn unsupported_and_wrong_direction_traffic_is_never_passthrough() {
    let (_dir, _s, mut e) = fixture("Nexus");
    two(&mut e);
    for op in EXCLUDED_MINIGAME_OPCODES
        .iter()
        .chain(CLIENTBOUND_ONLY_OPCODES)
    {
        assert!(
            e.receive(1, &app(&format!("{op}#{A}"))).is_err(),
            "opcode{op}"
        );
    }
    assert!(e.receive(1, &app(&format!("96#{A}"))).is_err());
    assert!(e.receive(1, &app(&format!("999#{A}"))).is_err());
    let mut malformed = app(&format!("12#{A}"));
    malformed.push(0);
    assert!(e.receive(1, &malformed).is_err());
    assert!(e.receive(1, &[0xff, 0xff]).is_err());
    assert!(e
        .drain_events()
        .iter()
        .any(|v| v.kind == "unsupported_opcode"));
}

#[test]
fn disconnect_releases_occupancy_and_destroys_remote_entity() {
    let (_dir, _s, mut e) = fixture("Nexus");
    let (a, _) = two(&mut e);
    send(&mut e, 1, &format!("9#{A}#5"));
    let out = e.disconnect(1).unwrap();
    assert!(texts(&out).contains(&(2, format!("10#{A}#5"))));
    assert!(texts(&out).contains(&(2, format!("14#{A}"))));
    let destroyed = out.iter().any(|o| {
        let Outbound::Send { message, .. } = o else {
            return false;
        };
        let mut r = Reader::new(message);
        r.read_u16().ok() == Some(message_id("Mirror.ObjectDestroyMessage"))
            && r.read_u32().ok() == Some(a)
    });
    assert!(destroyed);
    assert_eq!(
        texts(&send(&mut e, 2, &format!("8#{B}#5"))),
        vec![(2, "10##5".into())]
    );
}

#[test]
fn wardrobe_requires_http_lease_and_retains_then_retires_ghost() {
    let (_dir, s, mut e) = fixture("Nexus");
    two(&mut e);
    assert!(e.receive(1, &app(&format!("29#{A}"))).is_err());
    s.connection().unwrap().execute("UPDATE profile_state SET in_wardrobe=1,wardrobe_instance_id='world-test',wardrobe_updated_at=?WHERE ps4_id='world-test-account-a'",[NOW]).unwrap();
    send(&mut e, 2, &format!("3#{B}#{A}"));
    let out = send(&mut e, 1, &format!("29#{A}"));
    assert!(texts(&out).contains(&(1, format!("29#{A}"))));
    assert!(texts(&out).contains(&(2, format!("29#{A}"))));
    assert!(e.receive(1,&app("2#1#{\"position\":{\"x\":1,\"y\":0,\"z\":0},\"rotation\":{\"x\":0,\"y\":0,\"z\":0,\"w\":1}}" )).is_err());
    let out = e.disconnect(1).unwrap();
    assert!(!texts(&out).iter().any(|(_, t)| t == &format!("14#{A}")));
    s.connection()
        .unwrap()
        .execute(
            "UPDATE profile_state SET wardrobe_updated_at=?WHERE ps4_id='world-test-account-a'",
            [NOW - 61.0],
        )
        .unwrap();
    let out = e.tick().unwrap();
    assert!(texts(&out).contains(&(2, format!("14#{A}"))));
}

#[test]
fn unblocking_reseeds_each_viewer_before_reapplying_relationship() {
    let (_dir, s, mut e) = fixture("Nexus");
    two(&mut e);
    s.connection().unwrap().execute("INSERT INTO relations VALUES('world-test-account-a','World Beta','StandaloneWindows','block')",[]).unwrap();
    let out = send(&mut e, 1, &format!("24#{A}#World Beta#1"));
    assert!(texts(&out).contains(&(1, format!("28#{B}#5"))));
    assert!(texts(&out).contains(&(2, format!("28#{A}#6"))));
    s.connection()
        .unwrap()
        .execute("DELETE FROM relations WHERE kind='block'", [])
        .unwrap();
    let out = send(&mut e, 1, &format!("25#{A}#World Beta#1"));
    assert!(texts(&out).contains(&(1, format!("14#{B}"))));
    assert!(texts(&out).contains(&(2, format!("14#{A}"))));
    e.tick().unwrap();
    let out = e.tick().unwrap();
    assert!(texts(&out).contains(&(1, format!("28#{B}#0"))));
    assert!(texts(&out).contains(&(2, format!("28#{A}#0"))));
}

fn trusted_entry(kind: &str, class: &str) -> Value {
    json!({"kind":kind,"anchor":"scene-root","class":class,"item_id":"","path":[0],"slot":0,"ground_index":-1,"classification":"ordinary","extension_arity":0})
}
fn register(
    e: &mut Engine,
    id: u64,
    guid: &str,
    seq: i64,
    source: &str,
    entries: Vec<Value>,
) -> Vec<Outbound> {
    use base64::Engine as _;
    let doc = json!({"v":1,"source":source,"scene":e.config().space_id,"seq":seq,"entries":entries,"ground_sig":[]});
    let encoded =
        base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(serde_json::to_vec(&doc).unwrap());
    send(e, id, &format!("97#{guid}#{seq}#0#1#{encoded}"))
}
#[test]
fn trusted_registry_maps_peer_namespaces_and_failed_claim_disconnects() {
    let (dir, _s, mut e) = fixture("Nexus");
    two(&mut e);
    let trusted = json!({"format_version":1,"instances":[{"instance_id":"world-test","scene":"Nexus","epoch":"test-epoch1","trusted":true,"static_profile_available":true,"static_entries":[trusted_entry("occupable","Seat")],"furniture_entries":[],"ground_sig":[]}]});
    fs::write(
        dir.path().join("instance-interactions.json"),
        serde_json::to_vec(&trusted).unwrap(),
    )
    .unwrap();
    e.tick().unwrap();
    assert!(e.registry_trusted());
    let entry = |send: i32, receive: i32| {
        let mut v = trusted_entry("occupable", "Seat");
        v["send_id"] = json!(send);
        v["receive_id"] = json!(receive);
        v
    };
    register(&mut e, 1, A, 0, "initial", vec![entry(5, 7)]);
    register(&mut e, 1, A, 1, "load", vec![]);
    register(&mut e, 2, B, 0, "initial", vec![entry(15, 17)]);
    register(&mut e, 2, B, 1, "load", vec![]);
    let out = send(&mut e, 1, &format!("9#{A}#5"));
    assert!(texts(&out).contains(&(1, format!("9#{A}#7#{A}"))));
    assert!(texts(&out).contains(&(2, format!("9#{A}#17#{A}"))));
    let out = send(&mut e, 2, &format!("9#{B}#15"));
    assert!(out
        .iter()
        .any(|o| matches!(o, Outbound::Disconnect { peer: 2, .. })));
    assert!(!texts(&out).iter().any(|(_, t)| t.starts_with("9#")));
}

#[test]
fn registry_denies_untrusted_descriptors_and_minigame_semantics() {
    let (dir, _s, mut e) = fixture("Nexus");
    announce(&mut e, 1, A, "World Alpha");
    let mut entry = trusted_entry("generic", "MiniGameTable");
    entry["classification"] = json!("deferred_minigame");
    let trusted = json!({"format_version":1,"instances":[{"instance_id":"world-test","scene":"Nexus","epoch":"test-epoch1","trusted":true,"static_profile_available":true,"static_entries":[entry.clone()],"furniture_entries":[],"ground_sig":[]}]});
    fs::write(
        dir.path().join("instance-interactions.json"),
        serde_json::to_vec(&trusted).unwrap(),
    )
    .unwrap();
    e.tick().unwrap();
    entry["send_id"] = json!(5);
    entry["receive_id"] = json!(5);
    let mut forged = entry.clone();
    forged["class"] = json!("FakeClass");
    let out = register(&mut e, 1, A, 0, "initial", vec![forged]);
    assert!(texts(&out)
        .iter()
        .any(|(_, t)| t.contains("registry_unknown_or_duplicate_key")));
    register(&mut e, 1, A, 0, "initial", vec![entry]);
    register(&mut e, 1, A, 1, "load", vec![]);
    assert!(e.receive(1, &app(&format!("94#{A}#5#True"))).is_err());
}

#[test]
fn cross_instance_mailbox_delivers_invite_and_private_chat_with_live_authority() {
    let (dir, s, mut left) = fixture("Nexus");
    s.connection()
        .unwrap()
        .execute(
            "UPDATE allocations SET instance_id='world-other'WHERE guid=?",
            [B],
        )
        .unwrap();
    let mut right = Engine::new(
        Config {
            instance_id: "world-other".into(),
            space_id: "Nexus".into(),
            max_peers: 32,
        },
        s.clone(),
    )
    .unwrap();
    let status = dir.path().join("instances/world-other");
    fs::create_dir_all(&status).unwrap();
    fs::write(status.join("instance-status.json"),serde_json::to_vec(&json!({"format_version":1,"instance_id":"world-other","psidglobal":"Nexus","owner":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","listening":true,"listener_bound":true,"heartbeat":NOW})).unwrap()).unwrap();
    announce(&mut left, 1, A, "World Alpha");
    announce(&mut right, 2, B, "World Beta");
    left.set_listening(true).unwrap();
    right.set_listening(true).unwrap();
    send(&mut left, 1, "19#World Alpha#World Beta#6#1");
    let out = right.tick().unwrap();
    assert!(texts(&out)
        .iter()
        .any(|(p, t)| *p == 2 && t.starts_with("19#World Alpha#1#6##")));
    send(&mut left, 1, "19#World Alpha#World Beta#0#1");
    right.tick().unwrap();
    send(&mut right, 2, &format!("26#{B}#World Alpha#0#1"));
    left.tick().unwrap();
    let out = send(
        &mut left,
        1,
        &format!("13#{A}#World Beta#1#Across worlds#1"),
    );
    assert_eq!(
        texts(&out),
        vec![(1, format!("13#{A}#World Beta#1#Across worlds#1"))]
    );
    let out = right.tick().unwrap();
    assert!(texts(&out).contains(&(2, format!("13#{A}#World Alpha#1#Across worlds#1"))));
}

#[test]
fn explicit_revocation_and_ban_disconnect_bound_idle_peers() {
    let (_dir, s, mut e) = fixture("Nexus");
    two(&mut e);
    s.connection().unwrap().execute("INSERT INTO moderation_revoked_sessions VALUES(?,'world-test-account-a','test-ban',?,'test')",rusqlite::params![A,NOW as i64]).unwrap();
    s.connection()
        .unwrap()
        .execute(
            "INSERT INTO moderation_accounts(ps4_id,ban_enabled)VALUES('world-test-account-b',1)",
            [],
        )
        .unwrap();
    let out = e.tick().unwrap();
    assert_eq!(
        out.iter()
            .filter(|o| matches!(o, Outbound::Disconnect { .. }))
            .count(),
        2
    );
    assert_eq!(e.peer_count(), 0);
}

#[test]
fn owner_can_rebind_saved_furniture_epoch_but_visitors_reload() {
    let (dir, s, mut e) = fixture("Home");
    two(&mut e);
    s.connection().unwrap().execute("INSERT INTO housing_spaces VALUES('world-test','Home','Home','world-test-account-a',?)",[NOW]).unwrap();
    let furniture = |class: &str| json!({"kind":"generic","anchor":"","class":class,"item_id":"tableasset","path":[0],"slot":0,"ground_index":0,"classification":"ordinary","extension_arity":0,"send_id":5,"receive_id":5});
    let trust = |epoch: &str, class: &str| json!({"format_version":1,"instances":[{"instance_id":"world-test","scene":"Home","epoch":epoch,"trusted":true,"static_profile_available":true,"static_entries":[],"furniture_entries":[furniture(class)],"ground_sig":[]}]});
    let path = dir.path().join("instance-interactions.json");
    fs::write(
        &path,
        serde_json::to_vec(&trust("epoch1", "OldSwitch")).unwrap(),
    )
    .unwrap();
    e.tick().unwrap();
    for (id, guid) in [(1, A), (2, B)] {
        register(&mut e, id, guid, 0, "initial", vec![]);
        register(&mut e, id, guid, 1, "load", vec![furniture("OldSwitch")]);
    }
    fs::write(
        &path,
        serde_json::to_vec(&trust("epoch2", "NewSwitch")).unwrap(),
    )
    .unwrap();
    let out = e.tick().unwrap();
    assert!(!out
        .iter()
        .any(|o| matches!(o, Outbound::Disconnect { peer: 1, .. })));
    assert!(out
        .iter()
        .any(|o| matches!(o, Outbound::Disconnect { peer: 2, .. })));
    e.disconnect(2).unwrap();
    let out = register(&mut e, 1, A, 2, "save", vec![furniture("NewSwitch")]);
    assert!(texts(&out).contains(&(1, format!("97#{A}#2#1#accepted"))));
    let out = send(&mut e, 1, &format!("94#{A}#5#True"));
    assert_eq!(texts(&out), vec![(1, format!("94#{A}#5#True"))]);
}

#[test]
fn semantic_profile_requires_trusted_mapping_before_any_numeric_world_fallback() {
    let (_dir, mut s, _unused) = fixture("Nexus");
    s.readiness_profile = Some("nonmini-semantic-v1".into());
    let mut e = Engine::new(
        Config {
            instance_id: "world-test".into(),
            space_id: "Nexus".into(),
            max_peers: 32,
        },
        s,
    )
    .unwrap();
    two(&mut e);
    assert!(send(&mut e, 1, &format!("8#{A}#5")).is_empty());
    assert!(send(&mut e, 1, &format!("94#{A}#0#True")).is_empty());
    let out = send(&mut e, 1, &format!("9#{A}#5"));
    assert!(out.iter().any(|o|matches!(o,Outbound::Disconnect{peer:1,reason}if reason=="rejected_semantic_claim_requires_reload")));
    assert!(texts(&out).is_empty());
    assert!(e
        .drain_events()
        .iter()
        .any(|v| v.detail == "registry_not_ready"));
}
