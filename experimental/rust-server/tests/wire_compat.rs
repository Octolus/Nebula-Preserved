use nebula_preserved_server::{mirror::*, wire};
use serde_json::{json, Value};

fn python() -> Value {
    serde_json::from_str(include_str!("wire_python_vectors.json")).unwrap()
}
fn csharp() -> Value {
    serde_json::from_str(include_str!("wire_csharp_vectors.json")).unwrap()
}
fn bytes(value: &Value) -> Vec<u8> {
    hex::decode(value.as_str().unwrap()).unwrap()
}

#[test]
fn python_crypto_vectors_cover_empty_blocks_unicode_and_delimiters() {
    for vector in python()["crypto"].as_array().unwrap() {
        let plaintext = vector["plaintext"].as_str().unwrap();
        let ciphertext = vector["ciphertext"].as_str().unwrap();
        assert_eq!(wire::encrypt(plaintext).unwrap(), ciphertext);
        assert_eq!(wire::decrypt(ciphertext).unwrap(), plaintext);
    }
    for vector in csharp()["crypto"].as_array().unwrap() {
        assert_eq!(
            wire::encrypt(vector["plaintext"].as_str().unwrap()).unwrap(),
            vector["ciphertext"]
        );
    }
}

#[test]
fn malformed_crypto_is_rejected_and_native_limit_is_separate() {
    let reference = python();
    for ciphertext in reference["invalid_ciphertexts"].as_array().unwrap() {
        assert!(
            wire::decrypt(ciphertext.as_str().unwrap()).is_err(),
            "{ciphertext}"
        );
    }
    assert_eq!(
        wire::decrypt(reference["noncanonical_base64"].as_str().unwrap()).unwrap(),
        ""
    );
    assert_eq!(csharp()["noncanonical_base64"], "");
    let large = "#🚀".repeat(10_000);
    let encrypted = wire::encrypt(&large).unwrap();
    assert!(encrypted.len() > 65_532);
    assert_eq!(wire::decrypt(&encrypted).unwrap(), large);
    assert!(wire::decrypt_client(&encrypted).is_err());
    for bad in [
        "QrnGrub9EXAqpBYR/qr3Gw==\n",
        "QrnGrub9EXAqpBYR/qr3Gw===",
        "QrnGrub9EXAqpBYR/qr3G===",
    ] {
        assert!(wire::decrypt(bad).is_err());
    }
}

#[test]
fn request_platform_and_python_maxsplit_vectors() {
    let reference = python();
    for vector in reference["requests"].as_array().unwrap() {
        let limit = vector["maxsplit"].as_u64().map(|v| v as usize);
        let request = wire::Request::parse(vector["plaintext"].as_str().unwrap(), limit).unwrap();
        assert_eq!(
            serde_json::to_value(&request.fields).unwrap(),
            vector["fields"]
        );
        assert_eq!(request.platform, vector["platform"].as_str().unwrap());
        assert_eq!(
            request.require(request.fields.len()).unwrap(),
            request.fields
        );
        assert!(request.require(request.fields.len() + 1).is_err());
    }
    for plaintext in reference["invalid_requests"].as_array().unwrap() {
        let error = wire::Request::parse(plaintext.as_str().unwrap(), None).unwrap_err();
        assert_eq!(error.status, 400);
    }
    assert_eq!(
        wire::Request::parse("a#b#PS4", Some(usize::MAX))
            .unwrap()
            .fields,
        ["a", "b"]
    );
}

#[test]
fn session_guids_and_ascii_json_match_python_vectors() {
    let reference = python();
    for vector in reference["sessions"].as_array().unwrap() {
        assert_eq!(
            wire::session_guid(
                vector["id"].as_str().unwrap(),
                vector["request_hash"].as_str().unwrap()
            ),
            vector["guid"]
        );
    }
    for vector in reference["json"].as_array().unwrap() {
        let field = wire::json_field(&vector["value"]).unwrap();
        assert_eq!(
            field,
            vector["field"].as_str().unwrap(),
            "JSON input {}",
            vector["value"]
        );
        assert!(!field.contains('#'));
        assert!(field.is_ascii());
        assert_eq!(
            serde_json::from_str::<Value>(&field).unwrap(),
            vector["value"]
        );
    }
}

