//! Nebula application framing, from backend/wire.py and NebulaApplicationCrypto.cs.
use crate::error::{Error, Result};
use aes::{
    cipher::{generic_array::GenericArray, BlockDecrypt, BlockEncrypt, KeyInit},
    Aes128,
};
use base64::{
    alphabet,
    engine::general_purpose::{GeneralPurpose, GeneralPurposeConfig, STANDARD},
    Engine,
};
use sha1::{Digest, Sha1};
use sha2::Sha256;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Request {
    pub fields: Vec<String>,
    pub platform: String,
}

impl Request {
    /// Strip only the final platform token, then apply Python str.split's maxsplit.
    pub fn parse(plaintext: &str, maxsplit: Option<usize>) -> Result<Self> {
        let (body, platform) = plaintext
            .rsplit_once('#')
            .ok_or_else(|| Error::bad("Missing or unsupported client platform trailer"))?;
        if platform != "PS4" && platform != "StandaloneWindows" {
            return Err(Error::bad("Missing or unsupported client platform trailer"));
        }
        let fields = match maxsplit {
            Some(limit) if limit < usize::MAX => {
                body.splitn(limit + 1, '#').map(str::to_owned).collect()
            }
            _ => body.split('#').map(str::to_owned).collect(),
        };
        Ok(Self {
            fields,
            platform: platform.to_owned(),
        })
    }

    pub fn require(&self, count: usize) -> Result<&[String]> {
        if self.fields.len() != count {
            return Err(Error::bad(format!(
                "Expected {count} request fields, got {}",
                self.fields.len()
            )));
        }
        Ok(&self.fields)
    }
}

fn cipher() -> Aes128 {
    let digest = Sha1::digest(b"a56Bhg2Fbg789Lmk");
    Aes128::new(GenericArray::from_slice(&digest[..16]))
}

/// Replies never receive the client-side platform trailer.
pub fn encrypt(plaintext: &str) -> Result<String> {
    let mut bytes = plaintext.as_bytes().to_vec();
    let padding = 16 - bytes.len() % 16;
    bytes.resize(bytes.len() + padding, padding as u8);
    let cipher = cipher();
    for block in bytes.chunks_exact_mut(16) {
        cipher.encrypt_block(GenericArray::from_mut_slice(block));
    }
    Ok(STANDARD.encode(bytes))
}

pub fn decrypt(ciphertext: &str) -> Result<String> {
    if ciphertext.is_empty() || ciphertext.len() % 4 != 0 {
        return Err(Error::bad("invalid_ciphertext_length"));
    }
    // Convert.FromBase64String and Python validate=True accept nonzero unused
    // bits in the final sextet; base64's Rust default rejects those bits.
    let decoder = GeneralPurpose::new(
        &alphabet::STANDARD,
        GeneralPurposeConfig::new().with_decode_allow_trailing_bits(true),
    );
    let mut bytes = decoder
        .decode(ciphertext)
        .map_err(|_| Error::bad("invalid_ciphertext_base64"))?;
    if bytes.is_empty() || bytes.len() % 16 != 0 {
        return Err(Error::bad("invalid_ciphertext_block_length"));
    }
    let cipher = cipher();
    for block in bytes.chunks_exact_mut(16) {
        cipher.decrypt_block(GenericArray::from_mut_slice(block));
    }
    let padding = usize::from(*bytes.last().expect("nonempty ciphertext"));
    if padding == 0
        || padding > 16
        || !bytes[bytes.len() - padding..]
            .iter()
            .all(|b| usize::from(*b) == padding)
    {
        return Err(Error::bad("invalid_ciphertext_padding"));
    }
    bytes.truncate(bytes.len() - padding);
    String::from_utf8(bytes).map_err(|_| Error::bad("invalid_ciphertext_utf8"))
}

/// NebulaApplicationCrypto.DecryptClient's additional ingress length bound.
/// Backend wire.py itself does not impose this limit on legal ciphertexts.
pub fn decrypt_client(ciphertext: &str) -> Result<String> {
    if ciphertext.len() > 65532 {
        return Err(Error::bad("invalid_ciphertext_length"));
    }
    decrypt(ciphertext)
}

