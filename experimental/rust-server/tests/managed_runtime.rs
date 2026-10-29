//! Real encrypted HTTP -> durable demand -> actual Telepathy world -> presence.
//! This is a synthetic protocol client, not original-client acceptance.
use nebula_preserved_server::{
    mirror::{self, message_id, Reader, Writer},
    state::State,
    wire,
};
use std::path::PathBuf;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::watch,
    time::{timeout, Duration, Instant},
};

async fn http(address: std::net::SocketAddr, route: &str, fields: &[&str]) -> (u16, String) {
    let plaintext = format!("{}#StandaloneWindows", fields.join("#"));
    let query =
        serde_urlencoded::to_string([("data", wire::encrypt(&plaintext).unwrap())]).unwrap();
    let mut socket = TcpStream::connect(address).await.unwrap();
    socket
        .write_all(
            format!(
                "GET /{route}?{query} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            )
            .as_bytes(),
        )
        .await
        .unwrap();
    let mut raw = Vec::new();
    timeout(Duration::from_secs(5), socket.read_to_end(&mut raw))
        .await
        .unwrap()
        .unwrap();
    let response = String::from_utf8(raw).unwrap();
    let (header, body) = response.split_once("\r\n\r\n").unwrap();
    let status = header.split_whitespace().nth(1).unwrap().parse().unwrap();
    (status, wire::decrypt(body).unwrap())
}
async fn frame(socket: &mut TcpStream, messages: &[Vec<u8>]) {
    let payload = mirror::encode_batch(1.0, messages);
    socket
        .write_all(&mirror::telepathy_frame(&payload, 65536).unwrap())
        .await
        .unwrap();
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
async fn receive(socket: &mut TcpStream) -> Vec<u8> {
    let mut header = [0; 4];
    timeout(Duration::from_secs(5), socket.read_exact(&mut header))
        .await
        .unwrap()
        .unwrap();
    let mut body = vec![0; mirror::telepathy_payload_length(header, 65536).unwrap()];
    timeout(Duration::from_secs(5), socket.read_exact(&mut body))
        .await
        .unwrap()
        .unwrap();
    let (_, reader) = mirror::decode_batch(&body).unwrap();
    reader.remaining_slice().to_vec()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn managed_demand_starts_real_world_and_shutdown_preserves_account() {
    let temp = tempfile::tempdir().unwrap();
    let protocol = std::env::var_os("NEBULA_REFERENCE_PROTOCOL_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../protocol"));
    let mut state = State::open(temp.path(), &protocol).unwrap();
    state.managed_instances = true;
    state.readiness_profile = Some("nonmini-semantic-v1".into());
    nebula_preserved_server::lifecycle::initialize(&state).unwrap();
    let (listener, address) = {
        let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let a = l.local_addr().unwrap();
        (l, a)
    };
    let server = tokio::spawn(nebula_preserved_server::http::serve(
        listener,
        state.clone(),
        false,
    ));
    nebula_preserved_server::health::check(address)
        .await
        .unwrap();
    let (cancel, receiver) = watch::channel(false);
    let runtime = tokio::spawn(nebula_preserved_server::runtime::run(
        state.clone(),
        std::net::Ipv4Addr::LOCALHOST,
        2,
        receiver,
    ));
    let id = "runtime-synthetic-a";
    let name = "Runtime Synthetic A";
    let hash = "a".repeat(64);
    assert_eq!(
        http(address, "N2UserExist", &[name, "v72", "false", id, "1"])
            .await
            .0,
        200
    );
    assert_eq!(
        http(address, "ChannelGUIDServlet", &[id, &hash]).await.0,
        200
    );
    let guid = wire::session_guid(id, &hash);
    let (status, load) = http(
        address,
        "N2LoadSpace",
        &[&guid, id, "Login", "false", "", ""],
    )
    .await;
    assert_eq!(status, 200, "{load}");
    let start = Instant::now();
    let allocation = loop {
        let (status, result) = http(address, "N2SpaceLoading", &[&guid, id]).await;
        assert_eq!(status, 200, "{result}");
        let fields = result.split('#').map(str::to_owned).collect::<Vec<_>>();
        if fields.get(1).map(String::as_str) == Some("true") {
            break fields;
        }
        assert!(
            !runtime.is_finished(),
            "Supervisor failed before allocation"
        );
        assert!(
            start.elapsed() < Duration::from_secs(12),
            "Actual bound world never became eligible"
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    };
    assert_eq!(allocation[3], "Nexus");
    let instance = allocation[2].clone();
    let mut socket = TcpStream::connect(format!("{}:{}", allocation[4], allocation[5]))
        .await
        .unwrap();
    frame(
        &mut socket,
        &[
            empty("Mirror.ReadyMessage"),
            empty("Mirror.AddPlayerMessage"),
        ],
    )
    .await;
    let mut net_id = 0;
    for _ in 0..4 {
        let message = receive(&mut socket).await;
        let mut r = Reader::new(&message);
        if r.read_u16().unwrap() == message_id("Mirror.SpawnMessage") {
            net_id = r.read_u32().unwrap();
        }
    }
    assert!(net_id > 0);
    frame(&mut socket, &[app(&format!("1#{net_id}#{guid}#{name}#1"))]).await;
    let drain = tokio::spawn(async move {
        loop {
            let mut h = [0; 4];
            if socket.read_exact(&mut h).await.is_err() {
                break;
            }
            let size = match mirror::telepathy_payload_length(h, 65536) {
                Ok(n) => n,
                Err(_) => break,
            };
            let mut bytes = vec![0; size];
            if socket.read_exact(&mut bytes).await.is_err() {
                break;
            }
        }
    });
    let presence = state
        .state_dir
        .join("instances")
        .join(&instance)
        .join("instance-presence.json");
    let start = Instant::now();
    loop {
        let value = std::fs::read(&presence)
            .ok()
            .and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok());
        if value
            .as_ref()
            .is_some_and(|v| v.to_string().contains(&guid))
        {
            break;
        }
        assert!(
            start.elapsed() < Duration::from_secs(5),
            "Authenticated announced player missing from actual world presence"
        );
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    cancel.send(true).unwrap();
    timeout(Duration::from_secs(5), runtime)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    drain.await.unwrap();
    server.abort();
    let _ = server.await;
    let status: serde_json::Value = serde_json::from_slice(
        &std::fs::read(
            state
                .state_dir
                .join("instances")
                .join(instance)
                .join("instance-status.json"),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(status["listening"], false);
    drop(state);
    let reopened = State::open(temp.path(), &protocol).unwrap();
    let count: i64 = reopened
        .connection()
        .unwrap()
        .query_row("SELECT count(*) FROM profiles WHERE ps4_id=?", [id], |r| {
            r.get(0)
        })
        .unwrap();
    assert_eq!(count, 1);
}
