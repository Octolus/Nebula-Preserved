//! Immutable synthetic differential fixture, accessible only in the stdin probe.
//! No network endpoint exposes data seeding or arbitrary SQL.
use crate::{
    dispatch,
    error::{Error, Result},
    state::State,
};
use serde_json::Value;
pub fn apply(state: &State, fixture: &Value) -> Result<()> {
    let expected: Value = serde_json::from_str(include_str!(
        "../tests/fixtures/configured-mutations-v1.json"
    ))?;
    if fixture != &expected {
        return Err(Error::bad("UNREVIEWED_FIXTURE"));
    }
    let count: i64 = state
        .connection()?
        .query_row("SELECT count(*) FROM profiles", [], |r| r.get(0))?;
    if count != 0 {
        return Err(Error::bad("FIXTURE_REQUIRES_FRESH_DATABASE"));
    }
    for account in fixture["accounts"].as_array().unwrap() {
        let account_id = account["account_id"].as_str().unwrap();
        let name = account["username"].as_str().unwrap();
        let platform = account["platform"].as_str().unwrap();
        let hash = account["request_hash"].as_str().unwrap();
        dispatch::dispatch(
            state,
            "N2UserExist",
            &format!("{name}#v72#false#{account_id}#1.25#{platform}"),
            None,
        )?;
        dispatch::dispatch(
            state,
            "ChannelGUIDServlet",
            &format!("{account_id}#{hash}#{platform}"),
            None,
        )?;
    }
    let schema: Value = serde_json::from_str(include_str!("../tests/fixtures/schema.json"))?;
    let mut db = state.connection()?;
    let tx = db.transaction()?;
    for (table, columns) in schema["table_columns"].as_object().unwrap() {
        let columns = columns
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect::<Vec<_>>();
        // Identifiers are compiled, reviewed schema constants, never input.
        let sql = format!(
            "INSERT INTO \"{table}\" ({}) VALUES ({})",
            columns
                .iter()
                .map(|s| format!("\"{s}\""))
                .collect::<Vec<_>>()
                .join(","),
            vec!["?"; columns.len()].join(",")
        );
        for row in fixture["tables"][table].as_array().unwrap() {
            let values: Vec<rusqlite::types::Value> = columns
                .iter()
                .map(|c| match &row[*c] {
                    Value::Null => rusqlite::types::Value::Null,
                    Value::Bool(b) => (*b as i64).into(),
                    Value::String(s) => s.clone().into(),
                    Value::Number(n) => {
                        if let Some(i) = n.as_i64() {
                            i.into()
                        } else {
                            n.as_f64().unwrap().into()
                        }
                    }
                    _ => unreachable!("Immutable scalar fixture"),
                })
                .collect();
            tx.execute(&sql, rusqlite::params_from_iter(values))?;
        }
    }
    tx.commit()?;
    Ok(())
}
