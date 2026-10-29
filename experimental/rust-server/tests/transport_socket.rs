//! Real loopback sockets, ephemeral ports, and synthetic state only.
use nebula_preserved_server::{
    mirror::{self, message_id, Reader, Writer},
    state::State,
    transport, wire,
    world::Config,
};
use std::{fs, io, net::SocketAddr, path::PathBuf, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::watch,
    task::JoinHandle,
    time::timeout,
};

const IO_LIMIT: Duration = Duration::from_secs(5);
const MAX_FRAME: usize = 65_536;
const INSTANCE: &str = "socket-test";

struct Server {
    root: PathBuf,
    address: SocketAddr,
    shutdown: watch::Sender<bool>,
    task: Option<JoinHandle<anyhow::Result<()>>>,
}
impl Server {
    async fn start(max_peers: usize) -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("build-temp/transport-tests")
            .join(uuid::Uuid::new_v4().simple().to_string());
        let protocol = root.join("protocol");
        fs::create_dir_all(&protocol).unwrap();
        let mut state = State::open(&root.join("state"), &protocol).unwrap();
        state.fixed_time = Some(1000.0);
        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let address = listener.local_addr().unwrap();
        let (shutdown, receiver) = watch::channel(false);
        let config = Config {
            instance_id: INSTANCE.into(),
            space_id: "Nexus".into(),
            max_peers,
        };
        let task = tokio::spawn(transport::serve(listener, state, config, receiver));
        Self {
            root,
            address,
            shutdown,
            task: Some(task),
        }
    }
    async fn connect(&self) -> TcpStream {
        timeout(IO_LIMIT, TcpStream::connect(self.address))
            .await
            .unwrap()
            .unwrap()
    }
    async fn stop(&mut self) {
        self.shutdown.send(true).unwrap();
        timeout(IO_LIMIT, self.task.take().unwrap())
            .await
            .expect("listener shutdown timed out")
            .expect("listener task panicked")
            .expect("listener failed");
    }
    fn snapshot(&self, name: &str) -> serde_json::Value {
        let path = self.root.join("state/instances").join(INSTANCE).join(name);
        serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.shutdown.send(true);
    }
}

