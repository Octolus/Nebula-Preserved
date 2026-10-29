//! Internal management authority. Credentials are supplied explicitly at startup;
//! game credentials and client role headers never confer operator permissions.
use crate::{
    services::{flag, n, one, rows, s},
    state::State,
};
use rusqlite::{params, types::Value as SqlValue, Connection};
use serde_json::{json, Value};
use std::{
    collections::{HashMap, HashSet},
    path::{Path, PathBuf},
    sync::{Mutex, OnceLock},
};

pub const PREFIX: &str = "/management/v1";
pub const MAX_BODY: usize = 16 * 1024;
const MAX_BALANCE: i64 = 2_147_483_647;
const MAX_UTC: i64 = 253_402_300_799;
const ROLES: [&str; 3] = ["moderator", "admin", "owner"];
const MODERATOR: &[&str] = &[
    "read",
    "moderation.ban",
    "moderation.kick",
    "moderation.mute",
    "moderation.reports",
];
const ADMIN: &[&str] = &[
    "read",
    "wallet.adjust",
    "items.grant",
    "users.rename",
    "moderation.ban",
    "moderation.kick",
    "moderation.mute",
    "moderation.reports",
    "moderation.maintenance",
    "moderation.news",
];
const OWNER: &[&str] = &[
    "read",
    "wallet.adjust",
    "items.grant",
    "users.rename",
    "operators.manage",
    "moderation.ban",
    "moderation.kick",
    "moderation.mute",
    "moderation.reports",
    "moderation.maintenance",
    "moderation.news",
    "players.staff",
];
static TOKENS: OnceLock<Mutex<HashMap<PathBuf, Vec<u8>>>> = OnceLock::new();
#[derive(Debug, Clone)]
pub struct AdminResponse {
    pub status: u16,
    pub body: Value,
}
#[derive(Debug)]
struct Failure {
    status: u16,
    code: &'static str,
    message: String,
}
type Result<T> = std::result::Result<T, Failure>;
impl Failure {
    fn new(status: u16, code: &'static str, message: impl Into<String>) -> Self {
        Self {
            status,
            code,
            message: message.into(),
        }
    }
    fn invalid(message: impl Into<String>) -> Self {
        Self::new(400, "invalid_request", message)
    }
    fn forbidden(message: impl Into<String>) -> Self {
        Self::new(403, "forbidden", message)
    }
    fn conflict(message: impl Into<String>) -> Self {
        Self::new(409, "conflict", message)
    }
    fn missing(message: impl Into<String>) -> Self {
        Self::new(404, "not_found", message)
    }
}
impl From<crate::error::Error> for Failure {
    fn from(e: crate::error::Error) -> Self {
        if e.sqlite_code == Some(rusqlite::ErrorCode::ConstraintViolation) {
            return Self::conflict("The command could not be committed");
        }
        if e.status == 500 {
            return Self::new(
                503,
                "temporarily_unavailable",
                "Retry this command with the same idempotency key",
            );
        }
        let code = match e.status {
            403 => "forbidden",
            404 => "not_found",
            409 => "conflict",
            _ => "invalid_request",
        };
        Self::new(e.status, code, e.message)
    }
}
impl From<rusqlite::Error> for Failure {
    fn from(e: rusqlite::Error) -> Self {
        if let rusqlite::Error::SqliteFailure(ref inner, _) = e {
            if inner.code == rusqlite::ErrorCode::ConstraintViolation {
                return Self::conflict("The command could not be committed");
            }
        }
        Self::new(
            503,
            "temporarily_unavailable",
            "Retry this command with the same idempotency key",
        )
    }
}
impl From<std::io::Error> for Failure {
    fn from(_: std::io::Error) -> Self {
        Self::new(
            503,
            "temporarily_unavailable",
            "Management state is unavailable",
        )
    }
}
impl From<serde_json::Error> for Failure {
    fn from(_: serde_json::Error) -> Self {
        Self::invalid("Invalid JSON body")
    }
}
fn check(ok: bool, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(Failure::invalid(message))
    }
}
fn permissions(role: &str) -> &'static [&'static str] {
    match role {
        "moderator" => MODERATOR,
        "admin" => ADMIN,
        "owner" => OWNER,
        _ => &[],
    }
}
fn operator_id(v: &str) -> bool {
    let mut b = v.bytes();
    matches!(b.next(),Some(c)if c.is_ascii_alphanumeric())
        && v.len() <= 64
        && b.all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(&c))
}
fn key_id(v: &str) -> bool {
    v.len() >= 8
        && v.len() <= 128
        && v.as_bytes()[0].is_ascii_alphanumeric()
        && v.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_.:-".contains(&c))
}
fn wire_hex(v: &str, len: usize) -> bool {
    v.len() == len
        && v.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn text<'a>(value: &'a Value, label: &str, max: usize) -> Result<&'a str> {
    let value = value
        .as_str()
        .ok_or_else(|| Failure::invalid(format!("Invalid {label}")))?;
    check(
        !value.trim().is_empty()
            && value.chars().count() <= max
            && !value.chars().any(|c| c < ' ' || c == '\u{7f}'),
        &format!("Invalid {label}"),
    )?;
    Ok(value)
}
fn wire_text<'a>(value: &'a Value, label: &str, max: usize, empty: bool) -> Result<&'a str> {
    // Unicode 15.0 data is pinned to the recovered Python 3.12 authority.
    // A newer assigned codepoint (for example U+1C89) remains disallowed here.
    use unicode_general_category::{get_general_category, GeneralCategory::*};
    let value = value
        .as_str()
        .ok_or_else(|| Failure::invalid(format!("Invalid {label}")))?;
    check(
        (empty || !value.trim().is_empty())
            && value.chars().count() <= max
            && !value.contains('#')
            && !value.chars().any(|c| {
                matches!(
                    get_general_category(c),
                    Control | Format | PrivateUse | Surrogate | Unassigned
                )
            }),
        &format!("Invalid {label}"),
    )?;
    Ok(value)
}
fn fields(body: &Value, allowed: &[&str]) -> Result<()> {
    check(
        body.as_object()
            .is_some_and(|m| m.keys().all(|k| allowed.contains(&k.as_str()))),
        "Unexpected request fields",
    )
}
fn header<'a>(headers: &'a HashMap<String, String>, name: &str) -> Option<&'a str> {
    headers
        .iter()
        .find(|(k, _)| k.eq_ignore_ascii_case(name))
        .map(|(_, v)| v.as_str())
}
fn constant_eq(a: &[u8], b: &[u8]) -> bool {
    let mut diff = a.len() ^ b.len();
    for i in 0..512 {
        diff |= usize::from(a.get(i).copied().unwrap_or(0) ^ b.get(i).copied().unwrap_or(0));
    }
    diff == 0
}
fn canonical(value: &Value) -> String {
    fn ordered(v: &Value) -> Value {
        match v {
            Value::Object(m) => {
                let mut out = serde_json::Map::new();
                let mut keys: Vec<_> = m.keys().collect();
                keys.sort();
                for k in keys {
                    out.insert(k.clone(), ordered(&m[k]));
                }
                Value::Object(out)
            }
            Value::Array(v) => Value::Array(v.iter().map(ordered).collect()),
            v => v.clone(),
        }
    }
    crate::services::ascii_json(&ordered(value))
}
fn registry_key(state: &State) -> PathBuf {
    std::fs::canonicalize(state.state_dir.as_path())
        .unwrap_or_else(|_| state.state_dir.as_ref().clone())
}
fn core_error(e: Failure) -> crate::error::Error {
    crate::error::Error::new(e.status, e.message)
}

