//! Opt-in fixed-server tester enrollment. Local Steam identity is not Valve proof.
//! A private, origin/identity-bound retry secret exists before the first request.
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Pending {
    server: String,
    steam_id: String,
    enrollment_key: String,
}

impl Drop for Pending {
    fn drop(&mut self) {
        use zeroize::Zeroize;
        self.enrollment_key.zeroize();
    }
}
fn base64url(bytes: &[u8]) -> String {
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut result = String::new();
    for chunk in bytes.chunks(3) {
        let bits = (u32::from(chunk[0]) << 16)
            | (u32::from(*chunk.get(1).unwrap_or(&0)) << 8)
            | u32::from(*chunk.get(2).unwrap_or(&0));
        for shift in [18, 12, 6, 0].into_iter().take(chunk.len() + 1) {
            result.push(ALPHABET[((bits >> shift) & 63) as usize] as char);
        }
    }
    result
}

fn authorization(pending: &Pending) -> Result<Zeroizing<Vec<u8>>> {
    let id: u64 = pending.steam_id.parse().context("Invalid Steam account")?;
    let base = 76_561_197_960_265_728u64;
    ensure!(
        pending.steam_id.len() == 17
            && pending.steam_id.bytes().all(|b| b.is_ascii_digit())
            && id > base
            && id <= base + u64::from(u32::MAX),
        "Invalid Steam account"
    );
    ensure!(
        pending.enrollment_key.len() == 43
            && pending
                .enrollment_key
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'),
        "Invalid private enrollment key"
    );
    Ok(Zeroizing::new(
        format!(
            "Nebula-Account-v1 {}.{}",
            base64url(pending.steam_id.as_bytes()),
            pending.enrollment_key
        )
        .into_bytes(),
    ))
}

fn response(raw: &[u8], pending: &Pending) -> Result<Zeroizing<Vec<u8>>> {
    ensure!(raw.len() <= 8192, "Enrollment response exceeds its limit");
    let split = raw
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .context("Incomplete enrollment response")?;
    ensure!(split <= 4096, "Enrollment response headers are too large");
    let headers = std::str::from_utf8(&raw[..split])?;
    let mut lines = headers.split("\r\n");
    let mut status = lines
        .next()
        .context("Missing enrollment status")?
        .split(' ');
    ensure!(
        matches!(status.next(), Some("HTTP/1.1" | "HTTP/1.0")),
        "Invalid enrollment HTTP version"
    );
    let status: u16 = status
        .next()
        .context("Missing enrollment status")?
        .parse()?;
    let mut length = None;
    let mut json = false;
    for line in lines {
        let (name, value) = line.split_once(':').context("Invalid enrollment header")?;
        ensure!(
            !name.eq_ignore_ascii_case("transfer-encoding"),
            "Unsupported enrollment response framing"
        );
        if name.eq_ignore_ascii_case("content-length") {
            ensure!(length.is_none(), "Duplicate enrollment body length");
            length = Some(value.trim().parse::<usize>()?);
        }
        if name.eq_ignore_ascii_case("content-type") {
            json = value.trim().split(';').next() == Some("application/json");
        }
    }
    let length = length.context("Missing enrollment body length")?;
    ensure!(
        length <= 1024 && raw.len() == split + 4 + length && json,
        "Invalid enrollment body framing"
    );
    let body: serde_json::Value = serde_json::from_slice(&raw[split + 4..])?;
    let error_code = body["error"].as_str().unwrap_or("");
    match status {
        200 | 201 => {}
        409 if error_code=="account_banned" => anyhow::bail!("This player is banned from the server. Contact its moderators; no saved account was replaced."),
        409 => anyhow::bail!("This server has not enabled access to an existing player from this device. Your retry key is saved safely; try Start again after the server owner enables it."),
        429 if error_code=="registration_capacity_reached" => anyhow::bail!("The server's player registration limit has been reached. Ask its owner to increase the limit; your retry key is saved safely."),
        429 => anyhow::bail!("Account setup is busy. Wait a few minutes and try Start again; your retry key is saved safely."),
        404 => anyhow::bail!("Automatic account setup is not enabled on this server yet. Try again after the server update."),
        _ => anyhow::bail!("The server refused account setup (HTTP {status}). Try Start again; your retry key is saved safely."),
    }
    ensure!(
        body["steam_id"].as_str() == Some(pending.steam_id.as_str())
            && body["steam_identity_verified"].as_bool() == Some(false)
            && body["created"].as_bool() == Some(status == 201),
        "Enrollment response identity does not match this Steam account"
    );
    let expected = authorization(pending)?;
    ensure!(
        body["authorization"].as_str().map(str::as_bytes) == Some(expected.as_slice()),
        "Enrollment response credential does not match the protected retry key"
    );
    Ok(expected)
}

