//! A detached launcher process owns the game and restores files after it exits.
//! No identity secrets are stored in session status or command-line arguments.
use crate::{manifest, transaction};
use anyhow::{bail, ensure, Context, Result};
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    path::Path,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

#[derive(Debug, PartialEq, Eq)]
pub enum Prepare {
    Pristine,
    Restored,
    Running,
}

fn state(game: &Path) -> Result<std::path::PathBuf> {
    manifest::reject_link(game)?;
    let root = manifest::safe(game, ".nebula-preservation")?;
    if !root.exists() {
        fs::create_dir(&root)?;
    }
    manifest::reject_link(&root)?;
    Ok(root)
}
fn session_lock(root: &Path) -> Result<Option<File>> {
    let path = manifest::safe(root, "session.lock")?;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)?;
    match FileExt::try_lock_exclusive(&file) {
        Ok(()) => Ok(Some(file)),
        Err(error)
            if error.kind() == std::io::ErrorKind::WouldBlock
                || (cfg!(windows) && error.raw_os_error() == Some(33)) =>
        {
            Ok(None)
        }
        Err(error) => Err(error).context("Cannot check the game session lock"),
    }
}
#[cfg(windows)]
fn game_running() -> Result<bool> {
    use windows_sys::Win32::{
        Foundation::{CloseHandle, GetLastError, ERROR_NO_MORE_FILES, INVALID_HANDLE_VALUE},
        System::Diagnostics::ToolHelp::*,
    };
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        ensure!(
            snapshot != INVALID_HANDLE_VALUE,
            "Cannot enumerate game processes"
        );
        struct Handle(windows_sys::Win32::Foundation::HANDLE);
        impl Drop for Handle {
            fn drop(&mut self) {
                unsafe {
                    CloseHandle(self.0);
                }
            }
        }
        let _handle = Handle(snapshot);
        let mut item: PROCESSENTRY32W = std::mem::zeroed();
        item.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        ensure!(
            Process32FirstW(snapshot, &mut item) != 0,
            "Cannot read game process census"
        );
        loop {
            let n = item
                .szExeFile
                .iter()
                .position(|x| *x == 0)
                .unwrap_or(item.szExeFile.len());
            if String::from_utf16_lossy(&item.szExeFile[..n])
                .eq_ignore_ascii_case("Nebula Realms.exe")
            {
                return Ok(true);
            }
            if Process32NextW(snapshot, &mut item) == 0 {
                ensure!(
                    GetLastError() == ERROR_NO_MORE_FILES,
                    "Game process census failed"
                );
                return Ok(false);
            }
        }
    }
}
#[cfg(not(windows))]
fn game_running() -> Result<bool> {
    bail!("Game sessions require Windows")
}

