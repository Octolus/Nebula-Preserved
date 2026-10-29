use nebula_preserved_server::{admin, admin_http, state::State};
use serde_json::{json, Value};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::watch,
    time::{timeout, Duration},
};
async fn request(address: std::net::SocketAddr, headers: &str, body: &[u8]) -> (u16, Value) {
    let mut socket = TcpStream::connect(address).await.unwrap();
    socket.write_all(format!("POST /management/v1/maintenance HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: {}\r\n{headers}\r\n",body.len()).as_bytes()).await.unwrap();
    socket.write_all(body).await.unwrap();
    let mut raw = Vec::new();
    timeout(Duration::from_secs(3), socket.read_to_end(&mut raw))
        .await
        .unwrap()
        .unwrap();
    let reply = String::from_utf8(raw).unwrap();
    let (h, b) = reply.split_once("\r\n\r\n").unwrap();
    assert!(h.to_ascii_lowercase().contains("cache-control: no-store"));
    assert!(h
        .to_ascii_lowercase()
        .contains("x-content-type-options: nosniff"));
    (
        h.split_whitespace().nth(1).unwrap().parse().unwrap(),
        serde_json::from_str(b).unwrap(),
    )
}
#[tokio::test]
async fn actual_operator_listener_authenticates_before_strict_bounded_body_parse() {
    let temp = tempfile::tempdir().unwrap();
    let state = State::open(temp.path(), temp.path()).unwrap();
    let token = "synthetic-operator-socket-test-token-000000000";
    admin::initialize(
        &state,
        token.as_bytes(),
        &json!([{"id":"owner","role":"owner","enabled":true}]),
    )
    .unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (stop, receiver) = watch::channel(false);
    let task = tokio::spawn(admin_http::serve(listener, state, receiver));
    assert_eq!(
        request(address, "Content-Type: application/json\r\n", b"{")
            .await
            .0,
        401
    );
    let headers=format!("Authorization: Bearer {token}\r\nX-Management-Actor: owner\r\nContent-Type: application/json\r\nIdempotency-Key: socket-test-0001\r\n");
    let (status, value) = request(address, &headers, b"{\"enabled\":true,\"enabled\":false}").await;
    assert_eq!(status, 400);
    assert_eq!(value["error"]["code"], "invalid_request");
    assert_eq!(
        request(address, &headers, &vec![b' '; 16 * 1024 + 1])
            .await
            .0,
        413
    );
    let origin = format!("{headers}Origin: https://example.invalid\r\n");
    assert_eq!(request(address, &origin, b"{").await.0, 403);
    stop.send(true).unwrap();
    timeout(Duration::from_secs(3), task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
}