pub fn session_guid(ps4_id: &str, request_hash: &str) -> String {
    // Python's ascii(errors="replace") substitutes once per Unicode scalar.
    let source: Vec<u8> = ps4_id
        .chars()
        .chain(std::iter::once('#'))
        .chain(request_hash.chars())
        .map(|c| if c.is_ascii() { c as u8 } else { b'?' })
        .collect();
    hex::encode(Sha256::digest(source))[..32].to_owned()
}

fn json_string(value: &str, output: &mut String) {
    use std::fmt::Write;
    output.push('"');
    for c in value.chars() {
        match c {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\u{0008}' => output.push_str("\\b"),
            '\u{000c}' => output.push_str("\\f"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            '#' => output.push_str("\\u0023"),
            c if c < ' ' || c >= '\u{007f}' => {
                let mut units = [0; 2];
                for unit in c.encode_utf16(&mut units) {
                    let _ = write!(output, "\\u{unit:04x}");
                }
            }
            c => output.push(c),
        }
    }
    output.push('"');
}

// Python JSON uses repr(float): decimal exponents [-4,15], otherwise e±NN.
fn json_float(number: &serde_json::Number) -> String {
    let raw = number.to_string();
    let (negative, raw) = raw
        .strip_prefix('-')
        .map_or((false, raw.as_str()), |s| (true, s));
    let (mantissa, exponent) = raw
        .split_once(['e', 'E'])
        .map_or((raw, 0), |(m, e)| (m, e.parse::<i32>().unwrap_or(0)));
    let before = mantissa.find('.').unwrap_or(mantissa.len()) as i32;
    let mut digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let first = digits.find(|c| c != '0').unwrap_or(digits.len());
    if first == digits.len() {
        return if negative { "-0.0" } else { "0.0" }.to_owned();
    }
    let power = before + exponent - first as i32 - 1;
    digits.drain(..first);
    while digits.ends_with('0') {
        digits.pop();
    }
    let mut result = if negative {
        "-".to_owned()
    } else {
        String::new()
    };
    if !(-4..16).contains(&power) {
        result.push(digits.as_bytes()[0] as char);
        if digits.len() > 1 {
            result.push('.');
            result.push_str(&digits[1..]);
        }
        result.push('e');
        result.push(if power < 0 { '-' } else { '+' });
        result.push_str(&format!("{:02}", power.abs()));
    } else if power < 0 {
        result.push_str("0.");
        result.extend(std::iter::repeat('0').take((-power - 1) as usize));
        result.push_str(&digits);
    } else {
        let point = power as usize + 1;
        if point >= digits.len() {
            result.push_str(&digits);
            result.extend(std::iter::repeat('0').take(point - digits.len()));
            result.push_str(".0");
        } else {
            result.push_str(&digits[..point]);
            result.push('.');
            result.push_str(&digits[point..]);
        }
    }
    result
}

pub fn json_field(value: &serde_json::Value) -> Result<String> {
    fn encode(value: &serde_json::Value, output: &mut String) {
        use serde_json::Value;
        match value {
            Value::Null => output.push_str("null"),
            Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
            Value::Number(value) if value.is_f64() => output.push_str(&json_float(value)),
            Value::Number(value) => output.push_str(&value.to_string()),
            Value::String(value) => json_string(value, output),
            Value::Array(values) => {
                output.push('[');
                for (index, value) in values.iter().enumerate() {
                    if index != 0 {
                        output.push(',');
                    }
                    encode(value, output);
                }
                output.push(']');
            }
            Value::Object(values) => {
                output.push('{');
                for (index, (key, value)) in values.iter().enumerate() {
                    if index != 0 {
                        output.push(',');
                    }
                    json_string(key, output);
                    output.push(':');
                    encode(value, output);
                }
                output.push('}');
            }
        }
    }
    let mut result = String::new();
    encode(value, &mut result);
    Ok(result)
}