#[test]
fn mirror_strings_match_shipped_csharp_and_enforce_utf8_byte_limit() {
    for vector in csharp()["strings"].as_array().unwrap() {
        let mut writer = Writer::new();
        writer.write_string(vector["value"].as_str()).unwrap();
        assert_eq!(hex::encode(writer.as_slice()), vector["hex"]);
        let mut reader = Reader::new(writer.as_slice());
        assert_eq!(
            reader.read_string().unwrap().as_deref(),
            vector["value"].as_str()
        );
        reader.finish().unwrap();
    }
    let mut writer = Writer::new();
    writer.write_string(Some(&"a".repeat(32_767))).unwrap();
    assert!(writer.write_string(Some(&"a".repeat(32_768))).is_err());
    assert!(writer.write_string(Some(&"é".repeat(16_384))).is_err());
    for malformed in [vec![1], vec![2, 0], vec![3, 0, 0xff, 0xff], vec![1, 128]] {
        assert!(Reader::new(&malformed).read_string().is_err());
    }
}

#[test]
fn mirror_primitives_and_float_bits_match_shipped_csharp() {
    let reference = csharp();
    let expected = bytes(&reference["primitives"]);
    let mut writer = Writer::new();
    writer.write_u8(0xab);
    writer.write_i8(-7);
    writer.write_u16(0x1234);
    writer.write_i16(-300);
    writer.write_u32(0x89abcdef);
    writer.write_i32(-123456789);
    writer.write_u64(0x0123456789abcdef);
    writer.write_i64(i64::MIN);
    writer.write_f32(-0.0);
    writer.write_f32(f32::INFINITY);
    writer.write_f64(-123.5);
    writer.write_bool(true);
    writer.write_bool(false);
    writer.write_char(0xd800);
    assert_eq!(writer.as_slice(), expected);
    let mut reader = Reader::new(&expected);
    assert_eq!(reader.read_u8().unwrap(), 0xab);
    assert_eq!(reader.read_i8().unwrap(), -7);
    assert_eq!(reader.read_u16().unwrap(), 0x1234);
    assert_eq!(reader.read_i16().unwrap(), -300);
    assert_eq!(reader.read_u32().unwrap(), 0x89abcdef);
    assert_eq!(reader.read_i32().unwrap(), -123456789);
    assert_eq!(reader.read_u64().unwrap(), 0x0123456789abcdef);
    assert_eq!(reader.read_i64().unwrap(), i64::MIN);
    assert_eq!(reader.read_f32().unwrap().to_bits(), (-0.0f32).to_bits());
    assert_eq!(reader.read_f32().unwrap(), f32::INFINITY);
    assert_eq!(reader.read_f64().unwrap(), -123.5);
    assert!(reader.read_bool().unwrap());
    assert!(!reader.read_bool().unwrap());
    assert_eq!(reader.read_char().unwrap(), 0xd800);
    reader.finish().unwrap();
    let nan_bits = 0x7fa12345u32.to_le_bytes();
    assert_eq!(
        Reader::new(&nan_bits).read_f32().unwrap().to_bits(),
        0x7fa12345
    );
}

#[test]
fn mirror_nullables_guid_and_byte_arrays_match_shipped_csharp() {
    let reference = csharp();
    let guid = uuid::Uuid::parse_str("00112233-4455-6677-8899-aabbccddeeff").unwrap();
    let mut writer = Writer::new();
    writer.write_i32_nullable(None);
    writer.write_i32_nullable(Some(-123));
    writer.write_bool_nullable(None);
    writer.write_bool_nullable(Some(false));
    writer.write_bool_nullable(Some(true));
    writer.write_f32_nullable(Some(1.25));
    writer.write_f32_nullable(None);
    writer.write_guid_nullable(None);
    writer.write_guid_nullable(Some(guid.to_bytes_le()));
    assert_eq!(hex::encode(writer.as_slice()), reference["nullable"]);
    let mut reader = Reader::new(writer.as_slice());
    assert_eq!(reader.read_i32_nullable().unwrap(), None);
    assert_eq!(reader.read_i32_nullable().unwrap(), Some(-123));
    assert_eq!(reader.read_bool_nullable().unwrap(), None);
    assert_eq!(reader.read_bool_nullable().unwrap(), Some(false));
    assert_eq!(reader.read_bool_nullable().unwrap(), Some(true));
    assert_eq!(reader.read_f32_nullable().unwrap(), Some(1.25));
    assert_eq!(reader.read_f32_nullable().unwrap(), None);
    assert_eq!(reader.read_guid_nullable().unwrap(), None);
    assert_eq!(
        reader.read_guid_nullable().unwrap(),
        Some(guid.to_bytes_le())
    );
    reader.finish().unwrap();
    let mut writer = Writer::new();
    writer.write_uuid(guid);
    assert_eq!(hex::encode(writer.as_slice()), reference["guid"]);
    assert_eq!(Reader::new(writer.as_slice()).read_uuid().unwrap(), guid);
    let mut writer = Writer::new();
    writer.write_bytes_and_size(None).unwrap();
    writer.write_bytes_and_size(Some(&[])).unwrap();
    writer.write_bytes_and_size(Some(&[0, 128, 255])).unwrap();
    assert_eq!(hex::encode(writer.as_slice()), reference["bytes"]);
    let mut reader = Reader::new(writer.as_slice());
    assert_eq!(reader.read_bytes_and_size().unwrap(), None);
    assert_eq!(reader.read_bytes_and_size().unwrap(), Some(vec![]));
    assert_eq!(
        reader.read_bytes_and_size().unwrap(),
        Some(vec![0, 128, 255])
    );
    reader.finish().unwrap();
    assert_eq!(
        Reader::new(&[2, 123, 0, 0, 0]).read_i32_nullable().unwrap(),
        Some(123)
    );
    assert!(Reader::new(&[1]).read_i32_nullable().is_err());
    assert!(Reader::new(&[255, 255, 255, 255])
        .read_bytes_and_size()
        .is_err());
    assert!(Reader::new(&[4, 0, 0, 0, 1]).read_bytes_and_size().is_err());
}

