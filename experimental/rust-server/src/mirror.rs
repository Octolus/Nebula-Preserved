//! Mirror v66.0.9 little-endian serialization and Telepathy's big-endian envelope.
//!
//! Batches contain a double timestamp followed by messages with no length prefixes.
//! A message handler must consume its own fields before reading the next u16 ID.
use crate::error::{Error, Result};
use std::collections::VecDeque;

pub const MAX_STRING_LENGTH: usize = 32 * 1024;
pub const BATCH_HEADER_SIZE: usize = 8;
pub const MESSAGE_HEADER_SIZE: usize = 2;

macro_rules! read_number {
    ($name:ident, $nullable:ident, $ty:ty, $size:expr) => {
        pub fn $name(&mut self) -> Result<$ty> {
            Ok(<$ty>::from_le_bytes(
                self.read_bytes($size)?.try_into().expect("fixed length"),
            ))
        }
        pub fn $nullable(&mut self) -> Result<Option<$ty>> {
            if self.read_bool()? {
                Ok(Some(self.$name()?))
            } else {
                Ok(None)
            }
        }
    };
}

macro_rules! write_number {
    ($name:ident, $nullable:ident, $ty:ty) => {
        pub fn $name(&mut self, value: $ty) {
            self.write_bytes(&value.to_le_bytes());
        }
        pub fn $nullable(&mut self, value: Option<$ty>) {
            self.write_bool(value.is_some());
            if let Some(value) = value {
                self.$name(value);
            }
        }
    };
}

#[derive(Clone, Debug)]
pub struct Reader<'a> {
    bytes: &'a [u8],
    position: usize,
}

