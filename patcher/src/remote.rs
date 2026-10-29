//! Opt-in local TLS sidecar provisioning. Public CA material, no new secrets.
use anyhow::{ensure, Context, Result};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};
pub const LOCAL_API: &str = "http://127.0.0.1:38080";
fn folder() -> Result<PathBuf> {
    let base = PathBuf::from(std::env::var_os("LOCALAPPDATA").context("LOCALAPPDATA missing")?);
    crate::manifest::safe(&base, "NebulaPreservation")
}
fn fields(bytes: &[u8]) -> Result<BTreeMap<&str, &str>> {
    ensure!(
        bytes.len() <= 4096 && !bytes.contains(&0) && !bytes.contains(&b'\r'),
        "Invalid remote config encoding/size"
    );
    let text = std::str::from_utf8(bytes)?;
    let mut out = BTreeMap::new();
    for line in text.split('\n') {
        if line.is_empty() {
            continue;
        }
        let (k, v) = line
            .split_once('=')
            .context("Invalid remote config field")?;
        ensure!(out.insert(k, v).is_none(), "Duplicate remote config field");
    }
    Ok(out)
}
/// Read only the saved public origin; full credential/trust checks follow.
#[cfg(windows)]
pub fn saved_server() -> Result<Option<String>> {
    let root = folder()?;
    crate::manifest::reject_link(&root)?;
    let path = crate::manifest::safe(&root, "remote-game.conf")?;
    if !path.exists() {
        return Ok(None);
    }
    let bytes = crate::manifest::read_bounded(&path, 4096)?;
    Ok(Some(profile_server(&bytes)?))
}
#[cfg(any(windows, test))]
fn profile_server(bytes: &[u8]) -> Result<String> {
    let data = fields(&bytes)?;
    ensure!(
        data.get("format") == Some(&"nebula-remote-transport-v1"),
        "Unknown saved connection format"
    );
    let server = data
        .get("server_url")
        .context("Saved connection has no server address")?;
    crate::endpoint::validate(server, "127.0.0.1")?;
    ensure!(
        server.starts_with("https://"),
        "Saved connection requires HTTPS"
    );
    Ok((*server).to_owned())
}
fn der(bytes: &[u8]) -> Result<()> {
    ensure!(
        bytes.len() >= 4 && bytes[0] == 0x30,
        "CA must be a single DER certificate"
    );
    let first = bytes[1];
    let (header, length) = if first < 128 {
        (2, first as usize)
    } else {
        let n = (first & 127) as usize;
        ensure!(
            n > 0 && n <= 4 && bytes.len() > n + 2 && bytes[2] != 0,
            "Invalid DER length"
        );
        let mut length = 0usize;
        for b in &bytes[2..2 + n] {
            length = (length << 8) | *b as usize;
        }
        ensure!(length >= 128, "Noncanonical DER length");
        (2 + n, length)
    };
    ensure!(
        header + length == bytes.len(),
        "CA DER must contain one complete sequence"
    );
    Ok(())
}
pub fn check(server: &str) -> Result<()> {
    crate::endpoint::check_public_config(server)?;
    let root = folder()?;
    crate::manifest::reject_link(&root)?;
    let bytes =
        crate::manifest::read_bounded(&crate::manifest::safe(&root, "remote-game.conf")?, 4096)?;
    let f = fields(&bytes)?;
    let expected = [
        ("format", "nebula-remote-transport-v1"),
        ("server_url", server),
        ("gateway_port", "8443"),
        ("api_port", "38080"),
        ("first_scene_port", "28000"),
        ("last_scene_port", "28031"),
    ];
    ensure!(
        f.len() == 8 && expected.iter().all(|(k, v)| f.get(k) == Some(v)),
        "Remote transport profile differs from reviewed fixed-port contract"
    );
    let ca = PathBuf::from(f.get("ca_file").context("Missing CA file")?);
    ensure!(
        ca == root.join("operator-ca.der"),
        "CA file must be fixed direct-child operator-ca.der"
    );
    crate::manifest::reject_link(&ca)?;
    let pin = f.get("ca_sha256").context("Missing CA pin")?;
    crate::manifest::sha(pin)?;
    let bytes = crate::manifest::read_bounded(&ca, 1024 * 1024)?;
    ensure!(
        crate::manifest::hash(&bytes) == *pin,
        "CA fingerprint mismatch"
    );
    der(&bytes)?;
    Ok(())
}
#[cfg(windows)]
pub fn ca_bytes(server: &str) -> Result<Vec<u8>> {
    check(server)?;
    crate::manifest::read_bounded(
        &crate::manifest::safe(&folder()?, "operator-ca.der")?,
        1024 * 1024,
    )
}
pub fn validate_ca_file(ca_file: &Path, pin: &str) -> Result<Vec<u8>> {
    crate::manifest::sha(pin)?;
    crate::manifest::reject_link(ca_file)?;
    let bytes = crate::manifest::read_bounded(ca_file, 1024 * 1024)?;
    ensure!(
        crate::manifest::hash(&bytes) == pin,
        "CA fingerprint mismatch"
    );
    der(&bytes)?;
    Ok(bytes)
}
pub fn configure(server: &str, ca_file: &Path, pin: &str) -> Result<()> {
    crate::discovery::stopped()?;
    crate::endpoint::validate(server, "127.0.0.1")?;
    ensure!(
        server.starts_with("https://"),
        "Remote profile requires HTTPS"
    );
    crate::endpoint::check_public_config(server)?;
    let bytes = validate_ca_file(ca_file, pin)?;
    let root = folder()?;
    crate::manifest::reject_link(&root)?;
    let config = crate::manifest::safe(&root, "remote-game.conf")?;
    let target = crate::manifest::safe(&root, "operator-ca.der")?;
    ensure!(!config.exists()&&!target.exists(),"Remote config exists or provisioning was interrupted; use reset-remote-config before reprovisioning");
    let name = target.to_str().context("CA path must be UTF-8")?;
    ensure!(!name.contains(['\r', '\n', '\0']), "Invalid CA path");
    let text=format!("format=nebula-remote-transport-v1\nserver_url={server}\ngateway_port=8443\napi_port=38080\nfirst_scene_port=28000\nlast_scene_port=28031\nca_file={name}\nca_sha256={pin}\n");
    ensure!(text.len() <= 4096, "Remote config too large");
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        ensure!(
            target.as_os_str().encode_wide().count() < 260,
            "CA path exceeds bridge MAX_PATH contract"
        );
        crate::credentials::restrict(&root)?;
        crate::transaction::new_file(&target, &bytes)?;
        crate::credentials::restrict(&target)?;
        crate::transaction::new_file(&config, text.as_bytes())?;
        crate::credentials::restrict(&config)?;
        check(server)?;
        println!("Opt-in remote TLS profile configured with the supplied public CA pin. Account token unchanged.");
    }
    #[cfg(not(windows))]
    anyhow::bail!("Remote player provisioning requires Windows");
    Ok(())
}
pub fn reset() -> Result<()> {
    crate::discovery::stopped()?;
    let root = folder()?;
    if !root.exists() {
        println!("No remote profile exists.");
        return Ok(());
    }
    crate::manifest::reject_link(&root)?;
    let config = crate::manifest::safe(&root, "remote-game.conf")?;
    let ca = crate::manifest::safe(&root, "operator-ca.der")?;
    if config.exists() {
        let bytes = crate::manifest::read_bounded(&config, 4096)?;
        let f = fields(&bytes)?;
        ensure!(
            f.get("format") == Some(&"nebula-remote-transport-v1"),
            "Refusing unknown remote config"
        );
    }
    if ca.exists() {
        der(&crate::manifest::read_bounded(&ca, 1024 * 1024)?)?;
    }
    if config.exists() {
        std::fs::remove_file(config)?
    }
    if ca.exists() {
        std::fs::remove_file(ca)?
    }
    println!(
        "Removed only remote transport config and fixed public CA file; account token retained."
    );
    Ok(())
}