#[test]
fn mirror_varints_match_all_csharp_encoding_boundaries_and_reject_truncation() {
    let reference = csharp();
    for vector in reference["varuint"].as_array().unwrap() {
        let value: u64 = vector["value"].as_str().unwrap().parse().unwrap();
        let expected = bytes(&vector["hex"]);
        let mut writer = Writer::new();
        writer.write_var_u64(value);
        assert_eq!(writer.as_slice(), expected);
        let mut reader = Reader::new(&expected);
        assert_eq!(reader.read_var_u64().unwrap(), value);
        reader.finish().unwrap();
        for length in 0..expected.len() {
            assert!(Reader::new(&expected[..length]).read_var_u64().is_err());
        }
    }
    for vector in reference["varint"].as_array().unwrap() {
        let value: i64 = vector["value"].as_str().unwrap().parse().unwrap();
        let expected = bytes(&vector["hex"]);
        let mut writer = Writer::new();
        writer.write_var_i64(value);
        assert_eq!(writer.as_slice(), expected);
        assert_eq!(Reader::new(&expected).read_var_i64().unwrap(), value);
    }
    // Mirror accepts overlong encodings rather than imposing canonical varints.
    assert_eq!(Reader::new(&[250, 1, 0, 0]).read_var_u64().unwrap(), 1);
}

#[test]
fn mirror_stable_ids_batches_and_spawn_fields_match_csharp() {
    let reference = csharp();
    for (signature, hash) in reference["hashes"].as_object().unwrap() {
        assert_eq!(stable_hash(signature), hash.as_i64().unwrap() as i32);
        assert_eq!(message_id(signature), hash.as_i64().unwrap() as u16);
    }
    let mut batcher = Batcher::new(15);
    batcher.add_message(&[1, 2, 3], 1.5);
    batcher.add_message(&[4, 5, 6, 7], 2.5);
    batcher.add_message(&[8], 3.5);
    batcher.add_message(&[0; 20], 4.5);
    for expected in reference["batches"].as_array().unwrap() {
        assert_eq!(
            hex::encode(batcher.get_batch().unwrap()),
            expected.as_str().unwrap()
        );
    }
    assert!(batcher.get_batch().is_none());
    let messages = vec![pack_message(1, &[2, 3]), pack_message(4, &[5])];
    let encoded = encode_batch(1.25, &messages);
    let (timestamp, mut reader) = decode_batch(&encoded).unwrap();
    assert_eq!(timestamp, 1.25);
    assert_eq!(reader.read_u16().unwrap(), 1);
    assert_eq!(reader.read_bytes(2).unwrap(), &[2, 3]);
    assert_eq!(reader.read_u16().unwrap(), 4);
    assert_eq!(reader.read_u8().unwrap(), 5);
    reader.finish().unwrap();
    assert!(decode_batch(&[0; 7]).is_err());
    assert_eq!(decode_batch(&[0; 8]).unwrap().1.remaining(), 0);
    let mut initial = Writer::new();
    initial.write_u8(0);
    initial.write_i32(28);
    initial.write_vector3([1.0, -2.0, 3.5]);
    initial.write_quaternion([0.0, 0.0, 0.0, 1.0]);
    initial.write_u8(1);
    initial.write_i32(4);
    initial.write_f32(4.5);
    assert_eq!(hex::encode(initial.as_slice()), reference["spawn_initial"]);
    let mut delta = Writer::new();
    delta.write_u8(1);
    delta.write_i32(12);
    delta.write_u64(1);
    delta.write_f32(4.5);
    assert_eq!(hex::encode(delta.as_slice()), reference["speed_delta"]);
}

