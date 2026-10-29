use crate::{
    delta, discovery, endpoint,
    manifest::{self, Manifest},
    unityfs,
};
use anyhow::{bail, ensure, Context, Result};
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::Write,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};
#[derive(Serialize, Deserialize, Clone)]
#[serde(deny_unknown_fields)]
struct Entry {
    path: String,
    before: Option<String>,
    after: String,
    backup: Option<String>,
}
#[derive(Serialize, Deserialize, Clone)]
#[serde(deny_unknown_fields)]
struct Receipt {
    format: String,
    transaction: String,
    manifest: String,
    configuration: String,
    entries: Vec<Entry>,
    previous: Option<Box<Receipt>>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Journal {
    format: String,
    mode: String,
    receipt: Receipt,
    old_receipt: Option<Box<Receipt>>,
}
fn read(path: impl AsRef<Path>) -> Result<Vec<u8>> {
    manifest::read_bounded(path.as_ref(), 256 * 1024 * 1024)
}
pub fn new_file(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut f = OpenOptions::new().create_new(true).write(true).open(path)?;
    f.write_all(bytes)?;
    f.sync_all()?;
    Ok(())
}
fn replace(from: &Path, to: &Path) -> Result<()> {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::Storage::FileSystem::{
            MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
        };
        let src: Vec<u16> = from.as_os_str().encode_wide().chain(Some(0)).collect();
        let dst: Vec<u16> = to.as_os_str().encode_wide().chain(Some(0)).collect();
        ensure!(
            unsafe {
                MoveFileExW(
                    src.as_ptr(),
                    dst.as_ptr(),
                    MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
                )
            } != 0,
            "Atomic replacement failed: {}",
            std::io::Error::last_os_error()
        );
    }
    #[cfg(not(windows))]
    fs::rename(from, to)?;
    Ok(())
}
fn json_write<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let tmp = path.with_extension(format!("json.pending.{}-{nonce}", std::process::id()));
    new_file(&tmp, &serde_json::to_vec_pretty(value)?)?;
    replace(&tmp, path)
}
fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> Result<T> {
    let b = manifest::read_bounded(path, 4 * 1024 * 1024)?;
    ensure!(b.len() <= 4 * 1024 * 1024, "State too large");
    Ok(serde_json::from_slice(&b)?)
}
fn hash_at(path: &Path) -> Result<Option<String>> {
    if !path.exists() {
        return Ok(None);
    }
    manifest::reject_link(path)?;
    ensure!(path.is_file(), "Expected regular file");
    Ok(Some(manifest::hash(&read(path)?)))
}
fn lock(game: &Path) -> Result<File> {
    discovery::stopped()?;
    manifest::reject_link(game)?;
    let lock = manifest::safe(game, ".nebula-preservation.lock")?;
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(lock)?;
    file.try_lock_exclusive()
        .context("Another patcher owns the game lock")?;
    Ok(file)
}
fn state(game: &Path) -> Result<std::path::PathBuf> {
    let p = manifest::safe(game, ".nebula-preservation")?;
    if !p.exists() {
        fs::create_dir(&p)?
    }
    manifest::reject_link(&p)?;
    Ok(p)
}
fn check_exe(game: &Path) -> Result<()> {
    ensure!(
        hash_at(&manifest::safe(game, "Nebula Realms.exe")?)?.as_deref() == Some(manifest::EXE),
        "Steam executable differs from supported build; Steam licensing is not patched"
    );
    Ok(())
}
fn validate_receipt(r: &Receipt) -> Result<()> {
    ensure!(
        r.format == "nebula-receipt-v1" && r.entries.len() <= 16 && !r.entries.is_empty(),
        "Unsupported receipt"
    );
    manifest::sha(&r.manifest)?;
    manifest::sha(&r.configuration)?;
    ensure!(
        r.transaction
            .bytes()
            .all(|b| b.is_ascii_digit() || b == b'-')
            && !r.transaction.is_empty(),
        "Invalid transaction id"
    );
    let mut seen = std::collections::HashSet::new();
    for e in &r.entries {
        manifest::relative(&e.path)?;
        ensure!(seen.insert(&e.path), "Duplicate receipt target");
        ensure!(
            manifest::ORIGINALS.iter().any(|(p, _)| *p == e.path)
                || [
                    "NebulaRegistryBridge.dll",
                    "NebulaAutomation.dll",
                    "NebulaNetworkBridge.dll",
                    "NebulaPublicAccess.dll",
                    "NebulaRemoteTransport.exe",
                    "steam_appid.txt"
                ]
                .contains(&e.path.as_str()),
            "Unapproved receipt target"
        );
        manifest::sha(&e.after)?;
        if let Some(h) = &e.before {
            manifest::sha(h)?;
            let expected = format!("backups/{}/{}", r.transaction, e.path);
            ensure!(
                e.backup.as_deref() == Some(expected.as_str()),
                "Backup path mismatch"
            );
        } else {
            ensure!(e.backup.is_none(), "Unexpected backup for absent file")
        }
    }
    Ok(())
}
// A receipt is a local history record, never an authority for pristine hashes.
// Verify the complete bounded history before using any of its backups as input.
fn verified_backup_chain(
    game: &Path,
    root: &Path,
    active: &Receipt,
    required: &BTreeMap<String, String>,
) -> Result<BTreeMap<String, Vec<u8>>> {
    for path in required.keys() {
        ensure!(
            active.entries.iter().any(|entry| &entry.path == path),
            "Active receipt is missing required source binding: {}",
            path
        );
    }
    let mut expected: BTreeMap<String, Option<String>> = BTreeMap::new();
    let mut transactions = BTreeSet::new();
    let mut sources = BTreeMap::new();
    let mut generation = Some(active);
    for _ in 0..64 {
        let Some(receipt) = generation else { break };
        validate_receipt(receipt)?;
        ensure!(
            transactions.insert(&receipt.transaction),
            "Duplicate receipt transaction"
        );
        for entry in &receipt.entries {
            if let Some(previous_before) = expected.get(&entry.path) {
                ensure!(
                    previous_before.as_deref() == Some(entry.after.as_str()),
                    "Receipt history discontinuity for {}; use explicit --originals",
                    entry.path
                );
            } else {
                ensure!(
                    hash_at(&manifest::safe(game, &entry.path)?)?.as_deref()
                        == Some(entry.after.as_str()),
                    "Installed file changed since receipt: {}",
                    entry.path
                );
            }
            expected.insert(entry.path.clone(), entry.before.clone());
            if let Some(before) = &entry.before {
                let backup = manifest::safe(root, entry.backup.as_ref().unwrap())?;
                let bytes = read(backup)?;
                ensure!(
                    manifest::hash(&bytes) == *before,
                    "Historical backup pin mismatch for {}",
                    entry.path
                );
                if required.get(&entry.path) == Some(before) {
                    sources.entry(entry.path.clone()).or_insert(bytes);
                }
            }
        }
        generation = receipt.previous.as_deref();
    }
    ensure!(
        generation.is_none(),
        "Receipt history exceeds 64 transactions; use explicit --originals"
    );
    ensure!(required.keys().all(|path| sources.contains_key(path)),
        "Receipt history has no verified pristine backup; provide --originals pointing to the exact pristine build");
    Ok(sources)
}
fn backup_originals(
    game: &Path,
    root: &Path,
    active: &Receipt,
    m: &Manifest,
) -> Result<BTreeMap<String, Vec<u8>>> {
    let mut required = BTreeMap::new();
    for artifact in &m.artifacts {
        if let Some(original) = &artifact.original_sha256 {
            ensure!(
                manifest::ORIGINALS
                    .iter()
                    .any(|(path, hash)| *path == artifact.path && *hash == original),
                "Backup source is not an authoritative supported original: {}",
                artifact.path
            );
            if hash_at(&manifest::safe(game, &artifact.path)?)?.as_ref() != Some(original) {
                required.insert(artifact.path.clone(), original.clone());
            }
        }
    }
    verified_backup_chain(game, root, active, &required)
}
// Crossing the optional/network-only boundary requires restoring first. Never
// silently leave an old InputManager, character editor or automation patch.
fn profile_transition(
    game: &Path,
    active: Option<&Receipt>,
    m: &Manifest,
    remote_transport: bool,
) -> Result<()> {
    let network = manifest::network_only(m);
    if network {
        let has_remote = m
            .artifacts
            .iter()
            .any(|a| a.path == "NebulaRemoteTransport.exe");
        ensure!(has_remote == remote_transport,
            "network-only remote profile requires its seventh transport artifact and --remote-transport together");
        if let Some(r) = active {
            ensure!(manifest::NETWORK_PATHS.iter().all(|p| r.entries.iter().any(|e| e.path == *p)) &&
                r.entries.iter().all(|e| manifest::NETWORK_PATHS.contains(&e.path.as_str()) ||
                    (has_remote && e.path == "NebulaRemoteTransport.exe")),
                "Restore the previous client profile with restore before installing network-only; repeat restore until no active receipt remains");
        }
        for (path, original) in manifest::ORIGINALS.iter().skip(2) {
            ensure!(hash_at(&manifest::safe(game, path)?)?.as_deref() == Some(*original),
                "network-only requires pristine optional input/editor files; restore the previous profile or verify files in Steam before installing");
        }
        ensure!(hash_at(&manifest::safe(game, "NebulaAutomation.dll")?)?.is_none(),
            "network-only cannot retain NebulaAutomation.dll; restore the previous client profile first");
        if !has_remote {
            ensure!(hash_at(&manifest::safe(game, "NebulaRemoteTransport.exe")?)?.is_none(),
                "Restore the remote profile before installing the six-artifact direct network-only profile");
        }
    } else {
        ensure!(
            hash_at(&manifest::safe(game, "NebulaNetworkBridge.dll")?)?.is_none()
                && !active.is_some_and(|r| r
                    .entries
                    .iter()
                    .any(|e| e.path == "NebulaNetworkBridge.dll")),
            "Restore the network-only profile before installing an optional client profile"
        );
    }
    Ok(())
}
#[allow(clippy::too_many_arguments)]
pub fn patch(
    game: &Path,
    bundle: &Path,
    m: &Manifest,
    pin: &str,
    server: &str,
    advertise: &str,
    originals: Option<&Path>,
    dry_run: bool,
    remote_transport: bool,
) -> Result<()> {
    let _lock = if dry_run {
        discovery::stopped()?;
        None
    } else {
        Some(lock(game)?)
    };
    check_exe(game)?;
    let state_path = manifest::safe(game, ".nebula-preservation")?;
    let active = if state_path.exists() {
        manifest::reject_link(&state_path)?;
        ensure!(
            !manifest::safe(&state_path, "journal.json")?.exists(),
            "Unfinished transaction: run recover"
        );
        let p = manifest::safe(&state_path, "receipt.json")?;
        if p.exists() {
            let r: Receipt = read_json(&p)?;
            validate_receipt(&r)?;
            Some(r)
        } else {
            None
        }
    } else {
        None
    };
    profile_transition(game, active.as_ref(), m, remote_transport)?;
    if remote_transport {
        ensure!(
            server.starts_with("https://") && advertise == "127.0.0.1",
            "Remote transport requires HTTPS server and explicit --advertise-ip 127.0.0.1"
        );
        ensure!(
            m.artifacts
                .iter()
                .any(|a| a.path == "NebulaRemoteTransport.exe"),
            "Bundle has no remote transport sidecar"
        );
        crate::remote::check(server)?;
    }
    let configuration = manifest::hash(
        format!("metadata-v1\n{server}\n{advertise}\nremote={remote_transport}\n").as_bytes(),
    );
    if server.starts_with("https://") {
        ensure!(
            m.artifacts
                .iter()
                .any(|a| a.path == "NebulaPublicAccess.dll"),
            "HTTPS requires public-access helper"
        );
        endpoint::check_public_config(server)?;
    }
    if let Some(r) = &active {
        if r.manifest == pin && r.configuration == configuration {
            for e in &r.entries {
                ensure!(
                    hash_at(&manifest::safe(game, &e.path)?)?.as_deref() == Some(&e.after),
                    "Installed file changed since receipt"
                );
            }
            println!("Already installed; all receipt hashes verified.");
            return Ok(());
        }
    }
    let mut needs_backup = false;
    if originals.is_none() {
        for artifact in &m.artifacts {
            if let Some(original) = &artifact.original_sha256 {
                if hash_at(&manifest::safe(game, &artifact.path)?)?.as_ref() != Some(original) {
                    needs_backup = true;
                }
            }
        }
    }
    let mut backup_sources = if needs_backup {
        backup_originals(
            game,
            &state_path,
            active.as_ref().context(
                "Patched source has no receipt-bound pristine backup; provide --originals",
            )?,
            m,
        )?
    } else {
        BTreeMap::new()
    };
    let mut outputs = Vec::new();
    for a in &m.artifacts {
        let path = manifest::safe(game, &a.path)?;
        let before = hash_at(&path)?;
        let receipted = active
            .as_ref()
            .and_then(|r| r.entries.iter().find(|e| e.path == a.path))
            .is_some_and(|e| before.as_deref() == Some(e.after.as_str()));
        let allowed = before.as_ref().is_some_and(|h| {
            a.original_sha256.as_ref() == Some(h)
                || a.accepted_existing.contains(h)
                || a.output_sha256.as_ref() == Some(h)
        }) || receipted;
        ensure!(
            allowed || (before.is_none() && a.original_sha256.is_none()),
            "Unrecognized installed state for {}; no files changed",
            a.path
        );
        let source = if let Some(original) = &a.original_sha256 {
            let bytes = if before.as_ref() == Some(original) {
                read(&path)?
            } else if let Some(dir) = originals {
                read(manifest::safe(dir, &a.path)?)?
            } else {
                backup_sources
                    .remove(&a.path)
                    .context("No verified pristine transaction backup; provide --originals")?
            };
            ensure!(
                manifest::hash(&bytes) == *original,
                "Pristine original mismatch for {}",
                a.path
            );
            bytes
        } else {
            Vec::new()
        };
        let bytes = match a.operation.as_str() {
            "metadata" => endpoint::patch(
                &source,
                if remote_transport {
                    crate::remote::LOCAL_API
                } else {
                    server
                },
                advertise,
            )?,
            "delta" | "unityfs_delta" | "owned_file" => {
                let payload = read(manifest::safe(bundle, a.payload.as_ref().unwrap())?)?;
                ensure!(
                    payload.len() as u64 == a.payload_size.unwrap()
                        && manifest::hash(&payload) == *a.payload_sha256.as_ref().unwrap(),
                    "Payload pin mismatch"
                );
                if a.operation == "owned_file" {
                    payload
                } else {
                    let view = if a.operation == "unityfs_delta" {
                        unityfs::canonicalize(&source)?
                    } else {
                        source
                    };
                    ensure!(
                        a.source_view_sha256.as_deref() == Some(&manifest::hash(&view)),
                        "Source view pin mismatch"
                    );
                    delta::apply(&view, &payload)?
                }
            }
            _ => bail!("Unsupported operation"),
        };
        let after = manifest::hash(&bytes);
        if a.operation != "metadata" {
            ensure!(
                a.output_sha256.as_deref() == Some(&after),
                "Output pin mismatch for {}",
                a.path
            )
        }
        if a.path == "steam_appid.txt" {
            ensure!(bytes == b"919290", "Steam app-id payload differs")
        }
        outputs.push((a.path.clone(), before, after, bytes));
    }
    // Place loader dependencies before the importing binary. Restore reverses
    // this sequence, returning the previous GA before removing newer helpers.
    outputs.sort_by_key(|(path, _, _, _)| match path.as_str() {
        "steam_appid.txt" => 0,
        "NebulaRegistryBridge.dll" => 1,
        "NebulaAutomation.dll" => 2,
        "NebulaNetworkBridge.dll" => 2,
        "NebulaPublicAccess.dll" => 4,
        "NebulaRemoteTransport.exe" => 3,
        "GameAssembly.dll" => 6,
        _ => 5,
    });
    println!(
        "Verified {} staged outputs; no game is launched.",
        outputs.len()
    );
    if dry_run {
        println!("Dry run: no game files, backup state or receipt written.");
        return Ok(());
    }
    let root = state(game)?;
    let id = format!(
        "{}-{}",
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos(),
        std::process::id()
    );
    let stage = manifest::safe(&root, &format!("staging/{id}"))?;
    fs::create_dir_all(&stage)?;
    manifest::reject_link(&stage)?;
    let mut entries = Vec::new();
    for (i, (path, before, after, bytes)) in outputs.iter().enumerate() {
        let staged = stage.join(i.to_string());
        new_file(&staged, bytes)?;
        ensure!(
            hash_at(&staged)?.as_deref() == Some(after),
            "Stage read-back verification failed"
        );
        let backup = if let Some(h) = before {
            let rel = format!("backups/{id}/{path}");
            let dst = manifest::safe(&root, &rel)?;
            fs::create_dir_all(dst.parent().unwrap())?;
            let current = read(manifest::safe(game, path)?)?;
            ensure!(
                manifest::hash(&current) == *h,
                "Target changed during staging"
            );
            new_file(&dst, &current)?;
            ensure!(
                hash_at(&dst)?.as_deref() == Some(h),
                "Backup read-back failed"
            );
            Some(rel)
        } else {
            None
        };
        entries.push(Entry {
            path: path.clone(),
            before: before.clone(),
            after: after.clone(),
            backup,
        });
    }
    discovery::stopped()?;
    for e in &entries {
        ensure!(
            hash_at(&manifest::safe(game, &e.path)?)? == e.before,
            "Target changed before commit"
        )
    }
    let receipt = Receipt {
        format: "nebula-receipt-v1".into(),
        transaction: id,
        manifest: pin.into(),
        configuration,
        entries,
        previous: active.clone().map(Box::new),
    };
    let journal = Journal {
        format: "nebula-journal-v1".into(),
        mode: "patch".into(),
        receipt: receipt.clone(),
        old_receipt: active.map(Box::new),
    };
    let jp = manifest::safe(&root, "journal.json")?;
    json_write(&jp, &journal)?;
    let result = (|| -> Result<()> {
        for (i, e) in receipt.entries.iter().enumerate() {
            replace(&stage.join(i.to_string()), &manifest::safe(game, &e.path)?)?;
            ensure!(
                hash_at(&manifest::safe(game, &e.path)?)?.as_deref() == Some(&e.after),
                "Installed read-back mismatch"
            )
        }
        json_write(&manifest::safe(&root, "receipt.json")?, &receipt)?;
        Ok(())
    })();
    if let Err(error) = result {
        match rollback(game,&root,&journal){Ok(())=>{fs::remove_file(&jp)?;return Err(error.context("Installation failed and was rolled back"))},Err(rollback_error)=>bail!("Installation failed ({error:#}); rollback incomplete ({rollback_error:#}). Run recover; keep backups.")}
    }
    fs::remove_file(jp)?;
    println!("Installed verified files; receipt and backups saved. Runtime acceptance remains a separate step.");
    Ok(())
}
fn rollback(game: &Path, root: &Path, j: &Journal) -> Result<()> {
    validate_receipt(&j.receipt)?;
    for e in j.receipt.entries.iter().rev() {
        let dst = manifest::safe(game, &e.path)?;
        let actual = hash_at(&dst)?;
        if actual == e.before {
            continue;
        }
        ensure!(
            actual.as_deref() == Some(&e.after),
            "Recovery refuses unexpected changed target {}",
            e.path
        );
        if let Some(expected) = &e.before {
            let backup = manifest::safe(root, e.backup.as_ref().unwrap())?;
            ensure!(
                hash_at(&backup)?.as_deref() == Some(expected),
                "Backup pin mismatch"
            );
            let tmp = dst.with_extension("nebula-rollback");
            if tmp.exists() {
                ensure!(
                    hash_at(&tmp)?.as_deref() == Some(expected),
                    "Unexpected rollback scratch contents"
                );
            } else {
                new_file(&tmp, &read(backup)?)?;
            }
            replace(&tmp, &dst)?;
            ensure!(
                hash_at(&dst)?.as_deref() == Some(expected),
                "Rolled back hash mismatch"
            );
        } else {
            fs::remove_file(dst)?;
        }
    }
    let rp = manifest::safe(root, "receipt.json")?;
    if let Some(old) = &j.old_receipt {
        json_write(&rp, old)?
    } else if rp.exists() {
        fs::remove_file(rp)?
    }
    Ok(())
}
#[cfg(any(windows, test))]
fn verify_release_outputs(game: &Path, m: &Manifest, metadata_hash: &str) -> Result<()> {
    for artifact in &m.artifacts {
        let expected = if artifact.operation == "metadata" {
            metadata_hash
        } else {
            artifact
                .output_sha256
                .as_deref()
                .context("Missing output pin")?
        };
        ensure!(
            hash_at(&manifest::safe(game, &artifact.path)?)?.as_deref() == Some(expected),
            "Installed bytes differ from release recipe: {}",
            artifact.path
        );
    }
    Ok(())
}
#[cfg(test)]
mod launch_output_tests {
    use super::*;
    #[test]
    fn launch_checks_release_pins_even_if_a_receipt_could_be_forged() {
        let root = std::env::temp_dir().join(format!(
            "nebula-launch-pins-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&root).unwrap();
        let path = root.join("NebulaNetworkBridge.dll");
        let m = Manifest {
            format: "nebula-patch-v1".into(),
            app_id: manifest::APP.into(),
            build_id: manifest::BUILD.into(),
            status: "frozen".into(),
            review: "nonexecuting fixture".into(),
            profile: Some("network-only".into()),
            artifacts: vec![manifest::Artifact {
                path: "NebulaNetworkBridge.dll".into(),
                operation: "owned_file".into(),
                original_sha256: None,
                accepted_existing: vec![],
                payload: None,
                payload_sha256: None,
                payload_size: None,
                source_view_sha256: None,
                output_sha256: Some(manifest::hash(b"reviewed-output")),
            }],
        };
        fs::write(&path, b"reviewed-output").unwrap();
        assert!(verify_release_outputs(&root, &m, "").is_ok());
        fs::write(&path, b"counterfeit-receipt-output").unwrap();
        assert!(verify_release_outputs(&root, &m, "").is_err());
        fs::remove_file(&path).unwrap();
        assert!(verify_release_outputs(&root, &m, "").is_err());
        fs::remove_dir(root).unwrap();
    }
}
/// Launch gate binds installed bytes to the reviewed manifest, not just a mutable receipt.
#[cfg(windows)]
pub fn launch_verified(
    game: &Path,
    m: &Manifest,
    pin: &str,
    server: &str,
    allow_provisional: bool,
) -> Result<u32> {
    let _lock = lock(game)?;
    check_exe(game)?;
    ensure!(
        crate::launcher::release_status_allowed(&m.status, allow_provisional)
            && manifest::network_only(m),
        "Launcher requires a frozen network-only bundle"
    );
    let root = manifest::safe(game, ".nebula-preservation")?;
    ensure!(
        !manifest::safe(&root, "journal.json")?.exists(),
        "Interrupted transaction; run recover before launch"
    );
    let receipt: Receipt = read_json(&manifest::safe(&root, "receipt.json")?)?;
    validate_receipt(&receipt)?;
    let configuration =
        manifest::hash(format!("metadata-v1\n{server}\n127.0.0.1\nremote=true\n").as_bytes());
    ensure!(
        receipt.manifest == pin && receipt.configuration == configuration,
        "Installed receipt belongs to another bundle or server"
    );
    ensure!(
        receipt.entries.len() == m.artifacts.len()
            && m.artifacts
                .iter()
                .all(|a| receipt.entries.iter().any(|e| e.path == a.path)),
        "Receipt artifact set differs from reviewed manifest"
    );
    profile_transition(game, Some(&receipt), m, true)?;
    crate::remote::check(server)?;
    let metadata = m
        .artifacts
        .iter()
        .find(|a| a.operation == "metadata")
        .context("Missing metadata artifact")?;
    let required = BTreeMap::from([(
        metadata.path.clone(),
        metadata
            .original_sha256
            .clone()
            .context("Missing metadata original pin")?,
    )]);
    let originals = verified_backup_chain(game, &root, &receipt, &required)?;
    let metadata_hash = manifest::hash(&endpoint::patch(
        &originals[&metadata.path],
        crate::remote::LOCAL_API,
        "127.0.0.1",
    )?);
    verify_release_outputs(game, m, &metadata_hash)?;
    let mut child = std::process::Command::new(manifest::safe(game, "Nebula Realms.exe")?)
        .current_dir(game)
        .spawn()
        .context("Launch verified Steam executable")?;
    std::thread::sleep(std::time::Duration::from_millis(1800));
    ensure!(
        child.try_wait()?.is_none(),
        "Game exited during startup; inspect the game log and Steam session"
    );
    Ok(child.id())
}
pub fn recover(game: &Path) -> Result<()> {
    let _lock = lock(game)?;
    check_exe(game)?;
    let root = state(game)?;
    let jp = manifest::safe(&root, "journal.json")?;
    let j: Journal = read_json(&jp)?;
    ensure!(
        j.format == "nebula-journal-v1" && ["patch", "restore"].contains(&j.mode.as_str()),
        "Unsupported journal"
    );
    if j.mode == "restore" {
        finish_restore(game, &root, &j)?;
    } else {
        rollback(game, &root, &j)?;
    }
    fs::remove_file(jp)?;
    println!("Recovery completed and hashes verified.");
    Ok(())
}
fn finish_restore(game: &Path, root: &Path, j: &Journal) -> Result<()> {
    validate_receipt(&j.receipt)?;
    for e in j.receipt.entries.iter().rev() {
        let dst = manifest::safe(game, &e.path)?;
        let current = hash_at(&dst)?;
        if current == e.before {
            continue;
        }
        ensure!(
            current.as_deref() == Some(&e.after),
            "Restore refuses modified target {}",
            e.path
        );
        if let Some(before) = &e.before {
            let backup = manifest::safe(root, e.backup.as_ref().unwrap())?;
            ensure!(
                hash_at(&backup)?.as_deref() == Some(before),
                "Backup mismatch"
            );
            let tmp = dst.with_extension("nebula-restore");
            if tmp.exists() {
                ensure!(
                    hash_at(&tmp)?.as_deref() == Some(before),
                    "Unexpected restore scratch contents"
                );
            } else {
                new_file(&tmp, &read(backup)?)?;
            }
            replace(&tmp, &dst)?;
            ensure!(
                hash_at(&dst)?.as_deref() == Some(before),
                "Restored hash mismatch"
            );
        } else {
            fs::remove_file(dst)?;
        }
    }
    let rp = manifest::safe(root, "receipt.json")?;
    if let Some(previous) = &j.receipt.previous {
        json_write(&rp, previous)?
    } else if rp.exists() {
        fs::remove_file(rp)?
    }
    Ok(())
}
pub fn restore(game: &Path) -> Result<()> {
    let _lock = lock(game)?;
    check_exe(game)?;
    let root = state(game)?;
    let jp = manifest::safe(&root, "journal.json")?;
    ensure!(!jp.exists(), "Unfinished transaction: run recover");
    let receipt: Receipt = read_json(&manifest::safe(&root, "receipt.json")?)?;
    validate_receipt(&receipt)?;
    for e in &receipt.entries {
        ensure!(
            hash_at(&manifest::safe(game, &e.path)?)?.as_deref() == Some(&e.after),
            "Target modified since patch; restore refuses to overwrite"
        );
        if let Some(h) = &e.before {
            ensure!(
                hash_at(&manifest::safe(&root, e.backup.as_ref().unwrap())?)?.as_deref() == Some(h),
                "Backup mismatch"
            );
        }
    }
    let j = Journal {
        format: "nebula-journal-v1".into(),
        mode: "restore".into(),
        receipt,
        old_receipt: None,
    };
    json_write(&jp, &j)?;
    finish_restore(game, &root, &j)?;
    fs::remove_file(jp)?;
    println!("Restored previous verified state. Backups retained.");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture {
        game: std::path::PathBuf,
        root: std::path::PathBuf,
        journal: Journal,
    }
    impl Fixture {
        fn new() -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let game = std::env::temp_dir().join(format!(
                "nebula-transaction-fixture-{}-{nonce}",
                std::process::id()
            ));
            fs::create_dir(&game).unwrap();
            let root = game.join(".nebula-preservation");
            fs::create_dir_all(root.join("backups/1")).unwrap();
            fs::write(game.join("GameAssembly.dll"), b"after").unwrap();
            fs::write(root.join("backups/1/GameAssembly.dll"), b"manual-before").unwrap();
            fs::write(game.join("NebulaAutomation.dll"), b"helper-after").unwrap();
            let entries = vec![
                Entry {
                    path: "NebulaAutomation.dll".into(),
                    before: None,
                    after: manifest::hash(b"helper-after"),
                    backup: None,
                },
                Entry {
                    path: "GameAssembly.dll".into(),
                    before: Some(manifest::hash(b"manual-before")),
                    after: manifest::hash(b"after"),
                    backup: Some("backups/1/GameAssembly.dll".into()),
                },
            ];
            let receipt = Receipt {
                format: "nebula-receipt-v1".into(),
                transaction: "1".into(),
                manifest: manifest::hash(b"manifest"),
                configuration: manifest::hash(b"configuration"),
                entries,
                previous: None,
            };
            Self {
                game,
                root,
                journal: Journal {
                    format: "nebula-journal-v1".into(),
                    mode: "patch".into(),
                    receipt,
                    old_receipt: None,
                },
            }
        }
        fn before(&self) {
            assert_eq!(
                fs::read(self.game.join("GameAssembly.dll")).unwrap(),
                b"manual-before"
            );
            assert!(!self.game.join("NebulaAutomation.dll").exists());
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.game).unwrap();
        }
    }
    #[test]
    fn rollback_restores_exact_manual_state_and_is_idempotent() {
        let f = Fixture::new();
        rollback(&f.game, &f.root, &f.journal).unwrap();
        f.before();
        rollback(&f.game, &f.root, &f.journal).unwrap();
        f.before();
    }
    #[test]
    fn restore_resumes_only_hash_matching_scratch_and_repeats_safely() {
        let f = Fixture::new();
        let scratch = f.game.join("GameAssembly.nebula-restore");
        fs::write(&scratch, b"unknown").unwrap();
        assert!(finish_restore(&f.game, &f.root, &f.journal).is_err());
        assert_eq!(fs::read(f.game.join("GameAssembly.dll")).unwrap(), b"after");
        fs::write(&scratch, b"manual-before").unwrap();
        finish_restore(&f.game, &f.root, &f.journal).unwrap();
        f.before();
        finish_restore(&f.game, &f.root, &f.journal).unwrap();
        f.before();
        assert!(!scratch.exists());
    }
    #[test]
    fn rollback_refuses_changed_target_and_tampered_backup() {
        let f = Fixture::new();
        fs::write(f.game.join("GameAssembly.dll"), b"user-changed").unwrap();
        assert!(rollback(&f.game, &f.root, &f.journal).is_err());
        assert_eq!(
            fs::read(f.game.join("GameAssembly.dll")).unwrap(),
            b"user-changed"
        );
        fs::write(f.game.join("GameAssembly.dll"), b"after").unwrap();
        fs::write(f.root.join("backups/1/GameAssembly.dll"), b"tampered").unwrap();
        assert!(rollback(&f.game, &f.root, &f.journal).is_err());
        assert_eq!(fs::read(f.game.join("GameAssembly.dll")).unwrap(), b"after");
    }
    #[test]
    fn rollback_loader_target_precedes_dependency_removal() {
        let mut f = Fixture::new();
        f.journal.receipt.entries[0].after = manifest::hash(b"wrong-helper");
        assert!(rollback(&f.game, &f.root, &f.journal).is_err());
        assert_eq!(
            fs::read(f.game.join("GameAssembly.dll")).unwrap(),
            b"manual-before"
        );
        assert_eq!(
            fs::read(f.game.join("NebulaAutomation.dll")).unwrap(),
            b"helper-after"
        );
    }
}

