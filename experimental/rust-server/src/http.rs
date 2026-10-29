use crate::{dispatch, state::State, wire};
use axum::{
    extract::{RawQuery, State as AxumState},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Response},
    Router,
};
use std::{
    net::SocketAddr,
    sync::Arc,
    time::{Duration, Instant},
};
#[derive(Clone)]
pub struct HttpState {
    pub state: State,
    pub public_access: bool,
    pub permits: Arc<tokio::sync::Semaphore>,
    pub pending: Arc<tokio::sync::Semaphore>,
    pub waiters: Arc<tokio::sync::Semaphore>,
}
impl HttpState {
    pub fn new(state: State, public_access: bool) -> Self {
        Self {
            state,
            public_access,
            permits: Arc::new(tokio::sync::Semaphore::new(16)),
            pending: Arc::new(tokio::sync::Semaphore::new(128)),
            waiters: Arc::new(tokio::sync::Semaphore::new(64)),
        }
    }
}
fn text(status: u16, body: String) -> Response {
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
        [
            ("content-type", "text/plain; charset=utf-8"),
            ("cache-control", "no-store"),
        ],
        body,
    )
        .into_response()
}
async fn handle(
    AxumState(app): AxumState<HttpState>,
    method: Method,
    uri: axum::http::Uri,
    RawQuery(query): RawQuery,
    headers: HeaderMap,
) -> Response {
    let route = uri.path().trim_start_matches('/').to_owned();
    if route == "preservation/health" {
        return axum::Json(serde_json::json!({"service":"nebula-preservation-rust-experimental","reconstructed_http_handlers":dispatch::routes(),"game_ready":false,"networking_parity":"unproven","public_access":app.public_access})).into_response();
    }
    let _pending = match app.pending.clone().try_acquire_owned() {
        Ok(p) => p,
        Err(_) => return text(503, "Server busy".into()),
    };
    let query = match query {
        Some(q) if q.len() <= 2 * 1024 * 1024 => q,
        _ => return text(400, "Expected encrypted GET request".into()),
    };
    let fields: Vec<(String, String)> = match serde_urlencoded::from_str(&query) {
        Ok(f) => f,
        Err(_) => return text(400, "Expected encrypted GET request".into()),
    };
    let data = fields.iter().find(|(key, _)| key == "data").map(|(_, v)| v);
    if method != Method::GET || data.is_none() {
        return text(400, "Expected encrypted GET request".into());
    }
    let plaintext = match wire::decrypt(data.unwrap()) {
        Ok(p) => p,
        Err(_) => return text(400, "Invalid encrypted request".into()),
    };
    let authorization = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .map(str::to_owned);
    let state = app.state.clone();
    let actor = if app.public_access {
        let permit = app
            .permits
            .clone()
            .acquire_owned()
            .await
            .expect("owned semaphore remains open");
        match tokio::task::spawn_blocking(move || {
            let _permit = permit;
            crate::access::authenticate(&state, authorization.as_deref())
        })
        .await
        {
            Ok(Ok(a)) => Some(a),
            _ => return text(403, wire::encrypt("ERROR").unwrap_or_default()),
        }
    } else {
        None
    };
    let start = Instant::now();
    let mut waiting = None;
    let result = loop {
        let permit = app
            .permits
            .clone()
            .acquire_owned()
            .await
            .expect("owned semaphore remains open");
        let (state, route, plaintext, actor) = (
            app.state.clone(),
            route.clone(),
            plaintext.clone(),
            actor.clone(),
        );
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            dispatch::dispatch(&state, &route, &plaintext, actor.as_deref())
        })
        .await;
        match result {
            Ok(Err(e))
                if e.status == 503
                    && e.message == "Housing save is waiting for its original counterpart"
                    && start.elapsed() < Duration::from_secs(31) =>
            {
                if waiting.is_none() {
                    match app.waiters.clone().try_acquire_owned() {
                        Ok(p) => waiting = Some(p),
                        Err(_) => break Err(e),
                    }
                }
                tokio::time::sleep(Duration::from_millis(50)).await
            }
            Ok(r) => break r,
            Err(_) => break Err(crate::error::Error::new(500, "Request worker failed")),
        }
    };
    let (status, reply) = match result {
        Ok(p) => (200, p),
        Err(e) => (e.status, "ERROR".into()),
    };
    match wire::encrypt(&reply) {
        Ok(body) => text(status, body),
        Err(_) => text(500, "Response encryption failed".into()),
    }
}
pub async fn serve(
    listener: tokio::net::TcpListener,
    state: State,
    public_access: bool,
) -> anyhow::Result<()> {
    let address: SocketAddr = listener.local_addr()?;
    if !address.ip().is_loopback() && !public_access {
        anyhow::bail!("Non-loopback HTTP requires --public-access and a TLS reverse proxy");
    }
    let app = Router::new()
        .fallback(handle)
        .with_state(HttpState::new(state, public_access));
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    Ok(())
}

