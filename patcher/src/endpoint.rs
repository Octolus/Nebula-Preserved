use anyhow::{ensure, Context, Result};
use std::net::Ipv4Addr;
pub fn ipv4(value: &str) -> Result<Ipv4Addr> {
    let ip: Ipv4Addr = value.parse().context("Expected concrete canonical IPv4")?;
    ensure!(
        ip.to_string() == value
            && !ip.is_unspecified()
            && !ip.is_multicast()
            && ip != Ipv4Addr::BROADCAST,
        "Invalid concrete canonical IPv4"
    );
    Ok(ip)
}
pub fn validate(server: &str, advertise: &str) -> Result<()> {
    ipv4(advertise)?;
    ensure!(
        server.is_ascii() && server.len() <= 512,
        "Backend origin exceeds the native bridge's ASCII/512-character contract"
    );
    let url = url::Url::parse(server).context("Invalid backend origin")?;
    ensure!(
        url.username().is_empty()
            && url.password().is_none()
            && url.query().is_none()
            && url.fragment().is_none()
            && url.path() == "/",
        "Backend must be an origin without credentials/path/query/fragment"
    );
    ensure!(
        !server.ends_with('/') && !server.chars().any(char::is_whitespace) && url.port() != Some(0),
        "Noncanonical backend origin"
    );
    let host = url.host_str().context("Missing backend host")?;
    ensure!(
        host.len() <= 253
            && host.split('.').all(|label| !label.is_empty()
                && label.len() <= 63
                && !label.starts_with('-')
                && !label.ends_with('-')
                && label
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')),
        "Backend must use canonical IPv4 or lowercase ASCII DNS labels"
    );
    if url.scheme() == "http" {
        ipv4(host)?;
    } else {
        ensure!(
            url.scheme() == "https",
            "Only HTTP IPv4 or HTTPS origins supported"
        );
        if host.parse::<Ipv4Addr>().is_ok() {
            ipv4(host)?;
        }
    }
    // Keep explicit default ports valid, but reject host spelling normalized by URL parser.
    let authority = server.split_once("://").context("Missing scheme")?.1;
    let host_port = if authority == host {
        host.to_string()
    } else {
        let (h, p) = authority.rsplit_once(':').context("Invalid port")?;
        let n: u16 = p.parse().context("Invalid port")?;
        ensure!(
            h == host && n > 0 && n.to_string() == p,
            "Noncanonical authority"
        );
        format!("{h}:{p}")
    };
    ensure!(
        server == format!("{}://{host_port}", url.scheme()),
        "Noncanonical backend origin"
    );
    Ok(())
}
fn u32at(bytes: &[u8], pos: usize) -> Result<usize> {
    Ok(u32::from_le_bytes(
        bytes
            .get(pos..pos + 4)
            .context("Truncated metadata")?
            .try_into()?,
    ) as usize)
}
fn put(bytes: &mut [u8], pos: usize, n: usize) -> Result<()> {
    bytes[pos..pos + 4].copy_from_slice(&u32::try_from(n)?.to_le_bytes());
    Ok(())
}
pub fn patch(source: &[u8], server: &str, advertise: &str) -> Result<Vec<u8>> {
    validate(server, advertise)?;
    ensure!(
        u32at(source, 0)? == 0xFAB11BAF && u32at(source, 4)? == 29,
        "Unsupported metadata header"
    );
    let (ro, rs, bo, bs) = (
        u32at(source, 8)?,
        u32at(source, 12)?,
        u32at(source, 16)?,
        u32at(source, 20)?,
    );
    ensure!(
        rs % 8 == 0
            && ro.checked_add(rs).is_some_and(|n| n <= source.len())
            && bo.checked_add(bs).is_some_and(|n| n <= source.len()),
        "Invalid metadata literal tables"
    );
    let originals: [&[u8]; 4] = [
        b"https://nebularealms-na-east.appspot.com",
        b"http://localhost:8080",
        b"104.196.60.146",
        b"104.196.161.5",
    ];
    let mut seen = [false; 4];
    let mut selected = Vec::new();
    let mut records = Vec::new();
    for p in (ro..ro + rs).step_by(8) {
        let len = u32at(source, p)?;
        let index = u32at(source, p + 4)?;
        ensure!(
            index.checked_add(len).is_some_and(|n| n <= bs),
            "Literal exceeds blob"
        );
        let bytes = &source[bo + index..bo + index + len];
        let found = originals.iter().position(|v| *v == bytes);
        if let Some(i) = found {
            seen[i] = true;
            selected.push((
                p,
                index,
                len,
                if i < 2 {
                    server.as_bytes()
                } else {
                    advertise.as_bytes()
                },
            ));
        }
        records.push((p, index, len, found.is_some()));
    }
    ensure!(
        seen.iter().all(|b| *b),
        "Expected endpoint literals missing"
    );
    for &(_, i, l, _) in &selected {
        for &(_, j, k, is_selected) in &records {
            ensure!(
                is_selected || i + l <= j || j + k <= i,
                "Endpoint literal overlaps unselected data"
            );
        }
    }
    let mut output = source.to_vec();
    if server == "http://127.0.0.1:8080" && advertise == "127.0.0.1" {
        for &(p, i, l, replacement) in &selected {
            ensure!(replacement.len() <= l, "Default literal does not fit");
            output[bo + i..bo + i + l].fill(0);
            output[bo + i..bo + i + replacement.len()].copy_from_slice(replacement);
            put(&mut output, p, replacement.len())?;
        }
    } else {
        let mut blob = source[bo..bo + bs].to_vec();
        for &(p, _, _, replacement) in &selected {
            put(&mut output, p, replacement.len())?;
            put(&mut output, p + 4, blob.len())?;
            blob.extend_from_slice(replacement);
        }
        let offset = output.len();
        put(&mut output, 16, offset)?;
        put(&mut output, 20, blob.len())?;
        output.extend_from_slice(&blob);
    }
    let outbo = u32at(&output, 16)?;
    for &(p, i, l, is_selected) in &records {
        let oi = u32at(&output, p + 4)?;
        let ol = u32at(&output, p)?;
        if !is_selected {
            ensure!(
                output[outbo + oi..outbo + oi + ol] == source[bo + i..bo + i + l],
                "Unselected literal changed"
            );
        }
    }
    Ok(output)
}
pub fn check_public_config(server: &str) -> Result<()> {
    if !server.starts_with("https://") {
        return Ok(());
    }
    let base =
        std::env::var_os("LOCALAPPDATA").context("LOCALAPPDATA needed for HTTPS private config")?;
    let folder = std::path::PathBuf::from(base).join("NebulaPreservation");
    crate::manifest::reject_link(&folder)?;
    let path = crate::manifest::safe(&folder, "public-access.conf")?;
    let bytes = crate::manifest::read_bounded(&path, 4096)
        .context("Provision public-access.conf with reviewed account provisioning tool first")?;
    ensure!(
        bytes.len() <= 4096 && !bytes.contains(&0) && !bytes.contains(&b'\r'),
        "Invalid public-access config"
    );
    let text = std::str::from_utf8(&bytes)?;
    let mut format = None;
    let mut origin = None;
    let mut token = None;
    for line in text.split('\n') {
        if line.is_empty() {
            continue;
        }
        let (key, value) = line.split_once('=').context("Invalid public config line")?;
        let slot = match key {
            "format" => &mut format,
            "server_url" => &mut origin,
            "token_file" => &mut token,
            _ => anyhow::bail!("Unknown private config field"),
        };
        ensure!(
            slot.replace(value).is_none(),
            "Duplicate private config field"
        );
    }
    ensure!(
        format == Some("nebula-public-access-v1") && origin == Some(server),
        "HTTPS metadata origin must match private config server_url"
    );
    let token_path = std::path::PathBuf::from(token.context("Missing token_file")?);
    ensure!(
        token_path.is_absolute() && token_path.parent() == Some(folder.as_path()),
        "Token must be direct child of private config directory"
    );
    crate::manifest::reject_link(&token_path)?;
    let blob = crate::manifest::read_bounded(&token_path, 65536)?;
    ensure!(
        blob.len() >= 8
            && blob.len() <= 65536
            && blob.starts_with(b"NPA1")
            && u32::from_le_bytes(blob[4..8].try_into()?) as usize == blob.len() - 8,
        "Invalid protected token container"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn origin_validation_rejects_confusable_or_credentialed_routes() {
        assert!(validate("https://play.example.org:8443", "203.0.113.10").is_ok());
        assert!(validate("http://127.0.0.1:8080", "127.0.0.1").is_ok());
        for s in [
            "https://play.example.org/",
            "https://user@play.example.org",
            "https://play.example.org?token=x",
            "http://example.org",
            "http://127.0.0.1:0",
            "https://PLAY.example.org",
            "https://play.example.org:0443",
        ] {
            assert!(validate(s, "127.0.0.1").is_err());
        }
        assert!(validate("https://play.example.org", "0.0.0.0").is_err());
    }
    #[test]
    fn custom_literal_blob_preserves_unselected_content() {
        let literals: [&[u8]; 5] = [
            b"https://nebularealms-na-east.appspot.com",
            b"http://localhost:8080",
            b"104.196.60.146",
            b"104.196.161.5",
            b"unselected",
        ];
        let mut source = vec![0u8; 24 + 5 * 8];
        let bo = source.len();
        for (index, s) in literals.iter().enumerate() {
            let offset = source.len() - bo;
            put(&mut source, 24 + index * 8, s.len()).unwrap();
            put(&mut source, 28 + index * 8, offset).unwrap();
            source.extend_from_slice(s);
        }
        let size = source.len() - bo;
        for (p, n) in [
            (0, 0xFAB11BAF),
            (4, 29),
            (8, 24),
            (12, 40),
            (16, bo),
            (20, size),
        ] {
            put(&mut source, p, n).unwrap();
        }
        let out = patch(&source, "https://play.example.org:8443", "203.0.113.10").unwrap();
        assert_eq!(
            out.len(),
            source.len()
                + size
                + 2 * "https://play.example.org:8443".len()
                + 2 * "203.0.113.10".len()
        );
        assert!(out.windows(b"unselected".len()).any(|w| w == b"unselected"));
        assert_eq!(&out[bo..source.len()], &source[bo..]);
    }
}