#[cfg(windows)]
fn protect(bytes: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::Cryptography::{CryptProtectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB},
    };
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr() as *mut u8,
    };
    let mut output: CRYPT_INTEGER_BLOB = unsafe { std::mem::zeroed() };
    ensure!(
        unsafe {
            CryptProtectData(
                &input,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } != 0,
        "Windows could not protect the enrollment retry key"
    );
    let protected =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        LocalFree(output.pbData.cast());
    }
    Ok(Zeroizing::new(protected))
}

#[cfg(windows)]
fn unprotect(bytes: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::Cryptography::{
            CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
        },
    };
    ensure!(
        bytes.len() <= 65536,
        "Protected account material is too large"
    );
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr() as *mut u8,
    };
    let mut output: CRYPT_INTEGER_BLOB = unsafe { std::mem::zeroed() };
    ensure!(
        unsafe {
            CryptUnprotectData(
                &input,
                std::ptr::null_mut(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } != 0,
        "Windows could not read this user's protected account material"
    );
    let clear =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        std::ptr::write_bytes(output.pbData, 0, output.cbData as usize);
        LocalFree(output.pbData.cast());
    }
    Ok(Zeroizing::new(clear))
}

#[cfg(windows)]
pub(crate) fn saved_authorization(root: &std::path::Path) -> Result<Zeroizing<Vec<u8>>> {
    let path = crate::manifest::safe(root, "account-token.dpapi")?;
    let bytes = crate::manifest::read_bounded(&path, 65536)?;
    ensure!(
        bytes.len() >= 8
            && bytes.starts_with(b"NPA1")
            && u32::from_le_bytes(bytes[4..8].try_into()?) as usize == bytes.len() - 8,
        "Invalid protected account container"
    );
    unprotect(&bytes[8..])
}

#[cfg(windows)]
fn pending(root: &std::path::Path, server: &str, steam_id: &str) -> Result<Pending> {
    let path = crate::manifest::safe(root, "enrollment-pending.dpapi")?;
    if path.exists() {
        let bytes = crate::manifest::read_bounded(&path, 65536)?;
        ensure!(
            bytes.starts_with(b"NPE1"),
            "Unknown enrollment retry container"
        );
        let clear = unprotect(&bytes[4..])?;
        let value: Pending = serde_json::from_slice(&clear)?;
        ensure!(value.server == server && value.steam_id == steam_id,
            "A different Steam account has unfinished setup on this Windows user. Sign back into that Steam account and finish setup first.");
        authorization(&value)?;
        return Ok(value);
    }
    let mut random = Zeroizing::new([0u8; 32]);
    rustls::crypto::ring::default_provider()
        .secure_random
        .fill(random.as_mut_slice())
        .map_err(|_| anyhow::anyhow!("Windows random number generation failed"))?;
    let value = Pending {
        server: server.into(),
        steam_id: steam_id.into(),
        enrollment_key: base64url(random.as_slice()),
    };
    authorization(&value)?;
    let clear = Zeroizing::new(serde_json::to_vec(&value)?);
    let encrypted = protect(&clear)?;
    let mut container = b"NPE1".to_vec();
    container.extend_from_slice(&encrypted);
    crate::transaction::new_file(&path, &container)?;
    crate::credentials::restrict(&path)?;
    Ok(value)
}

