//! Optional, no-argument, game-owned API/TLS/Telepathy proxy. Never launches a game.
use anyhow::{bail, ensure, Context, Result};
use nebula_remote_transport::{profile, tls};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::Semaphore,
    time::timeout,
};
use tokio_rustls::{rustls::pki_types::ServerName, TlsConnector};
use zeroize::Zeroizing;

const API_PORT: u16 = 38080;
const FIRST: u16 = 28000;
const LAST: u16 = 28031;
const CONFIG_LIMIT: usize = 4096;
const HTTP_LIMIT: usize = 262144;
const RESPONSE_LIMIT: usize = 8 * 1024 * 1024;
const EXE: &str = "77bdecc37804194305c2402be5ac0851570f395bf9af3fb4ee03030c6d779d0d";

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn no_link(path: &Path) -> Result<()> {
    let meta = std::fs::symlink_metadata(path)?;
    ensure!(!meta.file_type().is_symlink(), "Linked path");
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        ensure!(meta.file_attributes() & 0x400 == 0, "Reparse path");
    }
    Ok(())
}
fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    no_link(path)?;
    let meta = std::fs::metadata(path)?;
    ensure!(
        meta.is_file() && meta.len() > 0 && meta.len() <= maximum as u64,
        "File bounds"
    );
    let bytes = std::fs::read(path)?;
    ensure!(
        bytes.len() == meta.len() as usize && bytes.len() <= maximum,
        "Changed file"
    );
    Ok(bytes)
}
fn config(path: &Path, keys: &[&str]) -> Result<BTreeMap<String, String>> {
    let raw = read_bounded(path, CONFIG_LIMIT)?;
    let result = profile::fields(&raw)?;
    ensure!(
        result.len() == keys.len() && keys.iter().all(|key| result.contains_key(*key)),
        "Config fields"
    );
    Ok(result)
}
fn child(folder: &Path, value: &str) -> Result<PathBuf> {
    let path = PathBuf::from(value);
    ensure!(
        path.is_absolute() && path.parent() == Some(folder),
        "Nonlocal profile path"
    );
    no_link(&path)?;
    Ok(path)
}
struct Profile {
    origin: String,
    hostname: String,
    gateway: u16,
    trust: tls::Trust,
    authorization: Zeroizing<Vec<u8>>,
}
impl Profile {
    fn load() -> Result<Self> {
        let folder = PathBuf::from(std::env::var_os("LOCALAPPDATA").context("No user profile")?)
            .join("NebulaPreservation");
        no_link(&folder)?;
        let public = config(
            &folder.join("public-access.conf"),
            &["format", "server_url", "token_file"],
        )?;
        let remote = profile::parse(&read_bounded(
            &folder.join("remote-game.conf"),
            CONFIG_LIMIT,
        )?)?;
        ensure!(
            public["format"] == "nebula-public-access-v1" && public["server_url"] == remote.origin,
            "Profile mismatch"
        );
        let trust = match remote.trust {
            profile::Trust::System => tls::Trust::System,
            profile::Trust::PinnedCa { file, sha256 } => {
                let ca = read_bounded(&child(&folder, &file)?, 65536)?;
                ensure!(hash(&ca) == sha256, "CA pin mismatch");
                tls::Trust::PinnedCa(ca)
            }
        };
        let encrypted = read_bounded(&child(&folder, &public["token_file"])?, 65536)?;
        let authorization = platform::unprotect(&encrypted)?;
        let b64 = |b: &u8| b.is_ascii_alphanumeric() || *b == b'-' || *b == b'_';
        ensure!(
            authorization.len() == 85
                && authorization.starts_with(b"Nebula-Account-v1 ")
                && authorization[18..41].iter().all(b64)
                && authorization[41] == b'.'
                && authorization[42..].iter().all(b64),
            "Credential grammar"
        );
        Ok(Self {
            origin: remote.origin,
            hostname: remote.hostname,
            gateway: remote.gateway,
            trust,
            authorization,
        })
    }
}

