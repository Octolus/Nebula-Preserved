use nebula_preserved_server::{services, state::State, wire::Request};
use rusqlite::params;
use serde_json::{json, Value};
use std::{fs, path::PathBuf};

const GA: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const GB: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const OWNER: &str = "11111111111111111111111111111111";
struct Fixture {
    root: PathBuf,
    state: State,
}
impl Fixture {
    fn new() -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("target/services-tests")
            .join(uuid::Uuid::new_v4().simple().to_string());
        let protocol = root.join("protocol");
        fs::create_dir_all(&protocol).unwrap();
        let write =
            |name: &str, value: Value| fs::write(protocol.join(name), value.to_string()).unwrap();
        write(
            "avatar-asset-catalog.json",
            json!({"items":[{"item_id":"hat","gender":"MALE","category":"HATS","bundle":"00/hat"}]}),
        );
        write(
            "resource-entitlements.json",
            json!({"format_version":1,"items":[{"kind":"companions","item_id":"PetA","grantable":true,"conflicts":[],"table":"COMPANIONS","bundle":"02/peta","requested_resource_path":"Wardrobe_EAB/COMPANIONS/PetA/PetA","asset_path":"Assets/ResourcesART/Wardrobe_EAB/COMPANIONS/PetA/PetA.prefab"}]}),
        );
        write(
            "http-nonminigame-gap-audit.json",
            json!({"housing_catalog":[{"item_id":"chair","table":"HOUSING_CHAIR","bundle":"01/chair","asset_path":"Assets/ResourcesART/Housing/HOUSING_CHAIR/chair/FBX/chair.prefab","grantable":true,"manifest_sha256":"proof"}],"personal_space_navigator_names":["Home"]}),
        );
        write(
            "housing-placement-contracts.json",
            json!({"format_version":1,"max_placement_space":200,"items":{"chair":{"table":"HOUSING_CHAIR","bundle":"01/chair","manifest_sha256":"proof","behaviour":"ground","placement_cost":1}},"personal_spaces":{"Home":{"wall_slots":2,"ceiling_slots":2}}}),
        );
        write(
            "skl-promo-catalog.json",
            json!({"records":[{"promo_id":1,"valid_sprite_pair_indices":[0]}],"promo_ids":[1]}),
        );
        let mut state = State::open(&root.join("state"), &protocol).unwrap();
        state.fixed_time = Some(1000.);
        {
            let db = state.connection().unwrap();
            for (id, name, guid) in [("a", "Alice", GA), ("b", "Bob", GB)] {
                db.execute(
                    "INSERT INTO profiles VALUES(?,?,?,'MALE',100)",
                    params![id, name, "StandaloneWindows"],
                )
                .unwrap();
                db.execute("INSERT INTO sessions VALUES(?,?,100)", params![guid, id])
                    .unwrap();
                db.execute("INSERT INTO profile_state(ps4_id) VALUES(?)", [id])
                    .unwrap();
            }
            db.execute("INSERT INTO shop_catalogs VALUES('s',0,'Test','','',1)", [])
                .unwrap();
            db.execute("INSERT INTO shop_wallets VALUES('a',100,50,0)", [])
                .unwrap();
        }
        Self { root, state }
    }
    fn call(
        &self,
        route: &str,
        fields: &[&str],
    ) -> Result<String, nebula_preserved_server::error::Error> {
        services::handle(
            &self.state,
            route,
            &Request {
                fields: fields.iter().map(|s| s.to_string()).collect(),
                platform: "StandaloneWindows".into(),
            },
        )
        .map(|o| o.unwrap())
    }
    fn offer(&self, offer: &str, kind: &str, item: Option<&str>, crystals: i64) {
        self.state.connection().unwrap().execute("INSERT INTO shop_offers VALUES(?,?,?,?,?,'s','type',0,?,'MALE/HATS/hat/hatThumbnail.png',?,7,1,1,100)",params![offer,kind,item,if kind=="wardrobe"{Some("MALE")}else{None},if kind=="wardrobe"{Some("HATS")}else{None},offer,crystals]).unwrap();
    }
    fn reopen(&mut self) {
        let mut state = State::open(&self.root.join("state"), &self.root.join("protocol")).unwrap();
        state.fixed_time = Some(1000.);
        self.state = state;
    }
    fn count(&self, table: &str) -> i64 {
        self.state
            .connection()
            .unwrap()
            .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0))
            .unwrap()
    }
    fn balance(&self) -> i64 {
        self.state
            .connection()
            .unwrap()
            .query_row(
                "SELECT crystals FROM shop_wallets WHERE ps4_id='a'",
                [],
                |r| r.get(0),
            )
            .unwrap()
    }
    fn home(&self) {
        let db = self.state.connection().unwrap();
        db.execute(
            "INSERT INTO housing_spaces VALUES('apt','Home','Home','a',100)",
            [],
        )
        .unwrap();
        db.execute(
            "INSERT INTO allocations VALUES(?,'apt','Home','127.0.0.1',7777,100)",
            [GA],
        )
        .unwrap();
        db.execute(
            "INSERT INTO housing_entitlements VALUES('a','chair','Chair',100)",
            [],
        )
        .unwrap();
    }
    fn lease(&self) {
        let p = self.state.state_dir.join("instances/apt");
        fs::create_dir_all(&p).unwrap();
        fs::write(p.join("instance-status.json"),json!({"instance_id":"apt","psidglobal":"Home","owner":OWNER,"listening":true,"listener_bound":true,"heartbeat":1000.}).to_string()).unwrap();
    }
}
impl Drop for Fixture {
    fn drop(&mut self) { /* Keep failed-test evidence within the approved workspace. */
    }
}