impl<'a> Reader<'a> {
    pub fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, position: 0 }
    }
    pub fn position(&self) -> usize {
        self.position
    }
    pub fn remaining(&self) -> usize {
        self.bytes.len() - self.position
    }
    pub fn length(&self) -> usize {
        self.bytes.len()
    }
    pub fn remaining_slice(&self) -> &'a [u8] {
        &self.bytes[self.position..]
    }
    pub fn read_bytes(&mut self, count: usize) -> Result<&'a [u8]> {
        if count > self.remaining() {
            return Err(Error::bad("Mirror reader exceeded end of message"));
        }
        let result = &self.bytes[self.position..self.position + count];
        self.position += count;
        Ok(result)
    }
    pub fn finish(&self) -> Result<()> {
        if self.remaining() == 0 {
            Ok(())
        } else {
            Err(Error::bad("Trailing Mirror message bytes"))
        }
    }
    read_number!(read_u8, read_u8_nullable, u8, 1);
    read_number!(read_i8, read_i8_nullable, i8, 1);
    read_number!(read_u16, read_u16_nullable, u16, 2);
    read_number!(read_i16, read_i16_nullable, i16, 2);
    read_number!(read_u32, read_u32_nullable, u32, 4);
    read_number!(read_i32, read_i32_nullable, i32, 4);
    read_number!(read_u64, read_u64_nullable, u64, 8);
    read_number!(read_i64, read_i64_nullable, i64, 8);
    read_number!(read_f32, read_f32_nullable, f32, 4);
    read_number!(read_f64, read_f64_nullable, f64, 8);
    pub fn read_bool(&mut self) -> Result<bool> {
        Ok(self.read_u8()? != 0)
    }
    pub fn read_bool_nullable(&mut self) -> Result<Option<bool>> {
        if self.read_bool()? {
            Ok(Some(self.read_bool()?))
        } else {
            Ok(None)
        }
    }
    /// A C# char is one UTF-16 code unit, including an isolated surrogate.
    pub fn read_char(&mut self) -> Result<u16> {
        self.read_u16()
    }
    pub fn read_char_nullable(&mut self) -> Result<Option<u16>> {
        self.read_u16_nullable()
    }
    pub fn read_string(&mut self) -> Result<Option<String>> {
        let size = self.read_u16()?;
        if size == 0 {
            return Ok(None);
        }
        let count = usize::from(size) - 1;
        if count >= MAX_STRING_LENGTH {
            return Err(Error::bad("Mirror string exceeds 32767 UTF-8 bytes"));
        }
        let bytes = self.read_bytes(count)?;
        let text =
            std::str::from_utf8(bytes).map_err(|_| Error::bad("Invalid Mirror string UTF-8"))?;
        Ok(Some(text.to_owned()))
    }
    pub fn read_bytes_and_size(&mut self) -> Result<Option<Vec<u8>>> {
        let count = self.read_u32()?;
        if count == 0 {
            return Ok(None);
        }
        let length = count - 1;
        if length > i32::MAX as u32 {
            return Err(Error::bad("Mirror byte array size overflows Int32"));
        }
        Ok(Some(self.read_bytes(length as usize)?.to_vec()))
    }
    /// Guid.ToByteArray order, not RFC 4122 network byte order.
    pub fn read_guid(&mut self) -> Result<[u8; 16]> {
        Ok(self.read_bytes(16)?.try_into().expect("fixed length"))
    }
    pub fn read_guid_nullable(&mut self) -> Result<Option<[u8; 16]>> {
        if self.read_bool()? {
            Ok(Some(self.read_guid()?))
        } else {
            Ok(None)
        }
    }
    pub fn read_uuid(&mut self) -> Result<uuid::Uuid> {
        Ok(uuid::Uuid::from_bytes_le(self.read_guid()?))
    }
    pub fn read_vector3(&mut self) -> Result<[f32; 3]> {
        Ok([self.read_f32()?, self.read_f32()?, self.read_f32()?])
    }
    pub fn read_vector3_nullable(&mut self) -> Result<Option<[f32; 3]>> {
        if self.read_bool()? {
            Ok(Some(self.read_vector3()?))
        } else {
            Ok(None)
        }
    }
    pub fn read_quaternion(&mut self) -> Result<[f32; 4]> {
        Ok([
            self.read_f32()?,
            self.read_f32()?,
            self.read_f32()?,
            self.read_f32()?,
        ])
    }
    pub fn read_quaternion_nullable(&mut self) -> Result<Option<[f32; 4]>> {
        if self.read_bool()? {
            Ok(Some(self.read_quaternion()?))
        } else {
            Ok(None)
        }
    }
    /// Mirror Compression.DecompressVarUInt (SQLite4-style, not LEB128).
    pub fn read_var_u64(&mut self) -> Result<u64> {
        let first = self.read_u8()?;
        match first {
            0..=240 => Ok(first.into()),
            241..=248 => Ok(240 + ((u64::from(first) - 241) << 8) + u64::from(self.read_u8()?)),
            249 => Ok(2288 + (u64::from(self.read_u8()?) << 8) + u64::from(self.read_u8()?)),
            250..=255 => {
                let count = usize::from(first - 247);
                let mut value = 0u64;
                for (index, byte) in self.read_bytes(count)?.iter().enumerate() {
                    value |= u64::from(*byte) << (index * 8);
                }
                Ok(value)
            }
        }
    }
    pub fn read_var_i64(&mut self) -> Result<i64> {
        let value = self.read_var_u64()?;
        Ok(((value >> 1) as i64) ^ -((value & 1) as i64))
    }
    pub fn read_packed_u64(&mut self) -> Result<u64> {
        self.read_var_u64()
    }
    pub fn read_packed_u32(&mut self) -> Result<u32> {
        self.read_var_u64()?
            .try_into()
            .map_err(|_| Error::bad("Packed UInt32 overflow"))
    }
}

#[derive(Clone, Debug, Default)]
pub struct Writer {
    bytes: Vec<u8>,
}

