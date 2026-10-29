use super::*;
pub(super) const ROUTES: &[&str] = &[
    "Get_GatherConsume",
    "Get_GatherConsumeReward",
    "Get_GatherMedievalVillage",
    "Get_GatherPhaseGame",
    "Get_GatherStatus",
    "Get_npGather",
    "Get_npGatherChristmas",
    "Get_npGatherProcessItem",
    "Send_GatherInitInSpace",
    "Send_GatherMedievalVillageConsume",
];
const SCENES: [&str; 5] = ["Nexus", "LeafPark", "Dome", "Cube", "Beach"];
fn event(state: &State, db: &Connection, id: &str, t: i64) -> Result<(Value, Value)> {
    let e = one(db, "SELECT * FROM gathering_events WHERE type_id=?", [t])?
        .ok_or_else(|| Error::new(404, "Gathering event is not locally configured"))?;
    db.execute("INSERT OR IGNORE INTO gathering_progress(ps4_id,type_id,rewards_earned,updated_at) VALUES(?,?,?,?)",rusqlite::params![id,t,n(&e,"phase"),state.now()])?;
    let p = one(
        db,
        "SELECT * FROM gathering_progress WHERE ps4_id=? AND type_id=?",
        rusqlite::params![id, t],
    )?
    .unwrap();
    Ok((e, p))
}
fn cooldown(state: &State, e: &Value, p: &Value) -> i64 {
    let last = p["last_consume_at"].as_f64().unwrap_or(0.);
    if last == 0. {
        0
    } else {
        (n(e, "cooldown_seconds") as f64 - (state.now() - last))
            .ceil()
            .max(0.) as i64
    }
}
fn flags(db: &Connection, id: &str) -> Result<Vec<String>> {
    let completed: HashSet<String> = rows(
        db,
        "SELECT psidglobal FROM gathering_scenes WHERE ps4_id=? AND type_id=4",
        [id],
    )?
    .iter()
    .map(|r| s(r, "psidglobal").to_string())
    .collect();
    Ok(SCENES
        .iter()
        .map(|s| {
            if completed.contains(*s) {
                "1".into()
            } else {
                "0".into()
            }
        })
        .collect())
}
fn reward(state: &State, db: &Connection, id: &str, e: &Value) -> Result<()> {
    let text = e["reward_json"]
        .as_str()
        .ok_or_else(|| Error::new(409, "Event has no configured local reward"))?;
    let r: Value = serde_json::from_str(text)?;
    let kind = match s(&r, "kind") {
        "companion" => "companions",
        "locomotion" => "locomotions",
        "wardrobe" => "wardrobe",
        "housing" => "housing",
        _ => return Err(Error::bad("Invalid gathering reward kind")),
    };
    shop::grant(
        state,
        db,
        id,
        kind,
        s(&r, "item_id"),
        r["gender"].as_str(),
        r["category"].as_str(),
        r["name"].as_str(),
    )
}
pub(super) fn handle(
    state: &State,
    db: &Connection,
    route: &str,
    req: &Request,
    actor: Option<&str>,
) -> Result<String> {
    let count = match route {
        "Get_npGatherProcessItem" => 5,
        "Get_npGather" | "Get_npGatherChristmas" | "Send_GatherInitInSpace" => 4,
        "Get_GatherConsume" | "Get_GatherConsumeReward" => req.fields.len(),
        _ => 3,
    };
    if count < 3 || count > 5 {
        return Err(Error::bad("Invalid gathering field count"));
    }
    let p = identity(state, db, req, count, Some(1), actor, false)?;
    let f = &req.fields;
    let id = s(&p, "ps4_id");
    if [
        "Get_GatherMedievalVillage",
        "Send_GatherMedievalVillageConsume",
    ]
    .contains(&route)
    {
        if f[2].is_empty()
            || !f[2].bytes().all(|b| b.is_ascii_digit())
            || f[2].len() > 19
            || f[2]
                .parse::<u64>()
                .ok()
                .is_none_or(|n| n > 9_999_999_999_999_999_999 || n.to_string() != f[2])
        {
            return Err(Error::bad("Invalid client DateTime ticks"));
        }
        let row = one(db, "SELECT * FROM gathering_medieval WHERE ps4_id=?", [id])?;
        if route == "Get_GatherMedievalVillage" {
            let Some(r) = row else {
                return Ok(reply(f, &["0".into(), "0".into(), "0".into()]));
            };
            let cd = (r["cooldown_until"].as_f64().unwrap_or(0.) - state.now())
                .ceil()
                .max(0.) as i64;
            return Ok(reply(
                f,
                &[
                    (flag(&r, "active") && cd == 0).to_string(),
                    cd.to_string(),
                    n(&r, "amount_left").to_string(),
                ],
            ));
        }
        let r = row
            .filter(|r| {
                flag(r, "active")
                    && r["cooldown_until"].as_f64().unwrap_or(0.) <= state.now()
                    && n(r, "amount_left") > 0
            })
            .ok_or_else(|| Error::new(409, "Medieval gathering is unavailable"))?;
        let left = n(&r, "amount_left") - 1;
        db.execute(
            "UPDATE gathering_medieval SET amount_left=?,updated_at=? WHERE ps4_id=?",
            rusqlite::params![left, state.now(), id],
        )?;
        return Ok(reply(
            f,
            &[
                if left == 0 { "5" } else { "1" }.into(),
                "0".into(),
                if left == 0 {
                    "Completed".into()
                } else {
                    left.to_string()
                },
            ],
        ));
    }
    let client_total = if ["Get_npGather", "Get_npGatherProcessItem"].contains(&route) {
        Some(canonical_uint(&f[3], "client gathering total", 1_000_000)?)
    } else {
        None
    };
    if ["Get_npGatherChristmas", "Send_GatherInitInSpace"].contains(&route) {
        token(&f[2], "space identifier", 256, false)?;
    }
    let christmas_step = if route == "Get_npGatherChristmas" {
        Some(canonical_uint(&f[3], "Christmas state", 1)?)
    } else {
        None
    };
    let t = if route == "Get_npGather" {
        let e = one(
            db,
            "SELECT type_id FROM gathering_events WHERE name=?",
            [&f[2]],
        )?
        .ok_or_else(|| Error::new(404, "Gathering name is not locally configured"))?;
        n(&e, "type_id")
    } else if route == "Get_npGatherChristmas" {
        1
    } else if route == "Get_npGatherProcessItem" {
        canonical_uint(&f[4], "gathering type", 8)?
    } else if route == "Send_GatherInitInSpace" {
        canonical_uint(&f[3], "gathering type", 8)?
    } else {
        canonical_uint(&f[2], "gathering type", 8)?
    };
    let consume = ["Get_GatherConsume", "Get_GatherConsumeReward"].contains(&route);
    let reward_route = route == "Get_GatherConsumeReward";
    let consume_supplied = if consume {
        let counted = [1, 2, 3, 5, 7].contains(&t);
        let short = if reward_route {
            [4, 6, 8].contains(&t)
        } else {
            [6, 8].contains(&t)
        };
        if counted {
            if f.len() != 4 {
                return Err(Error::bad("Missing client gathering count"));
            }
            Some(canonical_uint(&f[3], "client gathering count", 1_000_000)?)
        } else if t == 4 && !reward_route {
            if f.len() != 4 {
                return Err(Error::bad("Missing Christmas 2018 scene value"));
            }
            token(&f[3], "Christmas 2018 PSID", 256, false)?;
            None
        } else if short {
            if f.len() != 3 {
                return Err(Error::bad("Unexpected gathering request field"));
            }
            None
        } else {
            return Err(Error::new(409, "Unsupported gathering consume type"));
        }
    } else {
        None
    };
    let (e, p) = event(state, db, id, t)?;
    let active = flag(&e, "active");
    let current = n(&p, "current_items");
    let max = n(&e, "max_items");
    let earned = n(&p, "rewards_earned");
    match route {
        "Get_npGather" => {
            if client_total.unwrap() != max {
                return Err(Error::new(
                    409,
                    "Client gathering total differs from local configuration",
                ));
            }
            Ok(reply(
                f,
                &if active {
                    vec!["1".into(), current.to_string(), max.to_string()]
                } else {
                    vec!["0".into(), n(&e, "cooldown_seconds").to_string()]
                },
            ))
        }
        "Get_npGatherProcessItem" => {
            if s(&e, "name") != f[2] || client_total.unwrap() != max || !active {
                return Err(Error::new(
                    409,
                    "Gathering event is inactive or client configuration differs",
                ));
            }
            let next = max.min(current + 1);
            db.execute("UPDATE gathering_progress SET current_items=?,updated_at=? WHERE ps4_id=? AND type_id=?",rusqlite::params![next,state.now(),id,t])?;
            Ok(reply(
                f,
                &[
                    f[2].clone(),
                    next.to_string(),
                    max.to_string(),
                    next.to_string(),
                ],
            ))
        }
        "Get_GatherStatus" => Ok(reply(
            f,
            &[active.to_string(), t.to_string(), current.to_string()],
        )),
        "Send_GatherInitInSpace" | "Get_GatherPhaseGame" => {
            let mut values = if route == "Send_GatherInitInSpace" {
                token(&f[2], "space identifier", 256, false)?;
                vec![
                    t.to_string(),
                    current.to_string(),
                    earned.to_string(),
                    cooldown(state, &e, &p).to_string(),
                ]
            } else {
                vec![
                    t.to_string(),
                    cooldown(state, &e, &p).to_string(),
                    current.to_string(),
                    earned.to_string(),
                ]
            };
            if t == 4 {
                values.extend(flags(db, id)?);
            }
            Ok(reply(f, &values))
        }
        "Get_npGatherChristmas" => {
            let step = christmas_step.unwrap();
            let values = if !active {
                vec![step, 0, 0, n(&e, "cooldown_seconds"), current]
            } else if step == 0 {
                vec![0, 1, 0, 0, current]
            } else {
                vec![1, 0, 2, cooldown(state, &e, &p), current]
            };
            Ok(reply(
                f,
                &values.iter().map(|v| v.to_string()).collect::<Vec<_>>(),
            ))
        }
        "Get_GatherConsume" | "Get_GatherConsumeReward" => {
            if consume_supplied.is_some_and(|n| n != current) {
                return Err(Error::new(
                    409,
                    "Client gathering count differs from durable progress",
                ));
            }
            if reward_route {
                if !active || current < max || flag(&p, "reward_claimed") {
                    return Err(Error::new(
                        409,
                        "Gathering reward is unavailable or already claimed",
                    ));
                }
                reward(state, db, id, &e)?;
                db.execute("UPDATE gathering_progress SET current_items=0,rewards_earned=?,reward_claimed=1,last_consume_at=?,updated_at=? WHERE ps4_id=? AND type_id=?",rusqlite::params![earned+1,state.now(),state.now(),id,t])?;
                return Ok(reply(
                    f,
                    &[t.to_string(), "0".into(), (earned + 1).to_string()],
                ));
            }
            if !active || cooldown(state, &e, &p) > 0 {
                return Err(Error::new(
                    409,
                    "Gathering event is inactive or cooling down",
                ));
            }
            let next = if t == 4 {
                if !SCENES.contains(&f[3].as_str()) {
                    return Err(Error::new(
                        409,
                        "PSID is not part of the Christmas 2018 challenge",
                    ));
                }
                db.execute(
                    "INSERT OR IGNORE INTO gathering_scenes VALUES(?,4,?,?)",
                    rusqlite::params![id, f[3], state.now()],
                )?;
                let scenes: i64 = db.query_row(
                    "SELECT COUNT(*) FROM gathering_scenes WHERE ps4_id=? AND type_id=4",
                    [id],
                    |r| r.get(0),
                )?;
                max.min(scenes)
            } else {
                max.min(current + 1)
            };
            db.execute("UPDATE gathering_progress SET current_items=?,spaces_completed=CASE WHEN type_id=4 THEN ? ELSE spaces_completed END,updated_at=? WHERE ps4_id=? AND type_id=?",rusqlite::params![next,next,state.now(),id,t])?;
            Ok(reply(
                f,
                &[t.to_string(), next.to_string(), earned.to_string()],
            ))
        }
        _ => Err(Error::new(501, "Gathering route not reconstructed")),
    }
}
