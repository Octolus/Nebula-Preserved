use super::*;
pub(super) const ROUTES: &[&str] = &[
    "GetFeaturesServlet",
    "GetGenderDataShopServlet",
    "GetItemAssetsDataServlet",
    "GetShopDataShopServlet",
    "GetShopInfoPlayerShop",
    "GetShopTypeDataShopServlet",
    "NPShopBundleItemsServlet",
    "NPShopBuyItemServlet",
    "NPShopGiftItemServlet",
    "NPShopIsItemPurchasedServlet",
    "NPShopSyncCrystalsServlet",
];

pub(super) fn asset(
    state: &State,
    kind: &str,
    id: &str,
    gender: Option<&str>,
    category: Option<&str>,
) -> Result<Value> {
    token(id, "asset identifier", 1024, false)?;
    if kind == "housing" {
        return housing::catalog(state)?
            .remove(id)
            .ok_or_else(|| Error::new(404, "Unknown shipped housing asset"));
    }
    if kind == "wardrobe" {
        let cat = state.catalog("avatar-asset-catalog.json")?;
        let choices: Vec<Value> = cat["items"]
            .as_array()
            .unwrap_or(&Vec::new())
            .iter()
            .filter(|v| {
                s(v, "item_id") == id
                    && ["MALE", "FEMALE"].contains(&s(v, "gender"))
                    && s(v, "category") != "UNKNOWN"
                    && !flag(v, "category_conflict")
                    && gender.is_none_or(|g| s(v, "gender") == g)
                    && category.is_none_or(|c| s(v, "category") == c)
            })
            .cloned()
            .collect();
        if choices.is_empty() {
            return Err(Error::new(
                404,
                "Item has no unambiguous shipped wardrobe asset",
            ));
        }
        let keys: HashSet<_> = choices
            .iter()
            .map(|v| (s(v, "gender"), s(v, "category")))
            .collect();
        if keys.len() != 1 {
            return Err(Error::bad(
                "Item appears in multiple categories; supply gender and category",
            ));
        }
        return Ok(choices[0].clone());
    }
    if !["companions", "locomotions"].contains(&kind) {
        return Err(Error::bad("Unsupported grant kind"));
    }
    resource_catalog(state)?
        .remove(&(kind.to_string(), id.to_string()))
        .ok_or_else(|| Error::new(404, "Unknown or conflicting shipped resource"))
}
pub(super) fn resource_catalog(state: &State) -> Result<HashMap<(String, String), Value>> {
    let cat = state.catalog("resource-entitlements.json")?;
    if cat["format_version"] != 1 {
        return Err(Error::new(501, "Unsupported resource catalog"));
    }
    let items = cat["items"]
        .as_array()
        .ok_or_else(|| Error::new(500, "Missing resource catalog items"))?;
    let mut counts = HashMap::new();
    for v in items {
        *counts.entry(s(v, "item_id")).or_insert(0usize) += 1;
    }
    let mut out = HashMap::new();
    for v in items {
        let kind = s(v, "kind");
        let id = s(v, "item_id");
        if counts.get(id) != Some(&1) || !["companions", "locomotions"].contains(&kind) {
            continue;
        }
        let table = if kind == "companions" {
            "COMPANIONS"
        } else {
            "LOCOMOTIONS"
        };
        let prefix = if kind == "companions" { "02" } else { "03" };
        if s(v, "kind") != kind
            || v["grantable"] != true
            || v["conflicts"].as_array().is_some_and(|x| !x.is_empty())
            || s(v, "table") != table
            || s(v, "bundle") != format!("{prefix}/{}", id.to_lowercase())
            || s(v, "requested_resource_path") != format!("Wardrobe_EAB/{table}/{id}/{id}")
        {
            continue;
        }
        token(id, "resource identifier", 1024, false)?;
        out.insert((kind.into(), id.into()), v.clone());
    }
    Ok(out)
}
pub(super) fn grant(
    state: &State,
    db: &Connection,
    id: &str,
    kind: &str,
    item: &str,
    gender: Option<&str>,
    category: Option<&str>,
    name: Option<&str>,
) -> Result<()> {
    let a = asset(state, kind, item, gender, category)?;
    let label = name.unwrap_or(item);
    token(label, "item display name", 1024, false)?;
    match kind {
        "wardrobe" => {
            db.execute("INSERT OR IGNORE INTO entitlements(ps4_id,item_id,gender,category,bundle,display_name,granted_at) VALUES(?,?,?,?,?,?,?)",rusqlite::params![id,item,s(&a,"gender"),s(&a,"category"),s(&a,"bundle"),label,state.now()])?;
            if let Some(label) = name {
                db.execute("UPDATE entitlements SET display_name=? WHERE ps4_id=? AND item_id=? AND gender=? AND category=?",rusqlite::params![label,id,item,s(&a,"gender"),s(&a,"category")])?;
            }
        }
        "companions" | "locomotions" => {
            db.execute("INSERT INTO resource_entitlements VALUES(?,?,?,?,?,?,?) ON CONFLICT(ps4_id,kind,item_id) DO UPDATE SET bundle=excluded.bundle,asset_path=excluded.asset_path,display_name=CASE WHEN ? THEN excluded.display_name ELSE resource_entitlements.display_name END",rusqlite::params![id,kind,item,s(&a,"bundle"),s(&a,"asset_path"),label,state.now(),name.is_some()])?;
        }
        "housing" => {
            db.execute("INSERT INTO housing_entitlements VALUES(?,?,?,?) ON CONFLICT(ps4_id,item_id) DO UPDATE SET display_name=excluded.display_name",rusqlite::params![id,item,label,state.now()])?;
        }
        _ => return Err(Error::bad("Unsupported item kind")),
    }
    Ok(())
}
fn offer(db: &Connection, id: &str, active: bool) -> Result<Value> {
    one(
        db,
        if active {
            "SELECT * FROM shop_offers WHERE offer_id=? AND active=1"
        } else {
            "SELECT * FROM shop_offers WHERE offer_id=?"
        },
        [id],
    )?
    .ok_or_else(|| Error::new(404, "Unknown local offer"))
}
fn children(db: &Connection, id: &str) -> Result<Vec<Value>> {
    rows(db,"SELECT o.* FROM shop_bundle_items b JOIN shop_offers o ON o.offer_id=b.child_offer_id WHERE b.bundle_offer_id=? ORDER BY b.ordinal,o.offer_id",[id])
}
pub(super) fn owned(
    db: &Connection,
    id: &str,
    o: &Value,
    stack: &mut HashSet<String>,
) -> Result<bool> {
    if !stack.insert(s(o, "offer_id").into()) {
        return Err(Error::new(409, "Shop bundle cycle"));
    }
    let direct: bool = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM shop_owned WHERE ps4_id=? AND offer_id=?)",
        rusqlite::params![id, s(o, "offer_id")],
        |r| r.get(0),
    )?;
    let result = if direct {
        true
    } else {
        match s(o,"kind") {
        "wardrobe"=>db.query_row("SELECT EXISTS(SELECT 1 FROM entitlements WHERE ps4_id=? AND item_id=? AND gender=? AND category=?)",rusqlite::params![id,s(o,"item_id"),s(o,"gender"),s(o,"category")],|r|r.get(0))?,
        "companions"|"locomotions"=>db.query_row("SELECT EXISTS(SELECT 1 FROM resource_entitlements WHERE ps4_id=? AND item_id=? AND kind=?)",rusqlite::params![id,s(o,"item_id"),s(o,"kind")],|r|r.get(0))?,
        "housing"=>db.query_row("SELECT EXISTS(SELECT 1 FROM housing_entitlements WHERE ps4_id=? AND item_id=?)",rusqlite::params![id,s(o,"item_id")],|r|r.get(0))?,
        "bundle"=>{let c=children(db,s(o,"offer_id"))?;let mut all=!c.is_empty();for child in c{all &= owned(db,id,&child,stack)?;}all},
        _=>return Err(Error::new(500,"Invalid stored offer kind")),
    }
    };
    stack.remove(s(o, "offer_id"));
    Ok(result)
}
pub(super) fn grant_offer(
    state: &State,
    db: &Connection,
    id: &str,
    o: &Value,
    stack: &mut HashSet<String>,
) -> Result<()> {
    if !stack.insert(s(o, "offer_id").into()) {
        return Err(Error::new(409, "Shop bundle cycle"));
    }
    if s(o, "kind") == "bundle" {
        let c = children(db, s(o, "offer_id"))?;
        if c.is_empty() {
            return Err(Error::new(409, "Empty bundle cannot be granted"));
        }
        for child in c {
            grant_offer(state, db, id, &child, stack)?;
        }
    } else {
        grant(
            state,
            db,
            id,
            s(o, "kind"),
            s(o, "item_id"),
            o["gender"].as_str(),
            o["category"].as_str(),
            Some(s(o, "name")),
        )?;
    }
    stack.remove(s(o, "offer_id"));
    Ok(())
}
fn item(state: &State, o: &Value, profile: &Value) -> Result<String> {
    let table = match s(o, "kind") {
        "bundle" => "BUNDLES".to_string(),
        "wardrobe" => s(o, "category").into(),
        kind => s(&asset(state, kind, s(o, "item_id"), None, None)?, "table").into(),
    };
    let gender = if s(o, "kind") == "bundle" {
        "BundleMix"
    } else if s(o, "kind") == "wardrobe" {
        s(o, "gender")
    } else {
        s(profile, "gender")
    };
    let gender = if ["MALE", "FEMALE", "BundleMix"].contains(&gender) {
        gender
    } else {
        "MALE"
    };
    entry(&[
        s(o, "offer_id").into(),
        s(o, "name").into(),
        s(o, "image_path").into(),
        n(o, "crystals").to_string(),
        n(o, "np").to_string(),
        if s(o, "kind") == "bundle" {
            "True"
        } else {
            "False"
        }
        .into(),
        gender.into(),
        table,
    ])
}
fn list(f: &[String], entries: Vec<String>) -> String {
    reply(f, &[vec![entries.len().to_string()], entries].concat())
}
fn target(db: &Connection, sender: &Value, name: &str) -> Result<Value> {
    token(name, "gift target", 1024, false)?;
    let mut matches = Vec::new();
    for p in rows(
        db,
        "SELECT * FROM profiles WHERE username=? ORDER BY ps4_id",
        [name],
    )? {
        if relation(db, s(sender, "ps4_id"), name, s(&p, "platform"), "friend")? {
            matches.push(p);
        }
    }
    if matches.is_empty() {
        return Err(Error::new(403, "Gift target is not a local friend"));
    }
    if matches.len() != 1 {
        return Err(Error::new(
            409,
            "Gift target name is ambiguous across local platforms",
        ));
    }
    let t = matches.remove(0);
    if relation(
        db,
        s(sender, "ps4_id"),
        s(&t, "username"),
        s(&t, "platform"),
        "block",
    )? || relation(
        db,
        s(&t, "ps4_id"),
        s(sender, "username"),
        s(sender, "platform"),
        "block",
    )? {
        return Err(Error::new(403, "Gift is blocked by an account"));
    }
    Ok(t)
}
pub(super) fn handle(
    state: &State,
    db: &Connection,
    route: &str,
    req: &Request,
    actor: Option<&str>,
) -> Result<String> {
    let count = match route {
        "GetFeaturesServlet" | "GetShopInfoPlayerShop" => 2,
        "GetGenderDataShopServlet"
        | "NPShopBundleItemsServlet"
        | "NPShopIsItemPurchasedServlet" => 3,
        "GetShopTypeDataShopServlet" => 4,
        "NPShopBuyItemServlet" => 6,
        _ => 5,
    };
    let p = identity(state, db, req, count, Some(1), actor, false)?;
    let f = &req.fields;
    if platform(&req.platform)? != platform(s(&p, "platform"))? {
        return Err(Error::new(403, "Session platform mismatch"));
    }
    match route {
        "GetShopInfoPlayerShop" | "NPShopSyncCrystalsServlet" => {
            if route == "NPShopSyncCrystalsServlet" {
                token(&f[2], "crystal receipt ID", 1024, false)?;
                token(&f[3], "crystal receipt date", 1024, true)?;
                uint(&f[4], "consumed crystal count", i64::MAX)?;
            }
            let w =
                one(db, "SELECT * FROM shop_wallets WHERE ps4_id=?", [&f[1]])?.unwrap_or(json!({}));
            Ok(reply(
                f,
                &[
                    s(&p, "username").into(),
                    n(&w, "np").to_string(),
                    n(&w, "crystals").to_string(),
                ],
            ))
        }
        "GetGenderDataShopServlet" => {
            let r=rows(db,"SELECT DISTINCT gender_id FROM shop_offers o JOIN shop_catalogs s USING(shop_id) WHERE o.active=1 AND s.active=1 AND o.shop_id=? ORDER BY gender_id",[&f[2]])?;
            let mut out = vec![(r.len() * 2).to_string()];
            for v in r {
                out.extend([n(&v, "gender_id").to_string(), "True".into()]);
            }
            Ok(reply(f, &out))
        }
        "GetShopDataShopServlet" => {
            for v in [&f[2], &f[3]] {
                if !["true", "false", "True", "False"].contains(&v.as_str()) {
                    return Err(Error::bad("Invalid shop display flag"));
                }
            }
            let t = uint(&f[4], "shop type", i32::MAX.into())?;
            let mut entries = Vec::new();
            for v in rows(
                db,
                "SELECT * FROM shop_catalogs WHERE active=1 AND type_shop=? ORDER BY shop_id",
                [t],
            )? {
                entries.push(entry(&[
                    s(&v, "shop_id").into(),
                    s(&v, "name").into(),
                    s(&v, "description").into(),
                    s(&v, "url").into(),
                ])?);
            }
            Ok(list(f, entries))
        }
        "GetShopTypeDataShopServlet" => {
            let gender = uint(&f[3], "shop gender ID", i32::MAX.into())?;
            if gender <= 1 {
                let mut entries = Vec::new();
                for t in rows(db,"SELECT DISTINCT type_id FROM shop_offers o JOIN shop_catalogs s USING(shop_id) WHERE o.active=1 AND s.active=1 AND o.shop_id=? AND o.gender_id=? ORDER BY type_id",rusqlite::params![f[2],gender])?{entries.push(entry(&[f[2].clone(),s(&t,"type_id").into(),gender.to_string()])?);}
                return Ok(list(f, entries));
            }
            if gender == 4 {
                return Ok(list(f, vec![]));
            }
            if ![2, 3, 5, 6].contains(&gender) {
                return Err(Error::bad("Unsupported shop gender ID"));
            }
            let offers=rows(db,"SELECT o.* FROM shop_offers o JOIN shop_catalogs s USING(shop_id) WHERE o.active=1 AND s.active=1 AND o.shop_id=? AND o.gender_id=? ORDER BY o.offer_id",rusqlite::params![f[2],gender])?;
            Ok(list(
                f,
                offers
                    .iter()
                    .map(|o| item(state, o, &p))
                    .collect::<Result<_>>()?,
            ))
        }
        "GetFeaturesServlet" | "GetItemAssetsDataServlet" | "NPShopBundleItemsServlet" => {
            let offers = if route == "GetFeaturesServlet" {
                rows(
                    db,
                    "SELECT * FROM shop_offers WHERE active=1 AND featured=1 ORDER BY offer_id",
                    [],
                )?
            } else if route == "GetItemAssetsDataServlet" {
                let gender = uint(&f[3], "shop gender ID", i32::MAX.into())?;
                rows(db,"SELECT o.* FROM shop_offers o JOIN shop_catalogs s USING(shop_id) WHERE o.active=1 AND s.active=1 AND o.shop_id=? AND o.gender_id=? AND o.type_id=? ORDER BY o.offer_id",rusqlite::params![f[2],gender,f[4]])?
            } else {
                let parent = offer(db, &f[2], true)?;
                if s(&parent, "kind") != "bundle" {
                    return Err(Error::bad("Offer is not a bundle"));
                }
                children(db, &f[2])?
                    .into_iter()
                    .filter(|o| flag(o, "active"))
                    .collect()
            };
            Ok(list(
                f,
                offers
                    .iter()
                    .map(|o| item(state, o, &p))
                    .collect::<Result<_>>()?,
            ))
        }
        "NPShopIsItemPurchasedServlet" => Ok(reply(
            f,
            &[
                if owned(db, &f[1], &offer(db, &f[2], true)?, &mut HashSet::new())? {
                    "True"
                } else {
                    "False"
                }
                .into(),
            ],
        )),
        "NPShopBuyItemServlet" | "NPShopGiftItemServlet" => {
            let gift = route == "NPShopGiftItemServlet";
            let observed = if gift {
                token(&f[3], "gift target", 1024, false)?;
                (uint(&f[4], "displayed gift price", i32::MAX.into())?, 0, 0)
            } else {
                (
                    uint(&f[3], "displayed crystal price", i32::MAX.into())?,
                    uint(&f[4], "displayed NP price", i32::MAX.into())?,
                    uint(&f[5], "purchase option", i32::MAX.into())?,
                )
            };
            // Recipient authority is checked before resolving any offer, just
            // as in the recovered service (including error precedence).
            let gift_target = if gift {
                Some(target(db, &p, &f[3])?)
            } else {
                None
            };
            if !current(db, &f[1], &f[0])? {
                return Err(Error::new(
                    403,
                    if gift {
                        "Gift requires the current account session"
                    } else {
                        "Purchase requires the current account session"
                    },
                ));
            }
            let o = offer(db, &f[2], true)?;
            let (recipient, column, cost, failure) = if gift {
                let t = gift_target.unwrap();
                if observed.0 != n(&o, "crystals") {
                    return Err(Error::new(
                        409,
                        "Displayed gift price no longer matches the configured offer",
                    ));
                }
                (
                    s(&t, "ps4_id").to_string(),
                    "crystals",
                    n(&o, "crystals"),
                    "NOCRYSTALS",
                )
            } else {
                if (observed.0, observed.1) != (n(&o, "crystals"), n(&o, "np")) {
                    return Err(Error::new(
                        409,
                        "Displayed price no longer matches the configured offer",
                    ));
                }
                match observed.2 {
                    0 => (f[1].clone(), "crystals", n(&o, "crystals"), "NOCRYSTALS"),
                    1 => (f[1].clone(), "np", n(&o, "np"), "NOXP"),
                    _ => return Err(Error::bad("Unsupported local purchase option")),
                }
            };
            let response = |status: &str| {
                reply(
                    f,
                    &if gift {
                        vec![status.into(), f[3].clone(), f[2].clone()]
                    } else {
                        vec![status.into()]
                    },
                )
            };
            if owned(db, &recipient, &o, &mut HashSet::new())? {
                return Ok(response("ISPURCHASED"));
            }
            db.execute(
                "INSERT OR IGNORE INTO shop_wallets(ps4_id) VALUES(?)",
                [&f[1]],
            )?;
            let sql = format!(
                "UPDATE shop_wallets SET {column}={column}-? WHERE ps4_id=? AND {column}>=?"
            );
            if db.execute(&sql, rusqlite::params![cost, f[1], cost])? != 1 {
                return Ok(response(failure));
            }
            grant_offer(state, db, &recipient, &o, &mut HashSet::new())?;
            db.execute(
                "INSERT INTO shop_owned VALUES(?,?,?,?,?)",
                rusqlite::params![
                    recipient,
                    f[2],
                    if gift { "gift" } else { "buy" },
                    if gift { Some(f[1].as_str()) } else { None },
                    state.now()
                ],
            )?;
            if gift {
                ipc::enqueue(
                    state,
                    db,
                    &recipient,
                    &p,
                    3,
                    s(&o, "name"),
                    &format!("shop-gift:{}:{}:{}", f[1], recipient, f[2]),
                )?;
            }
            Ok(response("OK"))
        }
        _ => Err(Error::new(501, "Shop route is not reconstructed")),
    }
}