impl Writer {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            bytes: Vec::with_capacity(capacity),
        }
    }
    pub fn position(&self) -> usize {
        self.bytes.len()
    }
    pub fn as_slice(&self) -> &[u8] {
        &self.bytes
    }
    pub fn into_inner(self) -> Vec<u8> {
        self.bytes
    }
    pub fn write_bytes(&mut self, bytes: &[u8]) {
        self.bytes.extend_from_slice(bytes);
    }
    write_number!(write_u8, write_u8_nullable, u8);
    write_number!(write_i8, write_i8_nullable, i8);
    write_number!(write_u16, write_u16_nullable, u16);
    write_number!(write_i16, write_i16_nullable, i16);
    write_number!(write_u32, write_u32_nullable, u32);
    write_number!(write_i32, write_i32_nullable, i32);
    write_number!(write_u64, write_u64_nullable, u64);
    write_number!(write_i64, write_i64_nullable, i64);
    write_number!(write_f32, write_f32_nullable, f32);
    write_number!(write_f64, write_f64_nullable, f64);
    pub fn write_bool(&mut self, value: bool) {
        self.write_u8(u8::from(value));
    }
    pub fn write_bool_nullable(&mut self, value: Option<bool>) {
        self.write_bool(value.is_some());
        if let Some(value) = value {
            self.write_bool(value);
        }
    }
    pub fn write_char(&mut self, value: u16) {
        self.write_u16(value);
    }
    pub fn write_char_nullable(&mut self, value: Option<u16>) {
        self.write_u16_nullable(value);
    }
    pub fn write_string(&mut self, value: Option<&str>) -> Result<()> {
        match value {
            None => self.write_u16(0),
            Some(value) => {
                if value.len() >= MAX_STRING_LENGTH {
                    return Err(Error::bad("Mirror string exceeds 32767 UTF-8 bytes"));
                }
                self.write_u16((value.len() + 1) as u16);
                self.write_bytes(value.as_bytes());
            }
        }
        Ok(())
    }
    pub fn write_bytes_and_size(&mut self, value: Option<&[u8]>) -> Result<()> {
        match value {
            None => self.write_u32(0),
            Some(value) => {
                if value.len() > i32::MAX as usize {
                    return Err(Error::bad("Mirror byte array size overflows Int32"));
                }
                self.write_u32(value.len() as u32 + 1);
                self.write_bytes(value);
            }
        }
        Ok(())
    }
    pub fn write_guid(&mut self, value: [u8; 16]) {
        self.write_bytes(&value);
    }
    pub fn write_guid_nullable(&mut self, value: Option<[u8; 16]>) {
        self.write_bool(value.is_some());
        if let Some(value) = value {
            self.write_guid(value);
        }
    }
    pub fn write_uuid(&mut self, value: uuid::Uuid) {
        self.write_guid(value.to_bytes_le());
    }
    pub fn write_vector3(&mut self, value: [f32; 3]) {
        for element in value {
            self.write_f32(element);
        }
    }
    pub fn write_vector3_nullable(&mut self, value: Option<[f32; 3]>) {
        self.write_bool(value.is_some());
        if let Some(value) = value {
            self.write_vector3(value);
        }
    }
    pub fn write_quaternion(&mut self, value: [f32; 4]) {
        for element in value {
            self.write_f32(element);
        }
    }
    pub fn write_quaternion_nullable(&mut self, value: Option<[f32; 4]>) {
        self.write_bool(value.is_some());
        if let Some(value) = value {
            self.write_quaternion(value);
        }
    }
    pub fn write_var_u64(&mut self, value: u64) {
        if value <= 240 {
            self.write_u8(value as u8);
        } else if value <= 2287 {
            self.write_u8((((value - 240) >> 8) + 241) as u8);
            self.write_u8((value - 240) as u8);
        } else if value <= 67823 {
            self.write_u8(249);
            self.write_u8(((value - 2288) >> 8) as u8);
            self.write_u8((value - 2288) as u8);
        } else {
            let count = match value {
                0..=0x00ff_ffff => 3,
                0..=0xffff_ffff => 4,
                0..=0xff_ffff_ffff => 5,
                0..=0xffff_ffff_ffff => 6,
                0..=0xff_ffff_ffff_ffff => 7,
                _ => 8,
            };
            self.write_u8(247 + count as u8);
            self.write_bytes(&value.to_le_bytes()[..count]);
        }
    }
    pub fn write_var_i64(&mut self, value: i64) {
        self.write_var_u64(((value >> 63) ^ value.wrapping_shl(1)) as u64);
    }
    pub fn write_packed_u64(&mut self, value: u64) {
        self.write_var_u64(value);
    }
    pub fn write_packed_u32(&mut self, value: u32) {
        self.write_var_u64(value.into());
    }
}

