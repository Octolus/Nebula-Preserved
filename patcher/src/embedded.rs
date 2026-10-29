//! Extract only compile-time authenticated public release material into a private cache.
#[cfg(windows)]
include!(concat!(env!("OUT_DIR"), "/embedded_release.rs"));
#[cfg(windows)]
fn cache() -> anyhow::Result<std::path::PathBuf> {
    use anyhow::Context;
    let base =
        std::path::PathBuf::from(std::env::var_os("LOCALAPPDATA").context("LOCALAPPDATA missing")?);
    let root = crate::manifest::safe(&base, "NebulaPreservationLauncher")?;
    if !root.exists() {
        std::fs::create_dir(&root)?;
    }
    crate::manifest::reject_link(&root)?;
    crate::credentials::restrict(&root)?;
    Ok(root)
}
#[cfg(windows)]
fn materialize(
    root: &std::path::Path,
    name: &str,
    bytes: &[u8],
) -> anyhow::Result<std::path::PathBuf> {
    use anyhow::{ensure, Context};
    let path = crate::manifest::safe(root, name)?;
    if !path.exists() {
        std::fs::create_dir_all(path.parent().context("Release file parent")?)?;
        crate::manifest::safe(root, name)?;
        crate::transaction::new_file(&path, bytes)?;
    }
    ensure!(
        crate::manifest::hash(&crate::manifest::read_bounded(&path, 256 * 1024 * 1024)?)
            == crate::manifest::hash(bytes),
        "Cached release material changed; remove only the reported cache file and retry: {}",
        path.display()
    );
    Ok(path)
}
#[cfg(windows)]
#[allow(clippy::const_is_empty)] // Inputs intentionally vary between generic and private release builds.
pub fn bundle(pin: &str) -> anyhow::Result<Option<std::path::PathBuf>> {
    if BUNDLE.is_empty() {
        return Ok(None);
    }
    crate::manifest::sha(pin)?;
    let root = crate::manifest::safe(&cache()?, pin)?;
    if !root.exists() {
        std::fs::create_dir(&root)?;
    }
    for (name, bytes) in BUNDLE {
        materialize(&root, name, bytes)?;
    }
    Ok(Some(root))
}
#[cfg(windows)]
#[allow(clippy::const_is_empty)] // Generic builds intentionally contain no operator CA.
pub fn ca() -> anyhow::Result<Option<std::path::PathBuf>> {
    if CA.is_empty() {
        return Ok(None);
    }
    let root = cache()?;
    materialize(
        &root,
        &format!("operator-ca-{}.der", crate::manifest::hash(CA)),
        CA,
    )
    .map(Some)
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    #[test]
    fn cache_preserves_verified_bytes_and_refuses_tampering_and_traversal() {
        let root = std::env::temp_dir().join(format!(
            "nebula-cache-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        let file = materialize(&root, "payload/reviewed.bin", b"public release data").unwrap();
        assert_eq!(
            materialize(&root, "payload/reviewed.bin", b"public release data").unwrap(),
            file
        );
        std::fs::write(&file, b"tampered").unwrap();
        assert!(materialize(&root, "payload/reviewed.bin", b"public release data").is_err());
        assert_eq!(std::fs::read(&file).unwrap(), b"tampered");
        assert!(materialize(&root, "../escape", b"data").is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
