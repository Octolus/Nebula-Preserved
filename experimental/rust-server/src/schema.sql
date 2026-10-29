CREATE TABLE IF NOT EXISTS allocations (
                guid TEXT PRIMARY KEY REFERENCES sessions,
                instance_id TEXT NOT NULL, psidglobal TEXT NOT NULL,
                ip TEXT NOT NULL, port INTEGER NOT NULL, allocated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS cinema_capabilities (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                interaction_type INTEGER NOT NULL CHECK(interaction_type IN (0,1)),
                granted_at REAL NOT NULL, PRIMARY KEY(ps4_id,interaction_type));
CREATE TABLE IF NOT EXISTS consumable_balances (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                kind TEXT NOT NULL CHECK(kind IN ('coffee','oktoberfest')),
                units INTEGER NOT NULL CHECK(units>=0),
                prop_use_count INTEGER NOT NULL CHECK(prop_use_count>0),
                price_display TEXT NOT NULL, price_type_display TEXT NOT NULL,
                reward_index INTEGER NOT NULL CHECK(reward_index>=0),
                rewarded INTEGER NOT NULL CHECK(rewarded IN (0,1)),
                updated_at REAL NOT NULL, PRIMARY KEY(ps4_id,kind));
CREATE TABLE IF NOT EXISTS consumable_receipts (
                receipt_id TEXT PRIMARY KEY, ps4_id TEXT NOT NULL REFERENCES profiles,
                guid TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('coffee','oktoberfest')),
                table_id INTEGER NOT NULL CHECK(table_id=0),
                use_count INTEGER NOT NULL CHECK(use_count>0),
                reward_index INTEGER NOT NULL CHECK(reward_index>=0),
                issued_at REAL NOT NULL, expires_at REAL NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('prepared','pending','claimed','cancelled')),
                claimed_at REAL);
CREATE TABLE IF NOT EXISTS entitlements (
                ps4_id TEXT NOT NULL REFERENCES profiles, item_id TEXT NOT NULL,
                gender TEXT NOT NULL, category TEXT NOT NULL, bundle TEXT NOT NULL,
                display_name TEXT NOT NULL, granted_at REAL NOT NULL, asset_status INTEGER NOT NULL DEFAULT 1, item_type INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(ps4_id,item_id,gender,category));
CREATE TABLE IF NOT EXISTS friend_events (
                event_id TEXT PRIMARY KEY, operation TEXT NOT NULL,
                actor_ps4_id TEXT NOT NULL REFERENCES profiles,
                other_ps4_id TEXT NOT NULL REFERENCES profiles,
                created_at REAL NOT NULL, processed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS gathering_events (
                type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL, max_items INTEGER NOT NULL,
                phase INTEGER NOT NULL, cooldown_seconds INTEGER NOT NULL,
                reward_json TEXT, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS gathering_medieval (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles,
                active INTEGER NOT NULL DEFAULT 0,
                amount_left INTEGER NOT NULL DEFAULT 0,
                cooldown_until REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS gathering_progress (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                type_id INTEGER NOT NULL REFERENCES gathering_events,
                current_items INTEGER NOT NULL DEFAULT 0,
                rewards_earned INTEGER NOT NULL DEFAULT 0,
                spaces_completed INTEGER NOT NULL DEFAULT 0,
                reward_claimed INTEGER NOT NULL DEFAULT 0,
                last_consume_at REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,type_id));
CREATE TABLE IF NOT EXISTS gathering_scenes (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                type_id INTEGER NOT NULL REFERENCES gathering_events,
                psidglobal TEXT NOT NULL,
                completed_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,type_id,psidglobal));
CREATE TABLE IF NOT EXISTS housing_entitlements (
                ps4_id TEXT NOT NULL REFERENCES profiles, item_id TEXT NOT NULL,
                display_name TEXT NOT NULL, granted_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,item_id));
