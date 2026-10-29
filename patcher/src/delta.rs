//! NBD1: COPY pristine source, ADD authored bytes, ZERO padding. No executable recipe code.
use anyhow::{bail, ensure, Context, Result};
const MAX: usize = 256 * 1024 * 1024;
fn number(data: &[u8], cursor: &mut usize, size: usize) -> Result<u64> {
    let end = cursor.checked_add(size).context("Delta integer overflow")?;
    let bytes = data.get(*cursor..end).context("Truncated delta")?;
    *cursor = end;
    let mut n = [0; 8];
    n[..size].copy_from_slice(bytes);
    Ok(u64::from_le_bytes(n))
}
pub fn apply(source: &[u8], delta: &[u8]) -> Result<Vec<u8>> {
    ensure!(delta.starts_with(b"NBD1"), "Invalid delta magic");
    let mut pos = 4;
    let count = number(delta, &mut pos, 4)? as usize;
    let size = number(delta, &mut pos, 8)? as usize;
    ensure!(size <= MAX && count <= 1_000_000, "Delta exceeds limits");
    let mut output = Vec::with_capacity(size);
    for _ in 0..count {
        let kind = number(delta, &mut pos, 1)?;
        let offset = if kind == 0 {
            number(delta, &mut pos, 8)? as usize
        } else {
            0
        };
        let length = number(delta, &mut pos, 8)? as usize;
        ensure!(
            length > 0 && length <= size.saturating_sub(output.len()),
            "Delta output length invalid"
        );
        match kind {
            0 => output.extend_from_slice(
                source
                    .get(offset..offset.checked_add(length).context("COPY overflow")?)
                    .context("COPY beyond original")?,
            ),
            1 => {
                let end = pos.checked_add(length).context("ADD overflow")?;
                output.extend_from_slice(delta.get(pos..end).context("Truncated ADD")?);
                pos = end;
            }
            2 => output.resize(output.len() + length, 0),
            _ => bail!("Unknown delta operation"),
        }
    }
    ensure!(
        pos == delta.len() && output.len() == size,
        "Delta trailing bytes or wrong output length"
    );
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn copy_add_zero_and_reject_trailing_data() {
        let mut recipe = b"NBD1".to_vec();
        recipe.extend(3u32.to_le_bytes());
        recipe.extend(6u64.to_le_bytes());
        recipe.push(0);
        recipe.extend(1u64.to_le_bytes());
        recipe.extend(2u64.to_le_bytes());
        recipe.push(1);
        recipe.extend(2u64.to_le_bytes());
        recipe.extend(b"XY");
        recipe.push(2);
        recipe.extend(2u64.to_le_bytes());
        assert_eq!(apply(b"abc", &recipe).unwrap(), b"bcXY\0\0");
        recipe.push(0);
        assert!(apply(b"abc", &recipe).is_err());
    }
    #[test]
    fn rejects_out_of_bounds_copy_and_huge_output() {
        let mut recipe = b"NBD1".to_vec();
        recipe.extend(1u32.to_le_bytes());
        recipe.extend(1u64.to_le_bytes());
        recipe.push(0);
        recipe.extend(u64::MAX.to_le_bytes());
        recipe.extend(1u64.to_le_bytes());
        assert!(apply(b"a", &recipe).is_err());
        recipe[8..16].copy_from_slice(&u64::MAX.to_le_bytes());
        assert!(apply(b"a", &recipe).is_err());
    }
}
