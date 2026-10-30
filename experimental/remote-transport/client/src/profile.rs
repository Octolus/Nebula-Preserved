//! Exact, versioned transport profiles. Public trust never falls back to a file.
use anyhow::{ensure, Context, Result};
use std::collections::BTreeMap;

const LEGACY: &[&str] = &[
    "format",
    "server_url",
    "gateway_port",
    "api_port",
    "first_scene_port",
    "last_scene_port",
    "ca_file",
    "ca_sha256",
];
const SYSTEM: &[&str] = &[
    "format",
    "server_url",
    "gateway_port",
    "api_port",
    "first_scene_port",
    "last_scene_port",
    "trust",
];

#[derive(Debug, PartialEq, Eq)]
pub enum Trust {
    System,
    PinnedCa { file: String, sha256: String },
}
#[derive(Debug)]
pub struct Remote {
    pub origin: String,
    pub hostname: String,
    pub gateway: u16,
    pub trust: Trust,
}

pub fn fields(raw: &[u8]) -> Result<BTreeMap<String, String>> {
    ensure!(!raw.is_empty() && raw.len() <= 4096, "Config bounds");
    ensure!(!raw.contains(&0) && !raw.contains(&b'\r'), "Config framing");
    let mut result = BTreeMap::new();
    for line in std::str::from_utf8(raw)?.split_terminator('\n') {
        let (key, value) = line.split_once('=').context("Config field")?;
        ensure!(
            !key.is_empty()
                && !value.is_empty()
                && result.insert(key.into(), value.into()).is_none(),
            "Config grammar"
        );
    }
    Ok(result)
}

pub fn parse(raw: &[u8]) -> Result<Remote> {
    let data = fields(raw)?;
    let keys = match data.get("format").map(String::as_str) {
        Some("nebula-remote-transport-v1") => LEGACY,
        Some("nebula-remote-transport-v2") => SYSTEM,
        _ => anyhow::bail!("Unknown transport profile version"),
    };
    ensure!(
        data.len() == keys.len() && keys.iter().all(|key| data.contains_key(*key)),
        "Unexpected transport profile fields"
    );
    ensure!(
        data["api_port"] == "38080"
            && data["first_scene_port"] == "28000"
            && data["last_scene_port"] == "28031",
        "Local port profile"
    );
    let gateway: u16 = data["gateway_port"].parse()?;
    ensure!(
        gateway > 0 && gateway.to_string() == data["gateway_port"],
        "Gateway port"
    );
    let trust = if keys == SYSTEM {
        ensure!(
            data["trust"] == "system" && gateway == 8443,
            "System trust profile"
        );
        Trust::System
    } else {
        let pin = &data["ca_sha256"];
        ensure!(
            pin.len() == 64
                && pin
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
            "CA pin grammar"
        );
        Trust::PinnedCa {
            file: data["ca_file"].clone(),
            sha256: pin.clone(),
        }
    };
    let origin = &data["server_url"];
    let parsed = url::Url::parse(origin)?;
    ensure!(
        parsed.scheme() == "https"
            && parsed.username().is_empty()
            && parsed.password().is_none()
            && parsed.path() == "/"
            && parsed.query().is_none()
            && parsed.fragment().is_none()
            && !origin.ends_with('/')
            && !origin.chars().any(char::is_whitespace),
        "HTTPS origin required"
    );
    let hostname = parsed.host_str().context("TLS hostname")?.to_owned();
    ensure!(!hostname.contains(':'), "Hostname profile");
    Ok(Remote {
        origin: origin.clone(),
        hostname,
        gateway,
        trust,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    const SYSTEM_PROFILE: &str = "format=nebula-remote-transport-v2\nserver_url=https://play.example.org:8444\ngateway_port=8443\napi_port=38080\nfirst_scene_port=28000\nlast_scene_port=28031\ntrust=system\n";
    fn legacy() -> String {
        SYSTEM_PROFILE.replace("v2", "v1").replace(
            "trust=system\n",
            &format!(
                "ca_file=D:\\operator-ca.der\nca_sha256={}\n",
                "ab".repeat(32)
            ),
        )
    }
    #[test]
    fn system_profile_needs_no_certificate_file() {
        let value = parse(SYSTEM_PROFILE.as_bytes()).unwrap();
        assert_eq!(value.trust, Trust::System);
        assert_eq!(value.hostname, "play.example.org");
        assert_eq!(value.gateway, 8443);
        assert!(parse(
            SYSTEM_PROFILE
                .replace("play.example.org", "203.0.113.10")
                .as_bytes()
        )
        .is_ok());
    }
    #[test]
    fn legacy_pinned_profile_keeps_its_exact_contract() {
        assert_eq!(
            parse(legacy().as_bytes()).unwrap().trust,
            Trust::PinnedCa {
                file: "D:\\operator-ca.der".into(),
                sha256: "ab".repeat(32)
            }
        );
    }
    #[test]
    fn trust_versions_never_mix_or_downgrade() {
        for value in [
            SYSTEM_PROFILE.replace("v2", "v1"),
            legacy().replace("v1", "v2"),
            format!("{SYSTEM_PROFILE}ca_file=D:\\operator-ca.der\n"),
            format!("{}trust=system\n", legacy()),
            SYSTEM_PROFILE.replace("system", "any"),
            SYSTEM_PROFILE.replace("v2", "v3"),
        ] {
            assert!(parse(value.as_bytes()).is_err());
        }
    }
    #[test]
    fn malformed_duplicate_and_extra_fields_are_refused() {
        for value in [
            format!("{SYSTEM_PROFILE}trust=system\n"),
            format!("{SYSTEM_PROFILE}unused=x\n"),
            SYSTEM_PROFILE.replace("trust=system\n", "trust=\n"),
            SYSTEM_PROFILE.replace("\ntrust", "\r\ntrust"),
            format!("{SYSTEM_PROFILE}\0"),
            format!("{SYSTEM_PROFILE}\n"),
        ] {
            assert!(parse(value.as_bytes()).is_err());
        }
        assert!(parse(&vec![b'x'; 4097]).is_err());
    }
    #[test]
    fn port_and_origin_escape_paths_fail_closed() {
        for value in ["0", "08443", "65536", "8444"] {
            assert!(parse(
                SYSTEM_PROFILE
                    .replace("gateway_port=8443", &format!("gateway_port={value}"))
                    .as_bytes()
            )
            .is_err());
        }
        for value in [
            "http://play.example.org",
            "https://user@play.example.org",
            "https://play.example.org/",
            "https://play.example.org/path",
            "https://play.example.org?x=1",
            "https://play.example.org#x",
            "https://[::1]",
        ] {
            assert!(parse(
                SYSTEM_PROFILE
                    .replace("https://play.example.org:8444", value)
                    .as_bytes()
            )
            .is_err());
        }
    }
    #[test]
    fn private_ca_pin_must_remain_lowercase_sha256() {
        for pin in ["ab".repeat(31), "AB".repeat(32), "z0".repeat(32)] {
            assert!(parse(legacy().replace(&"ab".repeat(32), &pin).as_bytes()).is_err());
        }
    }
}
