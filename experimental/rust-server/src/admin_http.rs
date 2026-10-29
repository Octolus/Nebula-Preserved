//! Optional authenticated operator API, on a separate loopback listener.
use crate::{admin, state::State};
use axum::{
    extract::{Request, State as AxumState},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    Router,
};
use std::{collections::HashMap, sync::Arc};
#[derive(Clone)]
struct App {
    state: State,
    work: Arc<tokio::sync::Semaphore>,
    pending: Arc<tokio::sync::Semaphore>,
}
fn response(value: admin::AdminResponse) -> Response {
    (
        StatusCode::from_u16(value.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
        [
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        axum::Json(value.body),
    )
        .into_response()
}
async fn handle(AxumState(app): AxumState<App>, request: Request) -> Response {
    let _pending = match app.pending.clone().try_acquire_owned() {
        Ok(p) => p,
        Err(_) => {
            return response(admin::AdminResponse {
                status: 503,
                body: serde_json::json!({"error":{"code":"temporarily_unavailable","message":"Server busy"}}),
            })
        }
    };
    let method = request.method().to_string();
    let path = request
        .uri()
        .path()
        .strip_prefix("/management/v1/")
        .unwrap_or("__not_found");
    let mut tail = percent_encoding::percent_decode_str(path)
        .decode_utf8_lossy()
        .to_string();
    if let Some(query) = request.uri().query() {
        tail.push('?');
        tail.push_str(query);
    }
    let mut headers = HashMap::<String, String>::new();
    for (k, v) in request.headers() {
        headers
            .entry(k.to_string())
            .or_insert_with(|| v.to_str().unwrap_or("").to_owned());
    }
    let raw = match axum::body::to_bytes(request.into_body(), 16 * 1024).await {
        Ok(b) => b.to_vec(),
        Err(_) => vec![b' '; 16 * 1024 + 1],
    };
    let permit = app
        .work
        .clone()
        .acquire_owned()
        .await
        .expect("Owned semaphore remains open");
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        admin::handle_raw(&app.state, &method, &tail, &headers, &raw)
    })
    .await
    {
        Ok(value) => response(value),
        Err(_) => response(admin::AdminResponse {
            status: 500,
            body: serde_json::json!({"error":{"code":"internal_error","message":"Request worker failed"}}),
        }),
    }
}
pub async fn serve(
    listener: tokio::net::TcpListener,
    state: State,
    mut shutdown: tokio::sync::watch::Receiver<bool>,
) -> anyhow::Result<()> {
    if !listener.local_addr()?.ip().is_loopback() {
        anyhow::bail!("The experimental admin API requires a loopback listener");
    }
    let app = Router::new().fallback(handle).with_state(App {
        state,
        work: Arc::new(tokio::sync::Semaphore::new(16)),
        pending: Arc::new(tokio::sync::Semaphore::new(128)),
    });
    axum::serve(listener, app)
        .with_graceful_shutdown(async move {
            if !*shutdown.borrow() {
                let _ = shutdown.changed().await;
            }
        })
        .await?;
    Ok(())
}
