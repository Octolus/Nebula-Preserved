//! One verified trust policy shared by API HTTPS and the scene TLS gateway.
use anyhow::{ensure, Result};
use std::{sync::Arc, time::Duration};
use tokio_rustls::{rustls, TlsConnector};

pub enum Trust {
    System,
    PinnedCa(Vec<u8>),
}

fn roots(trust: &Trust) -> Result<rustls::RootCertStore> {
    match trust {
        Trust::PinnedCa(bytes) => {
            let mut roots = rustls::RootCertStore::empty();
            roots.add(rustls::pki_types::CertificateDer::from(bytes.clone()))?;
            Ok(roots)
        }
        Trust::System => {
            #[cfg(windows)]
            {
                crate::system_roots::load()
            }
            #[cfg(not(windows))]
            {
                anyhow::bail!("System certificate mode requires the Windows player client")
            }
        }
    }
}

pub fn clients(trust: &Trust) -> Result<(TlsConnector, reqwest::Client)> {
    clients_with_roots(roots(trust)?)
}

fn clients_with_roots(roots: rustls::RootCertStore) -> Result<(TlsConnector, reqwest::Client)> {
    ensure!(
        !roots.is_empty(),
        "No trusted server certificate authorities available"
    );
    // Both clients use exactly the same verifier and roots. No trust mode adds a
    // fallback CA, disables hostname verification, or accepts an invalid chain.
    let config = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()?
    .with_root_certificates(roots)
    .with_no_client_auth();
    let client = reqwest::Client::builder()
        .use_preconfigured_tls(config.clone())
        .https_only(true)
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(30))
        .http1_only()
        .no_proxy()
        .build()?;
    let mut gateway = config;
    gateway.alpn_protocols = vec![b"nebula-game/1".to_vec()];
    Ok((TlsConnector::from(Arc::new(gateway)), client))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rustls::{
        client::danger::ServerCertVerifier,
        client::WebPkiServerVerifier,
        pki_types::{CertificateDer, ServerName, UnixTime},
    };
    const CA: &[u8] = include_bytes!("../tests/fixtures/ca.der");
    const OTHER_CA: &[u8] = include_bytes!("../tests/fixtures/other-ca.der");
    const SERVER: &[u8] = include_bytes!("../tests/fixtures/server.der");
    const DNS_ONLY: &[u8] = include_bytes!("../tests/fixtures/dns-only.der");
    const VALID: u64 = 1_798_761_600; // 2027-01-01 00:00:00 UTC
    fn store(ca: &[u8]) -> rustls::RootCertStore {
        let mut roots = rustls::RootCertStore::empty();
        roots.add(CertificateDer::from(ca.to_vec())).unwrap();
        roots
    }
    fn verify(ca: &[u8], cert: &[u8], host: &str, seconds: u64) -> Result<()> {
        let verifier = WebPkiServerVerifier::builder_with_provider(
            Arc::new(store(ca)),
            Arc::new(rustls::crypto::ring::default_provider()),
        )
        .build()?;
        verifier.verify_server_cert(
            &CertificateDer::from(cert),
            &[],
            &ServerName::try_from(host.to_owned())?,
            &[],
            UnixTime::since_unix_epoch(Duration::from_secs(seconds)),
        )?;
        Ok(())
    }
    #[test]
    fn valid_chain_checks_both_dns_and_ip_sans() {
        verify(CA, SERVER, "play.example.org", VALID).unwrap();
        verify(CA, SERVER, "203.0.113.10", VALID).unwrap();
        verify(CA, DNS_ONLY, "play.example.org", VALID).unwrap();
    }
    #[test]
    fn wrong_host_and_missing_ip_san_are_rejected() {
        assert!(verify(CA, SERVER, "other.example.org", VALID).is_err());
        assert!(verify(CA, SERVER, "203.0.113.11", VALID).is_err());
        assert!(verify(CA, DNS_ONLY, "203.0.113.10", VALID).is_err());
    }
    #[test]
    fn certificate_expiry_and_not_yet_valid_are_rejected() {
        assert!(verify(CA, SERVER, "play.example.org", 1_577_836_800).is_err());
        assert!(verify(CA, SERVER, "play.example.org", 2_208_988_800).is_err());
    }
    #[test]
    fn wrong_root_and_corrupt_certificate_never_fall_back() {
        assert!(verify(OTHER_CA, SERVER, "play.example.org", VALID).is_err());
        let mut corrupted = SERVER.to_vec();
        *corrupted.last_mut().unwrap() ^= 1;
        assert!(verify(CA, &corrupted, "play.example.org", VALID).is_err());
        assert!(clients_with_roots(rustls::RootCertStore::empty()).is_err());
    }
    #[test]
    fn both_clients_build_from_the_same_explicit_root_set() {
        clients(&Trust::PinnedCa(CA.to_vec())).unwrap();
        assert!(clients(&Trust::PinnedCa(vec![0, 1, 2])).is_err());
    }
    #[cfg(windows)]
    #[test]
    fn windows_system_roots_are_available_without_a_ca_file() {
        let roots = roots(&Trust::System).unwrap();
        assert!(!roots.is_empty());
        clients(&Trust::System).unwrap();
    }
}
