//! Live authority comes from the same SQLite transaction domain as HTTP.
//! No packet, transport handshake, or cached JSON file can grant an identity.
use super::{Quaternion, Vector3};
use crate::{
    error::{Error, Result},
    state::State,
};
use rusqlite::{params, OptionalExtension};

#[derive(Clone, Debug)]
pub(super) struct Account {
    pub guid: String,
    pub id: String,
    pub username: String,
    pub platform: String,
    pub instance: String,
    pub selected_companion: String,
    pub selected_locomotion: String,
    pub companion_revision: i64,
    pub locomotion_revision: i64,
    pub wardrobe_active: bool,
    pub wardrobe_instance: String,
    pub wardrobe_updated: f64,
    pub position: Vector3,
    pub position_updated: f64,
    pub muted: bool,
}
impl Account {
    pub fn platform_number(&self) -> i32 {
        if self.platform == "PS4" {
            0
        } else {
            1
        }
    }
    pub fn wardrobe_lease(&self, instance: &str, now: f64) -> bool {
        self.wardrobe_active
            && self.wardrobe_instance == instance
            && now >= self.wardrobe_updated
            && now - self.wardrobe_updated <= 60.0
    }
}

pub(super) fn find(state: &State, guid: &str) -> Result<Account> {
    if guid.len() != 32
        || !guid
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(Error::bad("unknown_session"));
    }
    let db = state.connection()?;
    let now = state.now();
    let account = db.query_row(
        "SELECT s.guid,p.ps4_id,p.username,p.platform,COALESCE(a.instance_id,''), 
         COALESCE(c.item_id,''),COALESCE(l.item_id,''),COALESCE(c.revision,0),COALESCE(l.revision,0), 
         COALESCE(t.in_wardrobe,0),COALESCE(t.wardrobe_instance_id,''),COALESCE(t.wardrobe_updated_at,0), 
         COALESCE(q.x,0),COALESCE(q.y,0),COALESCE(q.z,0),COALESCE(q.updated_at,0), 
         COALESCE(m.mute_enabled,0),m.mute_expires_at,COALESCE(m.ban_enabled,0),m.ban_expires_at 
         FROM sessions s JOIN profiles p USING(ps4_id) LEFT JOIN allocations a USING(guid) 
         LEFT JOIN profile_state t USING(ps4_id) LEFT JOIN positions q USING(ps4_id) 
         LEFT JOIN moderation_accounts m USING(ps4_id) 
         LEFT JOIN resource_selections c ON c.ps4_id=p.ps4_id AND c.kind='companions' 
         LEFT JOIN resource_selections l ON l.ps4_id=p.ps4_id AND l.kind='locomotions' 
         WHERE s.guid=?1 AND NOT EXISTS(SELECT 1 FROM moderation_revoked_sessions r WHERE r.guid=s.guid) 
         AND NOT EXISTS(SELECT 1 FROM sessions n WHERE n.ps4_id=s.ps4_id AND 
         (n.created_at>s.created_at OR (n.created_at=s.created_at AND n.guid>s.guid)))",
        [guid], |r| {
            let muted: i64 = r.get(16)?;
            let mute_until: Option<i64> = r.get(17)?;
            let banned: i64 = r.get(18)?;
            let ban_until: Option<i64> = r.get(19)?;
            Ok((Account {
                guid:r.get(0)?, id:r.get(1)?, username:r.get(2)?, platform:r.get(3)?, instance:r.get(4)?,
                selected_companion:r.get(5)?, selected_locomotion:r.get(6)?,
                companion_revision:r.get(7)?, locomotion_revision:r.get(8)?,
                wardrobe_active:r.get::<_,i64>(9)? != 0, wardrobe_instance:r.get(10)?, wardrobe_updated:r.get(11)?,
                position:Vector3 {x:r.get(12)?, y:r.get(13)?, z:r.get(14)?}, position_updated:r.get(15)?,
                muted:muted != 0 && mute_until.map_or(true, |until| now < until as f64),
            }, banned != 0 && ban_until.map_or(true, |until| now < until as f64)))
        }).optional()?.ok_or_else(|| Error::bad("unknown_or_superseded_session"))?;
    if account.1 {
        return Err(Error::bad("account_banned"));
    }
    let maintenance: bool = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM moderation_maintenance WHERE started_at<=?1 AND end_at>?1)",
        [now],
        |r| r.get(0),
    )?;
    if maintenance {
        return Err(Error::bad("maintenance_active"));
    }
    let a = account.0;
    if !matches!(a.platform.as_str(), "PS4" | "StandaloneWindows")
        || a.id.is_empty()
        || a.id.len() > 128
        || a.username.len() > 128
        || a.id.contains('#')
        || a.username.contains(['#', '\0'])
        || !a.position.valid()
        || !a.position_updated.is_finite()
        || !a.wardrobe_updated.is_finite()
    {
        return Err(Error::bad("invalid_account_authority"));
    }
    for (kind, item) in [
        ("companions", a.selected_companion.as_str()),
        ("locomotions", a.selected_locomotion.as_str()),
    ] {
        if !item.is_empty() && !db.query_row("SELECT EXISTS(SELECT 1 FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?)",
            params![a.id,kind,item],|r|r.get::<_,bool>(0))? {
            return Err(Error::bad("invalid_resource_selection_authority"));
        }
    }
    Ok(a)
}

pub(super) fn all(state: &State) -> Result<Vec<Account>> {
    let guids: Vec<String> = {
        let db = state.connection()?;
        let mut s=db.prepare("SELECT s.guid FROM sessions s WHERE NOT EXISTS(SELECT 1 FROM sessions n WHERE n.ps4_id=s.ps4_id AND (n.created_at>s.created_at OR (n.created_at=s.created_at AND n.guid>s.guid))) ORDER BY s.guid")?;
        let v = s
            .query_map([], |r| r.get(0))?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        v
    };
    Ok(guids
        .into_iter()
        .filter_map(|g| find(state, &g).ok())
        .collect())
}

pub(super) fn select_resource(
    state: &State,
    a: &Account,
    kind: &str,
    item: &str,
    expected: i64,
) -> Result<i64> {
    if !matches!(kind, "companions" | "locomotions")
        || item.len() > 256
        || item.contains(['#', '\0'])
    {
        return Err(Error::bad("invalid_resource_selection"));
    }
    let path = state
        .state_dir
        .join("instances")
        .join(&a.instance)
        .join("instance-status.json");
    if std::fs::metadata(&path)?.len() > 65536 {
        return Err(Error::bad("resource_selection_instance_status_size"));
    }
    let status: serde_json::Value = serde_json::from_slice(&std::fs::read(path)?)?;
    let request = serde_json::json!({"format_version":1,"request_id":uuid::Uuid::new_v4().simple().to_string(),"guid":a.guid,
        "instance_id":a.instance,"instance_owner":status["owner"],"kind":kind,"item_id":item,"expected_revision":expected,
        "created_at":state.now(),"expires_at":state.now()+15.0});
    let result = crate::services::process_resource_selection(
        state,
        &request,
        &a.instance,
        Some(state.now()),
    )?;
    if result["status"] != "committed" {
        return Err(Error::bad(
            result["reason"]
                .as_str()
                .unwrap_or("resource_selection_not_committed"),
        ));
    }
    result["revision"]
        .as_i64()
        .ok_or_else(|| Error::bad("resource_selection_revision_missing"))
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub(super) struct Pose {
    pub ps4_id: String,
    pub position: Vector3,
    pub rotation: Quaternion,
    pub scale: Vector3,
    pub updated_at: f64,
}
