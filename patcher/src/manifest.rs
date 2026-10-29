use anyhow::{bail, ensure, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    path::{Component, Path, PathBuf},
};
pub const APP: &str = "919290";
pub const BUILD: &str = "11018722";
pub const EXE: &str = "77bdecc37804194305c2402be5ac0851570f395bf9af3fb4ee03030c6d779d0d";
pub const ORIGINALS: [(&str, &str); 4] = [
    (
        "GameAssembly.dll",
        "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac",
    ),
    (
        "Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat",
        "c59807c2950c1051202ae7d96744d126be4c489c7719f7e2d8d207f8f75681c1",
    ),
    (
        "Nebula Realms_Data/globalgamemanagers",
        "ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466",
    ),
    (
        "Nebula Realms_Data/StreamingAssets/StandaloneWindows/s/charactereditor",
        "5d1713e79b4e5bab090a3d57eb4d4c4139999629bb4a2038412a6cb92d1b02e0",
    ),
];
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub app_id: String,
    pub build_id: String,
    pub status: String,
    pub review: String,
    #[serde(
        default,
        deserialize_with = "profile_value",
        skip_serializing_if = "Option::is_none"
    )]
    pub profile: Option<String>,
    pub artifacts: Vec<Artifact>,
}
pub const NETWORK_PATHS: [&str; 6] = [
    "GameAssembly.dll",
    "Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat",
    "NebulaNetworkBridge.dll",
    "NebulaRegistryBridge.dll",
    "NebulaPublicAccess.dll",
    "steam_appid.txt",
];
fn profile_value<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<Option<String>, D::Error> {
    String::deserialize(deserializer).map(Some)
}
pub fn network_only(m: &Manifest) -> bool {
    m.profile.as_deref() == Some("network-only")
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Artifact {
    pub path: String,
    pub operation: String,
    pub original_sha256: Option<String>,
    pub accepted_existing: Vec<String>,
    pub payload: Option<String>,
    pub payload_sha256: Option<String>,
    pub payload_size: Option<u64>,
    pub source_view_sha256: Option<String>,
    pub output_sha256: Option<String>,
}
pub fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
pub fn sha(value: &str) -> Result<()> {
    ensure!(
        value.len() == 64
            && value
                .bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()),
        "Invalid lowercase SHA256"
    );
    Ok(())
}
pub fn relative(value: &str) -> Result<PathBuf> {
    ensure!(
        !value.is_empty() && !value.contains(['\\', ':']) && !value.starts_with('/'),
        "Unsafe relative path"
    );
    let p = Path::new(value);
    ensure!(
        p.components().all(|c| matches!(c, Component::Normal(_))),
        "Unsafe relative path component"
    );
    Ok(p.into())
}
pub fn safe(root: &Path, relative_path: &str) -> Result<PathBuf> {
    let rel = relative(relative_path)?;
    let mut current = root.to_path_buf();
    reject_link(&current)?;
    for component in rel.components() {
        current.push(component);
        match std::fs::symlink_metadata(&current) {
            Ok(_) => reject_link(&current)?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
    }
    Ok(current)
}
pub fn reject_link(path: &Path) -> Result<()> {
    let meta = std::fs::symlink_metadata(path)?;
    ensure!(
        !meta.file_type().is_symlink(),
        "Symlink path rejected: {}",
        path.display()
    );
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        ensure!(
            meta.file_attributes() & 0x400 == 0,
            "Reparse point rejected: {}",
            path.display()
        );
    }
    Ok(())
}
pub fn load(root: &Path, pin: &str) -> Result<Manifest> {
    sha(pin)?;
    let bytes = read_bounded(&safe(root, "manifest.json")?, 1024 * 1024)?;
    ensure!(
        bytes.len() <= 1024 * 1024 && hash(&bytes) == pin,
        "Manifest pin mismatch"
    );
    let m: Manifest = serde_json::from_slice(&bytes)?;
    ensure!(
        m.format == "nebula-patch-v1" && m.app_id == APP && m.build_id == BUILD,
        "Unsupported manifest identity"
    );
    ensure!(
        ["frozen", "provisional"].contains(&m.status.as_str()) && !m.review.trim().is_empty(),
        "Missing review status"
    );
    ensure!(
        m.profile.is_none() || network_only(&m),
        "Unknown client profile"
    );
    let mut seen = HashSet::new();
    for a in &m.artifacts {
        relative(&a.path)?;
        ensure!(seen.insert(a.path.as_str()), "Duplicate artifact");
        if let Some((_, expected)) = ORIGINALS.iter().find(|(p, _)| *p == a.path) {
            ensure!(
                a.original_sha256.as_deref() == Some(*expected),
                "Original fingerprint mismatch"
            );
            let required = if a.path.ends_with("global-metadata.dat") {
                "metadata"
            } else if a.path.ends_with("charactereditor") {
                "unityfs_delta"
            } else {
                "delta"
            };
            ensure!(a.operation == required, "Wrong operation for core artifact");
        } else {
            ensure!(
                [
                    "NebulaRegistryBridge.dll",
                    "NebulaAutomation.dll",
                    "NebulaNetworkBridge.dll",
                    "NebulaPublicAccess.dll",
                    "NebulaRemoteTransport.exe",
                    "steam_appid.txt"
                ]
                .contains(&a.path.as_str()),
                "Unapproved target {}",
                a.path
            );
            ensure!(
                a.operation == "owned_file" && a.original_sha256.is_none(),
                "Helper must be project-owned payload"
            );
        }
        for h in a
            .accepted_existing
            .iter()
            .chain(a.original_sha256.iter())
            .chain(a.output_sha256.iter())
            .chain(a.source_view_sha256.iter())
        {
            sha(h)?;
        }
        if a.operation != "metadata" {
            relative(a.payload.as_ref().context("Missing payload")?)?;
            sha(a.payload_sha256.as_ref().context("Missing payload hash")?)?;
            ensure!(
                a.payload_size.is_some_and(|s| s <= 256 * 1024 * 1024) && a.output_sha256.is_some(),
                "Missing payload/output pins"
            );
        } else {
            ensure!(
                a.payload.is_none(),
                "Metadata must use compiled source recipe"
            );
        }
    }
    if network_only(&m) {
        ensure!(NETWORK_PATHS.iter().all(|p| seen.contains(p)) &&
            seen.iter().all(|p| NETWORK_PATHS.contains(p) || *p == "NebulaRemoteTransport.exe"),
            "network-only profile requires exactly six networking artifacts, optionally the remote transport; no optional UI/input/editor or automation artifacts");
    } else {
        ensure!(
            !seen.contains("NebulaNetworkBridge.dll"),
            "Network bridge requires explicit network-only profile"
        );
        for (path, _) in ORIGINALS {
            ensure!(seen.contains(path), "Missing core artifact {path}");
        }
        for required in [
            "NebulaRegistryBridge.dll",
            "NebulaAutomation.dll",
            "NebulaPublicAccess.dll",
            "steam_appid.txt",
        ] {
            ensure!(
                seen.contains(required),
                "Missing required project-owned helper {required}"
            );
        }
    }
    if m.status == "frozen" && m.review.starts_with("PENDING") {
        bail!("Cannot freeze pending review");
    }
    Ok(m)
}