CREATE TABLE IF NOT EXISTS housing_layouts (
                instance_id TEXT PRIMARY KEY REFERENCES housing_spaces,
                layout_json TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS housing_save_receipts (
                batch_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES housing_spaces,
                guid TEXT NOT NULL, part0_sha256 TEXT NOT NULL, part1_sha256 TEXT NOT NULL,
                committed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS housing_save_stages (
                instance_id TEXT PRIMARY KEY REFERENCES housing_spaces,
                guid TEXT NOT NULL, owner_ps4_id TEXT NOT NULL,
                batch_id TEXT NOT NULL, shared_json TEXT NOT NULL,
                part0_json TEXT, part1_json TEXT, state TEXT NOT NULL,
                started_at REAL NOT NULL, deadline REAL NOT NULL);
CREATE TABLE IF NOT EXISTS housing_spaces (
                instance_id TEXT PRIMARY KEY, logical_space_key TEXT NOT NULL,
                psidglobal TEXT NOT NULL, owner_ps4_id TEXT NOT NULL REFERENCES profiles,
                created_at REAL NOT NULL, UNIQUE(owner_ps4_id,logical_space_key));
CREATE TABLE IF NOT EXISTS local_reports (
                guid TEXT NOT NULL,target TEXT NOT NULL,option INTEGER NOT NULL,
                text TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(guid,target,option));
CREATE TABLE IF NOT EXISTS local_reward_claims (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                route TEXT NOT NULL, trigger_key TEXT NOT NULL,
                outcome_json TEXT NOT NULL, claimed_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,route,trigger_key));
CREATE TABLE IF NOT EXISTS local_reward_definitions (
                route TEXT NOT NULL, trigger_key TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                grant_kind TEXT, item_id TEXT, gender TEXT, category TEXT,
                display_name TEXT, sprite_id INTEGER, units INTEGER, uses INTEGER,
                configured_at REAL NOT NULL, PRIMARY KEY(route,trigger_key));
CREATE TABLE IF NOT EXISTS moderation_accounts (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles,
                ban_enabled INTEGER NOT NULL DEFAULT 0 CHECK(ban_enabled IN (0,1)),
                ban_expires_at INTEGER, ban_reason TEXT NOT NULL DEFAULT '',
                mute_enabled INTEGER NOT NULL DEFAULT 0 CHECK(mute_enabled IN (0,1)),
                mute_expires_at INTEGER, mute_reason TEXT NOT NULL DEFAULT '', staff_label TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS moderation_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL, actor_role TEXT NOT NULL, operation TEXT NOT NULL,
                target_id TEXT NOT NULL, reason TEXT NOT NULL, before_json TEXT NOT NULL,
                after_json TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS moderation_maintenance (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                started_at INTEGER NOT NULL, end_at INTEGER NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS moderation_news (
                news_id TEXT PRIMARY KEY, text TEXT NOT NULL, date_label TEXT NOT NULL,
                created_at INTEGER NOT NULL, expires_at INTEGER,
                active INTEGER NOT NULL CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS moderation_report_index (
                report_id TEXT PRIMARY KEY, guid TEXT NOT NULL, target TEXT NOT NULL,
                option INTEGER NOT NULL, UNIQUE(guid,target,option),
                FOREIGN KEY(guid,target,option) REFERENCES local_reports(guid,target,option));
CREATE TABLE IF NOT EXISTS moderation_report_reviews (
                report_id TEXT PRIMARY KEY REFERENCES moderation_report_index,
                status TEXT NOT NULL CHECK(status IN ('open','resolved','dismissed')),
                note TEXT NOT NULL, actor_id TEXT NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS moderation_revoked_sessions (
                guid TEXT PRIMARY KEY, ps4_id TEXT NOT NULL REFERENCES profiles,
                request_id TEXT NOT NULL, revoked_at INTEGER NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notification_outbox (
              event_id TEXT PRIMARY KEY, target_ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
              source_username TEXT NOT NULL, source_platform INTEGER NOT NULL CHECK(source_platform IN (0,1)),
              notification_type INTEGER NOT NULL CHECK(notification_type IN (3,4)),
              arguments TEXT NOT NULL, ticks INTEGER NOT NULL, dedupe_key TEXT NOT NULL,
              created_at REAL NOT NULL, accepted_at REAL,
              UNIQUE(target_ps4_id,dedupe_key));
CREATE TABLE IF NOT EXISTS positions (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles,
                x REAL NOT NULL,y REAL NOT NULL,z REAL NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS preferences (
                ps4_id TEXT NOT NULL REFERENCES profiles, key TEXT NOT NULL,
                value TEXT NOT NULL, PRIMARY KEY(ps4_id,key));
CREATE TABLE IF NOT EXISTS preset_selection (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                gender TEXT NOT NULL, name TEXT NOT NULL,
                PRIMARY KEY(ps4_id,gender));
CREATE TABLE IF NOT EXISTS presets (
                ps4_id TEXT NOT NULL REFERENCES profiles, name TEXT NOT NULL,
                gender TEXT NOT NULL, preset_json TEXT NOT NULL,
                assets_json TEXT NOT NULL, position_json TEXT NOT NULL,
                updated_at REAL NOT NULL, PRIMARY KEY(ps4_id,name,gender));
CREATE TABLE IF NOT EXISTS profile_state (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles, last_preset TEXT,
                in_wardrobe INTEGER NOT NULL DEFAULT 0,
                online INTEGER NOT NULL DEFAULT 0, wardrobe_instance_id TEXT NOT NULL DEFAULT '', wardrobe_updated_at REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS profiles (
                ps4_id TEXT PRIMARY KEY, username TEXT NOT NULL,
                platform TEXT NOT NULL, gender TEXT NOT NULL DEFAULT 'MALE',
                created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS relations (
                ps4_id TEXT NOT NULL REFERENCES profiles, target TEXT NOT NULL,
                target_platform TEXT NOT NULL, kind TEXT NOT NULL,
                PRIMARY KEY(ps4_id,target,target_platform,kind));
CREATE TABLE IF NOT EXISTS resource_entitlements (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                kind TEXT NOT NULL CHECK(kind IN ('companions','locomotions')),
                item_id TEXT NOT NULL, bundle TEXT NOT NULL,
                asset_path TEXT NOT NULL, display_name TEXT NOT NULL,
                granted_at REAL NOT NULL, PRIMARY KEY(ps4_id,kind,item_id));
CREATE TABLE IF NOT EXISTS resource_selection_receipts (
                request_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                response_json TEXT NOT NULL, processed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS resource_selections (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                kind TEXT NOT NULL CHECK(kind IN ('companions','locomotions')),
                item_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
                updated_at REAL NOT NULL, PRIMARY KEY(ps4_id,kind));
CREATE TABLE IF NOT EXISTS sessions (
                guid TEXT PRIMARY KEY, ps4_id TEXT NOT NULL REFERENCES profiles,
                created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS shop_bundle_items (
                    bundle_offer_id TEXT NOT NULL REFERENCES shop_offers(offer_id),
                    child_offer_id TEXT NOT NULL REFERENCES shop_offers(offer_id),
                    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
                    PRIMARY KEY(bundle_offer_id,child_offer_id));
CREATE TABLE IF NOT EXISTS shop_catalogs (
                    shop_id TEXT PRIMARY KEY, type_shop INTEGER NOT NULL
                    CHECK(type_shop BETWEEN 0 AND 3), name TEXT NOT NULL,
                    description TEXT NOT NULL, url TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS shop_offers (
                    offer_id TEXT PRIMARY KEY, kind TEXT NOT NULL
                    CHECK(kind IN ('wardrobe','companions','locomotions','housing','bundle')),
                    item_id TEXT, gender TEXT, category TEXT,
                    shop_id TEXT NOT NULL REFERENCES shop_catalogs(shop_id),
                    type_id TEXT NOT NULL, gender_id INTEGER NOT NULL,
                    name TEXT NOT NULL, image_path TEXT NOT NULL,
                    crystals INTEGER NOT NULL CHECK(crystals>=0),
                    np INTEGER NOT NULL CHECK(np>=0),
                    featured INTEGER NOT NULL CHECK(featured IN (0,1)),
                    active INTEGER NOT NULL CHECK(active IN (0,1)),
                    created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS shop_owned (
                    ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                    offer_id TEXT NOT NULL REFERENCES shop_offers(offer_id),
                    source TEXT NOT NULL CHECK(source IN ('buy','gift','admin')),
                    granted_by TEXT, created_at REAL NOT NULL,
                    PRIMARY KEY(ps4_id,offer_id));
CREATE TABLE IF NOT EXISTS shop_wallets (
                    ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id),
                    crystals INTEGER NOT NULL DEFAULT 0 CHECK(crystals>=0),
                    np INTEGER NOT NULL DEFAULT 0 CHECK(np>=0),
                    level INTEGER NOT NULL DEFAULT 0 CHECK(level>=0));
CREATE TRIGGER IF NOT EXISTS moderation_events_no_delete BEFORE DELETE ON moderation_events
                BEGIN SELECT RAISE(ABORT,'Moderation history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS moderation_events_no_update BEFORE UPDATE ON moderation_events
                BEGIN SELECT RAISE(ABORT,'Moderation history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS moderation_news_no_delete BEFORE DELETE ON moderation_news
                BEGIN SELECT RAISE(ABORT,'News history cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS moderation_news_no_rewrite BEFORE UPDATE ON moderation_news
                WHEN NEW.news_id IS NOT OLD.news_id OR NEW.text IS NOT OLD.text
                  OR NEW.date_label IS NOT OLD.date_label OR NEW.created_at IS NOT OLD.created_at
                  OR NEW.expires_at IS NOT OLD.expires_at OR NEW.active != 0
                BEGIN SELECT RAISE(ABORT,'News content is immutable; archive it instead'); END;
CREATE TRIGGER IF NOT EXISTS moderation_report_index_no_delete BEFORE DELETE ON moderation_report_index
                BEGIN SELECT RAISE(ABORT,'Report identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS moderation_report_index_no_update BEFORE UPDATE ON moderation_report_index
                BEGIN SELECT RAISE(ABORT,'Report identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS moderation_reports_no_delete BEFORE DELETE ON local_reports
                BEGIN SELECT RAISE(ABORT,'Report receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS moderation_reports_no_update BEFORE UPDATE ON local_reports
                BEGIN SELECT RAISE(ABORT,'Report receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS moderation_revocations_no_delete BEFORE DELETE ON moderation_revoked_sessions
                BEGIN SELECT RAISE(ABORT,'Session revocations are permanent'); END;
CREATE TRIGGER IF NOT EXISTS moderation_revocations_no_update BEFORE UPDATE ON moderation_revoked_sessions
                BEGIN SELECT RAISE(ABORT,'Session revocations are permanent'); END;