async fn shutdown_signal() {
    #[cfg(unix)]
    {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut terminate) => {
                tokio::select! {_=tokio::signal::ctrl_c()=>{},_=terminate.recv()=>{}}
            }
            Err(_) => {
                let _ = tokio::signal::ctrl_c().await;
            }
        }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    async fn call(app: HttpState, fields: Vec<String>) -> Response {
        let p = format!("{}#StandaloneWindows", fields.join("#"));
        let q = serde_urlencoded::to_string([("data", wire::encrypt(&p).unwrap())]).unwrap();
        handle(
            AxumState(app),
            Method::GET,
            "/HousingSavePresetServletParts".parse().unwrap(),
            RawQuery(Some(q)),
            HeaderMap::new(),
        )
        .await
    }
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn pending_housing_saturation_preserves_capacity_for_counterpart() {
        let dir = tempfile::tempdir().unwrap();
        let protocol = std::env::var_os("NEBULA_REFERENCE_PROTOCOL_DIR")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| {
                std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../protocol")
            });
        let state = State::open(dir.path(), &protocol).unwrap();
        let fixture = serde_json::from_str(include_str!(
            "../tests/fixtures/configured-mutations-v1.json"
        ))
        .unwrap();
        crate::fixture::apply(&state, &fixture).unwrap();
        state
            .connection()
            .unwrap()
            .execute("DELETE FROM housing_save_stages", [])
            .unwrap();
        let parts: serde_json::Value =
            serde_json::from_str(include_str!("../tests/fixtures/housing-parts.json")).unwrap();
        let guid = parts["owner_guid"].as_str().unwrap();
        let app = HttpState::new(state.clone(), false);
        let mut jobs = tokio::task::JoinSet::new();
        for _ in 0..70 {
            jobs.spawn(call(
                app.clone(),
                vec![
                    guid.into(),
                    "fixture-parity-a".into(),
                    parts["parts"][1].as_str().unwrap().into(),
                    "1".into(),
                ],
            ));
        }
        tokio::time::timeout(Duration::from_secs(5), async {
            while app.waiters.available_permits() != 0 {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("First halves did not reach bounded waiting state");
        let complete = tokio::time::timeout(
            Duration::from_secs(3),
            call(
                app.clone(),
                vec![
                    guid.into(),
                    "fixture-parity-a".into(),
                    parts["parts"][0].as_str().unwrap().into(),
                    "0".into(),
                ],
            ),
        )
        .await
        .expect("Counterpart starved behind pending saves");
        assert_eq!(complete.status(), StatusCode::OK);
        let mut succeeded = 0;
        let mut busy = 0;
        tokio::time::timeout(Duration::from_secs(3), async {
            while let Some(response) = jobs.join_next().await {
                match response.unwrap().status() {
                    StatusCode::OK => succeeded += 1,
                    StatusCode::SERVICE_UNAVAILABLE => busy += 1,
                    status => panic!("Unexpected housing status {status}"),
                }
            }
        })
        .await
        .unwrap();
        assert!(succeeded >= 64);
        assert_eq!(succeeded + busy, 70);
        let count: i64 = state
            .connection()
            .unwrap()
            .query_row("SELECT count(*) FROM housing_save_receipts", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(count, 1);
    }
}