#[cfg(test)]
mod setup_tests {
    use super::*;
    #[test]
    fn saved_origin_refuses_duplicates_unknown_profiles_and_unsafe_addresses() {
        assert_eq!(
            profile_server(
                b"format=nebula-remote-transport-v1\nserver_url=https://play.example.org:8444\n"
            )
            .unwrap(),
            "https://play.example.org:8444"
        );
        for value in [
            "format=unknown\nserver_url=https://play.example.org:8444\n",
            "format=nebula-remote-transport-v1\nserver_url=http://play.example.org\n",
            "format=nebula-remote-transport-v1\nserver_url=https://user@play.example.org\n",
            "format=nebula-remote-transport-v1\nserver_url=https://play.example.org\nserver_url=https://other.example.org\n",
        ] { assert!(profile_server(value.as_bytes()).is_err()); }
    }
    #[test]
    fn certificate_preflight_is_read_only_and_rejects_wrong_pins_and_trailing_bytes() {
        let root = std::env::temp_dir().join(format!(
            "nebula-ca-preflight-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        let path = root.join("test.der");
        let cert = [0x30, 0x02, 0x05, 0x00];
        std::fs::write(&path, cert).unwrap();
        let pin = crate::manifest::hash(&cert);
        assert_eq!(validate_ca_file(&path, &pin).unwrap(), cert);
        assert!(validate_ca_file(&path, &"0".repeat(64)).is_err());
        std::fs::write(&path, [0x30, 0x02, 0x05, 0x00, 0]).unwrap();
        assert!(
            validate_ca_file(&path, &crate::manifest::hash(&[0x30, 0x02, 0x05, 0x00, 0])).is_err()
        );
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 1);
        std::fs::remove_file(path).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
}
