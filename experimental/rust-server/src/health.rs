//! Service liveness only; never claims native-client or historical parity.
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
    time::{timeout, Duration},
};
pub async fn check(address: std::net::SocketAddr) -> anyhow::Result<()> {
    if !address.ip().is_loopback() {
        anyhow::bail!("Health checks require a loopback endpoint");
    }
    timeout(Duration::from_secs(2),async{
        let mut socket=TcpStream::connect(address).await?;
        socket.write_all(b"GET /preservation/health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n").await?;
        let mut bytes=Vec::new();socket.take(64*1024).read_to_end(&mut bytes).await?;
        let response=String::from_utf8(bytes)?;let(header,body)=response.split_once("\r\n\r\n").ok_or_else(||anyhow::anyhow!("Invalid health response"))?;
        if header.split_whitespace().nth(1)!=Some("200"){anyhow::bail!("HTTP listener is unhealthy");}
        let value:serde_json::Value=serde_json::from_str(body)?;
        if value["service"]!="nebula-preservation-rust-experimental"{anyhow::bail!("Health endpoint belongs to another service");}
        Ok::<_,anyhow::Error>(())
    }).await??;
    Ok(())
}
