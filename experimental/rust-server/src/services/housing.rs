use super::*;
pub(super) const ROUTES: &[&str] = &[
    "GetPersonalSpacesServlet",
    "GetHousingTypeServlet",
    "HousingReadPresetServlet",
    "N2HousingReadPreset",
    "HousingSavePresetServletParts",
    "N2GetUserTypeSpace",
];
const TABLES: [&str; 11] = [
    "HOUSING_WALLHANGING",
    "HOUSING_CHAIR",
    "HOUSING_FOOTSTOOL",
    "HOUSING_TABLE",
    "HOUSING_FLOORING",
    "HOUSING_ORNAMENT",
    "HOUSING_LAMP",
    "HOUSING_LIGHT",
    "HOUSING_SOFA",
    "HOUSING_APPLIANCE",
    "HOUSING_STORAGE",
];
const GROUND: [&str; 5] = [
    "aidasset",
    "aidasset_tx",
    "aidasset_ty",
    "aidasset_tz",
    "aidasset_r",
];
const SHARED: [&str; 6] = [
    "psidglobal",
    "aidassetWall",
    "aidassetWallSlot",
    "aidassetCeiling",
    "aidassetCeilingSlot",
    "ground_count",
];
const FIELDS: [&str; 11] = [
    "psidglobal",
    "aidasset",
    "aidasset_tx",
    "aidasset_ty",
    "aidasset_tz",
    "aidasset_r",
    "aidassetWall",
    "aidassetWallSlot",
    "aidassetCeiling",
    "aidassetCeilingSlot",
    "atablename",
];
const SPACES: &[&str] = &[
    "Home",
    "Greenhouse",
    "Waterfall",
    "StarCrawlers",
    "BlueWaveHideout",
    "DressingRoom",
    "CutteridgeEstate",
    "TheMoonlightRoom",
    "LeChalet",
    "LakeApartment",
    "SereneGarden",
    "WoodlandClearing",
    "TheNebulian",
    "SorcerersEyrie",
    "ZeroDistrictDen",
    "CampSilverLake",
    "FlyingDevice",
    "Deadquarters",
    "HollyridgeEstate",
    "WinterSnowGlobe",
    "TokyoApartment",
    "NebuHouse",
    "WestValleyApartment",
    "WhisperingHillsMansion",
    "CliffApartment",
    "TheCrypt",
    "ForgottenStation",
    "GreekSummerHouse",
    "MountainHideout",
    "GingerbreadHouse",
    "WindMillFarmHouse",
];
pub(super) fn catalog(state: &State) -> Result<HashMap<String, Value>> {
    let audit = state.catalog("http-nonminigame-gap-audit.json")?;
    let placement = state.catalog("housing-placement-contracts.json")?;
    if placement["format_version"] != 1 || placement["max_placement_space"] != 200 {
        return Err(Error::new(501, "Unsupported housing placement evidence"));
    }
    let items = audit["housing_catalog"]
        .as_array()
        .ok_or_else(|| Error::new(500, "Missing housing catalog"))?;
    let mut out = HashMap::new();
    for row in items {
        let id = s(row, "item_id");
        let table = s(row, "table");
        let c = &placement["items"][id];
        let suffix = format!("ResourcesART/Housing/{table}/{id}/FBX/{id}.prefab");
        if row["grantable"] == true
            && TABLES.contains(&table)
            && s(row, "bundle") == format!("01/{}", id.to_lowercase())
            && [format!("Assets/{suffix}"), format!("Assets/ART/{suffix}")]
                .contains(&s(row, "asset_path").to_string())
            && c["table"] == row["table"]
            && c["bundle"] == row["bundle"]
            && c["manifest_sha256"] == row["manifest_sha256"]
            && ["ground", "floor", "wall", "ceiling"].contains(&s(c, "behaviour"))
            && (1..=200).contains(&n(c, "placement_cost"))
        {
            if out.contains_key(id) {
                return Err(Error::new(501, "Duplicate canonical housing ID"));
            }
            let mut v = row.clone();
            v["behaviour"] = c["behaviour"].clone();
            v["placement_cost"] = c["placement_cost"].clone();
            out.insert(id.into(), v);
        }
    }
    Ok(out)
}
pub(super) fn binding(db: &Connection, id: &str) -> Result<Option<Value>> {
    let b = one(db, "SELECT * FROM housing_spaces WHERE instance_id=?", [id])?;
    if let Some(ref b) = b {
        let key = s(b, "logical_space_key");
        let expected = if key == "SorcerersEyrie" {
            "SorcerersEyrie1"
        } else {
            key
        };
        if !SPACES.contains(&key) || s(b, "psidglobal") != expected {
            return Err(Error::new(
                409,
                "Stored housing binding is not a case-exact shipped scene",
            ));
        }
    }
    Ok(b)
}
fn allocated(
    state: &State,
    db: &Connection,
    guid: &str,
    scene: Option<&str>,
    write: bool,
) -> Result<Value> {
    let p = session(state, db, guid)?;
    if !current(db, s(&p, "ps4_id"), guid)? {
        return Err(Error::new(
            403,
            "Historical session cannot access this housing instance",
        ));
    }
    let a = one(
        db,
        "SELECT instance_id,psidglobal FROM allocations WHERE guid=?",
        [guid],
    )?
    .ok_or_else(|| {
        Error::new(
            403,
            "No personal-space allocation matches this housing request",
        )
    })?;
    let b = binding(db, s(&a, "instance_id"))?.ok_or_else(|| {
        Error::new(
            403,
            "No personal-space allocation matches this housing request",
        )
    })?;
    if a["psidglobal"] != b["psidglobal"] || scene.is_some_and(|v| v != s(&b, "psidglobal")) {
        return Err(Error::new(
            403,
            "No personal-space allocation matches this housing request",
        ));
    }
    if write && s(&b, "owner_ps4_id") != s(&p, "ps4_id") {
        return Err(Error::new(
            403,
            "Only the current owning account may save this housing layout",
        ));
    }
    Ok(b)
}
fn empty(scene: &str) -> Value {
    let mut v = serde_json::Map::new();
    for k in FIELDS {
        v.insert(
            k.into(),
            if k == "psidglobal" {
                json!(scene)
            } else {
                json!([])
            },
        );
    }
    Value::Object(v)
}
fn layout_json(v: &Value) -> String {
    format!(
        "{{{}}}",
        FIELDS
            .iter()
            .map(|k| format!("\"{k}\":{}", js(&v[*k])))
            .collect::<Vec<_>>()
            .join(",")
    )
}
fn arr<'a>(v: &'a Value, key: &str) -> Result<&'a Vec<Value>> {
    v[key]
        .as_array()
        .ok_or_else(|| Error::bad("Malformed housing array"))
}
fn validate(state: &State, b: &Value, v: &Value) -> Result<()> {
    let cat = catalog(state)?;
    let ground: Vec<&Value> = arr(v, "aidasset")?
        .iter()
        .filter(|v| v.as_str() != Some("null"))
        .collect();
    let wall = arr(v, "aidassetWall")?;
    let ceiling = arr(v, "aidassetCeiling")?;
    let mut cost = 0;
    for (items, kinds) in [
        (ground.as_slice(), &["ground", "floor"][..]),
        (wall.iter().collect::<Vec<_>>().as_slice(), &["wall"][..]),
        (
            ceiling.iter().collect::<Vec<_>>().as_slice(),
            &["ceiling"][..],
        ),
    ] {
        for id in items {
            let item = id
                .as_str()
                .and_then(|id| cat.get(id))
                .ok_or_else(|| Error::bad("Housing layout contains an unknown catalog item"))?;
            if !kinds.contains(&s(item, "behaviour")) {
                return Err(Error::bad(
                    "Housing item is stored in the wrong native placement class",
                ));
            }
            cost += n(item, "placement_cost");
        }
    }
    if cost > 200 {
        return Err(Error::bad(
            "Housing layout exceeds recovered 200-space client budget",
        ));
    }
    let p = state.catalog("housing-placement-contracts.json")?;
    let slots = &p["personal_spaces"][s(b, "logical_space_key")];
    if !slots.is_object() {
        return Err(Error::new(
            501,
            "Personal-space placement metadata is incomplete",
        ));
    }
    for (key, count_key) in [
        ("aidassetWallSlot", "wall_slots"),
        ("aidassetCeilingSlot", "ceiling_slots"),
    ] {
        let max = slots[count_key]
            .as_i64()
            .ok_or_else(|| Error::new(501, "Personal-space placement metadata is incomplete"))?;
        if arr(v, key)?
            .iter()
            .any(|v| v.as_i64().is_none_or(|n| n < 0 || n >= max))
        {
            return Err(Error::bad("Housing layout exceeds shipped slot bounds"));
        }
    }
    Ok(())
}
fn decode(text: &str) -> Result<Value> {
    let raw: Vec<u16> = text.encode_utf16().collect();
    let mut pos = 0;
    let mut take = || -> Result<String> {
        if pos >= raw.len() {
            return Err(Error::bad("Missing housing EntryData length"));
        }
        let len = raw[pos]
            .checked_sub(0x24)
            .ok_or_else(|| Error::bad("Malformed housing EntryData length"))?
            as usize;
        pos += 1;
        if pos + len > raw.len() {
            return Err(Error::bad("Truncated housing EntryData"));
        }
        let s = String::from_utf16(&raw[pos..pos + len])
            .map_err(|_| Error::bad("Invalid housing EntryData UTF16"))?;
        pos += len;
        Ok(s)
    };
    let mut v = serde_json::Map::new();
    for (i, key) in FIELDS.iter().enumerate() {
        let token = take()?;
        if token == "nulls" {
            v.insert((*key).into(), Value::Null);
            continue;
        }
        if i == 0 {
            v.insert((*key).into(), json!(token));
            continue;
        }
        let len = token
            .parse::<usize>()
            .ok()
            .filter(|n| *n <= 200)
            .ok_or_else(|| Error::bad("Housing array length outside configured bound"))?;
        let mut values = Vec::new();
        for _ in 0..len {
            let t = take()?;
            let val = if t == "nulls" {
                Value::Null
            } else if [1, 6, 8, 10].contains(&i) {
                json!(t)
            } else if [7, 9].contains(&i) {
                json!(t
                    .parse::<i32>()
                    .map_err(|_| Error::bad("Invalid housing slot"))?)
            } else {
                let number = t
                    .parse::<f32>()
                    .ok()
                    .filter(|n| n.is_finite())
                    .ok_or_else(|| Error::bad("Invalid housing transform"))?;
                json!(number)
            };
            values.push(val);
        }
        v.insert((*key).into(), json!(values));
    }
    if pos != raw.len() {
        return Err(Error::bad(
            "Trailing data after final housing EntryData field",
        ));
    }
    Ok(Value::Object(v))
}
fn owned(db: &Connection, id: &str) -> Result<HashSet<String>> {
    Ok(rows(
        db,
        "SELECT item_id FROM housing_entitlements WHERE ps4_id=?",
        [id],
    )?
    .iter()
    .map(|r| s(r, "item_id").into())
    .collect())
}
pub(super) fn is_durable_rejection(err: &Error) -> bool {
    err.message == "Housing save is waiting for its original counterpart"
        || err.message.starts_with("Housing save quarantine:")
}
fn quarantine(db: &Connection, instance: &str, message: &str) -> Result<String> {
    db.execute(
        "UPDATE housing_save_stages SET state='blocked' WHERE instance_id=?",
        [instance],
    )?;
    Err(Error::new(
        409,
        format!("Housing save quarantine: {message}"),
    ))
}
fn save(state: &State, db: &Connection, guid: &str, text: &str, part: &str) -> Result<()> {
    if !["0", "1"].contains(&part) {
        return Err(Error::bad("Invalid native housing part number"));
    }
    let v = decode(text)?;
    let b = allocated(state, db, guid, Some(s(&v, "psidglobal")), true)?;
    let ids = arr(&v, "aidasset")?;
    if GROUND
        .iter()
        .any(|k| v[*k].as_array().is_none_or(|a| a.len() != ids.len()))
    {
        return Err(Error::bad("Housing floor arrays have inconsistent lengths"));
    }
    for (items, slots) in [
        ("aidassetWall", "aidassetWallSlot"),
        ("aidassetCeiling", "aidassetCeilingSlot"),
    ] {
        let a = arr(&v, items)?;
        let slots = arr(&v, slots)?;
        let mut seen = HashSet::new();
        if a.len() != slots.len()
            || slots
                .iter()
                .any(|v| v.as_i64().is_none_or(|i| i < 0 || !seen.insert(i)))
            || a.iter().any(|v| v.as_str() == Some("null"))
        {
            return Err(Error::bad("Invalid housing slot arrays"));
        }
    }
    let owned = owned(db, s(&b, "owner_ps4_id"))?;
    for key in ["aidasset", "aidassetWall", "aidassetCeiling"] {
        for id in arr(&v, key)? {
            if id
                .as_str()
                .is_none_or(|i| i != "null" && !owned.contains(i))
            {
                return Err(Error::new(403, "Housing layout contains an ungranted item"));
            }
        }
    }
    let (start, stop) = if part == "0" {
        (0, ids.len().min(100))
    } else {
        (100, ids.len())
    };
    for (i, id) in ids.iter().enumerate() {
        if GROUND[1..]
            .iter()
            .any(|k| v[*k][i].as_f64().is_none_or(|n| !n.is_finite()))
        {
            return Err(Error::bad("Invalid housing transform"));
        }
        if !(start..stop).contains(&i)
            && (id.as_str() != Some("null")
                || GROUND[1..].iter().any(|k| v[*k][i].as_f64() != Some(0.)))
        {
            return Err(Error::bad(
                "Housing counterpart fields differ from native sparse padding",
            ));
        }
    }
    if !v["atablename"].is_null() {
        return Err(Error::bad("Native housing save leaves atablename null"));
    }
    let instance = s(&b, "instance_id");
    let now = state.now();
    let payload = layout_json(&v);
    let common = format!(
        "{{{}}}",
        SHARED
            .iter()
            .map(|key| format!(
                "\"{key}\":{}",
                if *key == "ground_count" {
                    ids.len().to_string()
                } else {
                    js(&v[*key])
                }
            ))
            .collect::<Vec<_>>()
            .join(",")
    );
    let mut old = one(
        db,
        "SELECT * FROM housing_save_stages WHERE instance_id=?",
        [instance],
    )?;
    if old.as_ref().is_some_and(|o| s(o, "guid") != guid) {
        db.execute(
            "DELETE FROM housing_save_stages WHERE instance_id=?",
            [instance],
        )?;
        old = None;
    }
    if let Some(ref o) = old {
        if s(o, "state") == "blocked" || now >= o["deadline"].as_f64().unwrap_or(0.) {
            return quarantine(
                db,
                instance,
                "ambiguous or expired save requires a fresh owner login",
            )
            .map(|_| ());
        }
    }
    if old.is_none() {
        if let Some(receipt)=one(db,"SELECT * FROM housing_save_receipts WHERE instance_id=? AND guid=? ORDER BY committed_at DESC,batch_id DESC LIMIT 1",rusqlite::params![instance,guid])?{
            if now<receipt["committed_at"].as_f64().unwrap_or(0.)+0.75 {if s(&receipt,&format!("part{part}_sha256"))==hash(&payload){return Ok(());}return Err(Error::new(409,"Previous housing save is still acknowledging; retry after its success popup"));}
        }
        db.execute(
            "INSERT INTO housing_save_stages VALUES(?,?,?,?,?,NULL,NULL,'open',?,?)",
            rusqlite::params![
                instance,
                guid,
                s(&b, "owner_ps4_id"),
                uuid(),
                common,
                now,
                now + 30.
            ],
        )?;
        old = one(
            db,
            "SELECT * FROM housing_save_stages WHERE instance_id=?",
            [instance],
        )?;
    }
    let o = old.unwrap();
    let column = if part == "0" {
        "part0_json"
    } else {
        "part1_json"
    };
    if s(&o, "shared_json") != common || (o[column].is_string() && s(&o, column) != payload) {
        return quarantine(
            db,
            instance,
            "conflicting original housing parts; fresh owner login required",
        )
        .map(|_| ());
    }
    db.execute(
        &format!("UPDATE housing_save_stages SET {column}=? WHERE instance_id=?"),
        rusqlite::params![payload, instance],
    )?;
    let row = one(
        db,
        "SELECT * FROM housing_save_stages WHERE instance_id=?",
        [instance],
    )?
    .unwrap();
    if row["part0_json"].is_string() && row["part1_json"].is_string() {
        let first: Value = serde_json::from_str(s(&row, "part0_json"))?;
        let second: Value = serde_json::from_str(s(&row, "part1_json"))?;
        let mut layout = empty(s(&b, "psidglobal"));
        for k in GROUND {
            let a = arr(&first, k)?;
            let b = arr(&second, k)?;
            layout[k] = json!([
                a[..a.len().min(100)].to_vec(),
                b[b.len().min(100)..].to_vec()
            ]
            .concat());
        }
        for k in &SHARED[..5] {
            layout[*k] = first[*k].clone();
        }
        validate(state, &b, &layout)?;
        db.execute("INSERT INTO housing_layouts VALUES(?,?,?) ON CONFLICT(instance_id) DO UPDATE SET layout_json=excluded.layout_json,updated_at=excluded.updated_at",rusqlite::params![instance,layout_json(&layout),now])?;
        db.execute(
            "INSERT INTO housing_save_receipts VALUES(?,?,?,?,?,?)",
            rusqlite::params![
                s(&row, "batch_id"),
                instance,
                guid,
                hash(s(&row, "part0_json")),
                hash(s(&row, "part1_json")),
                now
            ],
        )?;
        db.execute(
            "DELETE FROM housing_save_stages WHERE instance_id=?",
            [instance],
        )?;
        db.execute("DELETE FROM housing_save_receipts WHERE instance_id=? AND (committed_at<? OR batch_id NOT IN (SELECT batch_id FROM housing_save_receipts WHERE instance_id=? ORDER BY committed_at DESC,batch_id DESC LIMIT 16))",rusqlite::params![instance,now-300.,instance])?;
    } else if part == "1" {
        return Err(Error::new(
            503,
            "Housing save is waiting for its original counterpart",
        ));
    }
    Ok(())
}
pub(super) fn handle(
    state: &State,
    db: &Connection,
    route: &str,
    req: &Request,
    actor: Option<&str>,
) -> Result<String> {
    let count = if route == "GetPersonalSpacesServlet" {
        2
    } else if ["HousingSavePresetServletParts", "N2GetUserTypeSpace"].contains(&route) {
        4
    } else {
        3
    };
    let p = identity(
        state,
        db,
        req,
        count,
        Some(1),
        actor,
        route == "HousingSavePresetServletParts",
    )?;
    let f = &req.fields;
    match route {
        "GetPersonalSpacesServlet" => {
            let r=rows(db,"SELECT logical_space_key FROM housing_spaces WHERE owner_ps4_id=? ORDER BY logical_space_key",[s(&p,"ps4_id")])?;
            Ok(reply(
                f,
                &[r.iter()
                    .map(|r| s(r, "logical_space_key"))
                    .collect::<Vec<_>>()
                    .join("!")],
            ))
        }
        "GetHousingTypeServlet" => {
            let t = canonical_uint(&f[2], "housing category selector", 10)? as usize;
            let cat = catalog(state)?;
            let mut out = vec![f[2].clone()];
            for row in rows(
                db,
                "SELECT * FROM housing_entitlements WHERE ps4_id=? ORDER BY item_id",
                [&f[1]],
            )? {
                if let Some(item) = cat.get(s(&row, "item_id")) {
                    if s(item, "table") == TABLES[t] {
                        out.extend([
                            s(&row, "item_id").into(),
                            TABLES[t].into(),
                            s(&row, "display_name").into(),
                        ]);
                    }
                }
            }
            Ok(reply(f, &out))
        }
        "HousingReadPresetServlet" | "N2HousingReadPreset" => {
            let b = allocated(state, db, &f[0], Some(&f[2]), false)?;
            let owner=one(db,"SELECT guid FROM sessions WHERE ps4_id=? ORDER BY created_at DESC,guid DESC LIMIT 1",[s(&b,"owner_ps4_id")])?.ok_or_else(||Error::new(503,"Personal-space owner is no longer present in this instance"))?;
            let owner_guid = s(&owner, "guid");
            if s(&p, "ps4_id") != s(&b, "owner_ps4_id") {
                let pres = presence(state, db);
                let matching:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM allocations WHERE guid=? AND instance_id=? AND psidglobal=?)",rusqlite::params![owner_guid,s(&b,"instance_id"),s(&b,"psidglobal")],|r|r.get(0))?;
                if !matching || !pres.contains_key(owner_guid) {
                    return Err(Error::new(
                        503,
                        "Personal-space owner is no longer present in this instance",
                    ));
                }
            }
            let row = one(
                db,
                "SELECT layout_json FROM housing_layouts WHERE instance_id=?",
                [s(&b, "instance_id")],
            )?;
            let mut v = if let Some(r) = row {
                serde_json::from_str(s(&r, "layout_json"))?
            } else {
                empty(s(&b, "psidglobal"))
            };
            let keep: Vec<usize> = arr(&v, "aidasset")?
                .iter()
                .enumerate()
                .filter(|(_, v)| v.as_str() != Some("null"))
                .map(|(i, _)| i)
                .collect();
            for k in GROUND {
                let a = arr(&v, k)?;
                v[k] = json!(keep.iter().map(|i| a[*i].clone()).collect::<Vec<_>>());
            }
            let cat = catalog(state)?;
            let mut tables = Vec::new();
            for k in ["aidasset", "aidassetCeiling", "aidassetWall"] {
                for id in arr(&v, k)? {
                    let t = id.as_str().and_then(|id| cat.get(id)).ok_or_else(|| {
                        Error::new(409, "Stored housing item no longer has catalog evidence")
                    })?;
                    tables.push(s(t, "table").to_string());
                }
            }
            v["atablename"] = json!(tables);
            Ok(reply(f, &[layout_json(&v), owner_guid.into()]))
        }
        "HousingSavePresetServletParts" => {
            save(state, db, &f[0], &f[2], &f[3])?;
            Ok(reply(f, &["true".into()]))
        }
        "N2GetUserTypeSpace" => {
            if !["0", "1"].contains(&f[3].as_str()) {
                return Err(Error::bad("Unsupported personal-space platform"));
            }
            let mut available = false;
            if let Some(t) = find_user(db, &f[2], &f[3])? {
                let pres = presence(state, db);
                for a in rows(
                    db,
                    "SELECT a.* FROM allocations a JOIN sessions s USING(guid) WHERE s.ps4_id=?",
                    [s(&t, "ps4_id")],
                )? {
                    if pres.contains_key(s(&a, "guid"))
                        && ready(state, s(&a, "instance_id"), s(&a, "psidglobal"))
                        && binding(db, s(&a, "instance_id"))?
                            .is_some_and(|b| s(&b, "owner_ps4_id") == s(&t, "ps4_id"))
                    {
                        available = true;
                    }
                }
            }
            Ok(format!("OK##{available}"))
        }
        _ => Err(Error::new(501, "Housing route not reconstructed")),
    }
}