#[cfg(windows)]
fn request(pending: &Pending) -> Result<Zeroizing<Vec<u8>>> {
    use std::{
        io::{Read, Write},
        net::{TcpStream, ToSocketAddrs},
        sync::Arc,
        time::{Duration, Instant},
    };
    let url = url::Url::parse(&pending.server)?;
    let host = url.host_str().context("Enrollment host missing")?;
    let port = url
        .port_or_known_default()
        .context("Enrollment port missing")?;
    let config = crate::launcher::client_config(crate::system_roots::load()?)?;
    let name = rustls::pki_types::ServerName::try_from(host.to_owned())?;
    let connection = rustls::ClientConnection::new(Arc::new(config), name)?;
    let deadline = Instant::now() + Duration::from_secs(15);
    let mut socket = None;
    for address in (host, port).to_socket_addrs()? {
        let remaining = deadline.saturating_duration_since(Instant::now());
        ensure!(!remaining.is_zero(), "Account setup connection timed out");
        if let Ok(stream) =
            TcpStream::connect_timeout(&address, remaining.min(Duration::from_secs(4)))
        {
            socket = Some(stream);
            break;
        }
    }
    let socket = socket.context("Cannot reach the account setup server")?;
    socket.set_read_timeout(Some(Duration::from_secs(8)))?;
    socket.set_write_timeout(Some(Duration::from_secs(8)))?;
    let mut tls = rustls::StreamOwned::new(connection, socket);
    let body = Zeroizing::new(serde_json::to_vec(
        &serde_json::json!({"steam_id":pending.steam_id,"enrollment_key":pending.enrollment_key}),
    )?);
    ensure!(
        body.len() <= 1024,
        "Account setup request exceeds its limit"
    );
    write!(tls,"POST /preservation/enroll HTTP/1.1\r\nHost: {host}:{port}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len())?;
    tls.write_all(&body)?;
    tls.flush()?;
    let mut raw = Zeroizing::new(Vec::new());
    let mut chunk = [0u8; 1024];
    loop {
        ensure!(
            Instant::now() < deadline,
            "Account setup timed out; retry safely with Start"
        );
        let n = tls.read(&mut chunk)?;
        if n == 0 {
            break;
        }
        ensure!(
            raw.len() + n <= 8192,
            "Account setup response exceeds its limit"
        );
        raw.extend_from_slice(&chunk[..n]);
    }
    response(&raw, pending)
}

/// Called only after an explicit Start click in the fixed-server testing build.
#[cfg(windows)]
pub(crate) fn ensure_account(server: &str) -> Result<()> {
    ensure!(
        crate::launcher::tester_build(),
        "Automatic enrollment requires an explicit tester build"
    );
    ensure!(
        crate::launcher::fixed_tester_server()?.as_deref() == Some(server),
        "Automatic enrollment origin differs from the fixed server"
    );
    crate::discovery::stopped()?;
    crate::launcher::preflight(server, None)?;
    let steam_id = crate::discovery::active_steam_account()?;
    ensure_account_for_identity(server, &steam_id)
}
#[cfg(windows)]
fn ensure_account_for_identity(server: &str, steam_id: &str) -> Result<()> {
    ensure!(
        crate::launcher::tester_build()
            && crate::launcher::fixed_tester_server()?.as_deref() == Some(server),
        "Fixture must match the compiled tester origin"
    );
    let base = std::path::PathBuf::from(
        std::env::var_os("LOCALAPPDATA").context("LOCALAPPDATA unavailable")?,
    );
    let root = crate::manifest::safe(&base, "NebulaPreservation")?;
    if !root.exists() {
        std::fs::create_dir(&root)?;
    }
    crate::manifest::reject_link(&root)?;
    crate::credentials::restrict(&root)?;
    let retry = crate::manifest::safe(&root, "enrollment-pending.dpapi")?;
    if retry.exists() {
        pending(&root, server, &steam_id)?;
    }
    let config = crate::manifest::safe(&root, "public-access.conf")?;
    if config.exists() {
        crate::endpoint::check_public_config(server)?;
        let saved = saved_authorization(&root)?;
        let prefix = format!("Nebula-Account-v1 {}.", base64url(steam_id.as_bytes()));
        ensure!(saved.len()==85 && saved.starts_with(prefix.as_bytes()),
            "The saved player account belongs to another Steam login. Sign into its Steam account before starting; no credentials were changed.");
    } else {
        let pending = pending(&root, server, &steam_id)?;
        let credential = request(&pending)?;
        crate::credentials::configure_authorization(server, &credential, true)?;
    }
    match crate::remote::saved_connection()? {
        Some((origin, _)) => {
            ensure!(
                origin == server,
                "Saved transport belongs to another server; existing settings retained"
            );
            crate::remote::migrate_system(server)?;
        }
        None => crate::remote::configure_system(server)?,
    }
    crate::launcher::probe(server)?;
    let retry = crate::manifest::safe(&root, "enrollment-pending.dpapi")?;
    if retry.exists() {
        std::fs::remove_file(retry)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Pending {
        Pending {
            server: "https://play.example.org:8444".into(),
            steam_id: (76_561_197_960_265_728u64 + 42).to_string(),
            enrollment_key: "A".repeat(43),
        }
    }
    fn wire(status: u16, body: &serde_json::Value) -> Vec<u8> {
        let body = serde_json::to_vec(body).unwrap();
        let mut value=format!("HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",body.len()).into_bytes();
        value.extend(body);
        value
    }
    #[test]
    fn exact_authorization_and_response_bind_to_pending_account_and_secret() {
        let pending = fixture();
        let auth = authorization(&pending).unwrap();
        assert_eq!(auth.len(), 85);
        for status in [200, 201] {
            let body = serde_json::json!({"steam_id":pending.steam_id,"authorization":std::str::from_utf8(&auth).unwrap(),"created":status==201,"steam_identity_verified":false});
            assert_eq!(
                response(&wire(status, &body), &pending).unwrap().as_slice(),
                auth.as_slice()
            );
        }
        let mut body = serde_json::json!({"steam_id":pending.steam_id,"authorization":std::str::from_utf8(&auth).unwrap(),"created":true,"steam_identity_verified":false});
        body["steam_identity_verified"] = true.into();
        assert!(response(&wire(201, &body), &pending).is_err());
        body["steam_identity_verified"] = false.into();
        body["authorization"] = "different".into();
        assert!(response(&wire(201, &body), &pending).is_err());
    }
    #[test]
    fn enrollment_refuses_redirects_conflicts_oversize_and_ambiguous_framing() {
        let pending = fixture();
        for status in [301, 302, 307, 400, 404, 409, 429, 500] {
            assert!(response(&wire(status, &serde_json::json!({})), &pending).is_err());
        }
        let valid = wire(201, &serde_json::json!({}));
        let text = String::from_utf8(valid).unwrap();
        for altered in [
            text.replace("Content-Length:", "Content-Length: 1\r\nContent-Length:"),
            text.replace(
                "Content-Length:",
                "Transfer-Encoding: chunked\r\nContent-Length:",
            ),
            text.replace("application/json", "text/html"),
            text + "trailing",
        ] {
            assert!(response(altered.as_bytes(), &pending).is_err());
        }
        assert!(response(&vec![b'x'; 8193], &pending).is_err());
    }
    #[test]
    fn urlsafe_no_padding_encoding_and_invalid_pending_inputs() {
        assert_eq!(base64url(b"f"), "Zg");
        assert_eq!(base64url(b"fo"), "Zm8");
        assert_eq!(base64url(b"foo"), "Zm9v");
        assert_eq!(base64url(&[255; 32]).len(), 43);
        let mut value = fixture();
        value.steam_id = "0".into();
        assert!(authorization(&value).is_err());
        value = fixture();
        value.enrollment_key = "/".repeat(43);
        assert!(authorization(&value).is_err());
    }
    #[cfg(windows)]
    #[test]
    fn persisted_retry_key_is_stable_and_rejects_other_origins_or_steam_users() {
        let root = std::env::temp_dir().join(format!(
            "nebula-enrollment-fixture-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        crate::credentials::restrict(&root).unwrap();
        let id = fixture().steam_id.clone();
        let first = pending(&root, "https://play.example.org:8444", &id).unwrap();
        let bytes = std::fs::read(root.join("enrollment-pending.dpapi")).unwrap();
        assert!(!bytes
            .windows(first.enrollment_key.len())
            .any(|v| v == first.enrollment_key.as_bytes()));
        let reopened = pending(&root, "https://play.example.org:8444", &id).unwrap();
        assert_eq!(first.enrollment_key, reopened.enrollment_key);
        assert!(pending(&root, "https://other.example.org:8444", &id).is_err());
        assert!(pending(
            &root,
            "https://play.example.org:8444",
            &(76_561_197_960_265_728u64 + 43).to_string()
        )
        .is_err());
        assert_eq!(
            bytes,
            std::fs::read(root.join("enrollment-pending.dpapi")).unwrap()
        );
        assert!(
            root.starts_with(std::env::temp_dir())
                && root
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("nebula-enrollment-fixture-")
        );
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn server_error_codes_distinguish_bans_capacity_and_strict_existing_accounts() {
        let p = fixture();
        let banned = response(
            &wire(409, &serde_json::json!({"error":"account_banned"})),
            &p,
        )
        .unwrap_err()
        .to_string();
        assert!(banned.contains("banned") && !banned.contains("recovery"));
        let capacity = response(
            &wire(
                429,
                &serde_json::json!({"error":"registration_capacity_reached"}),
            ),
            &p,
        )
        .unwrap_err()
        .to_string();
        assert!(capacity.contains("registration limit"));
        let existing = response(
            &wire(409, &serde_json::json!({"error":"account_unavailable"})),
            &p,
        )
        .unwrap_err()
        .to_string();
        assert!(existing.contains("existing player") && !existing.contains("banned"));
    }
    #[cfg(windows)]
    #[test]
    #[ignore = "requires an authorized disposable claimed-ID policy account and two isolated profiles"]
    fn authorized_live_claimed_id_fixture() {
        use sha2::{Digest, Sha256};
        assert_eq!(
            std::env::var("NEBULA_ENROLLMENT_FIXTURE_POLICY").unwrap(),
            "trust_claimed_id"
        );
        let server = std::env::var("NEBULA_ENROLLMENT_FIXTURE_SERVER").unwrap();
        let id = std::env::var("NEBULA_ENROLLMENT_FIXTURE_STEAM_ID").unwrap();
        let report =
            std::path::PathBuf::from(std::env::var_os("NEBULA_ENROLLMENT_FIXTURE_REPORT").unwrap());
        let base = std::path::PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap());
        let resume =
            std::env::var("NEBULA_ENROLLMENT_FIXTURE_RESUME").as_deref() == Ok("authorized");
        assert!(base.is_dir() && (resume || base.read_dir().unwrap().next().is_none()));
        assert!(base
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("nebula-enrollment-live-fixture-"));
        assert_eq!(
            crate::launcher::fixed_tester_server().unwrap().as_deref(),
            Some(server.as_str())
        );
        crate::launcher::preflight(&server, None).unwrap();
        let mut credentials = Vec::new();
        let mut hashes = Vec::new();
        for name in ["device-a", "device-b"] {
            let device = base.join(name);
            std::fs::create_dir_all(&device).unwrap();
            let root = device.join("NebulaPreservation");
            std::fs::create_dir_all(&root).unwrap();
            crate::credentials::restrict(&root).unwrap();
            std::env::set_var("LOCALAPPDATA", &device);
            let auth = if resume && root.join("public-access.conf").exists() {
                saved_authorization(&root).unwrap()
            } else {
                let p = pending(&root, &server, &id).unwrap();
                let auth = request(&p).unwrap();
                crate::credentials::configure_authorization(&server, &auth, true).unwrap();
                crate::remote::configure_system(&server).unwrap();
                auth
            };
            ensure_account_for_identity(&server, &id).unwrap();
            assert!(!root.join("enrollment-pending.dpapi").exists());
            assert_eq!(
                saved_authorization(&root).unwrap().as_slice(),
                auth.as_slice()
            );
            hashes.push(format!(
                "{:x}",
                Sha256::digest(std::fs::read(root.join("account-token.dpapi")).unwrap())
            ));
            credentials.push(auth);
        }
        assert_ne!(credentials[0].as_slice(), credentials[1].as_slice());
        for (index, name) in ["device-a", "device-b"].into_iter().enumerate() {
            let device = base.join(name);
            std::env::set_var("LOCALAPPDATA", &device);
            ensure_account_for_identity(&server, &id).unwrap();
            assert_eq!(
                hashes[index],
                format!(
                    "{:x}",
                    Sha256::digest(
                        std::fs::read(device.join("NebulaPreservation/account-token.dpapi"))
                            .unwrap()
                    )
                )
            );
        }
        std::fs::write(report,serde_json::to_vec_pretty(&serde_json::json!({"passed":true,"enrollment_posts":2,"same_claimed_steam_id":true,"independent_client_keys":true,"both_dpapi_roundtrips":true,"both_profile_reopens_unchanged":true,"pending_removed_after_success":true,"remote_credential_acceptance":"separate operator protocol check required","game_launched":false,"credential_logged":false})).unwrap()).unwrap();
        std::env::set_var("LOCALAPPDATA", base);
    }
    #[cfg(windows)]
    #[test]
    #[ignore = "requires an explicitly authorized disposable live server account and isolated LOCALAPPDATA"]
    fn authorized_live_enrollment_fixture() {
        use sha2::{Digest, Sha256};
        let server = std::env::var("NEBULA_ENROLLMENT_FIXTURE_SERVER")
            .expect("Explicit authorized fixture server required");
        let id = std::env::var("NEBULA_ENROLLMENT_FIXTURE_STEAM_ID")
            .expect("Explicit unused synthetic Steam identity required");
        let report = std::path::PathBuf::from(
            std::env::var_os("NEBULA_ENROLLMENT_FIXTURE_REPORT")
                .expect("Private fixture report required"),
        );
        let base = std::path::PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap());
        assert!(
            base.is_dir() && base.read_dir().unwrap().next().is_none(),
            "Fixture LOCALAPPDATA must be a new empty directory"
        );
        assert!(base
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("nebula-enrollment-live-fixture-"));
        assert_eq!(
            crate::launcher::fixed_tester_server().unwrap().as_deref(),
            Some(server.as_str())
        );
        crate::launcher::preflight(&server, None).unwrap();
        let root = base.join("NebulaPreservation");
        std::fs::create_dir(&root).unwrap();
        crate::credentials::restrict(&root).unwrap();
        let first = pending(&root, &server, &id).unwrap();
        let protected = std::fs::read(root.join("enrollment-pending.dpapi")).unwrap();
        let first_credential = request(&first).unwrap();
        // Simulated lost response: no player files were configured. Reopen the
        // protected retry key and repeat exactly the same enrollment request.
        let reopened = pending(&root, &server, &id).unwrap();
        assert_eq!(first.enrollment_key, reopened.enrollment_key);
        assert_eq!(
            protected,
            std::fs::read(root.join("enrollment-pending.dpapi")).unwrap()
        );
        let retry_credential = request(&reopened).unwrap();
        assert_eq!(first_credential.as_slice(), retry_credential.as_slice());
        crate::credentials::configure_authorization(&server, &retry_credential, true).unwrap();
        crate::remote::configure_system(&server).unwrap();
        let snapshot = || {
            [
                "public-access.conf",
                "account-token.dpapi",
                "remote-game.conf",
            ]
            .into_iter()
            .map(|name| {
                (
                    name.to_owned(),
                    format!(
                        "{:x}",
                        Sha256::digest(std::fs::read(root.join(name)).unwrap())
                    ),
                )
            })
            .collect::<std::collections::BTreeMap<_, _>>()
        };
        let before = snapshot();
        ensure_account_for_identity(&server, &id).unwrap();
        assert!(!root.join("enrollment-pending.dpapi").exists());
        ensure_account_for_identity(&server, &id).unwrap();
        assert_eq!(before, snapshot());
        let saved = saved_authorization(&root).unwrap();
        assert_eq!(saved.as_slice(), first_credential.as_slice());
        std::fs::write(report,serde_json::to_vec_pretty(&serde_json::json!({"passed":true,"enrollment_posts":2,"lost_response_retry_same_credential":true,"protected_retry_reopened":true,"dpapi_account_roundtrip":true,"profile_reopen_unchanged":true,"normal_system_tls":true,"game_launched":false,"credential_logged":false})).unwrap()).unwrap();
    }
    #[cfg(windows)]
    #[test]
    fn pending_secret_uses_current_user_dpapi_and_detects_tampering() {
        let value = b"synthetic-private-retry-marker";
        let protected = protect(value).unwrap();
        assert!(!protected.windows(value.len()).any(|v| v == value));
        assert_eq!(unprotect(&protected).unwrap().as_slice(), value);
        let mut changed = protected.to_vec();
        let index = changed.len() - 1;
        changed[index] ^= 1;
        assert!(unprotect(&changed).is_err());
    }
}
