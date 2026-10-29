//! Matches preservation public_access.py credentials, with no secret logging.
use crate::{
    error::{Error, Result},
    state::State,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use rusqlite::OptionalExtension;
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};
use subtle::ConstantTimeEq;
fn cache() -> &'static Mutex<HashMap<[u8; 32], Instant>> {
    static CACHE: OnceLock<Mutex<HashMap<[u8; 32], Instant>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}
pub fn initialize(state: &State) -> Result<()> {
    let db = state.connection()?;
    db.execute_batch("CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY,applied_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS public_access_credentials(ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id) ON DELETE CASCADE,salt BLOB NOT NULL CHECK(length(salt)=16),verifier BLOB NOT NULL CHECK(length(verifier)=32),provenance_kind TEXT CHECK(provenance_kind IS NULL OR provenance_kind='operator-note'),provenance_evidence_sha256 TEXT CHECK(provenance_evidence_sha256 IS NULL OR length(provenance_evidence_sha256)=64),created_at REAL NOT NULL,revoked_at REAL);
    CREATE TABLE IF NOT EXISTS public_access_operator(singleton INTEGER PRIMARY KEY CHECK(singleton=1),salt BLOB NOT NULL CHECK(length(salt)=16),verifier BLOB NOT NULL CHECK(length(verifier)=32),created_at REAL NOT NULL);")?;
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations(name,applied_at) VALUES('public-access-v2',?)",
        [state.now()],
    )?;
    Ok(())
}
pub fn authenticate(state: &State, authorization: Option<&str>) -> Result<String> {
    let deny = || Error::new(403, "Invalid account credential");
    let payload = authorization
        .and_then(|s| s.strip_prefix("Nebula-Account-v1 "))
        .ok_or_else(deny)?;
    let (encoded, token) = payload.split_once('.').ok_or_else(deny)?;
    if encoded.len() > 64
        || token.len() != 43
        || !token
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    {
        return Err(deny());
    }
    let account = String::from_utf8(URL_SAFE_NO_PAD.decode(encoded).map_err(|_| deny())?)
        .map_err(|_| deny())?;
    if account.len() != 17
        || !account.starts_with("7656119")
        || !account.bytes().all(|c| c.is_ascii_digit())
    {
        return Err(deny());
    }
    let row: Option<(Vec<u8>, Vec<u8>)> = {
        let db = state.connection()?;
        db.query_row("SELECT salt,verifier FROM public_access_credentials WHERE ps4_id=? AND revoked_at IS NULL",[&account],|r|Ok((r.get(0)?,r.get(1)?))).optional()?
    };
    // Cache only successful KDF proofs, bound to the currently active DB salt
    // and verifier. Every request still checks revocation/rotation in SQLite.
    // Raw credentials never enter this bounded, short-lived cache.
    let key = row.as_ref().map(|(salt, verifier)| {
        let mut h = Sha256::new();
        h.update(account.as_bytes());
        h.update([0]);
        h.update(salt);
        h.update(verifier);
        h.update(Sha256::digest(token.as_bytes()));
        <[u8; 32]>::from(h.finalize())
    });
    if let Some(key) = key {
        if cache()
            .lock()
            .map_err(|_| Error::new(500, "Credential cache unavailable"))?
            .get(&key)
            .is_some_and(|t| t.elapsed() < Duration::from_secs(30))
        {
            return Ok(account);
        }
    }
    let salt = row.as_ref().map(|r| r.0.as_slice()).unwrap_or(&[0u8; 16]);
    let params = scrypt::Params::new(15, 8, 1, 32).map_err(|_| deny())?;
    let mut derived = [0u8; 32];
    scrypt::scrypt(token.as_bytes(), salt, &params, &mut derived).map_err(|_| deny())?;
    if !row
        .as_ref()
        .is_some_and(|(_, v)| v.len() == 32 && bool::from(derived.as_slice().ct_eq(v)))
    {
        return Err(deny());
    }
    // A concurrent rotation or revocation during the slow KDF invalidates this
    // request too; copied verifier bytes are not a lease on the old credential.
    let active: bool = {
        let db = state.connection()?;
        let (salt, verifier) = row.as_ref().unwrap();
        db.query_row("SELECT EXISTS(SELECT 1 FROM public_access_credentials WHERE ps4_id=? AND salt=? AND verifier=? AND revoked_at IS NULL)",rusqlite::params![account,salt,verifier],|r|r.get(0))?
    };
    if !active {
        return Err(deny());
    }
    if let Some(key) = key {
        let mut entries = cache()
            .lock()
            .map_err(|_| Error::new(500, "Credential cache unavailable"))?;
        entries.retain(|_, t| t.elapsed() < Duration::from_secs(30));
        if entries.len() >= 512 {
            entries.clear();
        }
        entries.insert(key, Instant::now());
    }
    Ok(account)
}