// The game-owned transport helper can take a moment to release its executable
// after the parent exits. Retry only Windows sharing/access errors, preserving
// the transactional journal. Never terminate another process or ignore changes.
fn restore_idle(game: &Path) -> Result<bool> {
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    loop {
        ensure!(
            !game_running()?,
            "The game is still running; originals will be restored after it exits"
        );
        match transaction::prepare_originals(game) {
            Ok(restored) => return Ok(restored),
            Err(error) => {
                let sharing = error
                    .chain()
                    .filter_map(|e| e.downcast_ref::<std::io::Error>())
                    .any(|e| matches!(e.raw_os_error(), Some(5 | 32 | 33)));
                if !sharing || std::time::Instant::now() >= deadline {
                    return Err(error);
                }
                std::thread::sleep(Duration::from_millis(100));
            }
        }
    }
}
/// Restore an old/crashed session only if no supervisor or game is running.
pub fn prepare(game: &Path) -> Result<Prepare> {
    let root = state(game)?;
    let Some(_lock) = session_lock(&root)? else {
        return Ok(Prepare::Running);
    };
    if game_running()? {
        return Ok(Prepare::Running);
    }
    let changed = restore_idle(game)?;
    Ok(if changed {
        Prepare::Restored
    } else {
        Prepare::Pristine
    })
}

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum Phase {
    Starting,
    Launched,
    Restored,
    Failed,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Status {
    format: String,
    nonce: String,
    phase: Phase,
    game_pid: Option<u32>,
    error: Option<String>,
}
impl Status {
    fn new(nonce: &str) -> Self {
        Self {
            format: "nebula-session-v1".into(),
            nonce: nonce.into(),
            phase: Phase::Starting,
            game_pid: None,
            error: None,
        }
    }
    fn validate(&self) -> Result<()> {
        ensure!(
            self.format == "nebula-session-v1",
            "Unsupported game session record"
        );
        manifest::sha(&self.nonce)?;
        ensure!(
            self.error.as_ref().is_none_or(|e| e.len() <= 4096),
            "Oversized session message"
        );
        ensure!(
            matches!(self.phase, Phase::Starting | Phase::Failed)
                || self.game_pid.is_some_and(|pid| pid > 0),
            "Incomplete session record"
        );
        Ok(())
    }
    fn save(&self, root: &Path) -> Result<()> {
        self.validate()?;
        transaction::json_write(&manifest::safe(root, "session.json")?, self)
    }
}
fn read_status(root: &Path, nonce: &str) -> Result<Option<Status>> {
    let path = manifest::safe(root, "session.json")?;
    if !path.exists() {
        return Ok(None);
    }
    let status: Status = serde_json::from_slice(&manifest::read_bounded(&path, 8192)?)?;
    status.validate()?;
    Ok((status.nonce == nonce).then_some(status))
}

fn wait_then_restore(
    child: &mut std::process::Child,
    restore: impl FnOnce() -> Result<bool>,
) -> Result<()> {
    child
        .wait()
        .context("Cannot wait for the owned game process; originals were not changed")?;
    restore().context(
        "The game exited but automatic restoration needs attention; start the launcher again",
    )?;
    Ok(())
}

/// The hidden supervisor performs the complete restore/patch/launch sequence.
/// GUI lifetime is deliberately independent of game and restoration lifetime.
#[cfg(windows)]
pub fn launch_supervised(
    game: &Path,
    m: &manifest::Manifest,
    pin: &str,
    server: &str,
    allow_provisional: bool,
) -> Result<u32> {
    use std::os::windows::process::CommandExt;
    let (_, compiled, compiled_pin) = crate::launcher::bundle(allow_provisional)?;
    ensure!(
        compiled_pin == pin && serde_json::to_vec(&compiled)? == serde_json::to_vec(m)?,
        "Session bundle differs from this launcher's reviewed release"
    );
    let server = crate::launcher::origin(server)?;
    if let Some(fixed) = crate::launcher::fixed_tester_server()? {
        ensure!(
            server == fixed,
            "Tester server differs from reviewed settings"
        );
    }
    let root = state(game)?;
    let nonce = manifest::hash(
        format!(
            "{}-{}",
            std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
        )
        .as_bytes(),
    );
    // Reset only the non-authoritative status while holding the lifetime lock.
    // A damaged old status must never make us abandon a newly started helper.
    let Some(preflight_lock) = session_lock(&root)? else {
        bail!("Another launcher is already managing this game session");
    };
    ensure!(
        !game_running()?,
        "Close Nebula Realms before starting another session"
    );
    Status::new(&nonce).save(&root)?;
    let mut command = std::process::Command::new(std::env::current_exe()?);
    command
        .arg("supervise-session")
        .arg("--game")
        .arg(game)
        .arg("--server")
        .arg(&server)
        .arg("--nonce")
        .arg(&nonce);
    if allow_provisional {
        command.arg("--allow-provisional");
    }
    drop(preflight_lock);
    let mut supervisor = command
        .creation_flags(0x08000000)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .context("Cannot start automatic game restoration supervisor")?;
    let deadline = std::time::Instant::now() + Duration::from_secs(180);
    let mut status_error = None;
    loop {
        let observed = match read_status(&root, &nonce) {
            Ok(value) => value,
            Err(error) => {
                status_error = Some(format!("{error:#}"));
                None
            }
        };
        if let Some(status) = observed {
            match status.phase {
                Phase::Launched => return status.game_pid.context("Game process ID missing"),
                Phase::Failed => bail!(
                    "{}",
                    status.error.unwrap_or_else(|| {
                        "Game session failed; originals will be checked next time.".into()
                    })
                ),
                Phase::Restored => {
                    bail!("Game exited during startup. Original files were restored.")
                }
                Phase::Starting => {}
            }
        }
        if supervisor.try_wait().context("Cannot check the restoration helper; it may still be running. Do not start another game session yet")?.is_some() {
            // One last read handles an atomic status replacement at process exit.
            if let Ok(Some(status))=read_status(&root,&nonce) {
                if status.phase==Phase::Failed { bail!("{}",status.error.unwrap_or_else(||"Game session failed".into())); }
                if status.phase==Phase::Restored { bail!("Game exited during startup. Original files were restored."); }
            }
            bail!("Game supervisor stopped unexpectedly. Start again to check and restore originals.");
        }
        if std::time::Instant::now() >= deadline {
            bail!("The game helper is taking longer than expected and may still start the game. Helper process {} remains responsible for restoration; do not start another session.{}",supervisor.id(),status_error.map(|e|format!(" Status: {e}")).unwrap_or_default());
        }
        std::thread::sleep(Duration::from_millis(75));
    }
}

#[cfg(windows)]
pub fn supervise(game: &Path, server: &str, nonce: &str, allow_provisional: bool) -> Result<()> {
    manifest::sha(nonce)?;
    // A supplied path is only a locator; the exact supported Steam executable,
    // local release pin, outputs and credential/TLS checks remain authoritative.
    let game = crate::discovery::select(Some(game.to_path_buf()))?;
    crate::discovery::select_executable(&game.join("Nebula Realms.exe"))?;
    let server = crate::launcher::origin(server)?;
    if let Some(fixed) = crate::launcher::fixed_tester_server()? {
        ensure!(
            server == fixed,
            "Tester server differs from reviewed settings"
        );
    }
    let root = state(&game)?;
    let Some(_session_lock) = session_lock(&root)? else {
        bail!("Another launcher is already managing this game session");
    };
    let mut status = Status::new(nonce);
    status.save(&root)?;
    let result = (|| -> Result<()> {
        ensure!(
            !game_running()?,
            "Close Nebula Realms before starting another session"
        );
        restore_idle(&game)?;
        let (bundle, m, pin) = crate::launcher::bundle(allow_provisional)?;
        transaction::patch(
            &game,
            &bundle,
            &m,
            &pin,
            &server,
            "127.0.0.1",
            None,
            false,
            true,
        )?;
        let mut game_child =
            transaction::launch_child_verified(&game, &m, &pin, &server, allow_provisional)?;
        status.phase = Phase::Launched;
        status.game_pid = Some(game_child.id());
        // Even if publishing the launch result fails, own the child until exit.
        let publish = status.save(&root);
        wait_then_restore(&mut game_child, || restore_idle(&game))?;
        publish?;
        status.phase = Phase::Restored;
        status.save(&root)?;
        Ok(())
    })();
    if let Err(error) = result {
        // A failed patch or an early game exit is restored immediately when
        // safe. If a game is still alive, startup recovery will retry later.
        let restore = if game_running()? {
            Ok(false)
        } else {
            restore_idle(&game)
        };
        let mut message = format!("{error:#}");
        if let Err(restore_error) = restore {
            message.push_str(&format!(
                ". Original-file recovery needs attention: {restore_error:#}"
            ));
        }
        status.phase = Phase::Failed;
        status.error = Some(message.chars().take(1000).collect());
        status.save(&root)?;
        bail!("{}", status.error.unwrap());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture(std::path::PathBuf);
    impl Fixture {
        fn new() -> Self {
            static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let root = std::env::temp_dir().join(format!(
                "nebula-session-fixture-{}-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_nanos(),
                NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            ));
            fs::create_dir(&root).unwrap();
            Self(root)
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            assert!(self.0.starts_with(std::env::temp_dir()));
            assert!(self
                .0
                .file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("nebula-session-fixture-"));
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
    #[test]
    fn exclusive_session_lock_survives_independent_file_handles_and_releases_on_drop() {
        let f = Fixture::new();
        let a = session_lock(&f.0).unwrap().unwrap();
        assert!(session_lock(&f.0).unwrap().is_none());
        drop(a);
        assert!(session_lock(&f.0).unwrap().is_some());
    }
    #[test]
    fn stale_status_cannot_report_another_game_as_launched() {
        let f = Fixture::new();
        let old = manifest::hash(b"old");
        let mut s = Status::new(&old);
        s.phase = Phase::Launched;
        s.game_pid = Some(42);
        s.save(&f.0).unwrap();
        assert!(read_status(&f.0, &manifest::hash(b"new"))
            .unwrap()
            .is_none());
        assert_eq!(read_status(&f.0, &old).unwrap().unwrap().game_pid, Some(42));
    }
    #[test]
    fn invalid_incomplete_or_oversized_session_records_are_rejected() {
        let f = Fixture::new();
        let nonce = manifest::hash(b"session");
        let mut s = Status::new(&nonce);
        s.phase = Phase::Launched;
        assert!(s.save(&f.0).is_err());
        s.game_pid = Some(1);
        s.error = Some("x".repeat(4097));
        assert!(s.save(&f.0).is_err());
        fs::write(f.0.join("session.json"), vec![b'x'; 8193]).unwrap();
        assert!(read_status(&f.0, &nonce).is_err());
    }
    // This is the test runner itself, never a game or fake game executable.
    #[test]
    #[ignore = "Owned subprocess fixture; invoked by the lifetime test"]
    fn owned_session_process_fixture() {
        use std::io::Read;
        let path = std::env::var_os("NEBULA_SESSION_PROCESS_FIXTURE")
            .expect("Only invoke through the owning fixture test");
        let root = std::path::PathBuf::from(path);
        assert!(root
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("nebula-session-fixture-"));
        let _lock = session_lock(&root).unwrap().unwrap();
        fs::write(root.join("ready"), b"ready").unwrap();
        let mut byte = [0u8];
        let _ = std::io::stdin().read(&mut byte);
    }
    #[test]
    fn restoration_waits_for_owned_child_and_lock_recovers_after_abrupt_exit() {
        use std::io::Write;
        for abrupt in [false, true] {
            let f = Fixture::new();
            let child = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "session::tests::owned_session_process_fixture",
                    "--ignored",
                    "--nocapture",
                ])
                .env("NEBULA_SESSION_PROCESS_FIXTURE", &f.0)
                .stdin(std::process::Stdio::piped())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()
                .unwrap();
            struct ChildGuard(std::process::Child);
            impl Drop for ChildGuard {
                fn drop(&mut self) {
                    let _ = self.0.kill();
                    let _ = self.0.wait();
                }
            }
            let mut child = ChildGuard(child);
            let deadline = std::time::Instant::now() + Duration::from_secs(10);
            while !f.0.join("ready").exists() {
                assert!(
                    std::time::Instant::now() < deadline,
                    "Owned fixture did not become ready"
                );
                assert!(
                    child.0.try_wait().unwrap().is_none(),
                    "Owned fixture exited too early"
                );
                std::thread::sleep(Duration::from_millis(10));
            }
            assert!(session_lock(&f.0).unwrap().is_none());
            assert!(!f.0.join("restored").exists());
            if abrupt {
                child.0.kill().unwrap();
            } else {
                child.0.stdin.as_mut().unwrap().write_all(b"x").unwrap();
            }
            wait_then_restore(&mut child.0, || {
                assert!(session_lock(&f.0)?.is_some());
                fs::write(f.0.join("restored"), b"originals")?;
                Ok(true)
            })
            .unwrap();
            assert_eq!(fs::read(f.0.join("restored")).unwrap(), b"originals");
        }
    }
}