pub fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    use std::io::Read;
    let file = std::fs::File::open(path)?;
    ensure!(
        file.metadata()?.len() <= maximum as u64,
        "Input file exceeds size limit"
    );
    let mut bytes = Vec::new();
    file.take(maximum as u64 + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= maximum, "Input file grew beyond size limit");
    Ok(bytes)
}

#[cfg(test)]
mod profile_tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

    fn fixture_directory(timestamp: u128) -> PathBuf {
        std::env::temp_dir().join(format!(
            "nebula-profile-{}-{timestamp}-{}",
            std::process::id(),
            NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed)
        ))
    }

    fn fixture(profile: Option<&str>, remote: bool) -> serde_json::Value {
        let paths: Vec<&str> = if profile == Some("network-only") {
            NETWORK_PATHS.to_vec()
        } else {
            ORIGINALS
                .iter()
                .map(|(p, _)| *p)
                .chain([
                    "NebulaRegistryBridge.dll",
                    "NebulaAutomation.dll",
                    "NebulaPublicAccess.dll",
                    "steam_appid.txt",
                ])
                .collect()
        };
        let mut artifacts = Vec::new();
        for path in paths
            .into_iter()
            .chain(remote.then_some("NebulaRemoteTransport.exe"))
        {
            let original = ORIGINALS.iter().find(|(p, _)| *p == path).map(|(_, h)| *h);
            let op = if path.ends_with("global-metadata.dat") {
                "metadata"
            } else if path.ends_with("charactereditor") {
                "unityfs_delta"
            } else if original.is_some() {
                "delta"
            } else {
                "owned_file"
            };
            artifacts.push(serde_json::json!({"path":path,"operation":op,"original_sha256":original,
                "accepted_existing":[],"payload":if op=="metadata" {None} else {Some("payload.bin")},
                "payload_sha256":hash(b"fixture"),"payload_size":7,"output_sha256":hash(b"fixture")}));
        }
        let mut value = serde_json::json!({"format":"nebula-patch-v1","app_id":APP,"build_id":BUILD,
            "status":"provisional","review":"Authored nonexecuting profile fixture","artifacts":artifacts});
        if let Some(p) = profile {
            value["profile"] = p.into();
        }
        value
    }
    fn checked(value: &serde_json::Value) -> Result<Manifest> {
        let root = fixture_directory(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
        );
        // I/O failures must fail a test, never count as an expected manifest
        // rejection. A counter also isolates parallel tests on coarse clocks.
        std::fs::create_dir(&root).expect("create private profile fixture");
        let raw = serde_json::to_vec(value).expect("serialize profile fixture");
        let path = root.join("manifest.json");
        std::fs::write(&path, &raw).expect("write profile fixture");
        let result = load(&root, &hash(&raw));
        std::fs::remove_file(path).expect("remove owned fixture file");
        std::fs::remove_dir(root).expect("remove owned fixture directory");
        result
    }
    #[test]
    fn fixture_names_stay_unique_for_parallel_checks_with_an_identical_clock() {
        let threads: Vec<_> = (0..16)
            .map(|_| std::thread::spawn(|| fixture_directory(123)))
            .collect();
        let paths: HashSet<_> = threads.into_iter().map(|t| t.join().unwrap()).collect();
        assert_eq!(paths.len(), 16);
        assert!(paths.iter().all(|p| p.starts_with(std::env::temp_dir())));
    }
    #[test]
    fn exact_network_six_and_remote_seven_and_legacy_eight_nine() {
        for profile in [None, Some("network-only")] {
            for remote in [false, true] {
                checked(&fixture(profile, remote)).unwrap_or_else(|error| {
                    panic!("profile={profile:?}, remote={remote}: {error:#}")
                });
            }
        }
    }
    #[test]
    fn every_network_artifact_is_required() {
        for i in 0..NETWORK_PATHS.len() {
            let mut v = fixture(Some("network-only"), false);
            v["artifacts"].as_array_mut().unwrap().remove(i);
            assert!(checked(&v).is_err(), "omission {i}");
        }
    }
    #[test]
    fn optional_ui_editor_or_automation_cannot_mix_into_network() {
        let legacy = fixture(None, false);
        for path in [ORIGINALS[2].0, ORIGINALS[3].0, "NebulaAutomation.dll"] {
            let mut v = fixture(Some("network-only"), false);
            let extra = legacy["artifacts"]
                .as_array()
                .unwrap()
                .iter()
                .find(|a| a["path"] == path)
                .unwrap()
                .clone();
            v["artifacts"].as_array_mut().unwrap().push(extra);
            assert!(checked(&v).is_err(), "mixed {path}");
        }
    }
    #[test]
    fn explicit_profile_and_matching_bridge_are_required() {
        for wrong in [None, Some("unknown"), Some("NETWORK-ONLY")] {
            let mut v = fixture(Some("network-only"), false);
            if let Some(p) = wrong {
                v["profile"] = p.into();
            } else {
                v.as_object_mut().unwrap().remove("profile");
            }
            assert!(checked(&v).is_err());
        }
        let mut v = fixture(None, false);
        v["profile"] = "network-only".into();
        assert!(checked(&v).is_err());
    }
    #[test]
    fn duplicate_unknown_and_wrong_operation_rejected() {
        let mut v = fixture(Some("network-only"), false);
        let duplicate = v["artifacts"][2].clone();
        v["artifacts"].as_array_mut().unwrap().push(duplicate);
        assert!(checked(&v).is_err());
        let mut v = fixture(Some("network-only"), false);
        v["artifacts"][2]["path"] = "Other.dll".into();
        assert!(checked(&v).is_err());
        let mut v = fixture(Some("network-only"), false);
        v["artifacts"][2]["operation"] = "delta".into();
        assert!(checked(&v).is_err());
    }
}
