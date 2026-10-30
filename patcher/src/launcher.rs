//! Release launcher policy; the CLI remains available for developer acceptance.
use anyhow::{ensure, Result};
#[cfg(any(windows, test))]
pub fn origin(input: &str) -> Result<String> {
    let input = input.trim();
    ensure!(
        !input.is_empty(),
        "Enter the server IPv4 address or HTTPS origin"
    );
    let server = if input.contains("://") {
        input.to_owned()
    } else {
        crate::endpoint::ipv4(input)?;
        format!("https://{input}:8444")
    };
    crate::endpoint::validate(&server, "127.0.0.1")?;
    ensure!(
        server.starts_with("https://"),
        "Launcher requires verified HTTPS transport"
    );
    Ok(server)
}
pub fn gui(allow_provisional: bool) -> Result<()> {
    #[cfg(windows)]
    {
        crate::gui::run(allow_provisional)
    }
    #[cfg(not(windows))]
    {
        let _ = allow_provisional;
        anyhow::bail!("The game launcher requires Windows; use --help for command-line tooling")
    }
}
#[cfg(windows)]
pub fn bundle(
    allow_provisional: bool,
) -> Result<(std::path::PathBuf, crate::manifest::Manifest, String)> {
    let pin = option_env!("NEBULA_BUNDLE_SHA256").unwrap_or("").to_owned();
    ensure!(!pin.is_empty(), "This development executable has no reviewed release bundle pin. Build a release with NEBULA_BUNDLE_SHA256 after native acceptance.");
    crate::manifest::sha(&pin)?;
    let exe = std::env::current_exe()?;
    let path = if let Some(embedded) = crate::embedded::bundle(&pin)? {
        embedded
    } else {
        crate::manifest::safe(
            exe.parent()
                .ok_or_else(|| anyhow::anyhow!("Launcher folder unavailable"))?,
            "bundle",
        )?
    };
    let manifest = crate::manifest::load(&path, &pin)?;
    ensure!(
        release_status_allowed(&manifest.status, allow_provisional)
            && crate::manifest::network_only(&manifest)
            && manifest
                .artifacts
                .iter()
                .any(|a| a.path == "NebulaRemoteTransport.exe"),
        "Launcher requires a frozen seven-artifact remote network-only release"
    );
    Ok((path, manifest, pin))
}
/// A certificate-verified, bounded probe of the existing HTTP protocol. This
/// establishes TLS/backend reachability, not account authentication or gameplay.
#[cfg(windows)]
pub fn probe(server: &str) -> Result<()> {
    match crate::remote::trust(server)? {
        crate::remote::Trust::System => preflight(server, None),
        crate::remote::Trust::PinnedCa(ca) => preflight(server, Some(&ca)),
    }
}
/// Check the selected trust policy before writing a new player profile.
/// None means Windows ROOT trust, never acceptance of an invalid certificate.
#[cfg(windows)]
pub fn preflight(server: &str, ca: Option<&[u8]>) -> Result<()> {
    crate::endpoint::validate(server, "127.0.0.1")?;
    ensure!(
        server.starts_with("https://"),
        "TLS requires an HTTPS origin"
    );
    let roots = if let Some(ca) = ca {
        let mut roots = rustls::RootCertStore::empty();
        roots.add(rustls::pki_types::CertificateDer::from(ca.to_vec()))?;
        roots
    } else {
        crate::system_roots::load()?
    };
    probe_with_roots(server, roots)
}
#[cfg(windows)]
fn probe_with_roots(server: &str, roots: rustls::RootCertStore) -> Result<()> {
    use anyhow::Context;
    use std::{
        io::{Read, Write},
        net::{TcpStream, ToSocketAddrs},
        sync::Arc,
        time::{Duration, Instant},
    };
    let url = url::Url::parse(server)?;
    let host = url.host_str().context("Missing server host")?;
    let port = url.port_or_known_default().context("Missing server port")?;
    let config = client_config(roots)?;
    let name = rustls::pki_types::ServerName::try_from(host.to_owned())?;
    let mut connection = rustls::ClientConnection::new(Arc::new(config), name)?;
    let deadline = Instant::now() + Duration::from_secs(12);
    let mut socket = None;
    for address in (host, port).to_socket_addrs()? {
        let remaining = deadline.saturating_duration_since(Instant::now());
        ensure!(!remaining.is_zero(), "Server connection timed out");
        if let Ok(stream) =
            TcpStream::connect_timeout(&address, remaining.min(Duration::from_secs(4)))
        {
            socket = Some(stream);
            break;
        }
    }
    let mut socket = socket.context("Cannot connect to the server; check address and firewall")?;
    socket.set_read_timeout(Some(Duration::from_secs(8)))?;
    socket.set_write_timeout(Some(Duration::from_secs(8)))?;
    let mut tls = rustls::Stream::new(&mut connection, &mut socket);
    // Missing encrypted data is deliberately read-only and elicits the backend's
    // bounded protocol error before account authentication. Never send a token.
    write!(tls, "GET /launcher-probe HTTP/1.1\r\nHost: {host}:{port}\r\nAuthorization: Nebula-Launcher-Probe\r\nConnection: close\r\n\r\n")?;
    tls.flush()?;
    let mut response = Vec::new();
    let mut chunk = [0u8; 1024];
    loop {
        ensure!(
            Instant::now() < deadline,
            "Server probe exceeded its time limit"
        );
        let size = tls.read(&mut chunk)?;
        if size == 0 {
            break;
        }
        ensure!(
            response.len() + size <= 8192,
            "Unexpected oversized server response"
        );
        response.extend_from_slice(&chunk[..size]);
    }
    let text = std::str::from_utf8(&response)?;
    ensure!(
        (text.starts_with("HTTP/1.1 400 ") || text.starts_with("HTTP/1.0 400 "))
            && text.ends_with("Expected encrypted GET request"),
        "Server did not answer with the expected preservation protocol"
    );
    Ok(())
}
#[cfg(windows)]
fn client_config(roots: rustls::RootCertStore) -> Result<rustls::ClientConfig> {
    ensure!(!roots.is_empty(), "No trusted TLS roots available");
    Ok(
        rustls::ClientConfig::builder_with_provider(std::sync::Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_safe_default_protocol_versions()?
        .with_root_certificates(roots)
        .with_no_client_auth(),
    )
}
#[cfg(all(test, windows))]
mod tls_tests {
    use super::*;
    use rustls::{
        client::danger::ServerCertVerifier,
        client::WebPkiServerVerifier,
        pki_types::{CertificateDer, ServerName, UnixTime},
    };
    use std::{sync::Arc, time::Duration};
    const CA: &[u8] = include_bytes!("../tests/fixtures/ca.der");
    const OTHER_CA: &[u8] = include_bytes!("../tests/fixtures/other-ca.der");
    const SERVER: &[u8] = include_bytes!("../tests/fixtures/server.der");
    const DNS_ONLY: &[u8] = include_bytes!("../tests/fixtures/dns-only.der");
    const VALID: u64 = 1_798_761_600;
    fn roots(ca: &[u8]) -> rustls::RootCertStore {
        let mut roots = rustls::RootCertStore::empty();
        roots.add(CertificateDer::from(ca.to_vec())).unwrap();
        roots
    }
    fn verify(ca: &[u8], cert: &[u8], name: &str, seconds: u64) -> Result<()> {
        // The same unmodified webpki verifier selected by with_root_certificates.
        let verifier = WebPkiServerVerifier::builder_with_provider(
            Arc::new(roots(ca)),
            Arc::new(rustls::crypto::ring::default_provider()),
        )
        .build()?;
        verifier.verify_server_cert(
            &CertificateDer::from(cert),
            &[],
            &ServerName::try_from(name.to_owned())?,
            &[],
            UnixTime::since_unix_epoch(Duration::from_secs(seconds)),
        )?;
        Ok(())
    }
    #[test]
    fn trusted_chain_verifies_exact_dns_and_ip_subjects() {
        verify(CA, SERVER, "play.example.org", VALID).unwrap();
        verify(CA, SERVER, "203.0.113.10", VALID).unwrap();
        assert!(verify(CA, SERVER, "other.example.org", VALID).is_err());
        assert!(verify(CA, DNS_ONLY, "203.0.113.10", VALID).is_err());
    }
    #[test]
    fn invalid_chain_dates_and_signatures_never_downgrade_trust() {
        assert!(verify(OTHER_CA, SERVER, "play.example.org", VALID).is_err());
        assert!(verify(CA, SERVER, "play.example.org", 1_577_836_800).is_err());
        assert!(verify(CA, SERVER, "play.example.org", 2_208_988_800).is_err());
        let mut corrupted = SERVER.to_vec();
        *corrupted.last_mut().unwrap() ^= 1;
        assert!(verify(CA, &corrupted, "play.example.org", VALID).is_err());
        assert!(client_config(rustls::RootCertStore::empty()).is_err());
        client_config(roots(CA)).unwrap();
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn provisional_requires_explicit_developer_opt_in() {
        assert!(release_status_allowed("frozen", false));
        assert!(!release_status_allowed("provisional", false));
        assert!(release_status_allowed("provisional", true));
        assert!(!release_status_allowed("unknown", true));
    }
    #[test]
    fn bare_address_uses_public_tls_port() {
        assert_eq!(
            origin(" 203.0.113.10 ").unwrap(),
            "https://203.0.113.10:8444"
        );
        assert_eq!(
            origin("https://play.example.org:8444").unwrap(),
            "https://play.example.org:8444"
        );
    }
    #[test]
    fn launcher_never_downgrades_or_accepts_ambiguous_origins() {
        for input in [
            "",
            "0.0.0.0",
            "https://user@play.example.org",
            "http://127.0.0.1:8080",
            "https://play.example.org/",
            "203.0.113.10:8444",
            "https://play.example.org?x=1",
            "https://PLAY.example.org",
        ] {
            assert!(origin(input).is_err(), "{input}");
        }
    }
}

#[cfg(any(windows, test))]
pub fn release_status_allowed(status: &str, allow_provisional: bool) -> bool {
    status == "frozen" || (allow_provisional && status == "provisional")
}
