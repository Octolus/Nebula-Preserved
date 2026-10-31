"""Operator starter wallet, applied exactly once in the profile-creating transaction.

A SQLite AFTER INSERT trigger on `profiles` credits the configured amounts and
records `starter_wallet_grants` (plus `management_wallet_ledger` rows when the
management ledger exists). Existing profiles never match the trigger, so a
later configuration change is never applied retroactively or twice.
"""
import os

LEDGER_COLUMNS = {"ledger_id", "request_id", "actor_id", "account_id", "currency", "delta",
                  "before_balance", "after_balance", "reason", "created_at"}
MAXIMUM = 10 ** 9


def starter_amounts(env=None):
    env = os.environ if env is None else env
    amounts = []
    for name in ("NEBULA_STARTER_CRYSTALS", "NEBULA_STARTER_NP"):
        raw = env.get(name, "").strip() or "0"
        value = int(raw)
        if not 0 <= value <= MAXIMUM:
            raise ValueError(name + " must be 0.." + str(MAXIMUM))
        amounts.append(value)
    return tuple(amounts)


class StarterPolicy:
    def __init__(self, store, *, crystals=None, np=None, env=None):
        configured = starter_amounts(env)
        self.crystals = configured[0] if crystals is None else int(crystals)
        self.np = configured[1] if np is None else int(np)
        if not (0 <= self.crystals <= MAXIMUM and 0 <= self.np <= MAXIMUM):
            raise ValueError("Starter wallet amounts are out of range")
        db = self.db = store.db
        columns = {row[1] for row in db.execute("PRAGMA table_info(management_wallet_ledger)")}
        once = "NOT EXISTS(SELECT 1 FROM starter_wallet_grants WHERE ps4_id=NEW.ps4_id)"
        ledger = "".join(f"""
                INSERT OR IGNORE INTO management_wallet_ledger(request_id,actor_id,account_id,currency,delta,
                    before_balance,after_balance,reason,created_at)
                SELECT 'starter-wallet:'||NEW.ps4_id||':{currency}','system:starter-policy',NEW.ps4_id,
                    '{currency}',{currency},0,{currency},'starter wallet policy',NEW.created_at
                FROM starter_wallet_policy WHERE singleton=1 AND {currency}>0 AND {once};"""
            for currency in ("crystals", "np")) if LEDGER_COLUMNS <= columns else ""
        # Schema first: executescript commits and is refused inside Store.atomic().
        db.executescript(f"""
            CREATE TABLE IF NOT EXISTS starter_wallet_policy (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                crystals INTEGER NOT NULL CHECK(crystals>=0), np INTEGER NOT NULL CHECK(np>=0));
            CREATE TABLE IF NOT EXISTS starter_wallet_grants (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id),
                crystals INTEGER NOT NULL, np INTEGER NOT NULL, created_at REAL NOT NULL);
            DROP TRIGGER IF EXISTS starter_wallet_on_profile_insert;
            CREATE TRIGGER starter_wallet_on_profile_insert AFTER INSERT ON profiles
            BEGIN
                INSERT INTO shop_wallets(ps4_id,crystals,np)
                    SELECT NEW.ps4_id,crystals,np FROM starter_wallet_policy
                    WHERE singleton=1 AND (crystals>0 OR np>0) AND {once}
                    ON CONFLICT(ps4_id) DO UPDATE SET crystals=shop_wallets.crystals+excluded.crystals,
                        np=shop_wallets.np+excluded.np;{ledger}
                -- Recorded last: the grant row is the once-per-account-ID marker.
                INSERT OR IGNORE INTO starter_wallet_grants
                    SELECT NEW.ps4_id,crystals,np,NEW.created_at FROM starter_wallet_policy WHERE singleton=1;
            END;
        """)
        with db:
            db.execute("""INSERT INTO starter_wallet_policy VALUES(1,?,?) ON CONFLICT(singleton)
                DO UPDATE SET crystals=excluded.crystals,np=excluded.np""", (self.crystals, self.np))

    def grant(self, ps4_id):
        row = self.db.execute("SELECT * FROM starter_wallet_grants WHERE ps4_id=?", (ps4_id,)).fetchone()
        return dict(row) if row else None
