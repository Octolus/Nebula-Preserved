//! Deterministic uncompressed UnityFS view. Node paths/content remain exact; compression changes.
use anyhow::{ensure, Context, Result};
const MAX: usize = 256 * 1024 * 1024;
struct Reader<'a> {
    b: &'a [u8],
    p: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let e = self.p.checked_add(n).context("UnityFS overflow")?;
        let r = self.b.get(self.p..e).context("Truncated UnityFS")?;
        self.p = e;
        Ok(r)
    }
    fn n(&mut self, n: usize) -> Result<u64> {
        let b = self.take(n)?;
        let mut a = [0; 8];
        a[8 - n..].copy_from_slice(b);
        Ok(u64::from_be_bytes(a))
    }
    fn string(&mut self) -> Result<Vec<u8>> {
        let n = self.b[self.p..]
            .iter()
            .position(|b| *b == 0)
            .context("Missing UnityFS terminator")?;
        ensure!(n < 65536, "UnityFS string too large");
        Ok(self.take(n + 1)?.to_vec())
    }
}
fn decode(input: &[u8], length: usize, mode: u64) -> Result<Vec<u8>> {
    ensure!(length <= MAX, "UnityFS output exceeds limit");
    if mode == 0 {
        ensure!(
            input.len() == length,
            "Uncompressed UnityFS length mismatch"
        );
        return Ok(input.to_vec());
    }
    if mode == 1 {
        // Unity stores the five LZMA property/dictionary bytes, omitting the
        // usual eight-byte size. The authoritative block table supplies it.
        struct Bounded {
            bytes: Vec<u8>,
            limit: usize,
        }
        impl std::io::Write for Bounded {
            fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
                if data.len() > self.limit.saturating_sub(self.bytes.len()) {
                    return Err(std::io::Error::other("LZMA output exceeds block size"));
                }
                self.bytes.extend_from_slice(data);
                Ok(data.len())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let mut output = Bounded {
            bytes: Vec::with_capacity(length),
            limit: length,
        };
        let options = lzma_rs::decompress::Options {
            unpacked_size: lzma_rs::decompress::UnpackedSize::UseProvided(Some(length as u64)),
            memlimit: Some(MAX),
            allow_incomplete: false,
        };
        lzma_rs::lzma_decompress_with_options(
            &mut std::io::Cursor::new(input),
            &mut output,
            &options,
        )
        .context("Invalid Unity LZMA block")?;
        ensure!(output.bytes.len() == length, "LZMA wrong output length");
        return Ok(output.bytes);
    }
    ensure!(
        mode == 2 || mode == 3,
        "Only uncompressed/LZ4/LZMA UnityFS supported"
    );
    let mut r = Reader { b: input, p: 0 };
    let mut out = Vec::with_capacity(length);
    while r.p < input.len() {
        let token = r.n(1)? as usize;
        let mut literals = token >> 4;
        if literals == 15 {
            loop {
                let n = r.n(1)? as usize;
                literals = literals.checked_add(n).context("LZ4 overflow")?;
                if n != 255 {
                    break;
                }
            }
        }
        ensure!(
            literals <= length.saturating_sub(out.len()),
            "LZ4 literal exceeds output"
        );
        out.extend_from_slice(r.take(literals)?);
        if r.p == input.len() {
            break;
        }
        let b = r.take(2)?;
        let offset = u16::from_le_bytes(b.try_into()?) as usize;
        ensure!(
            offset > 0 && offset <= out.len(),
            "Invalid LZ4 backreference"
        );
        let mut count = (token & 15) + 4;
        if token & 15 == 15 {
            loop {
                let n = r.n(1)? as usize;
                count = count.checked_add(n).context("LZ4 overflow")?;
                if n != 255 {
                    break;
                }
            }
        }
        ensure!(
            count <= length.saturating_sub(out.len()),
            "LZ4 match exceeds output"
        );
        for _ in 0..count {
            let value = out[out.len() - offset];
            out.push(value)
        }
    }
    ensure!(out.len() == length, "LZ4 wrong output length");
    Ok(out)
}
pub fn canonicalize(input: &[u8]) -> Result<Vec<u8>> {
    ensure!(input.len() <= MAX, "UnityFS exceeds limit");
    let mut r = Reader { b: input, p: 0 };
    ensure!(r.string()? == b"UnityFS\0", "Not UnityFS");
    let version = r.n(4)?;
    ensure!(version == 6 || version == 7, "Unsupported UnityFS version");
    let unity = r.string()?;
    let revision = r.string()?;
    let size = r.n(8)? as usize;
    let compressed = r.n(4)? as usize;
    let expanded = r.n(4)? as usize;
    let flags = r.n(4)?;
    ensure!(
        size == input.len() && flags & !0x3ff == 0 && flags & 0x40 != 0,
        "Unsupported UnityFS header flags/size"
    );
    if version >= 7 {
        r.p = (r.p + 15) & !15;
    }
    let info_offset = if flags & 0x80 != 0 {
        size.checked_sub(compressed)
            .context("Bad UnityFS info size")?
    } else {
        r.p
    };
    let info_end = info_offset
        .checked_add(compressed)
        .context("UnityFS info overflow")?;
    let info = decode(
        input
            .get(info_offset..info_end)
            .context("Bad UnityFS info range")?,
        expanded,
        flags & 63,
    )?;
    let mut ir = Reader { b: &info, p: 0 };
    ir.take(16)?;
    let count = ir.n(4)? as usize;
    ensure!(count <= 65536, "Too many UnityFS blocks");
    let mut blocks = Vec::new();
    let mut total = 0usize;
    for _ in 0..count {
        let expanded = ir.n(4)? as usize;
        let compressed = ir.n(4)? as usize;
        let mode = ir.n(2)?;
        ensure!(mode & !127 == 0, "Unsupported UnityFS block flags");
        total = total
            .checked_add(expanded)
            .context("UnityFS block overflow")?;
        ensure!(total <= MAX, "UnityFS expanded data too large");
        blocks.push((expanded, compressed, mode));
    }
    let nodes_start = ir.p;
    let nodes = ir.n(4)? as usize;
    ensure!(nodes <= 65536, "Too many UnityFS nodes");
    for _ in 0..nodes {
        let off = ir.n(8)?;
        let size = ir.n(8)?;
        ir.n(4)?;
        ir.string()?;
        ensure!(
            off.checked_add(size).is_some_and(|n| n <= total as u64),
            "UnityFS node exceeds data"
        );
    }
    ensure!(ir.p == info.len(), "UnityFS info trailing bytes");
    let mut pos = if flags & 0x80 != 0 { r.p } else { info_end };
    if flags & 0x200 != 0 {
        pos = (pos + 15) & !15;
    }
    let mut body = Vec::with_capacity(total);
    for (expanded, compressed, mode) in blocks {
        let end = pos
            .checked_add(compressed)
            .context("UnityFS data overflow")?;
        body.extend(decode(
            input.get(pos..end).context("UnityFS block range")?,
            expanded,
            mode & 63,
        )?);
        pos = end;
    }
    let data_end = if flags & 0x80 != 0 { info_offset } else { size };
    ensure!(pos == data_end, "UnityFS unexpected trailing data");
    let mut new_info = vec![0; 16];
    new_info.extend_from_slice(&1u32.to_be_bytes());
    new_info.extend_from_slice(&(total as u32).to_be_bytes());
    new_info.extend_from_slice(&(total as u32).to_be_bytes());
    new_info.extend_from_slice(&0u16.to_be_bytes());
    new_info.extend_from_slice(&info[nodes_start..]);
    let mut out = b"UnityFS\0".to_vec();
    out.extend_from_slice(&(version as u32).to_be_bytes());
    out.extend(unity);
    out.extend(revision);
    let size_at = out.len();
    out.extend_from_slice(&0u64.to_be_bytes());
    out.extend_from_slice(&(new_info.len() as u32).to_be_bytes());
    out.extend_from_slice(&(new_info.len() as u32).to_be_bytes());
    out.extend_from_slice(&0x40u32.to_be_bytes());
    if version >= 7 {
        out.resize((out.len() + 15) & !15, 0)
    }
    out.extend(new_info);
    out.extend(body);
    let len = out.len() as u64;
    out[size_at..size_at + 8].copy_from_slice(&len.to_be_bytes());
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_lz4_overlap_and_invalid_distance() {
        assert_eq!(
            decode(&[0x40, b'a', b'b', b'c', b'd', 4, 0], 8, 2).unwrap(),
            b"abcdabcd"
        );
        assert!(decode(&[0, 0, 0], 4, 2).is_err());
        assert!(decode(&[0x40, b'a', b'b', b'c', b'd', 4, 0], 7, 2).is_err());
        assert!(decode(b"x", 1, 1).is_err());
    }
}