#[cfg(test)]
mod backup_tests {
    use super::*;
    static NEXT_HISTORY: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    struct History {
        game: std::path::PathBuf,
        root: std::path::PathBuf,
        receipt: Receipt,
    }
    impl History {
        fn new() -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let game = std::env::temp_dir().join(format!(
                "nebula-backup-fixture-{}-{nonce}-{}",
                std::process::id(),
                NEXT_HISTORY.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            ));
            fs::create_dir(&game).unwrap();
            let root = game.join(".nebula-preservation");
            let mut history = Self {
                game,
                root,
                receipt: Receipt {
                    format: "nebula-receipt-v1".into(),
                    transaction: "0".into(),
                    manifest: manifest::hash(b"bundle"),
                    configuration: manifest::hash(b"config"),
                    entries: Vec::new(),
                    previous: None,
                },
            };
            fs::write(history.game.join("GameAssembly.dll"), b"pristine").unwrap();
            history.install("1", b"profile-one");
            history
        }
        fn install(&mut self, id: &str, bytes: &[u8]) {
            let current = fs::read(self.game.join("GameAssembly.dll")).unwrap();
            let backup = format!("backups/{id}/GameAssembly.dll");
            let path = self.root.join(&backup);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, &current).unwrap();
            let previous = if self.receipt.entries.is_empty() {
                None
            } else {
                Some(Box::new(self.receipt.clone()))
            };
            self.receipt = Receipt {
                format: "nebula-receipt-v1".into(),
                transaction: id.into(),
                manifest: manifest::hash(bytes),
                configuration: manifest::hash(id.as_bytes()),
                entries: vec![Entry {
                    path: "GameAssembly.dll".into(),
                    before: Some(manifest::hash(&current)),
                    after: manifest::hash(bytes),
                    backup: Some(backup),
                }],
                previous,
            };
            fs::write(self.game.join("GameAssembly.dll"), bytes).unwrap();
        }
        fn sources(&self) -> Result<BTreeMap<String, Vec<u8>>> {
            verified_backup_chain(
                &self.game,
                &self.root,
                &self.receipt,
                &BTreeMap::from([("GameAssembly.dll".into(), manifest::hash(b"pristine"))]),
            )
        }
    }
    impl Drop for History {
        fn drop(&mut self) {
            assert!(self.game.starts_with(std::env::temp_dir()));
            assert!(self
                .game
                .file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("nebula-backup-fixture-"));
            fs::remove_dir_all(&self.game).unwrap();
        }
    }
    #[test]
    fn backup_history_follows_three_generations_and_one_step_restores() {
        let mut h = History::new();
        h.install("2", b"repointed");
        h.install("3", b"profile-two");
        assert_eq!(h.sources().unwrap()["GameAssembly.dll"], b"pristine");
        for expected in [
            b"repointed".as_slice(),
            b"profile-one".as_slice(),
            b"pristine".as_slice(),
        ] {
            let journal = Journal {
                format: "nebula-journal-v1".into(),
                mode: "restore".into(),
                receipt: h.receipt.clone(),
                old_receipt: None,
            };
            finish_restore(&h.game, &h.root, &journal).unwrap();
            assert_eq!(fs::read(h.game.join("GameAssembly.dll")).unwrap(), expected);
            if let Some(previous) = h.receipt.previous.take() {
                h.receipt = *previous;
            }
        }
        assert!(!h.root.join("receipt.json").exists());
    }
    #[test]
    fn backup_history_refuses_modified_current_or_historical_backup() {
        for case in 0..4 {
            let mut h = History::new();
            h.install("2", b"second");
            match case {
                0 => fs::write(h.game.join("GameAssembly.dll"), b"edited").unwrap(),
                1 => fs::remove_file(h.game.join("GameAssembly.dll")).unwrap(),
                2 => fs::write(h.root.join("backups/1/GameAssembly.dll"), b"tampered").unwrap(),
                _ => fs::remove_file(h.root.join("backups/1/GameAssembly.dll")).unwrap(),
            }
            assert!(h.sources().is_err(), "case {case}");
        }
    }
    #[test]
    fn backup_history_rejects_discontinuous_stale_and_redirected_receipts() {
        for case in 0..3 {
            let mut h = History::new();
            h.install("2", b"second");
            match case {
                0 => {
                    // Even a hash-matching forged intermediate backup cannot break lineage.
                    h.receipt.entries[0].before = Some(manifest::hash(b"unreceipted"));
                    fs::write(h.root.join("backups/2/GameAssembly.dll"), b"unreceipted").unwrap();
                }
                1 => h.receipt.entries[0].after = manifest::hash(b"stale"),
                _ => h.receipt.entries[0].backup = Some("backups/1/GameAssembly.dll".into()),
            }
            assert!(h.sources().is_err(), "case {case}");
        }
    }
    #[test]
    fn backup_history_requires_the_requested_pristine_hash() {
        let h = History::new();
        let wanted =
            BTreeMap::from([("GameAssembly.dll".into(), manifest::hash(b"another-build"))]);
        assert!(verified_backup_chain(&h.game, &h.root, &h.receipt, &wanted).is_err());
    }
    #[test]
    fn backup_history_requires_a_current_receipt_binding() {
        let mut h = History::new();
        let previous = h.receipt.clone();
        fs::write(h.game.join("NebulaAutomation.dll"), b"helper").unwrap();
        h.receipt = Receipt {
            format: "nebula-receipt-v1".into(),
            transaction: "2".into(),
            manifest: manifest::hash(b"next"),
            configuration: manifest::hash(b"next"),
            entries: vec![Entry {
                path: "NebulaAutomation.dll".into(),
                before: None,
                after: manifest::hash(b"helper"),
                backup: None,
            }],
            previous: Some(Box::new(previous)),
        };
        assert!(h
            .sources()
            .unwrap_err()
            .to_string()
            .contains("Active receipt is missing required source binding"));
    }
    #[test]
    fn receipt_cannot_authorize_a_counterfeit_original() {
        let h = History::new();
        let m = Manifest {
            format: "nebula-patch-v1".into(),
            app_id: manifest::APP.into(),
            build_id: manifest::BUILD.into(),
            status: "provisional".into(),
            review: "fixture".into(),
            profile: None,
            artifacts: vec![manifest::Artifact {
                path: "GameAssembly.dll".into(),
                operation: "delta".into(),
                original_sha256: Some(manifest::hash(b"pristine")),
                accepted_existing: Vec::new(),
                payload: None,
                payload_sha256: None,
                payload_size: None,
                source_view_sha256: None,
                output_sha256: None,
            }],
        };
        assert!(backup_originals(&h.game, &h.root, &h.receipt, &m)
            .unwrap_err()
            .to_string()
            .contains("authoritative"));
    }
    #[test]
    fn backup_history_is_bounded_and_rejects_reused_transaction_ids() {
        let mut h = History::new();
        h.install("2", b"second");
        h.receipt.previous.as_mut().unwrap().transaction = "2".into();
        assert!(h.sources().is_err());
        let mut h = History::new();
        for id in 2..=65 {
            h.install(&id.to_string(), b"same-profile");
        }
        assert!(h
            .sources()
            .unwrap_err()
            .to_string()
            .contains("64 transactions"));
    }
}