/// Parse JSON without accepting duplicate keys at any nesting level. The
/// listener should call this before `handle` for raw POST request bodies.
pub fn parse_body(raw: &[u8]) -> std::result::Result<Value, AdminResponse> {
    strict_json(raw, MAX_BODY).map_err(response_error)
}
fn strict_json(raw: &[u8], maximum: usize) -> Result<Value> {
    if raw.len() > maximum {
        return Err(Failure::new(
            413,
            "invalid_request",
            "Request body is too large",
        ));
    }
    struct Strict(Value);
    impl<'de> serde::Deserialize<'de> for Strict {
        fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
            struct V;
            impl<'de> serde::de::Visitor<'de> for V {
                type Value = Strict;
                fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                    f.write_str("JSON value with unique object keys")
                }
                fn visit_bool<E: serde::de::Error>(
                    self,
                    v: bool,
                ) -> std::result::Result<Strict, E> {
                    Ok(Strict(json!(v)))
                }
                fn visit_i64<E: serde::de::Error>(self, v: i64) -> std::result::Result<Strict, E> {
                    Ok(Strict(json!(v)))
                }
                fn visit_u64<E: serde::de::Error>(self, v: u64) -> std::result::Result<Strict, E> {
                    Ok(Strict(json!(v)))
                }
                fn visit_f64<E: serde::de::Error>(self, v: f64) -> std::result::Result<Strict, E> {
                    serde_json::Number::from_f64(v)
                        .map(|n| Strict(Value::Number(n)))
                        .ok_or_else(|| E::custom("Non-finite JSON"))
                }
                fn visit_str<E: serde::de::Error>(self, v: &str) -> std::result::Result<Strict, E> {
                    Ok(Strict(json!(v)))
                }
                fn visit_string<E: serde::de::Error>(
                    self,
                    v: String,
                ) -> std::result::Result<Strict, E> {
                    Ok(Strict(json!(v)))
                }
                fn visit_none<E: serde::de::Error>(self) -> std::result::Result<Strict, E> {
                    Ok(Strict(Value::Null))
                }
                fn visit_unit<E: serde::de::Error>(self) -> std::result::Result<Strict, E> {
                    Ok(Strict(Value::Null))
                }
                fn visit_seq<A: serde::de::SeqAccess<'de>>(
                    self,
                    mut seq: A,
                ) -> std::result::Result<Strict, A::Error> {
                    let mut out = Vec::new();
                    while let Some(v) = seq.next_element::<Strict>()? {
                        out.push(v.0);
                    }
                    Ok(Strict(json!(out)))
                }
                fn visit_map<A: serde::de::MapAccess<'de>>(
                    self,
                    mut map: A,
                ) -> std::result::Result<Strict, A::Error> {
                    let mut out = serde_json::Map::new();
                    while let Some((k, v)) = map.next_entry::<String, Strict>()? {
                        if out.insert(k, v.0).is_some() {
                            return Err(serde::de::Error::custom("Duplicate JSON field"));
                        }
                    }
                    Ok(Strict(Value::Object(out)))
                }
            }
            d.deserialize_any(V)
        }
    }
    let parsed = (|| -> std::result::Result<Value, serde_json::Error> {
        let mut d = serde_json::Deserializer::from_slice(raw);
        let value = <Strict as serde::Deserialize>::deserialize(&mut d)?.0;
        d.end()?;
        Ok(value)
    })();
    match parsed {
        Ok(v) if v.is_object() => Ok(v),
        Ok(_) => Err(Failure::invalid("JSON object required")),
        Err(e) if e.to_string().starts_with("Duplicate JSON field") => {
            Err(Failure::invalid("Duplicate JSON field"))
        }
        Err(_) => Err(Failure::invalid("Invalid JSON body")),
    }
}
pub fn load_secret_file(path: &Path) -> crate::error::Result<Vec<u8>> {
    (move || -> Result<Vec<u8>> {
        let m = std::fs::symlink_metadata(path)?;
        check(
            m.is_file() && !m.file_type().is_symlink(),
            "A regular management token file is required",
        )?;
        let mut bytes = std::fs::read(path)?;
        check(bytes.len() <= 1024, "Management token file is too large")?;
        while bytes.last().is_some_and(|b| [b'\r', b'\n'].contains(b)) {
            bytes.pop();
        }
        check(
            (32..=512).contains(&bytes.len()) && bytes.iter().all(|b| (33..=126).contains(b)),
            "Management token must contain 32 to 512 printable non-space characters",
        )?;
        Ok(bytes)
    })()
    .map_err(core_error)
}
fn operators(value: &Value, file_defaults: bool) -> Result<Vec<Value>> {
    let list = value
        .as_array()
        .ok_or_else(|| Failure::invalid("Explicit operator bootstrap required"))?;
    check(
        !list.is_empty() && (!file_defaults || list.len() <= 100),
        if file_defaults {
            "Operator configuration requires an explicit operator list"
        } else {
            "Explicit operator bootstrap required"
        },
    )?;
    let mut out = Vec::new();
    let mut ids = HashSet::new();
    for row in list {
        fields(row, &["id", "role", "enabled", "password_scrypt"])?;
        let id = s(row, "id");
        let role = s(row, "role");
        let enabled = if file_defaults && !row.as_object().unwrap().contains_key("enabled") {
            Some(true)
        } else {
            row["enabled"].as_bool()
        };
        check(
            operator_id(id) && ROLES.contains(&role) && enabled.is_some(),
            if file_defaults {
                "Invalid operator identity, role or enabled flag"
            } else {
                "Invalid operator bootstrap"
            },
        )?;
        check(ids.insert(id), "Duplicate operator identity")?;
        out.push(json!({"id":id,"role":role,"enabled":enabled.unwrap()}));
    }
    Ok(out)
}
pub fn load_operator_file(path: &Path) -> crate::error::Result<Value> {
    (move || -> Result<Value> {
        let m = std::fs::symlink_metadata(path)?;
        check(
            m.is_file() && !m.file_type().is_symlink() && m.len() <= 65536,
            "A regular bounded operator configuration file is required",
        )?;
        let raw = std::fs::read(path)?;
        let value = strict_json(&raw, 65536)
            .map_err(|_| Failure::invalid("Invalid operator configuration"))?;
        check(
            value
                .as_object()
                .is_some_and(|m| m.len() == 1 && m.contains_key("operators")),
            "Operator configuration requires an explicit operator list",
        )?;
        let rows = operators(&value["operators"], true)?;
        check(
            rows.iter()
                .any(|r| s(r, "role") == "owner" && r["enabled"] == true),
            "At least one enabled owner is required",
        )?;
        Ok(json!(rows))
    })()
    .map_err(core_error)
}

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS management_operators(operator_id TEXT PRIMARY KEY,role TEXT NOT NULL CHECK(role IN('owner','admin','moderator')),enabled INTEGER NOT NULL CHECK(enabled IN(0,1)),created_at REAL NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS management_audit(audit_id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT NOT NULL UNIQUE,actor_id TEXT NOT NULL,actor_role TEXT NOT NULL,operation TEXT NOT NULL,target_id TEXT NOT NULL,reason TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS management_requests(actor_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,request_sha256 TEXT NOT NULL,response_json TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(actor_id,idempotency_key));
CREATE TABLE IF NOT EXISTS management_wallet_ledger(ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT NOT NULL UNIQUE,actor_id TEXT NOT NULL,account_id TEXT NOT NULL REFERENCES profiles(ps4_id),currency TEXT NOT NULL CHECK(currency IN('crystals','np')),delta INTEGER NOT NULL,before_balance INTEGER NOT NULL,after_balance INTEGER NOT NULL,reason TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS management_operator_accounts(operator_id TEXT PRIMARY KEY REFERENCES management_operators(operator_id),account_id TEXT NOT NULL UNIQUE REFERENCES profiles(ps4_id));
CREATE TRIGGER IF NOT EXISTS management_audit_no_update BEFORE UPDATE ON management_audit BEGIN SELECT RAISE(ABORT,'Management audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS management_audit_no_delete BEFORE DELETE ON management_audit BEGIN SELECT RAISE(ABORT,'Management audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS management_requests_no_update BEFORE UPDATE ON management_requests BEGIN SELECT RAISE(ABORT,'Management request receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS management_requests_no_delete BEFORE DELETE ON management_requests BEGIN SELECT RAISE(ABORT,'Management request receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS management_ledger_no_update BEFORE UPDATE ON management_wallet_ledger BEGIN SELECT RAISE(ABORT,'Management wallet ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS management_ledger_no_delete BEFORE DELETE ON management_wallet_ledger BEGIN SELECT RAISE(ABORT,'Management wallet ledger is append-only'); END;
"#;
pub fn initialize(state: &State, token: &[u8], operator_list: &Value) -> crate::error::Result<()> {
    (move || -> Result<()> {
        check(
            (32..=512).contains(&token.len()),
            "Explicit management token required",
        )?;
        let cleaned = operators(operator_list, false)?;
        let mut db = state.connection()?;
        db.execute_batch(SCHEMA)?;
        let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        if one(&tx, "SELECT 1 FROM management_operators LIMIT 1", [])?.is_none() {
            check(
                cleaned
                    .iter()
                    .any(|r| s(r, "role") == "owner" && r["enabled"] == true),
                "At least one enabled owner is required",
            )?;
            for row in cleaned {
                tx.execute(
                    "INSERT INTO management_operators VALUES(?,?,?,?,?)",
                    params![
                        s(&row, "id"),
                        s(&row, "role"),
                        flag(&row, "enabled") as i64,
                        state.now(),
                        state.now()
                    ],
                )?;
                audit(
                    state,
                    &tx,
                    &crate::services::uuid(),
                    &json!({"id":"bootstrap","role":"owner"}),
                    "operators.bootstrap",
                    s(&row, "id"),
                    "Explicit operator file initialization",
                    &Value::Null,
                    &row,
                )?;
            }
        }
        check(
            one(
                &tx,
                "SELECT 1 FROM management_operators WHERE role='owner' AND enabled=1",
                [],
            )?
            .is_some(),
            "No enabled management owner exists",
        )?;
        for row in rows(&tx, "SELECT guid,target,option FROM local_reports", [])? {
            let id = crate::services::hash(&canonical(&json!([
                row["guid"],
                row["target"],
                row["option"]
            ])));
            tx.execute(
                "INSERT OR IGNORE INTO moderation_report_index VALUES(?,?,?,?)",
                params![id, s(&row, "guid"), s(&row, "target"), n(&row, "option")],
            )?;
            let indexed = one(
                &tx,
                "SELECT guid,target,option FROM moderation_report_index WHERE report_id=?",
                [id],
            )?
            .ok_or_else(|| Failure::conflict("Report identity collision"))?;
            if indexed != row {
                return Err(Failure::conflict("Report identity collision"));
            }
        }
        tx.commit()?;
        drop(db);
        TOKENS
            .get_or_init(|| Mutex::new(HashMap::new()))
            .lock()
            .map_err(|_| {
                Failure::new(
                    503,
                    "temporarily_unavailable",
                    "Management authentication is unavailable",
                )
            })?
            .insert(registry_key(state), token.to_vec());
        Ok(())
    })()
    .map_err(core_error)
}
fn actor(
    db: &Connection,
    headers: &HashMap<String, String>,
    token: &[u8],
    permission: &str,
) -> Result<Value> {
    let candidate = header(headers, "Authorization")
        .and_then(|s| s.strip_prefix("Bearer "))
        .unwrap_or("");
    if !constant_eq(candidate.as_bytes(), token) {
        return Err(Failure::new(
            401,
            "unauthorized",
            "Management authentication required",
        ));
    }
    let id = header(headers, "X-Management-Actor").unwrap_or("");
    if !operator_id(id) {
        return Err(Failure::forbidden(
            "An enabled management operator is required",
        ));
    }
    let row = one(
        db,
        "SELECT operator_id AS id,role,enabled FROM management_operators WHERE operator_id=?",
        [id],
    )?
    .filter(|r| n(r, "enabled") == 1 && permissions(s(r, "role")).contains(&permission))
    .ok_or_else(|| Failure::forbidden("Management permission denied"))?;
    Ok(json!({"id":row["id"],"role":row["role"]}))
}
fn profile(db: &Connection, id: &str) -> Result<Value> {
    text(&json!(id), "account ID", 128)?;
    one(db,"SELECT p.ps4_id AS account_id,p.username,p.platform,p.gender,p.created_at,COALESCE(s.online,0) AS online,(SELECT MAX(created_at) FROM sessions WHERE ps4_id=p.ps4_id) AS last_login_at,(SELECT MAX(updated_at) FROM presets WHERE ps4_id=p.ps4_id) AS last_avatar_save_at FROM profiles p LEFT JOIN profile_state s USING(ps4_id) WHERE p.ps4_id=?",[id])?.ok_or_else(||Failure::missing("Account not found"))
}
fn wallet(db: &Connection, id: &str) -> Result<Value> {
    Ok(one(db, "SELECT * FROM shop_wallets WHERE ps4_id=?", [id])?
        .unwrap_or(json!({"ps4_id":id,"crystals":0,"np":0,"level":0})))
}
fn pagination(query: &HashMap<String, String>) -> Result<(usize, usize)> {
    let limit = query.get("limit").map(String::as_str).unwrap_or("25");
    let offset = query.get("cursor").map(String::as_str).unwrap_or("0");
    check(
        !limit.is_empty() && limit.len() <= 3 && limit.bytes().all(|c| c.is_ascii_digit()),
        "Limit must be between 1 and 100",
    )?;
    let limit: usize = limit.parse().unwrap();
    check(
        (1..=100).contains(&limit),
        "Limit must be between 1 and 100",
    )?;
    check(
        !offset.is_empty() && offset.len() <= 9 && offset.bytes().all(|c| c.is_ascii_digit()),
        "Invalid pagination cursor",
    )?;
    Ok((limit, offset.parse().unwrap()))
}
fn page(
    db: &Connection,
    sql: &str,
    args: &[SqlValue],
    query: &HashMap<String, String>,
) -> Result<Value> {
    let (limit, offset) = pagination(query)?;
    let total: i64 = db.query_row(
        &format!("SELECT COUNT(*) FROM({sql})"),
        rusqlite::params_from_iter(args),
        |r| r.get(0),
    )?;
    let mut p = args.to_vec();
    p.extend([
        SqlValue::Integer(limit as i64),
        SqlValue::Integer(offset as i64),
    ]);
    let items = rows(
        db,
        &format!("{sql} LIMIT ? OFFSET ?"),
        rusqlite::params_from_iter(p),
    )?;
    Ok(
        json!({"items":items,"next_cursor":if offset+limit<total as usize{Some((offset+limit).to_string())}else{None},"total":total,"limit":limit}),
    )
}
fn page_values(mut values: Vec<Value>, query: &HashMap<String, String>) -> Result<Value> {
    let (limit, offset) = pagination(query)?;
    let total = values.len();
    let items = if offset >= total {
        vec![]
    } else {
        values.drain(offset..(offset + limit).min(total)).collect()
    };
    Ok(
        json!({"items":items,"total":total,"limit":limit,"next_cursor":if offset+limit<total{Some((offset+limit).to_string())}else{None}}),
    )
}
fn decoded_audit(mut result: Value) -> Result<Value> {
    for row in result["items"].as_array_mut().unwrap() {
        for (k, out) in [("before_json", "before"), ("after_json", "after")] {
            let v: Value = serde_json::from_str(s(row, k))?;
            row.as_object_mut().unwrap().remove(k);
            row[out] = v;
        }
    }
    Ok(result)
}
fn audit(
    state: &State,
    db: &Connection,
    request: &str,
    actor: &Value,
    operation: &str,
    target: &str,
    reason: &str,
    before: &Value,
    after: &Value,
) -> Result<i64> {
    db.execute("INSERT INTO management_audit(request_id,actor_id,actor_role,operation,target_id,reason,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",params![request,s(actor,"id"),s(actor,"role"),operation,target,reason,canonical(before),canonical(after),state.now()])?;
    Ok(db.last_insert_rowid())
}
fn query_tail(tail: &str) -> Result<(&str, HashMap<String, String>)> {
    let (path, query) = tail.split_once('?').unwrap_or((tail, ""));
    let mut result = HashMap::new();
    for pair in query.split('&').filter(|p| !p.is_empty()) {
        let (k, v) = pair.split_once('=').unwrap_or((pair, ""));
        fn decode(v: &str) -> Result<String> {
            let mut bytes = Vec::new();
            let mut i = 0;
            let raw = v.as_bytes();
            while i < raw.len() {
                match raw[i] {
                    b'+' => bytes.push(b' '),
                    b'%' => {
                        if i + 2 >= raw.len() {
                            return Err(Failure::invalid("Invalid query encoding"));
                        }
                        let hex = std::str::from_utf8(&raw[i + 1..i + 3])
                            .map_err(|_| Failure::invalid("Invalid query encoding"))?;
                        bytes.push(
                            u8::from_str_radix(hex, 16)
                                .map_err(|_| Failure::invalid("Invalid query encoding"))?,
                        );
                        i += 2;
                    }
                    v => bytes.push(v),
                }
                i += 1;
            }
            String::from_utf8(bytes).map_err(|_| Failure::invalid("Invalid query encoding"))
        }
        result.entry(decode(k)?).or_insert(decode(v)?);
    }
    Ok((path, result))
}
fn response_error(e: Failure) -> AdminResponse {
    AdminResponse {
        status: e.status,
        body: json!({"error":{"code":e.code,"message":e.message}}),
    }
}
pub fn handle(
    state: &State,
    method: &str,
    tail: &str,
    headers: &HashMap<String, String>,
    body: &Value,
) -> AdminResponse {
    match dispatch(state, method, tail, headers, body) {
        Ok(result) => AdminResponse {
            status: 200,
            body: json!({"data":result}),
        },
        Err(e) => response_error(e),
    }
}
/// Raw HTTP entry point preserves authentication and content type precedence
/// before parsing untrusted bytes. GET and unsupported methods ignore the body.
pub fn handle_raw(
    state: &State,
    method: &str,
    tail: &str,
    headers: &HashMap<String, String>,
    raw: &[u8],
) -> AdminResponse {
    if method != "POST" {
        return handle(state, method, tail, headers, &Value::Null);
    }
    let authenticated = (|| -> Result<()> {
        if header(headers, "Origin").is_some() {
            return Err(Failure::forbidden("Management is a server-to-server API"));
        }
        let token = TOKENS
            .get_or_init(|| Mutex::new(HashMap::new()))
            .lock()
            .map_err(|_| {
                Failure::new(
                    503,
                    "temporarily_unavailable",
                    "Management authentication is unavailable",
                )
            })?
            .get(&registry_key(state))
            .cloned()
            .ok_or_else(|| {
                Failure::new(
                    503,
                    "temporarily_unavailable",
                    "Management is not initialized",
                )
            })?;
        let db = state.connection()?;
        actor(&db, headers, &token, "read")?;
        let content = header(headers, "Content-Type")
            .unwrap_or("")
            .split(';')
            .next()
            .unwrap_or("")
            .trim();
        if content != "application/json" {
            return Err(Failure::new(
                415,
                "invalid_request",
                "JSON content type required",
            ));
        }
        Ok(())
    })();
    if let Err(e) = authenticated {
        return response_error(e);
    }
    match parse_body(raw) {
        Ok(body) => handle(state, method, tail, headers, &body),
        Err(e) => e,
    }
}
fn dispatch(
    state: &State,
    method: &str,
    tail: &str,
    headers: &HashMap<String, String>,
    body: &Value,
) -> Result<Value> {
    if header(headers, "Origin").is_some() {
        return Err(Failure::forbidden("Management is a server-to-server API"));
    }
    let token = TOKENS
        .get_or_init(|| Mutex::new(HashMap::new()))
        .lock()
        .map_err(|_| {
            Failure::new(
                503,
                "temporarily_unavailable",
                "Management authentication is unavailable",
            )
        })?
        .get(&registry_key(state))
        .cloned()
        .ok_or_else(|| {
            Failure::new(
                503,
                "temporarily_unavailable",
                "Management is not initialized",
            )
        })?;
    let (tail, query) = query_tail(tail)?;
    let mut db = state.connection()?;
    let who = actor(&db, headers, &token, "read")?;
    match method {
        "GET" => read(state, &db, tail, &query, &who),
        "POST" => {
            let ct = header(headers, "Content-Type")
                .unwrap_or("")
                .split(';')
                .next()
                .unwrap_or("")
                .trim();
            if ct != "application/json" {
                return Err(Failure::new(
                    415,
                    "invalid_request",
                    "JSON content type required",
                ));
            }
            if body.to_string().len() > MAX_BODY {
                return Err(Failure::new(
                    413,
                    "invalid_request",
                    "Request body is too large",
                ));
            }
            check(body.is_object(), "JSON object required")?;
            let out = command(state, &mut db, tail, headers, body, &token)?;
            drop(db);
            let mut out = out;
            let published = (|| -> crate::error::Result<()> {
                crate::services::pump(state)?;
                if state.managed_instances {
                    crate::registry_snapshot::publish(state)?;
                    crate::lifecycle::export_desired(state)?;
                }
                Ok(())
            })();
            out["runtime_sync"] = json!(if published.is_ok() {
                "snapshot_published"
            } else {
                "pending"
            });
            Ok(out)
        }
        _ => Err(Failure::new(
            405,
            "method_not_allowed",
            "Use GET or POST for this API",
        )),
    }
}
fn read(
    state: &State,
    db: &Connection,
    tail: &str,
    query: &HashMap<String, String>,
    who: &Value,
) -> Result<Value> {
    match tail {
        "health" => {
            return Ok(json!({"service":"nebula-management","status":"ok","schema_version":1}))
        }
        "me" => {
            let mut p = permissions(s(who, "role")).to_vec();
            p.sort();
            return Ok(json!({"id":who["id"],"role":who["role"],"permissions":p}));
        }
        "roles" => {
            let items: Vec<_> = ROLES
                .iter()
                .map(|role| {
                    let mut p = permissions(role).to_vec();
                    p.sort();
                    json!({"id":role,"permissions":p})
                })
                .collect();
            return Ok(json!({"items":items}));
        }
        "capabilities" => {
            return Ok(
                json!({"dashboard_roles":ROLES,"game_roles_supported":[],"game_privilege_mutation_supported":false,"game_developer_flag_grant_supported":false,"grant_kinds":["wardrobe","companions","locomotions","housing","offer"],"currency_kinds":["crystals","np"],"historical_purchase_price_retained":false,"public_access_credential_management_supported":false,"moderation_supported":true,"moderation_actions":["ban","unban","kick","mute","unmute"],"announcement_supported":false,"news_supported":true,"staff_labels_supported":true,"operator_account_links_supported":true,"moderation_delivery":"Committed policy is not a client display acknowledgement"}),
            )
        }
        "moderation/status" => {
            return Ok(
                json!({"maintenance_minutes":maintenance(state,db)?["minutes"],"game_roles_supported":[],"announcement_supported":false}),
            )
        }
        "moderation/events" => {
            return decoded_audit(page(
                db,
                "SELECT * FROM moderation_events ORDER BY event_id DESC",
                &[],
                query,
            )?)
        }
        "moderation/news" => {
            return page(
                db,
                "SELECT * FROM moderation_news ORDER BY created_at DESC,news_id DESC",
                &[],
                query,
            )
        }
        "moderation/reports" => {
            let (limit, offset) = pagination(query)?;
            let total: i64 =
                db.query_row("SELECT COUNT(*) FROM local_reports", [], |r| r.get(0))?;
            let items=rows(db,"SELECT i.report_id,r.guid,r.target,r.option,r.text,r.created_at,s.ps4_id AS reporter_account_id,COALESCE(v.status,'open') AS status,COALESCE(v.note,'') AS note,v.actor_id,v.updated_at FROM moderation_report_index i JOIN local_reports r USING(guid,target,option) LEFT JOIN sessions s ON s.guid=r.guid LEFT JOIN moderation_report_reviews v USING(report_id) ORDER BY r.created_at DESC,i.report_id LIMIT ? OFFSET ?",params![limit as i64,offset as i64])?;
            return Ok(
                json!({"items":items,"total":total,"limit":limit,"next_cursor":if offset+limit<total as usize{Some((offset+limit).to_string())}else{None}}),
            );
        }
        "stats" => {
            let count = |sql: &str| -> Result<i64> { Ok(db.query_row(sql, [], |r| r.get(0))?) };
            return Ok(
                json!({"users":count("SELECT COUNT(*) FROM profiles")?,"online":count("SELECT COUNT(*) FROM profile_state WHERE online=1")?,"purchases":count("SELECT COUNT(*) FROM shop_owned WHERE source='buy'")?,"gift_grants":count("SELECT COUNT(*) FROM shop_owned WHERE source='gift'")?,"admin_offer_grants":count("SELECT COUNT(*) FROM shop_owned WHERE source='admin'")?,"crystals":count("SELECT COALESCE(SUM(crystals),0) FROM shop_wallets")?,"np":count("SELECT COALESCE(SUM(np),0) FROM shop_wallets")?,"audit_entries":count("SELECT COUNT(*) FROM management_audit")?}),
            );
        }
        "users" => {
            let search = query.get("q").cloned().unwrap_or_default();
            check(search.chars().count() <= 128, "Invalid account search")?;
            return page(db,"SELECT p.ps4_id AS account_id,p.username,p.platform,p.gender,p.created_at,COALESCE(s.online,0) AS online,COALESCE(w.crystals,0) AS crystals,COALESCE(w.np,0) AS np FROM profiles p LEFT JOIN profile_state s USING(ps4_id) LEFT JOIN shop_wallets w USING(ps4_id) WHERE instr(lower(p.ps4_id),lower(?))>0 OR instr(lower(p.username),lower(?))>0 ORDER BY p.ps4_id",&[search.clone().into(),search.into()],query);
        }
        "operators" => {
            if s(who, "role") != "owner" {
                return Err(Failure::forbidden(
                    "Only an owner may list dashboard operators",
                ));
            }
            return page(db,"SELECT o.operator_id AS id,o.role,o.enabled,o.created_at,o.updated_at,l.account_id FROM management_operators o LEFT JOIN management_operator_accounts l USING(operator_id) ORDER BY o.operator_id",&[],query);
        }
        "audit" => {
            return decoded_audit(page(
                db,
                "SELECT * FROM management_audit ORDER BY audit_id DESC",
                &[],
                query,
            )?)
        }
        "transactions" => {
            return page(
                db,
                "SELECT * FROM management_wallet_ledger ORDER BY ledger_id DESC",
                &[],
                query,
            )
        }
        "catalog" => return catalog(state, db, query),
        _ => {}
    }
    let parts: Vec<_> = tail.split('/').collect();
    if [2, 3].contains(&parts.len()) && parts[0] == "users" {
        let id = parts[1];
        let mut p = profile(db, id)?;
        if parts.len() == 2 {
            p["wallet"] = wallet(db, id)?;
            return Ok(p);
        }
        return match parts[2]{
        "wallet"=>wallet(db,id),"moderation"=>moderation_status(state,db,id),
        "owned"=>page(db,"SELECT 'wardrobe' AS kind,item_id,gender,category,display_name,granted_at FROM entitlements WHERE ps4_id=? UNION ALL SELECT kind,item_id,NULL,NULL,display_name,granted_at FROM resource_entitlements WHERE ps4_id=? UNION ALL SELECT 'housing',item_id,NULL,NULL,display_name,granted_at FROM housing_entitlements WHERE ps4_id=? ORDER BY kind,item_id,gender,category",&[id.to_owned().into(),id.to_owned().into(),id.to_owned().into()],query),
        "transactions"=>page(db,"SELECT * FROM management_wallet_ledger WHERE account_id=? ORDER BY ledger_id DESC",&[id.to_owned().into()],query),
        "audit"=>decoded_audit(page(db,"SELECT * FROM management_audit WHERE target_id=? AND operation IN('wallet.adjust','items.grant','users.rename','moderation.ban','moderation.kick','moderation.mute','players.staff') ORDER BY audit_id DESC",&[id.to_owned().into()],query)?),
        "purchases"=>{let mut out=page(db,"SELECT s.offer_id,s.source,s.granted_by,s.created_at,o.kind,o.item_id,o.name,o.crystals AS current_offer_crystals,o.np AS current_offer_np FROM shop_owned s LEFT JOIN shop_offers o USING(offer_id) WHERE s.ps4_id=? ORDER BY s.created_at DESC,s.offer_id",&[id.to_owned().into()],query)?;for row in out["items"].as_array_mut().unwrap(){row["historical_price_known"]=json!(false);}Ok(out)},
        _=>Err(Failure::missing("Management route not found")),
    };
    }
    Err(Failure::missing("Management route not found"))
}
fn controls(state: &State) -> Result<HashSet<String>> {
    let catalog = state.catalog("wardrobe-removal-sentinels.json")?;
    Ok(catalog["sentinels"]
        .as_array()
        .ok_or_else(|| Failure::invalid("Invalid wardrobe controls catalog"))?
        .iter()
        .map(|r| s(r, "item_id").to_string())
        .collect())
}
fn catalog(state: &State, db: &Connection, query: &HashMap<String, String>) -> Result<Value> {
    let kind = query.get("kind").map(String::as_str).unwrap_or("wardrobe");
    let search = query.get("q").cloned().unwrap_or_default();
    check(search.chars().count() <= 128, "Invalid item search")?;
    if kind == "offer" {
        return page(db,"SELECT offer_id,kind,item_id,gender,category,name,crystals,np,active FROM shop_offers WHERE instr(lower(name),lower(?))>0 OR instr(lower(offer_id),lower(?))>0 ORDER BY offer_id",&[search.clone().into(),search.into()],query);
    }
    if !["wardrobe", "companions", "locomotions", "housing"].contains(&kind) {
        return Err(Failure::invalid("Unsupported grant kind"));
    }
    let controls = if kind == "wardrobe" {
        controls(state)?
    } else {
        HashSet::new()
    };
    let mut values = Vec::new();
    for r in crate::services::admin_asset_catalog(state, kind)? {
        if controls.contains(s(&r, "item_id"))
            || !s(&r, "item_id")
                .to_lowercase()
                .contains(&search.to_lowercase())
        {
            continue;
        }
        values.push(json!({"kind":kind,"item_id":r["item_id"],"gender":if kind=="wardrobe"{r["gender"].clone()}else{Value::Null},"category":if kind=="wardrobe"{r["category"].clone()}else if kind=="housing"{r["table"].clone()}else{Value::Null}}));
    }
    values.sort_by(|a, b| {
        (s(a, "item_id"), s(a, "gender"), s(a, "category")).cmp(&(
            s(b, "item_id"),
            s(b, "gender"),
            s(b, "category"),
        ))
    });
    page_values(values, query)
}
fn command(
    state: &State,
    db: &mut Connection,
    tail: &str,
    headers: &HashMap<String, String>,
    body: &Value,
    token: &[u8],
) -> Result<Value> {
    let parts: Vec<_> = tail.split('/').collect();
    let (permission, target) = if parts.len() == 3 && parts[0] == "users" {
        let permission = match parts[2] {
            "wallet-adjustments" => "wallet.adjust",
            "items" => "items.grant",
            "rename" => "users.rename",
            "ban" | "unban" => "moderation.ban",
            "kick" => "moderation.kick",
            "mute" | "unmute" => "moderation.mute",
            "staff-label" => "players.staff",
            _ => return Err(Failure::missing("Management route not found")),
        };
        (permission, parts[1])
    } else if tail == "moderation/maintenance" {
        ("moderation.maintenance", "server")
    } else if parts.len() == 3 && parts[..2] == ["moderation", "reports"] {
        ("moderation.reports", parts[2])
    } else if tail == "moderation/news" {
        ("moderation.news", "server")
    } else if parts.len() == 4 && parts[..2] == ["moderation", "news"] && parts[3] == "archive" {
        ("moderation.news", parts[2])
    } else if parts.len() == 2 && parts[0] == "operators" {
        ("operators.manage", parts[1])
    } else if parts.len() == 3 && parts[0] == "operators" && parts[2] == "player-link" {
        ("operators.manage", parts[1])
    } else {
        return Err(Failure::missing("Management route not found"));
    };
    actor(db, headers, token, permission)?;
    let key = header(headers, "Idempotency-Key").unwrap_or("");
    check(
        key_id(key),
        "A bounded Idempotency-Key of at least eight characters is required",
    )?;
    let reason = text(&body["reason"], "audit reason", 512)?;
    let fingerprint = crate::services::hash(&canonical(
        &json!({"method":"POST","route":tail,"body":body}),
    ));
    let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let actor = actor(&tx, headers, token, permission)?;
    if let Some(old)=one(&tx,"SELECT request_sha256,response_json FROM management_requests WHERE actor_id=? AND idempotency_key=?",params![s(&actor,"id"),key])?{if !constant_eq(s(&old,"request_sha256").as_bytes(),fingerprint.as_bytes()){return Err(Failure::conflict("Idempotency key was used for another command"));}let mut result:Value=serde_json::from_str(s(&old,"response_json"))?;result["replayed"]=json!(true);tx.commit()?;return Ok(result);}
    let request = crate::services::uuid();
    let (before, after, changed) = match permission {
        "wallet.adjust" => adjust_wallet(state, &tx, target, body, &actor, &request, reason)?,
        "items.grant" => grant_item(state, &tx, target, body, &actor)?,
        "users.rename" => rename(&tx, target, body)?,
        "players.staff" => {
            fields(body, &["label", "reason"])?;
            profile(&tx, target)?;
            staff_label(state, &tx, target, &body["label"], &actor, &request, reason)?
        }
        "moderation.reports" => {
            fields(body, &["status", "note", "reason"])?;
            review_report(state, &tx, target, body, &actor, &request, reason)?
        }
        "moderation.news" => {
            if parts.len() == 4 {
                fields(body, &["reason"])?;
                archive_news(state, &tx, target, &actor, &request, reason)?
            } else {
                fields(body, &["text", "expires_at", "reason"])?;
                publish_news(state, &tx, body, &actor, &request, reason)?
            }
        }
        p if p.starts_with("moderation.") => moderate(
            state,
            &tx,
            target,
            parts[parts.len() - 1],
            body,
            &actor,
            &request,
            reason,
        )?,
        _ if parts.len() == 3 && parts[0] == "operators" => operator_link(&tx, target, body)?,
        _ => operator(state, &tx, target, body)?,
    };
    let audit_id = audit(
        state, &tx, &request, &actor, permission, target, reason, &before, &after,
    )?;
    let result = json!({"request_id":request,"audit_id":audit_id,"operation":permission,"account_id":if parts[0]=="users"{Some(target)}else{None},"operator_id":if parts[0]=="operators"{Some(target)}else{None},"before":before,"after":after,"changed":changed,"replayed":false});
    tx.execute(
        "INSERT INTO management_requests VALUES(?,?,?,?,?)",
        params![
            s(&actor, "id"),
            key,
            fingerprint,
            canonical(&result),
            state.now()
        ],
    )?;
    tx.commit()?;
    Ok(result)
}
fn adjust_wallet(
    state: &State,
    db: &Connection,
    target: &str,
    body: &Value,
    actor: &Value,
    request: &str,
    reason: &str,
) -> Result<(Value, Value, bool)> {
    fields(body, &["currency", "delta", "reason"])?;
    profile(db, target)?;
    let currency = s(body, "currency");
    let delta = body["delta"]
        .as_i64()
        .filter(|d| *d != 0 && (-MAX_BALANCE..=MAX_BALANCE).contains(d));
    check(
        ["crystals", "np"].contains(&currency) && delta.is_some(),
        "A supported currency and nonzero signed integer delta are required",
    )?;
    let delta = delta.unwrap();
    let before = wallet(db, target)?;
    let balance = n(&before, currency) + delta;
    if !(0..=MAX_BALANCE).contains(&balance) {
        return Err(Failure::conflict(
            "Wallet adjustment exceeds the supported balance range",
        ));
    }
    let mut after = before.clone();
    after[currency] = json!(balance);
    crate::services::admin_account(db, target)?;
    db.execute(
        "INSERT OR IGNORE INTO profile_state(ps4_id) VALUES(?)",
        [target],
    )?;
    db.execute("INSERT INTO shop_wallets VALUES(?,?,?,?) ON CONFLICT(ps4_id) DO UPDATE SET crystals=excluded.crystals,np=excluded.np,level=excluded.level",params![target,n(&after,"crystals"),n(&after,"np"),n(&after,"level")])?;
    db.execute("INSERT INTO management_wallet_ledger(request_id,actor_id,account_id,currency,delta,before_balance,after_balance,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)",params![request,s(actor,"id"),target,currency,delta,n(&before,currency),balance,reason,state.now()])?;
    Ok((before, after, true))
}
fn grant_item(
    state: &State,
    db: &Connection,
    target: &str,
    body: &Value,
    actor: &Value,
) -> Result<(Value, Value, bool)> {
    fields(
        body,
        &[
            "kind", "item_id", "offer_id", "gender", "category", "reason",
        ],
    )?;
    profile(db, target)?;
    let kind = s(body, "kind");
    let map = body.as_object().unwrap();
    if kind == "offer" {
        check(
            map.keys()
                .all(|k| ["kind", "offer_id", "reason"].contains(&k.as_str())),
            "Offer grants accept an offer ID only",
        )?;
        let id = text(&body["offer_id"], "offer ID", 128)?;
        let offer = one(db, "SELECT * FROM shop_offers WHERE offer_id=?", [id])?
            .filter(|o| n(o, "active") == 1)
            .ok_or_else(|| Failure::missing("Active configured offer not found"))?;
        let owned = crate::services::admin_offer_owned(db, target, &offer)?;
        let before = json!({"kind":kind,"offer_id":id,"owned":owned});
        let changed =
            crate::services::admin_grant_offer(state, db, target, &offer, s(actor, "id"))?;
        let mut after = before.clone();
        after["owned"] = json!(true);
        return Ok((before, after, changed));
    }
    check(
        !map.contains_key("offer_id"),
        "Asset grants do not accept an offer ID",
    )?;
    let item = text(&body["item_id"], "item ID", 128)?;
    if !["wardrobe", "companions", "locomotions", "housing"].contains(&kind) {
        return Err(Failure::invalid("Unsupported grant kind"));
    }
    if kind != "wardrobe" {
        check(
            !map.contains_key("gender") && !map.contains_key("category"),
            if kind == "housing" {
                "Housing grant has no gender/category"
            } else {
                "Resource grant has no gender/category"
            },
        )?;
    } else if (!body["gender"].is_null() && !body["gender"].is_string())
        || (!body["category"].is_null() && !body["category"].is_string())
    {
        return Err(Failure::missing(
            "Item has no unambiguous shipped wardrobe asset",
        ));
    }
    let asset = crate::services::admin_resolve_asset(
        state,
        kind,
        item,
        body["gender"].as_str(),
        body["category"].as_str(),
    )
    .map_err(|e| {
        if kind == "housing" && e.status == 404 {
            Failure::missing("Shipped housing item not found")
        } else {
            e.into()
        }
    })?;
    let (mut key, owned) = if kind == "wardrobe" {
        check(
            !controls(state)?.contains(item),
            "Wardrobe removal controls are not grantable items",
        )?;
        let own = one(
            db,
            "SELECT 1 FROM entitlements WHERE ps4_id=? AND item_id=? AND gender=? AND category=?",
            params![target, item, s(&asset, "gender"), s(&asset, "category")],
        )?
        .is_some();
        (
            json!({"kind":kind,"item_id":item,"gender":asset["gender"],"category":asset["category"]}),
            own,
        )
    } else {
        let own = if kind == "housing" {
            one(
                db,
                "SELECT 1 FROM housing_entitlements WHERE ps4_id=? AND item_id=?",
                params![target, item],
            )?
            .is_some()
        } else {
            one(
                db,
                "SELECT 1 FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?",
                params![target, kind, item],
            )?
            .is_some()
        };
        (json!({"kind":kind,"item_id":item}), own)
    };
    if !owned {
        crate::services::admin_grant_asset(
            state,
            db,
            target,
            kind,
            item,
            body["gender"].as_str(),
            body["category"].as_str(),
        )?;
        db.execute(
            "INSERT OR IGNORE INTO profile_state(ps4_id) VALUES(?)",
            [target],
        )?;
    }
    key["owned"] = json!(owned);
    let mut after = key.clone();
    after["owned"] = json!(true);
    Ok((key, after, !owned))
}
fn rename(db: &Connection, target: &str, body: &Value) -> Result<(Value, Value, bool)> {
    fields(body, &["username", "reason"])?;
    let before = profile(db, target)?;
    let username = text(&body["username"], "username", 64)?;
    if s(&before, "username") != username {
        crate::character::identity(target, Some(username))?;
        let old = s(&before, "username");
        let platform = crate::character::canonical_platform(s(&before, "platform"))?;
        for row in rows(
            db,
            "SELECT username,platform FROM profiles WHERE ps4_id<>? AND username IN(?,?)",
            params![target, old, username],
        )? {
            if [old, username].contains(&s(&row, "username"))
                && crate::character::canonical_platform(s(&row, "platform"))? == platform
            {
                return Err(Failure::conflict(
                    "Local username/platform identity is ambiguous",
                ));
            }
        }
        db.execute("INSERT OR IGNORE INTO relations(ps4_id,target,target_platform,kind) SELECT ps4_id,?,?,kind FROM relations WHERE target=? AND target_platform=?",params![username,platform,old,platform])?;
        db.execute(
            "DELETE FROM relations WHERE target=? AND target_platform=?",
            params![old, platform],
        )?;
        db.execute(
            "UPDATE profiles SET username=?,platform=? WHERE ps4_id=?",
            params![username, platform, target],
        )?;
        db.execute(
            "INSERT OR IGNORE INTO profile_state(ps4_id) VALUES(?)",
            [target],
        )?;
    }
    let after = profile(db, target)?;
    let changed = before != after;
    Ok((before, after, changed))
}
fn operator(
    state: &State,
    db: &Connection,
    target: &str,
    body: &Value,
) -> Result<(Value, Value, bool)> {
    fields(body, &["role", "enabled", "reason"])?;
    check(operator_id(target), "Invalid operator ID")?;
    let role = s(body, "role");
    let enabled = body["enabled"].as_bool();
    check(
        ROLES.contains(&role) && enabled.is_some(),
        "Explicit role and enabled flag required",
    )?;
    let before = one(
        db,
        "SELECT operator_id AS id,role,enabled FROM management_operators WHERE operator_id=?",
        [target],
    )?
    .unwrap_or(Value::Null);
    let enabled = enabled.unwrap() as i64;
    db.execute("INSERT INTO management_operators VALUES(?,?,?,?,?) ON CONFLICT(operator_id) DO UPDATE SET role=excluded.role,enabled=excluded.enabled,updated_at=excluded.updated_at",params![target,role,enabled,state.now(),state.now()])?;
    if one(
        db,
        "SELECT 1 FROM management_operators WHERE role='owner' AND enabled=1",
        [],
    )?
    .is_none()
    {
        return Err(Failure::conflict(
            "Cannot disable or demote the last enabled owner",
        ));
    }
    let after = json!({"id":target,"role":role,"enabled":enabled});
    let changed = before != after;
    Ok((before, after, changed))
}
fn operator_link(db: &Connection, target: &str, body: &Value) -> Result<(Value, Value, bool)> {
    fields(body, &["account_id", "reason"])?;
    check(
        body.as_object().unwrap().contains_key("account_id"),
        "An explicit account ID or null is required",
    )?;
    if one(
        db,
        "SELECT 1 FROM management_operators WHERE operator_id=?",
        [target],
    )?
    .is_none()
    {
        return Err(Failure::missing("Dashboard operator not found"));
    }
    let old = one(
        db,
        "SELECT account_id FROM management_operator_accounts WHERE operator_id=?",
        [target],
    )?;
    let before = json!({"operator_id":target,"account_id":old.map(|o|o["account_id"].clone()).unwrap_or(Value::Null)});
    let account = &body["account_id"];
    if account.is_null() {
        db.execute(
            "DELETE FROM management_operator_accounts WHERE operator_id=?",
            [target],
        )?;
    } else {
        let account = text(account, "account ID", 128)?;
        profile(db, account)?;
        if one(
            db,
            "SELECT operator_id FROM management_operator_accounts WHERE account_id=?",
            [account],
        )?
        .is_some_and(|o| s(&o, "operator_id") != target)
        {
            return Err(Failure::conflict("Player is linked to another operator"));
        }
        db.execute("INSERT INTO management_operator_accounts VALUES(?,?) ON CONFLICT(operator_id) DO UPDATE SET account_id=excluded.account_id",params![target,account])?;
    }
    let after = json!({"operator_id":target,"account_id":account});
    let changed = before != after;
    Ok((before, after, changed))
}

fn now(state: &State) -> Result<f64> {
    let v = state.now();
    if v.is_finite() && (0.0..=MAX_UTC as f64).contains(&v) {
        Ok(v)
    } else {
        Err(Failure::new(
            503,
            "invalid_request",
            "Moderation clock is unavailable",
        ))
    }
}
fn mutation(
    state: &State,
    db: &Connection,
    actor: &Value,
    request: &str,
    reason: &str,
) -> Result<i64> {
    if db.is_autocommit() {
        return Err(Failure::conflict(
            "Moderation mutation requires the caller's Store.atomic()",
        ));
    }
    if !operator_id(s(actor, "id")) || !ROLES.contains(&s(actor, "role")) {
        return Err(Failure::forbidden(
            "A verified management actor is required",
        ));
    }
    check(wire_hex(request, 32), "Invalid moderation request ID")?;
    wire_text(&json!(reason), "moderation reason", 512, false)?;
    if one(
        db,
        "SELECT 1 FROM moderation_events WHERE request_id=?",
        [request],
    )?
    .is_some()
    {
        return Err(Failure::conflict(
            "Moderation request was already committed; replay its management receipt",
        ));
    }
    Ok(now(state)? as i64)
}
fn moderation_account(db: &Connection, id: &str) -> Result<()> {
    wire_text(&json!(id), "account ID", 128, false)?;
    if one(db, "SELECT 1 FROM profiles WHERE ps4_id=?", [id])?.is_none() {
        return Err(Failure::missing("Account not found"));
    }
    Ok(())
}
fn policy(db: &Connection, id: &str) -> Result<Value> {
    Ok(one(db,"SELECT * FROM moderation_accounts WHERE ps4_id=?",[id])?.unwrap_or(json!({"ps4_id":id,"ban_enabled":0,"ban_expires_at":null,"ban_reason":"","mute_enabled":0,"mute_expires_at":null,"mute_reason":"","staff_label":""})))
}
fn online(db: &Connection, id: &str) -> Result<i64> {
    Ok(
        one(db, "SELECT online FROM profile_state WHERE ps4_id=?", [id])?
            .map(|v| n(&v, "online"))
            .unwrap_or(0),
    )
}
fn maintenance(state: &State, db: &Connection) -> Result<Value> {
    let mut p = one(
        db,
        "SELECT started_at,end_at,reason FROM moderation_maintenance WHERE singleton=1",
        [],
    )?
    .unwrap_or(json!({"started_at":null,"end_at":null,"reason":""}));
    p["minutes"] = json!(if p["end_at"].is_null() {
        0
    } else {
        ((n(&p, "end_at") as f64 - now(state)?) / 60.)
            .ceil()
            .max(0.) as i64
    });
    Ok(p)
}
fn moderation_status(state: &State, db: &Connection, id: &str) -> Result<Value> {
    moderation_account(db, id)?;
    let p = policy(db, id)?;
    let now = now(state)?;
    let active = |kind: &str| {
        n(&p, &format!("{kind}_enabled")) != 0
            && (p[format!("{kind}_expires_at")].is_null()
                || now < p[format!("{kind}_expires_at")].as_f64().unwrap_or(0.))
    };
    Ok(
        json!({"account_id":id,"banned":active("ban"),"ban_expires_at":p["ban_expires_at"],"ban_reason":p["ban_reason"],"muted":active("mute"),"mute_expires_at":p["mute_expires_at"],"mute_reason":p["mute_reason"],"role":"player","staff_label":p["staff_label"],"maintenance":maintenance(state,db)?["minutes"]}),
    )
}
fn expiry(state: &State, value: &Value) -> Result<Option<i64>> {
    if value.is_null() {
        return Ok(None);
    }
    let v = value
        .as_i64()
        .filter(|v| (*v as f64) > state.now() && *v <= MAX_UTC);
    check(
        v.is_some(),
        "Expiry must be a future UTC integer second or null",
    )?;
    Ok(v)
}
fn event(
    db: &Connection,
    request: &str,
    actor: &Value,
    operation: &str,
    target: &str,
    reason: &str,
    before: &Value,
    after: &Value,
    now: i64,
) -> Result<()> {
    db.execute("INSERT INTO moderation_events(request_id,actor_id,actor_role,operation,target_id,reason,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",params![request,s(actor,"id"),s(actor,"role"),operation,target,reason,canonical(before),canonical(after),now])?;
    Ok(())
}
fn revoke(
    db: &Connection,
    id: &str,
    guids: &[String],
    request: &str,
    reason: &str,
    now: i64,
) -> Result<Vec<String>> {
    let mut added = Vec::new();
    for guid in guids {
        wire_text(&json!(guid), "session identifier", 128, false)?;
        if db.execute(
            "INSERT OR IGNORE INTO moderation_revoked_sessions VALUES(?,?,?,?,?)",
            params![guid, id, request, now, reason],
        )? != 0
        {
            added.push(guid.clone());
        }
    }
    Ok(added)
}
fn moderate(
    state: &State,
    db: &Connection,
    target: &str,
    action: &str,
    body: &Value,
    actor: &Value,
    request: &str,
    reason: &str,
) -> Result<(Value, Value, bool)> {
    if action == "maintenance" {
        fields(body, &["minutes", "reason"])?;
        let now = mutation(state, db, actor, request, reason)?;
        let minutes = body["minutes"].as_i64().filter(|m| (0..=1440).contains(m));
        check(
            minutes.is_some(),
            "Maintenance minutes must be an integer from 0 to 1440",
        )?;
        let end = now + minutes.unwrap() * 60;
        check(
            end <= MAX_UTC,
            "Maintenance deadline exceeds supported UTC range",
        )?;
        let before = maintenance(state, db)?;
        db.execute("INSERT INTO moderation_maintenance VALUES(1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET started_at=excluded.started_at,end_at=excluded.end_at,reason=excluded.reason",params![now,end,reason])?;
        let after = maintenance(state, db)?;
        event(
            db,
            request,
            actor,
            "maintenance",
            "global",
            reason,
            &before,
            &after,
            now,
        )?;
        let changed = before != after;
        return Ok((before, after, changed));
    }
    profile(db, target)?;
    if let Some(link)=one(db,"SELECT o.role FROM management_operators o JOIN management_operator_accounts l USING(operator_id) WHERE l.account_id=? AND o.enabled=1",[target])?{let rank=|r:&str|ROLES.iter().position(|v|*v==r).unwrap_or(0);if s(actor,"role")!="owner"&&rank(s(actor,"role"))<=rank(s(&link,"role")){return Err(Failure::forbidden("An operator may not sanction an equal or higher enabled operator"));}}
    fields(
        body,
        if ["ban", "mute"].contains(&action) {
            &["expires_at", "reason"]
        } else {
            &["reason"]
        },
    )?;
    let now = mutation(state, db, actor, request, reason)?;
    moderation_account(db, target)?;
    if action == "kick" {
        let current = one(
            db,
            "SELECT guid FROM sessions WHERE ps4_id=? ORDER BY created_at DESC,guid DESC LIMIT 1",
            [target],
        )?
        .map(|r| s(&r, "guid").to_string());
        let revoked = if let Some(g) = &current {
            one(
                db,
                "SELECT 1 FROM moderation_revoked_sessions WHERE guid=?",
                [g],
            )?
            .is_some()
        } else {
            false
        };
        let before = json!({"account_id":target,"current_guid":current,"revoked":revoked,"online":online(db,target)?});
        let added = revoke(
            db,
            target,
            &current.into_iter().collect::<Vec<_>>(),
            request,
            reason,
            now,
        )?;
        db.execute("UPDATE profile_state SET online=0 WHERE ps4_id=?", [target])?;
        let mut after = before.clone();
        after["revoked"] = json!(!before["current_guid"].is_null());
        after["newly_revoked_guids"] = json!(added);
        after["online"] = json!(online(db, target)?);
        let changed = !added.is_empty() || before["online"] != after["online"];
        event(
            db, request, actor, "kick", target, reason, &before, &after, now,
        )?;
        return Ok((before, after, changed));
    }
    let enabled = ["ban", "mute"].contains(&action);
    let kind = if ["ban", "unban"].contains(&action) {
        "ban"
    } else {
        "mute"
    };
    let expires = if enabled {
        expiry(state, &body["expires_at"])?
    } else {
        None
    };
    let mut before = policy(db, target)?;
    before["online"] = json!(online(db, target)?);
    db.execute(
        "INSERT OR IGNORE INTO moderation_accounts(ps4_id) VALUES(?)",
        [target],
    )?;
    db.execute(&format!("UPDATE moderation_accounts SET {kind}_enabled=?,{kind}_expires_at=?,{kind}_reason=? WHERE ps4_id=?"),params![enabled as i64,expires,if enabled{reason}else{""},target])?;
    let mut added = Vec::new();
    if enabled && kind == "ban" {
        let guids = rows(
            db,
            "SELECT guid FROM sessions WHERE ps4_id=? ORDER BY guid",
            [target],
        )?
        .iter()
        .map(|r| s(r, "guid").to_string())
        .collect::<Vec<_>>();
        added = revoke(db, target, &guids, request, reason, now)?;
        db.execute("UPDATE profile_state SET online=0 WHERE ps4_id=?", [target])?;
    }
    let mut after = policy(db, target)?;
    after["online"] = json!(online(db, target)?);
    let changed = before != after || !added.is_empty();
    after["newly_revoked_guids"] = json!(added);
    event(
        db, request, actor, action, target, reason, &before, &after, now,
    )?;
    Ok((before, after, changed))
}
fn staff_label(
    state: &State,
    db: &Connection,
    target: &str,
    label: &Value,
    actor: &Value,
    request: &str,
    reason: &str,
) -> Result<(Value, Value, bool)> {
    let now = mutation(state, db, actor, request, reason)?;
    if s(actor, "role") != "owner" {
        return Err(Failure::forbidden(
            "Only an owner may assign a player display label",
        ));
    }
    moderation_account(db, target)?;
    let label = wire_text(label, "staff display label", 32, true)?;
    check(
        !label.contains(['<', '>']),
        "Staff display labels must be plain text",
    )?;
    let before = json!({"account_id":target,"staff_label":policy(db,target)?["staff_label"]});
    db.execute(
        "INSERT OR IGNORE INTO moderation_accounts(ps4_id) VALUES(?)",
        [target],
    )?;
    db.execute(
        "UPDATE moderation_accounts SET staff_label=? WHERE ps4_id=?",
        params![label, target],
    )?;
    let after = json!({"account_id":target,"staff_label":label});
    event(
        db,
        request,
        actor,
        "players.staff",
        target,
        reason,
        &before,
        &after,
        now,
    )?;
    let changed = before != after;
    Ok((before, after, changed))
}
// Gregorian UTC conversion over the moderation authority's supported years
// 1970..=9999. No local timezone or platform date range participates.
fn date_label(seconds: i64) -> String {
    let days = seconds / 86400;
    let z = days + 719468;
    let era = z / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let mut year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    let time = seconds % 86400;
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        time / 3600,
        time / 60 % 60,
        time % 60
    )
}
fn publish_news(
    state: &State,
    db: &Connection,
    body: &Value,
    actor: &Value,
    request: &str,
    reason: &str,
) -> Result<(Value, Value, bool)> {
    let now = mutation(state, db, actor, request, reason)?;
    if !["owner", "admin"].contains(&s(actor, "role")) {
        return Err(Failure::forbidden(
            "News publication requires an admin or owner",
        ));
    }
    let text = wire_text(&body["text"], "news text", 1000, false)?;
    let expires = expiry(state, &body["expires_at"])?;
    let id = uuid::Uuid::parse_str(request)
        .map_err(|_| Failure::invalid("Invalid moderation request ID"))?
        .to_string();
    db.execute(
        "INSERT INTO moderation_news VALUES(?,?,?,?,?,1)",
        params![id, text, date_label(now), now, expires],
    )?;
    let after = one(db, "SELECT * FROM moderation_news WHERE news_id=?", [&id])?
        .ok_or_else(|| Failure::missing("News not found"))?;
    event(
        db,
        request,
        actor,
        "news.publish",
        &id,
        reason,
        &Value::Null,
        &after,
        now,
    )?;
    Ok((Value::Null, after, true))
}
fn archive_news(
    state: &State,
    db: &Connection,
    id: &str,
    actor: &Value,
    request: &str,
    reason: &str,
) -> Result<(Value, Value, bool)> {
    let now = mutation(state, db, actor, request, reason)?;
    if !["owner", "admin"].contains(&s(actor, "role")) {
        return Err(Failure::forbidden(
            "News archival requires an admin or owner",
        ));
    }
    check(
        uuid::Uuid::parse_str(id)
            .ok()
            .is_some_and(|v| v.to_string() == id),
        "Invalid news ID",
    )?;
    let before = one(db, "SELECT * FROM moderation_news WHERE news_id=?", [id])?
        .ok_or_else(|| Failure::missing("News not found"))?;
    db.execute(
        "UPDATE moderation_news SET active=0 WHERE news_id=? AND active=1",
        [id],
    )?;
    let mut after = before.clone();
    after["active"] = json!(0);
    event(
        db,
        request,
        actor,
        "news.archive",
        id,
        reason,
        &before,
        &after,
        now,
    )?;
    let changed = before != after;
    Ok((before, after, changed))
}
fn review_report(
    state: &State,
    db: &Connection,
    id: &str,
    body: &Value,
    actor: &Value,
    request: &str,
    reason: &str,
) -> Result<(Value, Value, bool)> {
    let now = mutation(state, db, actor, request, reason)?;
    check(wire_hex(id, 64), "Invalid report ID")?;
    let status = s(body, "status");
    check(
        ["open", "resolved", "dismissed"].contains(&status),
        "Invalid report status",
    )?;
    let empty_note = json!("");
    let note = wire_text(
        body.get("note").unwrap_or(&empty_note),
        "report review note",
        512,
        true,
    )?;
    if one(
        db,
        "SELECT 1 FROM moderation_report_index WHERE report_id=?",
        [id],
    )?
    .is_none()
    {
        return Err(Failure::missing("Report not found"));
    }
    let before = one(
        db,
        "SELECT status,note,actor_id,updated_at FROM moderation_report_reviews WHERE report_id=?",
        [id],
    )?
    .unwrap_or(json!({"status":"open","note":"","actor_id":null,"updated_at":null}));
    db.execute("INSERT INTO moderation_report_reviews VALUES(?,?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET status=excluded.status,note=excluded.note,actor_id=excluded.actor_id,updated_at=excluded.updated_at",params![id,status,note,s(actor,"id"),now])?;
    let after = json!({"status":status,"note":note,"actor_id":actor["id"],"updated_at":now});
    event(
        db,
        request,
        actor,
        "report.review",
        id,
        reason,
        &before,
        &after,
        now,
    )?;
    let changed = before != after;
    Ok((before, after, changed))
}
