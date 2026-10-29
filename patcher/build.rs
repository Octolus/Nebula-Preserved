//! Optional private release inputs, never checked-in game files or account secrets.
use sha2::{Digest, Sha256};
use std::{
    env, fs,
    path::{Component, Path, PathBuf},
};
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn source(root: &Path, name: &str) -> PathBuf {
    assert!(
        !name.is_empty()
            && !name.contains(['\\', ':'])
            && Path::new(name)
                .components()
                .all(|c| matches!(c, Component::Normal(_))),
        "Unsafe embedded payload path"
    );
    let path = root
        .join(name)
        .canonicalize()
        .expect("Embedded file unavailable");
    assert!(
        path.starts_with(root),
        "Embedded payload escapes release directory"
    );
    assert!(
        fs::metadata(&path).unwrap().len() <= 256 * 1024 * 1024,
        "Embedded payload is oversized"
    );
    println!("cargo:rerun-if-changed={}", path.display());
    path
}
fn main() {
    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let manifest =
            PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap()).join("launcher.manifest");
        println!("cargo:rerun-if-changed={}", manifest.display());
        if env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc") {
            println!("cargo:rustc-link-arg-bin=nebula-preservation-patcher=/MANIFEST:EMBED");
            println!(
                "cargo:rustc-link-arg-bin=nebula-preservation-patcher=/MANIFESTINPUT:{}",
                manifest.display()
            );
        } else {
            let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
            let rc = out.join("launcher.rc");
            let object = out.join("launcher-resource.o");
            fs::write(
                &rc,
                format!(
                    "1 24 \"{}\"\n",
                    manifest.to_str().unwrap().replace('\\', "/")
                ),
            )
            .unwrap();
            let result = std::process::Command::new("windres")
                .arg("-i")
                .arg(&rc)
                .args(["-O", "coff", "-o"])
                .arg(&object)
                .status()
                .expect("Windows GNU builds need windres for the launcher manifest");
            assert!(result.success(), "Cannot build launcher manifest resource");
            println!(
                "cargo:rustc-link-arg-bin=nebula-preservation-patcher={}",
                object.display()
            );
        }
    }
    for name in [
        "NEBULA_DEFAULT_SERVER",
        "NEBULA_BUNDLE_SHA256",
        "NEBULA_CA_SHA256",
        "NEBULA_EMBED_BUNDLE",
        "NEBULA_EMBED_CA",
    ] {
        println!("cargo:rerun-if-env-changed={name}");
    }
    let mut generated = String::from("pub const BUNDLE: &[(&str, &[u8])] = &[\n");
    if let Some(path) = env::var_os("NEBULA_EMBED_BUNDLE") {
        let root = PathBuf::from(path)
            .canonicalize()
            .expect("Embedded bundle directory unavailable");
        let manifest_path = source(&root, "manifest.json");
        let bytes = fs::read(&manifest_path).unwrap();
        assert!(bytes.len() <= 4 * 1024 * 1024, "Manifest too large");
        assert_eq!(
            hash(&bytes),
            env::var("NEBULA_BUNDLE_SHA256").expect("Embedding requires reviewed bundle SHA256")
        );
        let manifest: serde_json::Value =
            serde_json::from_slice(&bytes).expect("Invalid embedded manifest");
        assert_eq!(
            manifest["status"], "frozen",
            "Never embed a provisional bundle"
        );
        assert_eq!(manifest["profile"], "network-only");
        let artifacts = manifest["artifacts"].as_array().expect("Missing artifacts");
        let allowed = [
            "GameAssembly.dll",
            "Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat",
            "NebulaNetworkBridge.dll",
            "NebulaRegistryBridge.dll",
            "NebulaPublicAccess.dll",
            "steam_appid.txt",
            "NebulaRemoteTransport.exe",
        ];
        assert_eq!(
            artifacts.len(),
            allowed.len(),
            "Require remote networking-only release"
        );
        let mut seen = std::collections::BTreeSet::new();
        generated.push_str(&format!(
            "(\"manifest.json\", include_bytes!({:?})),\n",
            manifest_path.to_str().expect("Build path must be Unicode")
        ));
        for artifact in artifacts {
            let target = artifact["path"].as_str().expect("Missing artifact target");
            assert!(
                allowed.contains(&target) && seen.insert(target),
                "Unapproved or duplicate embedded target"
            );
            if artifact["operation"] == "metadata" {
                continue;
            }
            let name = artifact["payload"].as_str().expect("Missing payload");
            assert!(name != "manifest.json", "Payload collides with manifest");
            let path = source(&root, name);
            let data = fs::read(&path).unwrap();
            assert_eq!(Some(data.len() as u64), artifact["payload_size"].as_u64());
            assert_eq!(
                hash(&data),
                artifact["payload_sha256"]
                    .as_str()
                    .expect("Payload hash missing")
            );
            generated.push_str(&format!(
                "({name:?}, include_bytes!({:?})),\n",
                path.to_str().expect("Build path must be Unicode")
            ));
        }
    }
    generated.push_str("];\npub const CA: &[u8] = ");
    if let Some(path) = env::var_os("NEBULA_EMBED_CA") {
        let path = PathBuf::from(path)
            .canonicalize()
            .expect("Public CA unavailable");
        let data = fs::read(&path).unwrap();
        assert!(data.len() <= 1024 * 1024, "CA too large");
        assert_eq!(
            hash(&data),
            env::var("NEBULA_CA_SHA256").expect("Embedded CA requires trusted fingerprint")
        );
        println!("cargo:rerun-if-changed={}", path.display());
        generated.push_str(&format!(
            "include_bytes!({:?});\n",
            path.to_str().expect("Build path must be Unicode")
        ));
    } else {
        generated.push_str("&[];\n");
    }
    fs::write(
        PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("embedded_release.rs"),
        generated,
    )
    .unwrap();
}