pub fn stable_hash(text: &str) -> i32 {
    text.encode_utf16().fold(23i32, |hash, unit| {
        hash.wrapping_mul(31).wrapping_add(i32::from(unit))
    })
}
pub fn message_id(full_name: &str) -> u16 {
    stable_hash(full_name) as u16
}
pub fn pack_message(id: u16, payload: &[u8]) -> Vec<u8> {
    let mut writer = Writer::with_capacity(MESSAGE_HEADER_SIZE + payload.len());
    writer.write_u16(id);
    writer.write_bytes(payload);
    writer.into_inner()
}

/// No per-message size prefixes: preserve the exact serialized messages.
pub fn encode_batch(timestamp: f64, messages: &[Vec<u8>]) -> Vec<u8> {
    let mut writer = Writer::new();
    writer.write_f64(timestamp);
    for message in messages {
        writer.write_bytes(message);
    }
    writer.into_inner()
}
pub fn decode_batch(bytes: &[u8]) -> Result<(f64, Reader<'_>)> {
    let mut reader = Reader::new(bytes);
    let timestamp = reader.read_f64()?;
    Ok((timestamp, reader))
}

/// Mirror's threshold batching allows a large message to form its own batch.
pub struct Batcher {
    threshold: usize,
    ready: VecDeque<Vec<u8>>,
    current: Option<Vec<u8>>,
}
impl Batcher {
    pub fn new(threshold: usize) -> Self {
        Self {
            threshold,
            ready: VecDeque::new(),
            current: None,
        }
    }
    pub fn add_message(&mut self, message: &[u8], timestamp: f64) {
        if self
            .current
            .as_ref()
            .is_some_and(|batch| batch.len().saturating_add(message.len()) > self.threshold)
        {
            self.ready
                .push_back(self.current.take().expect("batch present"));
        }
        let batch = self
            .current
            .get_or_insert_with(|| timestamp.to_le_bytes().to_vec());
        batch.extend_from_slice(message);
    }
    pub fn get_batch(&mut self) -> Option<Vec<u8>> {
        self.ready.pop_front().or_else(|| self.current.take())
    }
}

/// Validate before allocating a Telepathy payload. A nonpositive signed size is invalid.
pub fn telepathy_payload_length(header: [u8; 4], max_message_size: usize) -> Result<usize> {
    let size = i32::from_be_bytes(header);
    if size <= 0 || size as usize > max_message_size {
        return Err(Error::bad("Invalid Telepathy message length"));
    }
    Ok(size as usize)
}
pub fn telepathy_frame(payload: &[u8], max_message_size: usize) -> Result<Vec<u8>> {
    if payload.is_empty() || payload.len() > max_message_size || payload.len() > i32::MAX as usize {
        return Err(Error::bad("Invalid Telepathy message length"));
    }
    let mut frame = Vec::with_capacity(4 + payload.len());
    frame.extend_from_slice(&(payload.len() as i32).to_be_bytes());
    frame.extend_from_slice(payload);
    Ok(frame)
}
/// Return one complete frame and consumed length, or None for an incomplete stream.
pub fn decode_telepathy(bytes: &[u8], max_message_size: usize) -> Result<Option<(&[u8], usize)>> {
    if bytes.len() < 4 {
        return Ok(None);
    }
    let size = telepathy_payload_length(
        bytes[..4].try_into().expect("header length"),
        max_message_size,
    )?;
    if bytes.len() - 4 < size {
        return Ok(None);
    }
    Ok(Some((&bytes[4..4 + size], 4 + size)))
}