#[test]
fn shop_debit_grant_idempotency_and_reopen() {
    let mut f = Fixture::new();
    f.offer("hat-offer", "wardrobe", Some("hat"), 20);
    assert!(f
        .call(
            "NPShopBuyItemServlet",
            &[GA, "a", "hat-offer", "19", "7", "0"]
        )
        .is_err());
    assert_eq!(f.balance(), 100);
    assert!(f
        .call(
            "NPShopBuyItemServlet",
            &[GA, "a", "hat-offer", "20", "7", "0"]
        )
        .unwrap()
        .ends_with("#OK"));
    assert_eq!(f.balance(), 80);
    assert_eq!(f.count("entitlements"), 1);
    f.reopen();
    assert!(f
        .call(
            "NPShopBuyItemServlet",
            &[GA, "a", "hat-offer", "20", "7", "0"]
        )
        .unwrap()
        .ends_with("#ISPURCHASED"));
    assert_eq!(f.balance(), 80);
    let req = Request {
        fields: vec![
            GA.into(),
            "a".into(),
            "hat-offer".into(),
            "20".into(),
            "7".into(),
            "0".into(),
        ],
        platform: "StandaloneWindows".into(),
    };
    assert_eq!(
        services::handle_as(&f.state, "NPShopBuyItemServlet", &req, Some("b"))
            .unwrap_err()
            .status,
        403
    );
}
#[test]
fn bundle_failure_rolls_back_wallet_and_prior_grants() {
    let f = Fixture::new();
    f.offer("bundle", "bundle", None, 30);
    f.offer("good", "wardrobe", Some("hat"), 0);
    f.offer("bad", "wardrobe", Some("missing"), 0);
    {
        let db = f.state.connection().unwrap();
        db.execute(
            "INSERT INTO shop_bundle_items VALUES('bundle','good',0)",
            [],
        )
        .unwrap();
        db.execute("INSERT INTO shop_bundle_items VALUES('bundle','bad',1)", [])
            .unwrap();
    }
    assert_eq!(
        f.call("NPShopBuyItemServlet", &[GA, "a", "bundle", "30", "7", "0"])
            .unwrap_err()
            .status,
        404
    );
    assert_eq!(f.balance(), 100);
    assert_eq!(f.count("entitlements"), 0);
    assert_eq!(f.count("shop_owned"), 0);
}
#[test]
fn gift_requires_friendship_and_commits_one_notice() {
    let f = Fixture::new();
    f.offer("gift", "wardrobe", Some("hat"), 20);
    assert_eq!(
        f.call("NPShopGiftItemServlet", &[GA, "a", "gift", "Bob", "20"])
            .unwrap_err()
            .status,
        403
    );
    f.state
        .connection()
        .unwrap()
        .execute(
            "INSERT INTO relations VALUES('a','Bob','StandaloneWindows','friend')",
            [],
        )
        .unwrap();
    assert!(f
        .call("NPShopGiftItemServlet", &[GA, "a", "gift", "Bob", "20"])
        .unwrap()
        .contains("#OK#Bob#gift"));
    assert_eq!(f.balance(), 80);
    assert_eq!(f.count("notification_outbox"), 1);
    assert!(f
        .call("NPShopGiftItemServlet", &[GA, "a", "gift", "Bob", "20"])
        .unwrap()
        .contains("#ISPURCHASED#"));
    assert_eq!(f.balance(), 80);
    assert_eq!(f.count("notification_outbox"), 1);
}
#[test]
fn rewards_are_atomic_idempotent_and_consumable_receipts_are_durable() {
    let mut f = Fixture::new();
    {
        f.state.connection().unwrap().execute("INSERT INTO local_reward_definitions VALUES('GenericReward','coffee-trigger',1,'coffee','coffee',NULL,NULL,NULL,NULL,2,4,100)",[]).unwrap();
    }
    assert!(f
        .call("GenericReward", &[GA, "a", "coffee-trigger"])
        .unwrap()
        .ends_with("#true"));
    assert!(f
        .call("GenericReward", &[GA, "a", "coffee-trigger"])
        .unwrap()
        .ends_with("#false"));
    assert_eq!(f.count("local_reward_claims"), 1);
    assert_eq!(f.count("notification_outbox"), 1);
    let r = f
        .call("GetConsumableServlet", &[GA, "a", "coffee", "0"])
        .unwrap();
    let id = r.split('#').nth(6).unwrap();
    let path = f
        .state
        .state_dir
        .join("consumable-receipts")
        .join(format!("{id}.json"));
    let receipt: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    assert_eq!(receipt["use_count"], 4);
    f.reopen();
    assert!(f
        .call("GetConsumablePriceServlet", &[GA, "a", "coffee", "0"])
        .unwrap()
        .ends_with("#1#false"));
    let status: String = f
        .state
        .connection()
        .unwrap()
        .query_row(
            "SELECT status FROM consumable_receipts WHERE receipt_id=?",
            [id],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(status, "pending");
}
#[test]
fn consumable_publication_failure_refunds_reservation() {
    let f = Fixture::new();
    f.state
        .connection()
        .unwrap()
        .execute(
            "INSERT INTO consumable_balances VALUES('a','coffee',1,2,'1','token',0,0,100)",
            [],
        )
        .unwrap();
    fs::write(
        f.state.state_dir.join("consumable-receipts"),
        "blocking-file",
    )
    .unwrap();
    assert!(f
        .call("GetConsumableServlet", &[GA, "a", "coffee", "0"])
        .is_err());
    let db = f.state.connection().unwrap();
    let units: i64 = db
        .query_row("SELECT units FROM consumable_balances", [], |r| r.get(0))
        .unwrap();
    let status: String = db
        .query_row("SELECT status FROM consumable_receipts", [], |r| r.get(0))
        .unwrap();
    assert_eq!(units, 1);
    assert_eq!(status, "cancelled");
}
fn e(tokens: &[&str]) -> String {
    tokens
        .iter()
        .map(|v| {
            format!(
                "{}{}",
                char::from_u32((v.encode_utf16().count() + 0x24) as u32).unwrap(),
                v
            )
        })
        .collect()
}
fn part(id: &str) -> String {
    e(&[
        "Home", "1", id, "1", "0", "1", "0", "1", "0", "1", "0", "0", "0", "0", "0", "nulls",
    ])
}
#[test]
fn housing_part1_waits_across_reopen_and_commits_whole_layout_once() {
    let mut f = Fixture::new();
    f.home();
    let part0 = part("chair");
    let part1 = part("null");
    assert_eq!(
        f.call("HousingSavePresetServletParts", &[GA, "a", &part1, "1"])
            .unwrap_err()
            .status,
        503
    );
    assert_eq!(f.count("housing_layouts"), 0);
    f.reopen();
    assert!(f
        .call("HousingSavePresetServletParts", &[GA, "a", &part0, "0"])
        .unwrap()
        .ends_with("#true"));
    assert_eq!(f.count("housing_layouts"), 1);
    assert_eq!(f.count("housing_save_stages"), 0);
    assert!(f
        .call("HousingSavePresetServletParts", &[GA, "a", &part1, "1"])
        .is_ok());
    let r = f
        .call("HousingReadPresetServlet", &[GA, "a", "Home"])
        .unwrap();
    assert!(r
        .split('#')
        .nth(3)
        .unwrap()
        .starts_with("{\"psidglobal\":\"Home\",\"aidasset\":[\"chair\"],\"aidasset_tx\":[0.0]"));
    let layout: Value = serde_json::from_str(r.split('#').nth(3).unwrap()).unwrap();
    assert_eq!(layout["aidasset"], json!(["chair"]));
    assert_eq!(layout["atablename"], json!(["HOUSING_CHAIR"]));
}
#[test]
fn resource_selection_cas_replay_and_revocation_survive_reopen() {
    let mut f = Fixture::new();
    f.home();
    f.lease();
    f.state.connection().unwrap().execute("INSERT INTO resource_entitlements VALUES('a','companions','PetA','02/peta','p','Pet',100)",[]).unwrap();
    let v = json!({"format_version":1,"request_id":"22222222222222222222222222222222","guid":GA,"instance_id":"apt","instance_owner":OWNER,"kind":"companions","item_id":"PetA","expected_revision":0,"created_at":999.,"expires_at":1010.});
    let r = services::process_resource_selection(&f.state, &v, "apt", None).unwrap();
    assert_eq!(r["status"], "committed");
    assert_eq!(r["revision"], 1);
    f.reopen();
    assert_eq!(
        services::process_resource_selection(&f.state, &v, "apt", None).unwrap(),
        r
    );
    let mut different = v.clone();
    different["item_id"] = json!("");
    assert_eq!(
        services::process_resource_selection(&f.state, &different, "apt", None)
            .unwrap_err()
            .status,
        409
    );
    f.state
        .connection()
        .unwrap()
        .execute("DELETE FROM resource_entitlements WHERE ps4_id='a'", [])
        .unwrap();
    services::pump(&f.state).unwrap();
    let snap = services::resource_selection_snapshot(&f.state, "a").unwrap();
    assert_eq!(snap["selected_companion"], "");
    assert_eq!(snap["companion_revision"], 2);
    services::pump(&f.state).unwrap();
    assert_eq!(
        services::resource_selection_snapshot(&f.state, "a").unwrap()["companion_revision"],
        2
    );
}
#[test]
fn report_duplicate_keeps_original_text_and_identity_after_reopen() {
    let mut f = Fixture::new();
    assert!(f
        .call("ReportServlet", &[GA, "a", "1", "Bob", "first"])
        .unwrap()
        .ends_with("#true"));
    assert!(f
        .call("ReportServlet", &[GA, "a", "1", "Bob", "rewritten"])
        .unwrap()
        .ends_with("#false"));
    f.reopen();
    assert_eq!(f.count("moderation_report_index"), 1);
    let text: String = f
        .state
        .connection()
        .unwrap()
        .query_row("SELECT text FROM local_reports", [], |r| r.get(0))
        .unwrap();
    assert_eq!(text, "first");
}
#[test]
fn gathering_count_authority_and_reward_claim_are_durable() {
    let mut f = Fixture::new();
    {
        let db = f.state.connection().unwrap();
        db.execute("INSERT INTO gathering_events VALUES(1,'Christmas',1,1,0,0,?,100)",[json!({"kind":"wardrobe","item_id":"hat","gender":"MALE","category":"HATS","name":"Hat"}).to_string()]).unwrap();
    }
    assert_eq!(
        f.call("Get_GatherConsume", &[GA, "a", "1", "7"])
            .unwrap_err()
            .status,
        409
    );
    assert!(f
        .call("Get_GatherConsume", &[GA, "a", "1", "0"])
        .unwrap()
        .ends_with("#1#1#0"));
    assert!(f
        .call("Get_GatherConsumeReward", &[GA, "a", "1", "1"])
        .unwrap()
        .ends_with("#1#0#1"));
    f.reopen();
    assert_eq!(f.count("entitlements"), 1);
    assert_eq!(
        f.call("Get_GatherConsumeReward", &[GA, "a", "1", "0"])
            .unwrap_err()
            .status,
        409
    );
}
#[test]
fn rejected_gathering_read_persists_initialized_progress_and_reward_failure_rolls_back() {
    let f = Fixture::new();
    f.state
        .connection()
        .unwrap()
        .execute(
            "INSERT INTO gathering_events VALUES(1,'Christmas',1,1,2,0,?,100)",
            [
                json!({"kind":"wardrobe","item_id":"missing","gender":"MALE","category":"HATS"})
                    .to_string(),
            ],
        )
        .unwrap();
    assert_eq!(
        f.call("Get_npGather", &[GA, "a", "Christmas", "7"])
            .unwrap_err()
            .status,
        409
    );
    assert_eq!(f.count("gathering_progress"), 1);
    f.state
        .connection()
        .unwrap()
        .execute("UPDATE gathering_progress SET current_items=1", [])
        .unwrap();
    assert_eq!(
        f.call("Get_GatherConsumeReward", &[GA, "a", "1", "1"])
            .unwrap_err()
            .status,
        404
    );
    assert_eq!(f.count("entitlements"), 0);
    let (current, claimed): (i64, i64) = f
        .state
        .connection()
        .unwrap()
        .query_row(
            "SELECT current_items,reward_claimed FROM gathering_progress",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!((current, claimed), (1, 0));
}
#[test]
fn housing_conflict_quarantines_without_overwriting_committed_layout() {
    let mut f = Fixture::new();
    f.home();
    let first = part("chair");
    f.call("HousingSavePresetServletParts", &[GA, "a", &first, "0"])
        .unwrap();
    let conflicting = e(&[
        "Home", "1", "chair", "1", "1", "1", "0", "1", "0", "1", "0", "0", "0", "0", "0", "nulls",
    ]);
    assert_eq!(
        f.call(
            "HousingSavePresetServletParts",
            &[GA, "a", &conflicting, "0"]
        )
        .unwrap_err()
        .status,
        409
    );
    f.reopen();
    let status: String = f
        .state
        .connection()
        .unwrap()
        .query_row("SELECT state FROM housing_save_stages", [], |r| r.get(0))
        .unwrap();
    assert_eq!(status, "blocked");
    assert_eq!(f.count("housing_layouts"), 0);
    assert_eq!(
        f.call(
            "HousingSavePresetServletParts",
            &[GA, "a", &part("null"), "1"]
        )
        .unwrap_err()
        .status,
        409
    );
}
#[test]
fn delayed_friend_approval_cannot_resurrect_a_removed_friendship() {
    let mut f = Fixture::new();
    let dir = f.state.state_dir.join("friend-events");
    fs::create_dir_all(&dir).unwrap();
    let id = "33333333-3333-4333-8333-333333333333";
    let event = json!({"format_version":1,"policy":"correlated_online_request_v1","event_id":id,"operation":"accept_friendship","actor_ps4_id":"a","other_ps4_id":"b","created_at":900.});
    fs::write(dir.join(format!("{id}.json")), event.to_string()).unwrap();
    assert_eq!(
        f.call("GetSocialList", &[GA, "0"]).unwrap(),
        "OK#{\"lUsernames\":[\"Bob\"]}"
    );
    assert_eq!(
        f.call("N2RemoveFriend", &[GA, "Bob", "1"]).unwrap(),
        "OK#true"
    );
    f.reopen();
    let delayed = "44444444-4444-4444-8444-444444444444";
    let mut v = event;
    v["event_id"] = json!(delayed);
    v["created_at"] = json!(950.);
    fs::write(dir.join(format!("{delayed}.json")), v.to_string()).unwrap();
    assert_eq!(
        f.call("GetSocialList", &[GA, "0"]).unwrap(),
        "OK#{\"lUsernames\":[]}"
    );
    assert_eq!(f.count("relations"), 0);
    assert_eq!(f.count("friend_events"), 3);
}
