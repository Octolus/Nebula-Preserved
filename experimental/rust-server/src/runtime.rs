//! Demand-driven in-process worlds. Intent, bound sockets and admitted readiness
//! remain separate; a request never marks a world complete by itself.
use crate::{state::State, world::Config};
use std::{collections::HashMap, net::Ipv4Addr, time::Duration};
use tokio::{sync::watch, task::JoinHandle};
struct Running {
    cancel: watch::Sender<bool>,
    task: JoinHandle<anyhow::Result<()>>,
}
pub async fn run(
    state: State,
    bind: Ipv4Addr,
    max_worlds: usize,
    shutdown: watch::Receiver<bool>,
) -> anyhow::Result<()> {
    run_with_ports(state, bind, max_worlds, 0, 0, shutdown).await
}
pub async fn run_with_ports(
    state: State,
    bind: Ipv4Addr,
    max_worlds: usize,
    first: u16,
    last: u16,
    mut shutdown: watch::Receiver<bool>,
) -> anyhow::Result<()> {
    if first > last || (first != 0 && (first < 1024 || last - first >= 32)) {
        anyhow::bail!("Invalid bounded scene port range");
    }
    let mut worlds: HashMap<String, Running> = HashMap::new();
    let mut timer = tokio::time::interval(Duration::from_millis(250));
    timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut pulse = 0u64;
    let mut error = None;
    loop {
        tokio::select! {_=shutdown.changed()=>break,_=timer.tick()=>{}}
        if *shutdown.borrow() {
            break;
        }
        let state_copy = state.clone();
        let publish = pulse % 4 == 0;
        pulse += 1;
        let desired =
            tokio::task::spawn_blocking(move || -> crate::error::Result<serde_json::Value> {
                crate::services::pump(&state_copy)?;
                if state_copy.managed_instances {
                    if publish {
                        crate::registry_snapshot::publish(&state_copy)?;
                    }
                    crate::lifecycle::export_desired(&state_copy)
                } else {
                    Ok(serde_json::json!({"instances":[]}))
                }
            })
            .await;
        let desired = match desired {
            Ok(Ok(d)) => d,
            Ok(Err(e)) => {
                error = Some(anyhow::anyhow!(e));
                break;
            }
            Err(e) => {
                error = Some(e.into());
                break;
            }
        };
        let entries = desired["instances"].as_array().cloned().unwrap_or_default();
        let stop: Vec<_> = worlds
            .iter()
            .filter(|(id, w)| {
                w.task.is_finished()
                    || !entries.iter().any(|v| {
                        v["instance_id"].as_str() == Some(id.as_str())
                            && v["desired_state"] == "running"
                    })
            })
            .map(|(id, _)| id.clone())
            .collect();
        for id in stop {
            if let Some(world) = worlds.remove(&id) {
                let _ = world.cancel.send(true);
                match world.task.await {
                    Ok(Ok(())) => {}
                    Ok(Err(e)) => eprintln!("World stopped after runtime failure: {e}"),
                    Err(e) => eprintln!("World task failed: {e}"),
                }
            }
        }
        for entry in entries {
            let Some(id) = entry["instance_id"].as_str() else {
                continue;
            };
            let Some(space) = entry["psidglobal"].as_str() else {
                continue;
            };
            if entry["desired_state"] != "running"
                || worlds.contains_key(id)
                || worlds.len() >= max_worlds
            {
                continue;
            }
            let mut listener = None;
            for port in first..=last {
                if let Ok(bound) = tokio::net::TcpListener::bind((bind, port)).await {
                    listener = Some(bound);
                    break;
                }
            }
            let Some(listener) = listener else {
                continue;
            };
            let (cancel, receiver) = watch::channel(false);
            let config = Config {
                instance_id: id.into(),
                space_id: space.into(),
                max_peers: 32,
            };
            let task = tokio::spawn(crate::transport::serve(
                listener,
                state.clone(),
                config,
                receiver,
            ));
            worlds.insert(id.into(), Running { cancel, task });
        }
    }
    for world in worlds.values() {
        let _ = world.cancel.send(true);
    }
    for (_, world) in worlds {
        let _ = world.task.await;
    }
    if let Some(error) = error {
        return Err(error);
    }
    Ok(())
}