#[cfg(windows)]
mod platform {
    use super::*;
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::{
        Foundation::*,
        NetworkManagement::IpHelper::*,
        Networking::WinSock::AF_INET,
        Security::Cryptography::*,
        System::{Diagnostics::ToolHelp::*, Threading::*},
    };
    pub struct Handle(pub usize);
    impl Drop for Handle {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0 as HANDLE);
            }
        }
    }
    pub struct Parent {
        pub handle: Handle,
        pub pid: u32,
        pub created: u64,
    }
    impl Parent {
        pub fn identify() -> Result<Self> {
            unsafe {
                let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
                ensure!(snapshot != INVALID_HANDLE_VALUE, "Process census");
                let snapshot = Handle(snapshot as usize);
                let mut entry: PROCESSENTRY32W = zeroed();
                entry.dwSize = size_of::<PROCESSENTRY32W>() as u32;
                ensure!(
                    Process32FirstW(snapshot.0 as HANDLE, &mut entry) != 0,
                    "Process census"
                );
                let current = GetCurrentProcessId();
                let pid = loop {
                    if entry.th32ProcessID == current {
                        break entry.th32ParentProcessID;
                    }
                    if Process32NextW(snapshot.0 as HANDLE, &mut entry) == 0 {
                        bail!("Creator process missing");
                    }
                };
                let raw = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | 0x00100000, 0, pid);
                ensure!(!raw.is_null(), "Creator process access");
                let handle = Handle(raw as usize);
                let (mut created, mut exited, mut kernel, mut user): (
                    FILETIME,
                    FILETIME,
                    FILETIME,
                    FILETIME,
                ) = (zeroed(), zeroed(), zeroed(), zeroed());
                ensure!(
                    GetProcessTimes(raw, &mut created, &mut exited, &mut kernel, &mut user) != 0,
                    "Creator lifetime"
                );
                let mut path = [0u16; 32768];
                let mut length = path.len() as u32;
                ensure!(
                    QueryFullProcessImageNameW(raw, 0, path.as_mut_ptr(), &mut length) != 0,
                    "Creator image"
                );
                let parent_path = PathBuf::from(String::from_utf16(&path[..length as usize])?);
                let sibling = std::env::current_exe()?
                    .parent()
                    .context("Sibling directory")?
                    .join("Nebula Realms.exe");
                ensure!(
                    parent_path
                        .to_string_lossy()
                        .eq_ignore_ascii_case(&sibling.to_string_lossy())
                        && hash(&read_bounded(&parent_path, 16 * 1024 * 1024)?) == EXE,
                    "Creator image fingerprint"
                );
                ensure!(
                    WaitForSingleObject(raw, 0) == WAIT_TIMEOUT,
                    "Creator already stopped"
                );
                Ok(Self {
                    handle,
                    pid,
                    created: ((created.dwHighDateTime as u64) << 32) | created.dwLowDateTime as u64,
                })
            }
        }
        pub fn alive(&self) -> bool {
            unsafe { WaitForSingleObject(self.handle.0 as HANDLE, 0) == WAIT_TIMEOUT }
        }
        pub fn singleton(&self) -> Result<Handle> {
            unsafe {
                let name: Vec<u16> = format!(
                    "Local\\NebulaRemoteTransport-Mutex-{}-{}",
                    self.pid, self.created
                )
                .encode_utf16()
                .chain(Some(0))
                .collect();
                let raw = CreateMutexW(std::ptr::null(), 1, name.as_ptr());
                ensure!(!raw.is_null(), "Proxy mutex");
                let owned = Handle(raw as usize);
                ensure!(
                    GetLastError() != ERROR_ALREADY_EXISTS,
                    "Proxy already active"
                );
                Ok(owned)
            }
        }
        pub fn ready(&self) -> Result<Handle> {
            unsafe {
                let name: Vec<u16> =
                    format!("Local\\NebulaRemoteTransport-{}-{}", self.pid, self.created)
                        .encode_utf16()
                        .chain(Some(0))
                        .collect();
                let event = OpenEventW(EVENT_MODIFY_STATE, 0, name.as_ptr());
                ensure!(!event.is_null(), "Creator readiness event missing");
                let handle = Handle(event as usize);
                ensure!(SetEvent(event) != 0, "Readiness signal");
                Ok(handle)
            }
        }
        pub fn owns_tcp(&self, peer: std::net::SocketAddr, local_port: u16) -> bool {
            unsafe {
                if peer.ip() != std::net::IpAddr::V4(std::net::Ipv4Addr::LOCALHOST) {
                    return false;
                }
                let mut size = 0;
                if GetExtendedTcpTable(
                    std::ptr::null_mut(),
                    &mut size,
                    0,
                    AF_INET as u32,
                    TCP_TABLE_OWNER_PID_ALL,
                    0,
                ) != ERROR_INSUFFICIENT_BUFFER
                    || !(4..=1024 * 1024).contains(&size)
                {
                    return false;
                }
                let mut buffer = vec![0u64; (size as usize).div_ceil(8)];
                if GetExtendedTcpTable(
                    buffer.as_mut_ptr().cast(),
                    &mut size,
                    0,
                    AF_INET as u32,
                    TCP_TABLE_OWNER_PID_ALL,
                    0,
                ) != 0
                {
                    return false;
                }
                let bytes = std::slice::from_raw_parts(buffer.as_ptr().cast::<u8>(), size as usize);
                let count = u32::from_ne_bytes(bytes[0..4].try_into().unwrap()) as usize;
                if 4 + count * size_of::<MIB_TCPROW_OWNER_PID>() > bytes.len() {
                    return false;
                }
                (0..count).any(|i| {
                    let row = std::ptr::read_unaligned(
                        bytes
                            .as_ptr()
                            .add(4 + i * size_of::<MIB_TCPROW_OWNER_PID>())
                            .cast::<MIB_TCPROW_OWNER_PID>(),
                    );
                    row.dwOwningPid == self.pid
                        && row.dwState == 5
                        && row.dwLocalAddr == u32::from_ne_bytes([127, 0, 0, 1])
                        && row.dwRemoteAddr == u32::from_ne_bytes([127, 0, 0, 1])
                        && u16::from_be(row.dwLocalPort as u16) == peer.port()
                        && u16::from_be(row.dwRemotePort as u16) == local_port
                })
            }
        }
    }
    pub fn unprotect(file: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
        unsafe {
            ensure!(
                file.len() >= 8
                    && &file[..4] == b"NPA1"
                    && u32::from_le_bytes(file[4..8].try_into()?) as usize == file.len() - 8,
                "Protected container"
            );
            let input = CRYPT_INTEGER_BLOB {
                cbData: (file.len() - 8) as u32,
                pbData: file[8..].as_ptr() as *mut u8,
            };
            let mut output: CRYPT_INTEGER_BLOB = zeroed();
            ensure!(
                CryptUnprotectData(
                    &input,
                    std::ptr::null_mut(),
                    std::ptr::null(),
                    std::ptr::null_mut(),
                    std::ptr::null(),
                    CRYPTPROTECT_UI_FORBIDDEN,
                    &mut output
                ) != 0,
                "DPAPI protection"
            );
            let bytes = Zeroizing::new(
                std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec(),
            );
            std::ptr::write_bytes(output.pbData, 0, output.cbData as usize);
            LocalFree(output.pbData.cast());
            Ok(bytes)
        }
    }
}

