//! JSONL probe: disposable local files only, no listener, process or desktop control.
use crate::{
    dispatch,
    error::{Error, Result},
    state::State,
    wire,
};
use serde_json::{json, Value};
use std::{
    io::{self, BufRead, Write},
    path::PathBuf,
};

fn field<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v.get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| Error::bad(format!("Missing {key}")))
}
fn snapshot(state: &State) -> Result<Value> {
    let db = state.connection()?;
    let names:Vec<String>=db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")?.query_map([],|r|r.get(0))?.collect::<rusqlite::Result<_>>()?;
    let mut tables = serde_json::Map::new();
    for name in names {
        let quoted = format!("\"{}\"", name.replace('"', "\"\""));
        let columns: Vec<(String, String)> = db
            .prepare(&format!("PRAGMA table_info({quoted})"))?
            .query_map([], |r| Ok((r.get(1)?, r.get(2)?)))?
            .collect::<rusqlite::Result<_>>()?;
        let mut stmt = db.prepare(&format!("SELECT * FROM {quoted}"))?;
        let rows: Vec<Value> = stmt
            .query_map([], |row| {
                let mut result = serde_json::Map::new();
                for (i, (column, _)) in columns.iter().enumerate() {
                    use rusqlite::types::ValueRef;
                    let value = match row.get_ref(i)? {
                        ValueRef::Null => Value::Null,
                        ValueRef::Integer(x) => json!(x),
                        ValueRef::Real(x) => json!(x),
                        ValueRef::Text(x) => json!(String::from_utf8_lossy(x)),
                        ValueRef::Blob(x) => json!({"blob_hex":hex::encode(x)}),
                    };
                    result.insert(column.clone(), value);
                }
                Ok(Value::Object(result))
            })?
            .collect::<rusqlite::Result<_>>()?;
        tables.insert(name,json!({"columns":columns.iter().map(|(name,ty)|json!({"name":name,"type":ty})).collect::<Vec<_>>(),"rows":rows}));
    }
    Ok(json!({"tables":tables}))
}
pub fn run() -> anyhow::Result<()> {
    let mut state: Option<State> = None;
    let mut location: Option<(PathBuf, PathBuf)> = None;
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in io::stdin().lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let v: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(_) => {
                writeln!(
                    out,
                    "{}",
                    json!({"id":null,"ok":false,"error":"INVALID_JSON"})
                )?;
                out.flush()?;
                continue;
            }
        };
        let id = v.get("id").cloned().unwrap_or(Value::Null);
        let result = (|| -> Result<Value> {
            match field(&v, "op")? {
                "init" => {
                    let dir = PathBuf::from(field(&v, "state_dir")?);
                    let protocol = PathBuf::from(field(&v, "reference_protocol_dir")?);
                    let opened = State::open(&dir, &protocol)?;
                    if let Some(fixture) = v.get("fixture") {
                        crate::fixture::apply(&opened, fixture)?;
                    }
                    state = Some(opened);
                    location = Some((dir, protocol));
                    Ok(json!({}))
                }
                "restart" => {
                    state = None;
                    let (dir, protocol) = location
                        .as_ref()
                        .ok_or_else(|| Error::bad("NOT_INITIALIZED"))?;
                    state = Some(State::open(dir, protocol)?);
                    Ok(json!({}))
                }
                "snapshot" => Ok(
                    json!({"state":snapshot(state.as_ref().ok_or_else(||Error::bad("NOT_INITIALIZED"))?)?}),
                ),
                "close" => {
                    state = None;
                    Ok(json!({}))
                }
                "admin_init" => {
                    let state = state
                        .as_ref()
                        .ok_or_else(|| Error::bad("NOT_INITIALIZED"))?;
                    crate::admin::initialize(
                        state,
                        field(&v, "token")?.as_bytes(),
                        v.get("operators")
                            .ok_or_else(|| Error::bad("Missing operators"))?,
                    )?;
                    Ok(json!({}))
                }
                "admin" => {
                    let state = state
                        .as_ref()
                        .ok_or_else(|| Error::bad("NOT_INITIALIZED"))?;
                    let headers: std::collections::HashMap<String, String> =
                        serde_json::from_value(
                            v.get("headers").cloned().unwrap_or_else(|| json!({})),
                        )?;
                    let mut tail = field(&v, "tail")?.to_string();
                    if let Some(query) = v.get("query").and_then(Value::as_str) {
                        tail.push('?');
                        tail.push_str(query);
                    }
                    let reply = crate::admin::handle(
                        state,
                        field(&v, "method")?,
                        &tail,
                        &headers,
                        v.get("body").unwrap_or(&Value::Null),
                    );
                    Ok(json!({"status":reply.status,"body":reply.body}))
                }
                "http" => {
                    let state = state
                        .as_ref()
                        .ok_or_else(|| Error::bad("NOT_INITIALIZED"))?;
                    let route = field(&v, "route")?;
                    let method = v.get("method").and_then(Value::as_str).unwrap_or("GET");
                    if method != "GET" || (!v["plaintext"].is_string() && !v["data"].is_string()) {
                        return Ok(
                            json!({"status":400,"body":"Expected encrypted GET request","plaintext":null,"content_type":"text/plain"}),
                        );
                    }
                    let plaintext = if let Some(p) = v["plaintext"].as_str() {
                        p.to_owned()
                    } else {
                        match wire::decrypt(v["data"].as_str().unwrap()) {
                            Ok(p) => p,
                            Err(_) => {
                                return Ok(
                                    json!({"status":400,"body":"Invalid encrypted request","plaintext":null,"content_type":"text/plain"}),
                                )
                            }
                        }
                    };
                    let started = std::time::Instant::now();
                    let reply = loop {
                        match dispatch::dispatch(
                            state,
                            route,
                            &plaintext,
                            v.get("actor").and_then(Value::as_str),
                        ) {
                            Err(e)
                                if e.status == 503
                                    && e.message
                                        == "Housing save is waiting for its original counterpart"
                                    && started.elapsed().as_secs() < 31 =>
                            {
                                std::thread::sleep(std::time::Duration::from_millis(50))
                            }
                            other => break other,
                        }
                    };
                    let (status, reply) = match reply {
                        Ok(p) => (200, p),
                        Err(e) => (e.status, "ERROR".into()),
                    };
                    Ok(
                        json!({"status":status,"body":wire::encrypt(&reply)?,"plaintext":reply,"content_type":"text/plain"}),
                    )
                }
                _ => Err(Error::bad("NOT_IMPLEMENTED")),
            }
        })();
        let response = match result {
            Ok(Value::Object(mut map)) => {
                map.insert("id".into(), id);
                map.insert("ok".into(), json!(true));
                Value::Object(map)
            }
            Ok(_) => unreachable!(),
            Err(e) => json!({"id":id,"ok":false,"error":e.message}),
        };
        writeln!(out, "{response}")?;
        out.flush()?;
    }
    Ok(())
}
