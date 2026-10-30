//! Opt-in local TLS sidecar provisioning. Public CA material, no new secrets.
use anyhow::{ensure, Context, Result};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};
pub const LOCAL_API: &str = "http://127.0.0.1:38080";
#[derive(Debug, PartialEq, Eq)]
enum Mode {
    PinnedCa,
    System,
}
#[cfg(windows)]
pub enum Trust {
    PinnedCa(Vec<u8>),
    System,
}
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
pub fn saved_connection() -> Result<Option<(String, bool)>> {
    let root = folder()?;
    crate::manifest::reject_link(&root)?;
    let path = crate::manifest::safe(&root, "remote-game.conf")?;
    if !path.exists() {
        return Ok(None);
    }
    let bytes = crate::manifest::read_bounded(&path, 4096)?;
    let server = profile_server(&bytes)?;
    let system = profile_mode(&fields(&bytes)?, &server)? == Mode::System;
    Ok(Some((server, system)))
}
#[cfg(any(windows, test))]
fn profile_server(bytes: &[u8]) -> Result<String> {
    let data = fields(&bytes)?;
    ensure!(
        matches!(
            data.get("format"),
            Some(&"nebula-remote-transport-v1") | Some(&"nebula-remote-transport-v2")
        ),
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
fn profile_mode(f: &BTreeMap<&str, &str>, server: &str) -> Result<Mode> {
    let expected = [
        ("server_url", server),
        ("gateway_port", "8443"),
        ("api_port", "38080"),
        ("first_scene_port", "28000"),
        ("last_scene_port", "28031"),
    ];
    ensure!(
        expected.iter().all(|(k, v)| f.get(k) == Some(v)),
        "Remote transport profile differs from reviewed fixed-port contract"
    );
    match f.get("format").copied() {
        Some("nebula-remote-transport-v1") => {
            ensure!(
                f.len() == 8 && f.contains_key("ca_file") && f.contains_key("ca_sha256"),
                "Private CA profile must contain exactly its reviewed fields"
            );
            Ok(Mode::PinnedCa)
        }
        Some("nebula-remote-transport-v2") => {
            ensure!(f.len() == 7 && f.get("trust") == Some(&"system"), "System trust profile must contain exactly its reviewed fields and no private CA override");
            Ok(Mode::System)
        }
        _ => anyhow::bail!("Unknown remote TLS profile format"),
    }
}
fn checked_trust(server: &str) -> Result<Option<Vec<u8>>> {
    crate::endpoint::check_public_config(server)?;
    let root = folder()?;
    crate::manifest::reject_link(&root)?;
    let bytes =
        crate::manifest::read_bounded(&crate::manifest::safe(&root, "remote-game.conf")?, 4096)?;
    let f = fields(&bytes)?;
    if profile_mode(&f, server)? == Mode::System {
        return Ok(None);
    }
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
    Ok(Some(bytes))
}
pub fn check(server: &str) -> Result<()> {
    checked_trust(server).map(|_| ())
}
#[cfg(windows)]
pub fn trust(server: &str) -> Result<Trust> {
    Ok(match checked_trust(server)? {
        Some(bytes) => Trust::PinnedCa(bytes),
        None => Trust::System,
    })
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
pub fn configure_system(server: &str) -> Result<()> {
    crate::discovery::stopped()?;
    crate::endpoint::validate(server, "127.0.0.1")?;
    ensure!(
        server.starts_with("https://"),
        "Remote profile requires HTTPS"
    );
    crate::endpoint::check_public_config(server)?;
    let root = folder()?;
    crate::manifest::reject_link(&root)?;
    let config = crate::manifest::safe(&root, "remote-game.conf")?;
    let old_ca = crate::manifest::safe(&root, "operator-ca.der")?;
    ensure!(!config.exists() && !old_ca.exists(), "Remote config exists or provisioning was interrupted; use reset-remote-config before reprovisioning");
    let text = system_profile_text(server);
    ensure!(text.len() <= 4096, "Remote config too large");
    #[cfg(windows)]
    {
        crate::credentials::restrict(&root)?;
        crate::transaction::new_file(&config, text.as_bytes())?;
        crate::credentials::restrict(&config)?;
        check(server)?;
        println!("Remote TLS profile configured with Windows certificate trust. No certificate file is required.");
    }
    #[cfg(not(windows))]
    anyhow::bail!("Remote player provisioning requires Windows");
    Ok(())
}
fn system_profile_text(server: &str) -> String {
    format!("format=nebula-remote-transport-v2\nserver_url={server}\ngateway_port=8443\napi_port=38080\nfirst_scene_port=28000\nlast_scene_port=28031\ntrust=system\n")
}
/// This is an explicit trust migration, never an error-triggered TLS fallback.
/// Existing account/DPAPI bytes and the old public CA remain untouched.
pub fn migrate_system(server: &str) -> Result<()> {
    crate::discovery::stopped()?;
    crate::endpoint::validate(server, "127.0.0.1")?;
    ensure!(
        server.starts_with("https://"),
        "Remote profile requires HTTPS"
    );
    crate::endpoint::check_public_config(server)?;
    #[cfg(windows)]
    {
        let root = folder()?;
        crate::manifest::reject_link(&root)?;
        let config = crate::manifest::safe(&root, "remote-game.conf")?;
        let original = crate::manifest::read_bounded(&config, 4096)?;
        let fields = fields(&original)?;
        let mode = profile_mode(&fields, server)?;
        if mode == Mode::PinnedCa {
            ensure!(
                Path::new(fields["ca_file"]) == root.join("operator-ca.der"),
                "Private CA profile uses an unexpected path"
            );
            crate::manifest::sha(fields["ca_sha256"])?;
        }
        // Check the new authority before any profile replacement. A failed
        // hostname, chain or backend check retains the old profile byte-for-byte.
        crate::launcher::preflight(server, None)?;
        if mode == Mode::PinnedCa {
            replace_profile(&config, &original, system_profile_text(server).as_bytes())?;
        }
        check(server)?;
        println!("Saved connection now uses Windows certificate trust. Existing account and protected token retained.");
    }
    #[cfg(not(windows))]
    anyhow::bail!("Remote player trust migration requires Windows");
    Ok(())
}
#[cfg(windows)]
fn replace_profile(config: &Path, expected: &[u8], replacement: &[u8]) -> Result<()> {
    use std::{io::Write, os::windows::ffi::OsStrExt};
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    ensure!(
        crate::manifest::read_bounded(config, 4096)? == expected,
        "Saved connection changed during its trust check; retry"
    );
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_nanos();
    let stage = crate::manifest::safe(
        config.parent().context("Profile folder")?,
        &format!(".remote-trust-{}-{nonce}.stage", std::process::id()),
    )?;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&stage)?;
    let result = (|| -> Result<()> {
        file.write_all(replacement)?;
        file.sync_all()?;
        drop(file);
        crate::credentials::restrict(&stage)?;
        ensure!(
            crate::manifest::read_bounded(config, 4096)? == expected,
            "Saved connection changed during its trust check; retry"
        );
        let target: Vec<u16> = config.as_os_str().encode_wide().chain(Some(0)).collect();
        let source: Vec<u16> = stage.as_os_str().encode_wide().chain(Some(0)).collect();
        // Same-directory rename, with no copy-across-volume fallback. Unlike
        // ReplaceFileW without a backup, a failed move cannot delete the target
        // first. The staged file already has the restricted account ACL.
        ensure!(
            unsafe {
                MoveFileExW(
                    source.as_ptr(),
                    target.as_ptr(),
                    MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
                )
            } != 0,
            "Windows could not atomically replace the saved TLS profile"
        );
        Ok(())
    })();
    if result.is_err() && stage.exists() {
        // This unpredictable direct-child path was created exclusively above.
        let _ = std::fs::remove_file(&stage);
    }
    result
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
            matches!(
                f.get("format"),
                Some(&"nebula-remote-transport-v1") | Some(&"nebula-remote-transport-v2")
            ),
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
    #[cfg(windows)]
    #[test]
    fn trust_replacement_keeps_account_and_old_profile_on_stale_or_locked_target() {
        use std::os::windows::fs::OpenOptionsExt;
        use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
        let root = std::env::temp_dir().join(format!(
            "nebula-trust-replace-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        let config = root.join("remote-game.conf");
        let token = root.join("account-token.dpapi");
        std::fs::write(&config, b"original-profile").unwrap();
        std::fs::write(&token, b"unchanged-account").unwrap();
        assert!(replace_profile(&config, b"stale-profile", b"system-profile").is_err());
        assert_eq!(std::fs::read(&config).unwrap(), b"original-profile");
        let lock = std::fs::OpenOptions::new()
            .read(true)
            .share_mode(FILE_SHARE_READ)
            .open(&config)
            .unwrap();
        assert!(replace_profile(&config, b"original-profile", b"system-profile").is_err());
        assert_eq!(std::fs::read(&config).unwrap(), b"original-profile");
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 2);
        drop(lock);
        replace_profile(&config, b"original-profile", b"system-profile").unwrap();
        assert_eq!(std::fs::read(&config).unwrap(), b"system-profile");
        assert_eq!(std::fs::read(&token).unwrap(), b"unchanged-account");
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 2);
        std::fs::remove_file(config).unwrap();
        std::fs::remove_file(token).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
    fn system_profile(extra: &str) -> Vec<u8> {
        format!("format=nebula-remote-transport-v2\nserver_url=https://play.example.org:8444\ngateway_port=8443\napi_port=38080\nfirst_scene_port=28000\nlast_scene_port=28031\ntrust=system\n{extra}").into_bytes()
    }
    #[test]
    fn automatic_trust_profile_is_explicit_and_never_accepts_ca_overrides() {
        let raw = system_profile("");
        let f = fields(&raw).unwrap();
        assert_eq!(
            profile_mode(&f, "https://play.example.org:8444").unwrap(),
            Mode::System
        );
        assert_eq!(
            profile_server(&raw).unwrap(),
            "https://play.example.org:8444"
        );
        for extra in [
            "ca_file=operator-ca.der\n",
            "ca_sha256=00\n",
            "trust=system\n",
            "untrusted=yes\n",
        ] {
            let raw = system_profile(extra);
            assert!(fields(&raw)
                .and_then(|f| profile_mode(&f, "https://play.example.org:8444"))
                .is_err());
        }
        for (from, to) in [
            ("trust=system", "trust=any"),
            ("gateway_port=8443", "gateway_port=8444"),
            ("api_port=38080", "api_port=8080"),
            ("last_scene_port=28031", "last_scene_port=65535"),
            ("transport-v2", "transport-v3"),
        ] {
            let raw = String::from_utf8(system_profile(""))
                .unwrap()
                .replace(from, to);
            assert!(profile_mode(
                &fields(raw.as_bytes()).unwrap(),
                "https://play.example.org:8444"
            )
            .is_err());
        }
        assert!(profile_mode(&f, "https://other.example.org:8444").is_err());
    }
    #[test]
    fn legacy_pinned_profile_cannot_be_silently_promoted_to_system_trust() {
        let raw = String::from_utf8(system_profile(""))
            .unwrap()
            .replace("transport-v2", "transport-v1")
            .replace("trust=system\n", "ca_file=operator-ca.der\nca_sha256=00\n");
        assert_eq!(
            profile_mode(
                &fields(raw.as_bytes()).unwrap(),
                "https://play.example.org:8444"
            )
            .unwrap(),
            Mode::PinnedCa
        );
        for broken in [
            raw.replace("ca_file=operator-ca.der\n", ""),
            raw.replace("ca_sha256=00\n", "trust=system\n"),
            format!("{raw}trust=system\n"),
        ] {
            assert!(profile_mode(
                &fields(broken.as_bytes()).unwrap(),
                "https://play.example.org:8444"
            )
            .is_err());
        }
    }
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