#[test]
fn telepathy_big_endian_frames_handle_fragments_multiple_frames_and_invalid_sizes() {
    assert_eq!(csharp()["telepathy_header"], "00123456");
    assert_eq!(
        telepathy_payload_length([0, 0x12, 0x34, 0x56], 0x123456).unwrap(),
        0x123456
    );
    let frame = telepathy_frame(&[1, 2, 3], 3).unwrap();
    assert_eq!(frame, [0, 0, 0, 3, 1, 2, 3]);
    for size in 0..frame.len() {
        assert!(decode_telepathy(&frame[..size], 3).unwrap().is_none());
    }
    let stream = [frame.clone(), frame.clone()].concat();
    let (payload, consumed) = decode_telepathy(&stream, 3).unwrap().unwrap();
    assert_eq!(payload, [1, 2, 3]);
    assert_eq!(consumed, frame.len());
    assert!(decode_telepathy(&stream[consumed..], 3).unwrap().is_some());
    for header in [[0, 0, 0, 0], [255; 4], [128, 0, 0, 0], [0, 0, 0, 4]] {
        assert!(telepathy_payload_length(header, 3).is_err());
        assert!(decode_telepathy(&header, 3).is_err());
    }
    assert!(telepathy_frame(&[], 3).is_err());
    assert!(telepathy_frame(&[0; 4], 3).is_err());
}

#[test]
fn vector_nullables_preserve_float_bytes_and_missing_fields_fail() {
    let mut writer = Writer::new();
    writer.write_vector3_nullable(Some([1.0, -0.0, f32::from_bits(1)]));
    writer.write_quaternion_nullable(None);
    let mut reader = Reader::new(writer.as_slice());
    let values = reader.read_vector3_nullable().unwrap().unwrap();
    assert_eq!(
        values.map(f32::to_bits),
        [1.0f32.to_bits(), (-0.0f32).to_bits(), 1]
    );
    assert_eq!(reader.read_quaternion_nullable().unwrap(), None);
    reader.finish().unwrap();
    assert!(Reader::new(&[1, 0]).read_vector3_nullable().is_err());
    assert_eq!(
        wire::json_field(&json!({"#": "\\u0023"})).unwrap(),
        "{\"\\u0023\":\"\\\\u0023\"}"
    );
}

#[test]
fn malformed_behavior_matches_executed_csharp_reference() {
    let cases = &csharp()["malformed"];
    assert_eq!(
        Reader::new(&[3, 0, 255, 255]).read_string().is_err(),
        cases["string_invalid_utf8"]
    );
    assert_eq!(
        Reader::new(&[2, 0]).read_string().is_err(),
        cases["string_truncated"]
    );
    assert_eq!(
        Writer::new()
            .write_string(Some(&"a".repeat(32768)))
            .is_err(),
        cases["string_limit"]
    );
    assert_eq!(
        Reader::new(&[1]).read_i32_nullable().is_err(),
        cases["nullable_truncated"]
    );
    assert_eq!(
        Reader::new(&[255; 4]).read_bytes_and_size().is_err(),
        cases["bytes_size_overflow"]
    );
    assert_eq!(
        Reader::new(&[4, 0, 0, 0, 1]).read_bytes_and_size().is_err(),
        cases["bytes_truncated"]
    );
    assert_eq!(
        Reader::new(&[2]).read_bool().unwrap(),
        cases["bool_nonzero"]
    );
    assert_eq!(decode_batch(&[0; 7]).is_ok(), cases["batch_short_accepted"]);
    assert_eq!(
        decode_batch(&[0; 8]).is_ok(),
        cases["batch_timestamp_only_accepted"]
    );
    assert_eq!(
        decode_batch(&[0; 8]).unwrap().1.remaining() > 0,
        cases["batch_timestamp_only_has_message"]
    );
}
