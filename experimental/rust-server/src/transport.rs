//! Bounded Telepathy adapter. A cancelled partial read always closes its socket.
use crate::{
    error::{Error, Result},
    mirror::{self, message_id},
    state::State,
    world::{Config, Engine, Outbound},
};
use std::{
    collections::HashMap,
    io::Write,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{mpsc, watch, Semaphore},
};
const MAX_FRAME: usize = 65536;
const MAX_MESSAGES: usize = 256;
const QUEUE: usize = 64;
pub fn split_batch(bytes: &[u8]) -> Result<Vec<Vec<u8>>> {
    let (_, mut reader) = mirror::decode_batch(bytes)?;
    let mut result = Vec::new();
    while reader.remaining() > 0 {
        if result.len() >= MAX_MESSAGES {
            return Err(Error::bad("Too many messages in one batch"));
        }
        let start = reader.position();
        let id = reader.read_u16()?;
        if id == message_id("Mirror.ReadyMessage") || id == message_id("Mirror.AddPlayerMessage") {
        } else if id == message_id("Mirror.NetworkPingMessage") {
            reader.read_f64()?;
        } else if id == message_id("Mirror.CommandMessage") {
            reader.read_u32()?;
            reader.read_u8()?;
            reader.read_i32()?;
            reader.read_bytes_and_size()?;
        } else if id == message_id("NebulaMessage") {
            reader.read_string()?;
        } else {
            return Err(Error::bad("Unsupported inbound Mirror message"));
        }
        result.push(bytes[start..reader.position()].to_vec());
    }
    Ok(result)
}
enum Event {
    Connect {
        peer: u64,
        queue: mpsc::Sender<Vec<u8>>,
        cancel: watch::Sender<bool>,
    },
    Packet {
        peer: u64,
        bytes: Vec<u8>,
    },
    Disconnected(u64),
    Tick,
    Stop,
}
struct Peer {
    queue: mpsc::Sender<Vec<u8>>,
    cancel: watch::Sender<bool>,
}
fn deliver(engine: &mut Engine, peers: &mut HashMap<u64, Peer>, actions: Vec<Outbound>) {
    let mut disconnect = Vec::new();
    for action in actions {
        match action {
            Outbound::Send { peer, message, .. } => {
                if let Some(p) = peers.get(&peer) {
                    if p.queue.try_send(message).is_err() {
                        disconnect.push(peer);
                    }
                }
            }
            Outbound::Disconnect { peer, .. } => disconnect.push(peer),
        }
    }
    disconnect.sort_unstable();
    disconnect.dedup();
    for peer in disconnect {
        if let Some(p) = peers.remove(&peer) {
            let _ = p.cancel.send(true);
            if let Ok(actions) = engine.disconnect(peer) {
                deliver(engine, peers, actions);
            }
        }
    }
}
async fn socket(
    peer: u64,
    stream: TcpStream,
    events: mpsc::Sender<Event>,
    _permit: tokio::sync::OwnedSemaphorePermit,
) {
    let _ = stream.set_nodelay(true);
    let (mut read, mut write) = stream.into_split();
    let (queue, mut messages) = mpsc::channel::<Vec<u8>>(QUEUE);
    let (cancel, mut closed) = watch::channel(false);
    if events
        .send(Event::Connect {
            peer,
            queue,
            cancel: cancel.clone(),
        })
        .await
        .is_err()
    {
        return;
    }
    let writer = tokio::spawn(async move {
        while let Some(first) = messages.recv().await {
            let values = vec![first];
            let size = values[0].len() + 8;
            // One frame per first message avoids oversized coalescing; additional
            // queued messages are framed by their next iteration under backpressure.
            if size > MAX_FRAME {
                return;
            }
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64();
            let batch = mirror::encode_batch(now, &values);
            let frame = match mirror::telepathy_frame(&batch, MAX_FRAME) {
                Ok(f) => f,
                Err(_) => return,
            };
            if !matches!(
                tokio::time::timeout(Duration::from_secs(5), write.write_all(&frame)).await,
                Ok(Ok(()))
            ) {
                return;
            }
        }
    });
    let reader = async {
        loop {
            let mut header = [0; 4];
            if !matches!(
                tokio::time::timeout(Duration::from_secs(60), read.read_exact(&mut header)).await,
                Ok(Ok(_))
            ) {
                break;
            }
            let size = match mirror::telepathy_payload_length(header, MAX_FRAME) {
                Ok(s) => s,
                Err(_) => break,
            };
            let mut body = vec![0; size];
            if !matches!(
                tokio::time::timeout(Duration::from_secs(5), read.read_exact(&mut body)).await,
                Ok(Ok(_))
            ) {
                break;
            }
            let messages = match split_batch(&body) {
                Ok(m) => m,
                Err(_) => break,
            };
            for bytes in messages {
                if events.send(Event::Packet { peer, bytes }).await.is_err() {
                    return;
                }
            }
        }
    };
    tokio::select! {_ = reader=>{},_ = closed.changed()=>{},_ = async{while !writer.is_finished(){tokio::time::sleep(Duration::from_millis(20)).await;}}=>{}}
    writer.abort();
    let _ = writer.await;
    drop(read);
    drop(_permit);
    let _ = events.send(Event::Disconnected(peer)).await;
}
pub async fn serve(
    listener: TcpListener,
    state: State,
    config: Config,
    mut shutdown: watch::Receiver<bool>,
) -> anyhow::Result<()> {
    if *shutdown.borrow() {
        return Ok(());
    }
    let address = listener.local_addr()?;
    let directory = state.state_dir.join("instances").join(&config.instance_id);
    std::fs::create_dir_all(&directory)?;
    let lock = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(directory.join("rust-listener.lock"))?;
    fs2::FileExt::try_lock_exclusive(&lock)?;
    let capacity = config.max_peers;
    let status_state = state.clone();
    let mut engine = Engine::new(config, state)?;
    let owner = uuid::Uuid::new_v4().simple().to_string();
    engine.set_listening(true)?;
    let (events, mut receiver) = mpsc::channel::<Event>(capacity.saturating_mul(8).clamp(16, 2048));
    let worker = tokio::task::spawn_blocking(move || {
        let mut peers = HashMap::new();
        let mut last_status = Instant::now() - Duration::from_secs(2);
        let publish = |engine: &Engine, listening: bool| -> Result<()> {
            let mut value = serde_json::json!({"format_version":1,"instance_id":engine.config().instance_id,"psidglobal":engine.config().space_id,"ip":status_state.advertised_ip,"bind":address.ip().to_string(),"port":address.port(),"maxusers":capacity,"players":engine.peer_count(),"listening":listening,"listener_bound":listening,"heartbeat":status_state.now(),"game_ready":false,"protocol_complete":false,"networking_parity":"unproven","readiness_scope":status_state.readiness_profile,"core_test_eligible":engine.scene_inventory_verified()&&status_state.readiness_profile.is_some(),"board_tables":0,"darts_tables":0,"housing_bound":false,"housing_owner":""});
            value["owner"] = serde_json::json!(owner);
            if status_state.managed_instances {
                value["core_test_eligible"] = serde_json::json!(false);
                let fields = crate::registry_snapshot::descriptor_fields(
                    &status_state,
                    &engine.config().instance_id,
                    &engine.config().space_id,
                )?;
                if let Some(fields) = fields.as_object() {
                    for (k, v) in fields {
                        value[k] = v.clone();
                    }
                }
            }
            {
                let db = status_state.connection()?;
                use rusqlite::OptionalExtension;
                if let Some(owner) = db
                    .query_row(
                        "SELECT owner_ps4_id FROM housing_spaces WHERE instance_id=?",
                        [&engine.config().instance_id],
                        |r| r.get::<_, String>(0),
                    )
                    .optional()?
                {
                    value["housing_bound"] = serde_json::json!(true);
                    value["housing_owner"] = serde_json::json!(owner);
                }
            }
            let pending = directory.join("instance-status.json.pending");
            let mut file = std::fs::File::create(&pending)?;
            file.write_all(serde_json::to_string(&value)?.as_bytes())?;
            file.sync_all()?;
            std::fs::rename(pending, directory.join("instance-status.json"))?;
            Ok(())
        };
        let _ = publish(&engine, true);
        while let Some(event) = receiver.blocking_recv() {
            let actions = match event {
                Event::Connect {
                    peer,
                    queue,
                    cancel,
                } => {
                    peers.insert(peer, Peer { queue, cancel });
                    engine.connect(peer)
                }
                // Application validation failures are rejections, as in the
                // original handlers; framing errors close in the socket task.
                Event::Packet { peer, bytes } => engine.receive(peer, &bytes),
                Event::Disconnected(peer) => {
                    peers.remove(&peer);
                    engine.disconnect(peer)
                }
                Event::Tick => engine.tick(),
                Event::Stop => break,
            };
            if let Ok(actions) = actions {
                deliver(&mut engine, &mut peers, actions);
            }
            // Journals are diagnostic, never unbounded retained history.
            let _ = engine.drain_events();
            if last_status.elapsed() >= Duration::from_secs(1) {
                if publish(&engine, true).is_err() {
                    break;
                }
                last_status = Instant::now();
            }
        }
        for (_, peer) in peers {
            let _ = peer.cancel.send(true);
        }
        let _ = engine.set_listening(false);
        let _ = publish(&engine, false);
        drop(lock);
    });
    let permits = Arc::new(Semaphore::new(capacity));
    let mut next = 1u64;
    let mut tasks = tokio::task::JoinSet::new();
    let mut failure = None;
    let mut tick = tokio::time::interval(Duration::from_millis(50));
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            _=shutdown.changed()=>{break;},
            _=tick.tick()=>{if worker.is_finished(){break;}let _=events.try_send(Event::Tick);},
            _=tasks.join_next(),if !tasks.is_empty()=>{},
            connection=listener.accept()=>{match connection{Ok((stream,_))=>{if let Ok(permit)=permits.clone().try_acquire_owned(){let peer=next;let Some(value)=next.checked_add(1)else{failure=Some(anyhow::anyhow!("Peer identifier exhausted"));break;};next=value;tasks.spawn(socket(peer,stream,events.clone(),permit));}},Err(error)=>{failure=Some(error.into());break;}}},
        }
    }
    let _ = events.send(Event::Stop).await;
    worker.await?;
    if tokio::time::timeout(Duration::from_secs(5), async {
        while tasks.join_next().await.is_some() {}
    })
    .await
    .is_err()
    {
        tasks.abort_all();
        while tasks.join_next().await.is_some() {}
    }
    if let Some(error) = failure {
        return Err(error);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mirror::Writer;
    #[test]
    fn concatenated_batches_preserve_message_boundaries() {
        let mut ready = Writer::new();
        ready.write_u16(message_id("Mirror.ReadyMessage"));
        let mut ping = Writer::new();
        ping.write_u16(message_id("Mirror.NetworkPingMessage"));
        ping.write_f64(1.25);
        let messages = vec![ready.into_inner(), ping.into_inner()];
        assert_eq!(
            split_batch(&mirror::encode_batch(2.0, &messages)).unwrap(),
            messages
        );
    }
    #[test]
    fn truncated_unknown_and_too_many_messages_reject() {
        assert!(split_batch(&[0; 7]).is_err());
        let mut unknown = Writer::new();
        unknown.write_u16(65535);
        assert!(split_batch(&mirror::encode_batch(0.0, &[unknown.into_inner()])).is_err());
        let mut ping = Writer::new();
        ping.write_u16(message_id("Mirror.NetworkPingMessage"));
        ping.write_u8(1);
        assert!(split_batch(&mirror::encode_batch(0.0, &[ping.into_inner()])).is_err());
        let id = message_id("Mirror.ReadyMessage").to_le_bytes().to_vec();
        assert!(split_batch(&mirror::encode_batch(0.0, &vec![id; 257])).is_err());
    }
}