async fn owned(parent: &platform::Parent, socket: &TcpStream, port: u16) -> Result<()> {
    let peer = socket.peer_addr()?;
    for _ in 0..4 {
        if parent.alive() && parent.owns_tcp(peer, port) {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    bail!("Local socket is not creator-owned")
}

async fn game(
    mut local: TcpStream,
    port: u16,
    profile: Arc<Profile>,
    connector: TlsConnector,
) -> Result<()> {
    let remote = timeout(
        Duration::from_secs(5),
        TcpStream::connect((profile.hostname.as_str(), profile.gateway)),
    )
    .await??;
    remote.set_nodelay(true)?;
    let name = ServerName::try_from(profile.hostname.clone())?;
    let mut tls = timeout(Duration::from_secs(5), connector.connect(name, remote)).await??;
    ensure!(
        tls.get_ref().1.alpn_protocol() == Some(b"nebula-game/1"),
        "Gateway protocol mismatch"
    );
    let mut header = Vec::from(*b"NRT1");
    header.extend_from_slice(&port.to_be_bytes());
    header.extend_from_slice(&85u16.to_be_bytes());
    tls.write_all(&header).await?;
    tls.write_all(&profile.authorization).await?;
    tls.flush().await?;
    let mut response = [0u8; 4];
    timeout(Duration::from_secs(10), tls.read_exact(&mut response)).await??;
    ensure!(response == *b"OK01", "Gateway denied connection");
    timeout(
        Duration::from_secs(24 * 3600),
        tokio::io::copy_bidirectional(&mut local, &mut tls),
    )
    .await??;
    Ok(())
}

async fn api(mut local: TcpStream, profile: Arc<Profile>, client: reqwest::Client) -> Result<()> {
    let mut request = Vec::new();
    timeout(Duration::from_secs(10), async {
        loop {
            if let Some(end) = request.windows(4).position(|part| part == b"\r\n\r\n") {
                ensure!(end + 4 == request.len(), "No pipelined request or body");
                break;
            }
            ensure!(request.len() < HTTP_LIMIT, "HTTP header bound");
            let mut chunk = [0u8; 4096];
            let length = local.read(&mut chunk).await?;
            ensure!(
                length > 0 && request.len() + length <= HTTP_LIMIT,
                "HTTP header bound"
            );
            request.extend_from_slice(&chunk[..length]);
        }
        Ok::<(), anyhow::Error>(())
    })
    .await??;
    let text = std::str::from_utf8(&request)?;
    let mut lines = text.split("\r\n");
    let first: Vec<_> = lines
        .next()
        .context("HTTP request line")?
        .split(' ')
        .collect();
    ensure!(
        first.len() == 3 && first[0] == "GET" && ["HTTP/1.0", "HTTP/1.1"].contains(&first[2]),
        "Only original GET supported"
    );
    let target = first[1];
    ensure!(
        target.starts_with('/')
            && !target.starts_with("//")
            && !target.contains(['#', '\\'])
            && target.bytes().all(|b| b > 0x20 && b < 0x7f),
        "Origin-relative target required"
    );
    let mut host = None;
    for line in lines.take_while(|line| !line.is_empty()) {
        let (key, value) = line.split_once(':').context("HTTP header")?;
        if key.eq_ignore_ascii_case("Host") {
            ensure!(host.replace(value.trim()).is_none(), "Duplicate host");
        }
        if key.eq_ignore_ascii_case("Transfer-Encoding") {
            bail!("No request body");
        }
        if key.eq_ignore_ascii_case("Content-Length") {
            ensure!(value.trim() == "0", "No request body");
        }
    }
    ensure!(host == Some("127.0.0.1:38080"), "Loopback Host required");
    let authorization = reqwest::header::HeaderValue::from_bytes(&profile.authorization)?;
    let mut response = client
        .get(format!("{}{target}", profile.origin))
        .header(reqwest::header::AUTHORIZATION, authorization)
        .send()
        .await?;
    ensure!(!response.status().is_redirection(), "Redirect forbidden");
    let status = response.status().as_u16();
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await? {
        ensure!(body.len() + chunk.len() <= RESPONSE_LIMIT, "Response bound");
        body.extend_from_slice(&chunk);
    }
    let header = format!("HTTP/1.1 {status} Backend\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len());
    timeout(Duration::from_secs(10), async {
        local.write_all(header.as_bytes()).await?;
        local.write_all(&body).await?;
        local.shutdown().await
    })
    .await??;
    Ok(())
}

async fn run() -> Result<()> {
    ensure!(std::env::args_os().count() == 1, "No arguments supported");
    let parent = Arc::new(platform::Parent::identify()?);
    let _singleton = parent.singleton()?;
    let profile = Arc::new(Profile::load()?);
    let (connector, client) = tls::clients(&profile.trust)?;
    let mut listeners = Vec::new();
    listeners.push((
        API_PORT,
        TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, API_PORT)).await?,
    ));
    for port in FIRST..=LAST {
        listeners.push((
            port,
            TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, port)).await?,
        ));
    }
    let _event = parent.ready()?;
    let slots = Arc::new(Semaphore::new(64));
    let mut tasks = tokio::task::JoinSet::new();
    for (port, listener) in listeners {
        let (profile, parent, connector, client, slots) = (
            profile.clone(),
            parent.clone(),
            connector.clone(),
            client.clone(),
            slots.clone(),
        );
        tasks.spawn(async move {
            loop {
                let (socket, _) = listener.accept().await?;
                let permit = match slots.clone().try_acquire_owned() {
                    Ok(value) => value,
                    Err(_) => continue,
                };
                let (profile, parent, connector, client) = (
                    profile.clone(),
                    parent.clone(),
                    connector.clone(),
                    client.clone(),
                );
                tokio::spawn(async move {
                    let _permit = permit;
                    let result = async {
                        owned(&parent, &socket, port).await?;
                        if port == API_PORT {
                            api(socket, profile, client).await
                        } else {
                            game(socket, port, profile, connector).await
                        }
                    }
                    .await;
                    drop(result); // Metadata-only caller reports readiness; never print URL/credentials.
                });
            }
            #[allow(unreachable_code)]
            Ok::<(), anyhow::Error>(())
        });
    }
    let lifetime = tokio::time::sleep(Duration::from_secs(24 * 3600));
    tokio::pin!(lifetime);
    loop {
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(250)) => { if !parent.alive() { break; } },
            _ = &mut lifetime => break,
            _ = tasks.join_next() => bail!("Listener stopped"),
        }
    }
    tasks.abort_all();
    Ok(())
}

#[tokio::main]
async fn main() {
    if run().await.is_err() {
        // Error chains from HTTP clients can contain encrypted request URLs.
        // Keep all failure output fixed and free of secrets or packet content.
        eprintln!("Nebula remote transport stopped: configuration or runtime failure.");
        std::process::exit(1);
    }
}