fn empty_message(name: &str) -> Vec<u8> {
    message_id(name).to_le_bytes().to_vec()
}
fn ping(value: f64) -> Vec<u8> {
    let mut writer = Writer::new();
    writer.write_u16(message_id("Mirror.NetworkPingMessage"));
    writer.write_f64(value);
    writer.into_inner()
}
fn frame(messages: &[Vec<u8>]) -> Vec<u8> {
    mirror::telepathy_frame(&mirror::encode_batch(12.5, messages), MAX_FRAME).unwrap()
}
async fn receive_message(stream: &mut TcpStream) -> io::Result<Vec<u8>> {
    timeout(IO_LIMIT, async {
        let mut header = [0; 4];
        stream.read_exact(&mut header).await?;
        let size = mirror::telepathy_payload_length(header, MAX_FRAME)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e.message))?;
        let mut body = vec![0; size];
        stream.read_exact(&mut body).await?;
        let (timestamp, reader) = mirror::decode_batch(&body)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e.message))?;
        if !timestamp.is_finite() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid batch timestamp",
            ));
        }
        Ok(reader.remaining_slice().to_vec())
    })
    .await
    .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "response frame timed out"))?
}
async fn check_pong(stream: &mut TcpStream, value: f64) {
    stream.write_all(&frame(&[ping(value)])).await.unwrap();
    let message = receive_message(stream).await.unwrap();
    let mut reader = Reader::new(&message);
    assert_eq!(
        reader.read_u16().unwrap(),
        message_id("Mirror.NetworkPongMessage")
    );
    assert_eq!(reader.read_f64().unwrap().to_bits(), value.to_bits());
    assert_eq!(reader.read_f64().unwrap(), 1000.0);
    reader.finish().unwrap();
}
async fn closed(stream: &mut TcpStream) {
    closed_as(stream, "socket").await;
}
async fn closed_as(stream: &mut TcpStream, case: &str) {
    let result = timeout(IO_LIMIT, stream.read(&mut [0; 1]))
        .await
        .unwrap_or_else(|_| panic!("{case}: server did not close socket"));
    match result {
        Ok(0) => {}
        Err(error)
            if matches!(
                error.kind(),
                io::ErrorKind::ConnectionReset
                    | io::ErrorKind::ConnectionAborted
                    | io::ErrorKind::BrokenPipe
                    | io::ErrorKind::UnexpectedEof
            ) => {}
        other => panic!("{case}: expected closed socket, got {other:?}"),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fragmented_frame_and_concatenated_messages_emit_exact_spawn_sequence() {
    let mut server = Server::start(2).await;
    let mut client = server.connect().await;
    let request = frame(&[
        empty_message("Mirror.ReadyMessage"),
        empty_message("Mirror.AddPlayerMessage"),
        ping(2.25),
    ]);
    // Separate writes split both the four-byte Telepathy header and Mirror body.
    for chunk in request[..4].chunks(1).chain(request[4..].chunks(3)) {
        client.write_all(chunk).await.unwrap();
        tokio::task::yield_now().await;
    }
    assert_eq!(
        receive_message(&mut client).await.unwrap(),
        empty_message("Mirror.ObjectSpawnStartedMessage")
    );
    let spawn = receive_message(&mut client).await.unwrap();
    let mut reader = Reader::new(&spawn);
    assert_eq!(
        reader.read_u16().unwrap(),
        message_id("Mirror.SpawnMessage")
    );
    assert_eq!(reader.read_u32().unwrap(), 1);
    assert!(reader.read_bool().unwrap());
    assert!(reader.read_bool().unwrap());
    assert_eq!(reader.read_u64().unwrap(), 0);
    assert_eq!(
        reader.read_guid().unwrap(),
        [
            0x73, 0x18, 0x04, 0x86, 0x99, 0xb0, 0xe4, 0xed, 0x68, 0x7c, 0x67, 0x60, 0x6e, 0x37,
            0x96, 0x83
        ]
    );
    assert_eq!(reader.read_vector3().unwrap(), [0.0; 3]);
    assert_eq!(reader.read_quaternion().unwrap(), [0.0, 0.0, 0.0, 1.0]);
    assert_eq!(reader.read_vector3().unwrap(), [1.0; 3]);
    let initial = reader.read_bytes_and_size().unwrap().unwrap();
    reader.finish().unwrap();
    // NebulaSpawnState.Initial: component 0 / 28 bytes, component 1 / 4 bytes.
    assert_eq!(
        initial,
        hex::decode(concat!(
            "001c000000",
            "000000000000000000000000",
            "0000000000000000000000000000803f",
            "010400000000000000"
        ))
        .unwrap()
    );
    assert_eq!(
        receive_message(&mut client).await.unwrap(),
        empty_message("Mirror.ObjectSpawnFinishedMessage")
    );
    let application = receive_message(&mut client).await.unwrap();
    let mut reader = Reader::new(&application);
    assert_eq!(reader.read_u16().unwrap(), message_id("NebulaMessage"));
    assert_eq!(
        wire::decrypt(&reader.read_string().unwrap().unwrap()).unwrap(),
        "0"
    );
    reader.finish().unwrap();
    let pong = receive_message(&mut client).await.unwrap();
    let mut reader = Reader::new(&pong);
    assert_eq!(
        reader.read_u16().unwrap(),
        message_id("Mirror.NetworkPongMessage")
    );
    assert_eq!(reader.read_f64().unwrap(), 2.25);
    assert_eq!(reader.read_f64().unwrap(), 1000.0);
    reader.finish().unwrap();
    // A second Telepathy frame remains readable after the fragmented first one.
    check_pong(&mut client, 3.5).await;
    server.stop().await;
    closed(&mut client).await;
    assert_eq!(
        server.snapshot("instance-avatar-state.json")["listening"],
        false
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn malformed_headers_and_batches_close_only_the_offending_socket() {
    let mut server = Server::start(4).await;
    let mut healthy = server.connect().await;
    check_pong(&mut healthy, 1.0).await;
    let mut truncated_ping = Writer::new();
    truncated_ping.write_u16(message_id("Mirror.NetworkPingMessage"));
    truncated_ping.write_u8(1);
    let mut invalid_utf8 = Writer::new();
    invalid_utf8.write_u16(message_id("NebulaMessage"));
    invalid_utf8.write_bytes(&[3, 0, 255, 255]);
    let invalid = [
        ("zero Telepathy length", vec![0, 0, 0, 0]),
        ("negative Telepathy length", vec![255, 255, 255, 255]),
        (
            "oversized Telepathy length",
            (65_537i32).to_be_bytes().to_vec(),
        ),
        (
            "truncated batch timestamp",
            mirror::telepathy_frame(&[0; 7], MAX_FRAME).unwrap(),
        ),
        ("unsupported message ID", frame(&[vec![255, 255]])),
        ("truncated ping", frame(&[truncated_ping.into_inner()])),
        ("invalid UTF-8 string", frame(&[invalid_utf8.into_inner()])),
        (
            "257 messages in one batch",
            frame(&vec![empty_message("Mirror.ReadyMessage"); 257]),
        ),
    ];
    for (index, (case, bytes)) in invalid.iter().enumerate() {
        let mut malicious = server.connect().await;
        malicious.write_all(bytes).await.unwrap();
        closed_as(&mut malicious, case).await;
        check_pong(&mut healthy, index as f64 + 10.0).await;
    }
    // This message has valid framing. The application rejects AddPlayer before
    // Ready while retaining the connection, so a following Ping still succeeds.
    let mut invalid_state = server.connect().await;
    invalid_state
        .write_all(&frame(&[empty_message("Mirror.AddPlayerMessage")]))
        .await
        .unwrap();
    check_pong(&mut invalid_state, 77.5).await;
    let mut truncated_body = server.connect().await;
    truncated_body
        .write_all(&[0, 0, 0, 32, 1, 2])
        .await
        .unwrap();
    truncated_body.shutdown().await.unwrap();
    closed(&mut truncated_body).await;
    check_pong(&mut healthy, 99.0).await;
    server.stop().await;
    closed(&mut healthy).await;
    closed(&mut invalid_state).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn connection_cap_rejects_excess_and_releases_a_closed_peer_slot() {
    let mut server = Server::start(1).await;
    let mut first = server.connect().await;
    check_pong(&mut first, 1.0).await;
    let mut excess = server.connect().await;
    closed(&mut excess).await;
    check_pong(&mut first, 2.0).await;
    first.shutdown().await.unwrap();
    drop(first);
    let mut replacement = timeout(IO_LIMIT, async {
        loop {
            let mut candidate = server.connect().await;
            if candidate.write_all(&frame(&[ping(3.0)])).await.is_ok() {
                if let Ok(response) = receive_message(&mut candidate).await {
                    let mut reader = Reader::new(&response);
                    assert_eq!(
                        reader.read_u16().unwrap(),
                        message_id("Mirror.NetworkPongMessage")
                    );
                    assert_eq!(reader.read_f64().unwrap(), 3.0);
                    assert_eq!(reader.read_f64().unwrap(), 1000.0);
                    reader.finish().unwrap();
                    break candidate;
                }
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("closed peer's capacity permit was not released");
    check_pong(&mut replacement, 4.0).await;
    server.stop().await;
    closed(&mut replacement).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shutdown_cancels_partial_header_and_body_reads_and_publishes_offline() {
    let mut server = Server::start(2).await;
    let mut header = server.connect().await;
    check_pong(&mut header, 1.0).await;
    let mut body = server.connect().await;
    check_pong(&mut body, 2.0).await;
    header.write_all(&[0]).await.unwrap();
    body.write_all(&[0, 0, 0, 32, 1, 2, 3]).await.unwrap();
    server.stop().await;
    closed(&mut header).await;
    closed(&mut body).await;
    assert_eq!(
        server.snapshot("instance-avatar-state.json")["listening"],
        false
    );
    assert_eq!(
        server.snapshot("instance-presence.json")["players"],
        serde_json::json!([])
    );
    assert!(
        TcpStream::connect(server.address).await.is_err(),
        "listener retained the bound port after shutdown"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn a_nonreading_ping_flood_does_not_starve_another_peer_or_shutdown() {
    let mut server = Server::start(2).await;
    let mut healthy = server.connect().await;
    check_pong(&mut healthy, 1.0).await;
    let mut flood = server.connect().await;
    let batch = frame(&vec![ping(7.0); 256]);
    let stream = batch.repeat(128);
    // Whether the OS send buffer fills or the bounded queue disconnects this
    // peer depends on scheduling. Responsiveness and shutdown are deterministic.
    let (write_result, ()) = tokio::join!(
        timeout(IO_LIMIT, flood.write_all(&stream)),
        check_pong(&mut healthy, 8.0)
    );
    if let Ok(Err(error)) = write_result {
        assert!(matches!(
            error.kind(),
            io::ErrorKind::ConnectionReset
                | io::ErrorKind::ConnectionAborted
                | io::ErrorKind::BrokenPipe
                | io::ErrorKind::NotConnected
        ));
    }
    server.stop().await;
    closed(&mut healthy).await;
}
