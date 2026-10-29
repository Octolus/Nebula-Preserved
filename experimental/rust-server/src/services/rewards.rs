use super::*;
pub(super) const ROUTES: &[&str] = &[
    "CheckOwnGenericReward",
    "GenericReward",
    "RewardClothServlet",
    "RewardConsumeServlet",
    "SKLPromoServlet",
    "SKLPromoTriggerServlet",
    "checkRewardAvailableServlet",
    "CinemaInteractionNPServlet",
    "CheckIfSpaceStillExistServlet",
    "GetConsumableServlet",
    "GetConsumablePriceServlet",
];
const TYPES: &[&str] = &[
    "Halloween",
    "ArcheryBow",
    "ArcheryCarcaj",
    "Chess",
    "CastleSword",
    "PatricksDay2018",
    "Cube",
    "CampSilverLake0",
    "CampSilverLake1",
    "CampSilverLake2",
    "CampSilverLake3",
    "GhostWolf",
];
fn definition(db: &Connection, route: &str, key: &str) -> Result<Option<Value>> {
    one(
        db,
        "SELECT * FROM local_reward_definitions WHERE route=? AND trigger_key=?",
        rusqlite::params![route, key],
    )
}
fn required(state: &State, db: &Connection, route: &str, key: &str) -> Result<Value> {
    let d = definition(db, route, key)?
        .filter(|d| flag(d, "enabled"))
        .ok_or_else(|| Error::new(404, "No enabled local reward definition"))?;
    if route == "RewardClothServlet" && (key != "0" || s(&d, "grant_kind") != "wardrobe") {
        return Err(Error::new(
            500,
            "Stored cloth reward is outside the shipped contract",
        ));
    }
    if route == "SKLPromoServlet" {
        canonical_uint(key, "numeric reward trigger", i32::MAX.into())?;
        let cat = state.catalog("skl-promo-catalog.json")?;
        let found = cat["records"].as_array().and_then(|a| {
            a.iter().find(|v| {
                v["promo_id"].as_i64().map(|i| i.to_string()).as_deref() == Some(key)
                    || s(v, "promo_id") == key
            })
        });
        let Some(record) = found else {
            return Err(Error::new(404, "Unknown shipped SKL promo trigger"));
        };
        if !record["valid_sprite_pair_indices"]
            .as_array()
            .is_some_and(|a| a.contains(&d["sprite_id"]))
        {
            return Err(Error::new(
                500,
                "Stored promo sprite is outside the shipped trigger",
            ));
        }
    }
    if route == "checkRewardAvailableServlet" && !TYPES.contains(&key) {
        return Err(Error::new(
            500,
            "Stored reward type is outside the shipped enum",
        ));
    }
    Ok(d)
}
fn claimed(db: &Connection, id: &str, route: &str, key: &str) -> Result<bool> {
    Ok(one(
        db,
        "SELECT outcome_json FROM local_reward_claims WHERE ps4_id=? AND route=? AND trigger_key=?",
        rusqlite::params![id, route, key],
    )?
    .is_some())
}
pub(super) fn grant_consumable(
    state: &State,
    db: &Connection,
    id: &str,
    kind: &str,
    units: i64,
    uses: i64,
) -> Result<()> {
    if !["coffee", "oktoberfest"].contains(&kind) || units <= 0 || uses <= 0 {
        return Err(Error::bad(
            "Consumable reward requires matching kind, positive units and uses",
        ));
    }
    db.execute("INSERT INTO consumable_balances VALUES(?,?,?,?,?,?,0,0,?) ON CONFLICT(ps4_id,kind) DO UPDATE SET units=consumable_balances.units+excluded.units,prop_use_count=excluded.prop_use_count,price_display=excluded.price_display,price_type_display=excluded.price_type_display,reward_index=0,rewarded=0,updated_at=excluded.updated_at",rusqlite::params![id,kind,units,uses,"1","local token",state.now()])?;
    Ok(())
}
fn claim(
    state: &State,
    db: &Connection,
    p: &Value,
    route: &str,
    key: &str,
) -> Result<(bool, Value)> {
    let d = required(state, db, route, key)?;
    let id = s(p, "ps4_id");
    if claimed(db, id, route, key)? {
        return Ok((false, d));
    }
    let kind = s(&d, "grant_kind");
    let item = s(&d, "item_id");
    match kind {
        "wardrobe" | "companions" | "locomotions" | "housing" => shop::grant(
            state,
            db,
            id,
            kind,
            item,
            d["gender"].as_str(),
            d["category"].as_str(),
            d["display_name"].as_str(),
        )?,
        "coffee" | "oktoberfest" => {
            if item != kind {
                return Err(Error::new(500, "Invalid stored consumable reward target"));
            }
            grant_consumable(state, db, id, kind, n(&d, "units"), n(&d, "uses"))?;
        }
        "cinema" => {
            let interaction = canonical_uint(item, "cinema interaction", 1)?;
            db.execute(
                "INSERT OR IGNORE INTO cinema_capabilities VALUES(?,?,?)",
                rusqlite::params![id, interaction, state.now()],
            )?;
        }
        _ => {
            return Err(Error::new(
                500,
                "Reward definition has no validated grant target",
            ))
        }
    }
    db.execute(
        "INSERT INTO local_reward_claims VALUES(?,?,?,?,?)",
        rusqlite::params![
            id,
            route,
            key,
            js(&json!({"grant_kind":kind,"item_id":item})),
            state.now()
        ],
    )?;
    if [
        "GenericReward",
        "RewardClothServlet",
        "RewardConsumeServlet",
        "SKLPromoServlet",
    ]
    .contains(&route)
    {
        ipc::enqueue(state, db, id, p, 4, "", &format!("reward:{route}:{key}"))?;
    }
    Ok((true, d))
}
pub(super) fn handle(
    state: &State,
    db: &Connection,
    route: &str,
    req: &Request,
    actor: Option<&str>,
) -> Result<String> {
    let consumable = route.starts_with("GetConsumable");
    let p = identity(
        state,
        db,
        req,
        if consumable { 4 } else { 3 },
        Some(1),
        actor,
        false,
    )?;
    let f = &req.fields;
    let key = &f[2];
    if !consumable {
        token(key, "reward trigger", 256, false)?;
    }
    if !consumable && platform(&req.platform)? != platform(s(&p, "platform"))? {
        return Err(Error::new(403, "Session platform mismatch"));
    }
    if consumable {
        if f[3].is_empty()
            || !f[3].bytes().all(|b| b.is_ascii_digit())
            || uint(&f[3], "consumable table ID", 0).is_err()
        {
            return Err(Error::bad("Unsupported consumable table ID"));
        }
        if !["coffee", "oktoberfest"].contains(&key.as_str()) {
            return Err(Error::new(
                404,
                "Unsupported consumable (picnic/minigames are deferred)",
            ));
        }
        let balance = one(
            db,
            "SELECT * FROM consumable_balances WHERE ps4_id=? AND kind=?",
            rusqlite::params![f[1], key],
        )?;
        if route == "GetConsumablePriceServlet" {
            let b =
                balance.unwrap_or(json!({"price_display":"1","price_type_display":"local token"}));
            return Ok(reply(
                f,
                &[
                    key.clone(),
                    "".into(),
                    s(&b, "price_display").into(),
                    s(&b, "price_type_display").into(),
                    n(&b, "units").to_string(),
                    flag(&b, "rewarded").to_string(),
                ],
            ));
        }
        if !current(db, &f[1], &f[0])? {
            return Err(Error::new(
                403,
                "Consumable issue requires the current account session",
            ));
        }
        let Some(b) = balance.filter(|b| n(b, "units") > 0) else {
            return Ok(reply(
                f,
                &[
                    key.clone(),
                    "".into(),
                    "false".into(),
                    "".into(),
                    "0".into(),
                ],
            ));
        };
        let receipt = uuid();
        let now = state.now();
        db.execute(
            "UPDATE consumable_balances SET units=units-1,updated_at=? WHERE ps4_id=? AND kind=?",
            rusqlite::params![now, f[1], key],
        )?;
        db.execute(
            "INSERT INTO consumable_receipts VALUES(?,?,?,?,0,?,?,?,?,'prepared',NULL)",
            rusqlite::params![
                receipt,
                f[1],
                f[0],
                key,
                n(&b, "prop_use_count"),
                n(&b, "reward_index"),
                now,
                now + 300.
            ],
        )?;
        return Ok(reply(
            f,
            &[
                key.clone(),
                "".into(),
                "true".into(),
                receipt,
                n(&b, "reward_index").to_string(),
            ],
        ));
    }
    match route {
        "CheckIfSpaceStillExistServlet" => {
            let a = one(
                db,
                "SELECT instance_id,psidglobal FROM allocations WHERE guid=?",
                [&f[0]],
            )?;
            let live = a.is_some_and(|a| {
                s(&a, "instance_id") == key && ready(state, key, s(&a, "psidglobal"))
            });
            Ok(format!("true#{live}"))
        }
        "CheckOwnGenericReward" => {
            let enabled =
                definition(db, "GenericReward", key)?.is_some_and(|d| flag(&d, "enabled"));
            Ok(format!(
                "false#{}#{}#{}",
                f[0],
                f[1],
                !enabled || claimed(db, &f[1], "GenericReward", key)?
            ))
        }
        "SKLPromoTriggerServlet" => {
            required(state, db, "SKLPromoServlet", key)?;
            Ok(reply(
                f,
                &[claimed(db, &f[1], "SKLPromoServlet", key)?.to_string()],
            ))
        }
        "checkRewardAvailableServlet" => {
            if !TYPES.contains(&key.as_str()) {
                return Err(Error::bad("Unknown shipped reward type"));
            }
            let avail = definition(db, route, key)?.is_some_and(|d| flag(&d, "enabled"));
            Ok(format!("true#{}#{avail}", f[0]))
        }
        "CinemaInteractionNPServlet" => {
            canonical_uint(key, "cinema interaction", 1)?;
            claim(state, db, &p, route, key)?;
            Ok(reply(f, &["true".into()]))
        }
        _ => {
            let (fresh, d) = claim(state, db, &p, route, key)?;
            match route {
                "GenericReward" => Ok(format!("false#{}#{}#{fresh}", f[0], f[1])),
                "RewardClothServlet" => {
                    canonical_uint(key, "cloth reward", i32::MAX.into())?;
                    Ok(format!("false#{}#{fresh}", f[0]))
                }
                "SKLPromoServlet" => Ok(reply(f, &[n(&d, "sprite_id").to_string()])),
                _ => Ok(format!("true#{}#{}", f[0], f[1])),
            }
        }
    }
}
/// Publish only after the SQLite reservation commits, and refund on IO failure.
pub(super) fn publish_consumable(state: &State, response: &str) -> Result<()> {
    let f: Vec<_> = response.split('#').collect();
    if f.len() != 8 || f[5] != "true" {
        return Ok(());
    }
    let id = f[6];
    let db = state.connection()?;
    let row = one(
        &db,
        "SELECT * FROM consumable_receipts WHERE receipt_id=?",
        [id],
    )?
    .ok_or_else(|| Error::new(500, "Missing reserved consumable receipt"))?;
    drop(db);
    let payload = json!({"format_version":1,"policy":"local_consumable_receipt_v1","receipt_id":id,"guid":row["guid"],"ps4_id":row["ps4_id"],"kind":row["kind"],"table_id":0,"use_count":row["use_count"],"reward_index":row["reward_index"],"issued_at":row["issued_at"],"expires_at":row["expires_at"]});
    if let Err(err) = ipc::publish(
        &state
            .state_dir
            .join("consumable-receipts")
            .join(format!("{id}.json")),
        &payload,
        false,
    ) {
        let mut db = state.connection()?;
        let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        if tx.execute("UPDATE consumable_receipts SET status='cancelled' WHERE receipt_id=? AND status='prepared'",[id])?==1{tx.execute("UPDATE consumable_balances SET units=units+1 WHERE ps4_id=? AND kind=?",rusqlite::params![s(&row,"ps4_id"),s(&row,"kind")])?;}
        tx.commit()?;
        return Err(err);
    }
    state.connection()?.execute(
        "UPDATE consumable_receipts SET status='pending' WHERE receipt_id=? AND status='prepared'",
        [id],
    )?;
    Ok(())
}
