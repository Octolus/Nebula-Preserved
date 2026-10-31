"""Offline shop reconstruction with explicit, administrator-authored offers.

The wire DTOs and route shapes are recovered client contracts.  Prices,
balances and transaction rules are deliberately local replacement policy: no
Steam order, retired-service price, or client-supplied price is trusted.
"""
import sqlite3
import time

from avatar_entry_codec import encode_entry_fields
from catalog_inventory import client_item_order, client_type_id, client_type_ids
from wire import ProtocolError
from diagnostic_logging import missing_data
from public_access import gift_recipient_grant
from space_shop import (SHOP_SPACES, SPACE_GENDER_ID, SPACE_ITEM_GENDER, SPACE_TABLENAME,
                        SPACE_TYPE_ID)


SHOP_DATA = [
    {"name": "id", "type": "string"},
    {"name": "name", "type": "string"},
    {"name": "desciption", "type": "string"},  # recovered client spelling
    {"name": "url", "type": "string"},
]
GENDER_DATA = [
    {"name": "genderID", "type": "int"},
    {"name": "show", "type": "bool"},
]
TYPE_DATA = [
    {"name": "shopID", "type": "string"},
    {"name": "typeID", "type": "string"},
    {"name": "gender", "type": "string"},
]
ITEM_DATA = [
    {"name": "id", "type": "string"},
    {"name": "name", "type": "string"},
    {"name": "imagePath", "type": "string"},
    {"name": "crystals", "type": "int"},
    {"name": "np", "type": "int"},
    {"name": "isBundle", "type": "bool"},
    {"name": "gender", "type": "string"},
    {"name": "tablename", "type": "string"},
]

KINDS = ("wardrobe", "companions", "locomotions", "housing", "personal_spaces", "bundle")
# Shared by table creation and the one-time CHECK migration of older databases.
OFFERS_DDL = """CREATE TABLE {name} (
    offer_id TEXT PRIMARY KEY, kind TEXT NOT NULL
    CHECK(kind IN ('wardrobe','companions','locomotions','housing','personal_spaces','bundle')),
    item_id TEXT, gender TEXT, category TEXT,
    shop_id TEXT NOT NULL REFERENCES shop_catalogs(shop_id),
    type_id TEXT NOT NULL, gender_id INTEGER NOT NULL,
    name TEXT NOT NULL, image_path TEXT NOT NULL,
    crystals INTEGER NOT NULL CHECK(crystals>=0),
    np INTEGER NOT NULL CHECK(np>=0),
    featured INTEGER NOT NULL CHECK(featured IN (0,1)),
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    created_at REAL NOT NULL)"""
TYPE_SHOPS = range(4)
TYPE_LIST_GENDERS = (0, 1)
DIRECT_ITEM_GENDERS = (2, 3, 5, 6)
# These shipped assets have no recovered item thumbnail. The generic Shops/shop
# sprite is loaded by the original EntryBase thumbnail consumer. This fallback
# changes presentation only; it does not supply a name or historical store.
GENERIC_THUMBNAIL_ITEMS = frozenset(("O08f1sQQOR6VVuRpIXAdCria00L0r33b", "sL0D2k3asbB756Yb2qJ0LchSiLsKw5Cf"))


def _text(value, label, allow_empty=False):
    if (not isinstance(value, str) or (not value and not allow_empty)
            or len(value) > 1024 or "#" in value or "\x00" in value):
        raise ProtocolError("Invalid " + label)
    return value


def _uint(value, label):
    if isinstance(value, bool):
        raise ProtocolError("Invalid " + label)
    try:
        result = int(value, 10) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        raise ProtocolError("Invalid " + label) from None
    if result < 0 or result > 2_147_483_647:
        raise ProtocolError("Invalid " + label)
    return result


def _uint64(value, label):
    if isinstance(value, bool):
        raise ProtocolError("Invalid " + label)
    try:
        result = int(value, 10) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        raise ProtocolError("Invalid " + label) from None
    if result < 0 or result > 9_223_372_036_854_775_807:
        raise ProtocolError("Invalid " + label)
    return result


def _bool(value, label):
    if value not in ("True", "False", "true", "false"):
        raise ProtocolError("Invalid " + label)
    return value.lower() == "true"


class Shop:
    ROUTES = {
        "GetFeaturesServlet", "GetGenderDataShopServlet",
        "GetItemAssetsDataServlet", "GetShopDataShopServlet",
        "GetShopInfoPlayerShop", "GetShopTypeDataShopServlet",
        "NPShopBundleItemsServlet", "NPShopBuyItemServlet",
        "NPShopGiftItemServlet", "NPShopIsItemPurchasedServlet",
        "NPShopSyncCrystalsServlet",
    }

    def __init__(self, store, catalog, resources, housing, notifications=None):
        self.store = store
        self.catalog = catalog
        self.resources = resources
        self.housing = housing
        self.notifications = notifications
        # ApartmentPolicy; Service attaches it. Apartment offers grant bindings.
        self.apartments = None
        self._migrate_offer_kinds()
        with store.db:
            store.db.executescript("""
                CREATE TABLE IF NOT EXISTS shop_wallets (
                    ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id),
                    crystals INTEGER NOT NULL DEFAULT 0 CHECK(crystals>=0),
                    np INTEGER NOT NULL DEFAULT 0 CHECK(np>=0),
                    level INTEGER NOT NULL DEFAULT 0 CHECK(level>=0));
                CREATE TABLE IF NOT EXISTS shop_catalogs (
                    shop_id TEXT PRIMARY KEY, type_shop INTEGER NOT NULL
                    CHECK(type_shop BETWEEN 0 AND 3), name TEXT NOT NULL,
                    description TEXT NOT NULL, url TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)));
                {offers};
                CREATE TABLE IF NOT EXISTS shop_bundle_items (
                    bundle_offer_id TEXT NOT NULL REFERENCES shop_offers(offer_id),
                    child_offer_id TEXT NOT NULL REFERENCES shop_offers(offer_id),
                    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
                    PRIMARY KEY(bundle_offer_id,child_offer_id));
                CREATE TABLE IF NOT EXISTS shop_owned (
                    ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                    offer_id TEXT NOT NULL REFERENCES shop_offers(offer_id),
                    source TEXT NOT NULL CHECK(source IN ('buy','gift','admin')),
                    granted_by TEXT, created_at REAL NOT NULL,
                    PRIMARY KEY(ps4_id,offer_id));
            """.replace("{offers}", OFFERS_DDL.format(name="IF NOT EXISTS shop_offers")))

    def _migrate_offer_kinds(self):
        """Rebuild an older shop_offers table whose CHECK lacks personal_spaces.

        SQLite cannot alter a CHECK; this is its documented table-rebuild
        procedure. Rows, IDs and every referencing row are kept unchanged.
        """
        db = self.store.db
        row = db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='shop_offers'").fetchone()
        if row is None or "'personal_spaces'" in row[0]:
            return
        db.commit()
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            db.executescript("BEGIN IMMEDIATE;" + OFFERS_DDL.format(name="shop_offers_migrating") + ";"
                             "INSERT INTO shop_offers_migrating SELECT * FROM shop_offers;"
                             "DROP TABLE shop_offers;"
                             "ALTER TABLE shop_offers_migrating RENAME TO shop_offers;")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                db.rollback()
                raise ProtocolError("Shop offer migration would break a reference", 500)
            db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")

    def configure_shop(self, shop_id, type_shop, name, description="", url="", active=True):
        shop_id = _text(shop_id, "shop ID")
        type_shop = _uint(type_shop, "shop type")
        if type_shop not in TYPE_SHOPS:
            raise ProtocolError("Unsupported shop type")
        for value, label in ((name, "shop name"), (description, "shop description"),
                             (url, "shop URL")):
            _text(value, label, allow_empty=label != "shop name")
        with self.store.db:
            self.store.db.execute("""INSERT INTO shop_catalogs VALUES(?,?,?,?,?,?)
                ON CONFLICT(shop_id) DO UPDATE SET type_shop=excluded.type_shop,
                name=excluded.name,description=excluded.description,url=excluded.url,
                active=excluded.active""",
                (shop_id, type_shop, name, description, url, int(bool(active))))

    def configure_offer(self, offer_id, kind, item_id, shop_id, type_id,
                        gender_id, name, image_path="", crystals=0, np=0,
                        gender=None, category=None, featured=False, active=True):
        offer_id = _text(offer_id, "offer ID")
        if kind not in KINDS:
            raise ProtocolError("Unsupported offer kind")
        if not self.store.db.execute("SELECT 1 FROM shop_catalogs WHERE shop_id=?", (shop_id,)).fetchone():
            raise ProtocolError("Unknown configured shop", 404)
        _text(type_id, "shop type ID")
        gender_id = _uint(gender_id, "shop gender ID")
        _text(name, "offer name")
        _text(image_path, "offer image path", allow_empty=True)
        crystals, np = _uint(crystals, "crystal price"), _uint(np, "NP price")
        if kind == "bundle":
            if item_id not in (None, ""):
                raise ProtocolError("Bundle offers do not name a single asset")
            item_id = None
            gender = category = None
            if not image_path:
                raise ProtocolError("Bundle offers require a manifest-compatible thumbnail path")
            image_path = self._checked_thumbnail(image_path)
            if not self.store.db.execute(
                    "SELECT 1 FROM shop_offers WHERE kind!='bundle' AND image_path=?",
                    (image_path,)).fetchone():
                raise ProtocolError("Bundle thumbnail must reuse a configured shipped thumbnail")
        else:
            item_id = _text(item_id, "shipped item ID")
            asset = self._resolve_asset(kind, item_id, gender, category)
            if kind == "wardrobe":
                gender, category = _text(gender, "wardrobe gender"), _text(category, "wardrobe category")
                expected_gender_id = {"MALE": 0, "FEMALE": 1}.get(gender)
                if gender_id != expected_gender_id:
                    raise ProtocolError("Wardrobe gender ID does not match the shipped asset")
            else:
                gender = category = None
            if kind == "personal_spaces" and (gender_id, type_id) != (SPACE_GENDER_ID, SPACE_TYPE_ID):
                # Only the native Spaces tab (gender 4, type PERSON) lists apartments.
                raise ProtocolError("Apartment offers use the Spaces tab (gender 4, type PERSON)")
            derived_image = self._thumbnail(kind, item_id, asset)
            if image_path and image_path != derived_image:
                raise ProtocolError("Offer thumbnail does not match the shipped manifest asset")
            image_path = derived_image
        with self.store.db:
            self.store.db.execute("""INSERT INTO shop_offers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(offer_id) DO UPDATE SET kind=excluded.kind,item_id=excluded.item_id,
                gender=excluded.gender,category=excluded.category,shop_id=excluded.shop_id,
                type_id=excluded.type_id,gender_id=excluded.gender_id,name=excluded.name,
                image_path=excluded.image_path,crystals=excluded.crystals,np=excluded.np,
                featured=excluded.featured,active=excluded.active""",
                (offer_id, kind, item_id, gender, category, shop_id, type_id,
                 gender_id, name, image_path, crystals, np, int(bool(featured)),
                 int(bool(active)), time.time()))

    def add_bundle_item(self, bundle_offer_id, child_offer_id, ordinal=0):
        bundle = self._offer(bundle_offer_id, active=False)
        child = self._offer(child_offer_id, active=False)
        if bundle["kind"] != "bundle" or child["kind"] == "bundle":
            raise ProtocolError("Bundles require a bundle parent and non-bundle child")
        with self.store.db:
            self.store.db.execute("""INSERT INTO shop_bundle_items VALUES(?,?,?)
                ON CONFLICT(bundle_offer_id,child_offer_id) DO UPDATE SET ordinal=excluded.ordinal""",
                (bundle_offer_id, child_offer_id, _uint(ordinal, "bundle ordinal")))

    def set_wallet(self, ps4_id, crystals, np=0, level=0):
        self.store.account(ps4_id)
        values = tuple(_uint(x, name) for x, name in
                       ((crystals, "crystal balance"), (np, "NP balance"), (level, "level")))
        with self.store.db:
            self.store.db.execute("""INSERT INTO shop_wallets VALUES(?,?,?,?)
                ON CONFLICT(ps4_id) DO UPDATE SET crystals=excluded.crystals,
                np=excluded.np,level=excluded.level""", (ps4_id, *values))
        return self.wallet(ps4_id)

    def wallet(self, ps4_id):
        row = self.store.db.execute("SELECT * FROM shop_wallets WHERE ps4_id=?", (ps4_id,)).fetchone()
        return dict(row) if row else {"ps4_id": ps4_id, "crystals": 0, "np": 0, "level": 0}

    def _ensure_wallet(self, ps4_id):
        with self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO shop_wallets(ps4_id) VALUES(?)", (ps4_id,))

    def list_offers(self):
        return [dict(row) for row in self.store.db.execute("SELECT * FROM shop_offers ORDER BY offer_id")]

    def dispatch(self, command, request):
        handlers = {
            "GetFeaturesServlet": self._features,
            "GetGenderDataShopServlet": self._genders,
            "GetItemAssetsDataServlet": self._items,
            "GetShopDataShopServlet": self._shops,
            "GetShopInfoPlayerShop": self._info,
            "GetShopTypeDataShopServlet": self._types,
            "NPShopBundleItemsServlet": self._bundle,
            "NPShopBuyItemServlet": self._buy,
            "NPShopGiftItemServlet": self._gift,
            "NPShopIsItemPurchasedServlet": self._is_purchased,
            "NPShopSyncCrystalsServlet": self._sync,
        }
        if command not in handlers:
            raise ProtocolError("Unsupported shop command", 404)
        return handlers[command](request)

    def _profile(self, request, count):
        fields = request.require(count)
        profile = self.store.session(fields[0], fields[1])
        if profile["platform"] != request.platform:
            raise ProtocolError("Session platform mismatch", 403)
        return fields, profile

    @staticmethod
    def _list(guid, ps4_id, rows, schema):
        return "#".join(["true", guid, ps4_id, str(len(rows)),
                         *[encode_entry_fields(row, schema) for row in rows]])

    def _offer(self, offer_id, active=True):
        sql = "SELECT * FROM shop_offers WHERE offer_id=?" + (" AND active=1" if active else "")
        row = self.store.db.execute(sql, (offer_id,)).fetchone()
        if not row:
            inactive = active and self.store.db.execute(
                "SELECT 1 FROM shop_offers WHERE offer_id=?", (offer_id,)).fetchone()
            missing_data("shop_offer_inactive" if inactive else "shop_offer_unknown", offer_id=offer_id)
            raise ProtocolError("Unknown local offer", 404)
        return dict(row)

    # ItemData.id is a single client value. EntryItem.Set (0x4aa380) stores it
    # as itemSelected, and the 3D try-on loader SetShopBase.Init(itemSelected,
    # tablename) and WardrobeWindow.buyItem/OnClickBuyNP/OnClickGift
    # (0x4b8500/0x4b75e0/0x4b7700) all send that same value back. Lists
    # therefore expose the shipped asset ID, and the return paths accept either
    # that asset ID or a legacy/bundle offer ID. No stored row changes.
    _IDENTITY_SQL = ("kind || '|' || CASE kind WHEN 'wardrobe' THEN "
                     "coalesce(gender,'') || '|' || coalesce(category,'') ELSE '' END")

    def _ambiguous_item_ids(self):
        """Asset IDs that cannot name exactly one underlying local item."""
        rows = self.store.db.execute(
            f"""SELECT item_id FROM shop_offers WHERE active=1 AND kind<>'bundle' AND item_id IS NOT NULL
                GROUP BY item_id HAVING COUNT(DISTINCT {self._IDENTITY_SQL})>1
                UNION SELECT o.item_id FROM shop_offers o JOIN shop_offers p
                ON p.offer_id=o.item_id AND p.offer_id<>o.offer_id""")
        return {row[0] for row in rows}

    def _client_offer(self, key, price=None):
        """Resolve an ItemData.id sent back by the client to one active offer."""
        if self.store.db.execute("SELECT 1 FROM shop_offers WHERE offer_id=?", (key,)).fetchone():
            return self._offer(key)
        rows = [dict(row) for row in self.store.db.execute(
            f"""SELECT *, {self._IDENTITY_SQL} AS identity FROM shop_offers
                WHERE item_id=? AND kind<>'bundle' AND active=1 ORDER BY offer_id""", (key,))]
        if not rows:
            return self._offer(key)  # unknown/inactive reporting is unchanged
        if len({row["identity"] for row in rows}) != 1:
            raise ProtocolError("Asset ID names several different local items", 409)
        if price is not None:
            # Same item in several stores: the displayed price selects the offer.
            rows = [row for row in rows if price(row)] or rows
        offer = rows[0]
        del offer["identity"]
        return offer

    def _resolve_asset(self, kind, item_id, gender=None, category=None):
        if kind == "wardrobe":
            return self.catalog.resolve(item_id, gender, category)
        if kind in ("companions", "locomotions"):
            if self.resources.catalog is None:
                raise ProtocolError("Resource catalog is required", 501)
            return self.resources.catalog.resolve(kind, item_id)
        if kind == "housing":
            if item_id not in self.housing.catalog:
                missing_data("housing_item_unknown", item_id=item_id)
                raise ProtocolError("Unknown shipped housing asset", 404)
            return self.housing.catalog[item_id]
        if kind == "personal_spaces":
            if item_id not in SHOP_SPACES:
                missing_data("personal_space_unknown", item_id=item_id)
                raise ProtocolError("Unknown shipped apartment shop ID", 404)
            return SHOP_SPACES[item_id]
        raise ProtocolError("Bundle has no direct shipped asset")

    @staticmethod
    def _checked_thumbnail(path):
        path = _text(path, "offer image path")
        if path == "Shops/shop.png":
            return path
        if (not path.endswith(".png") or "/" not in path
                or not any(marker in path for marker in
                           ("MALE/", "FEMALE/", "COMPANIONS/", "Housing/", "LOCOMOTIONS/", "PersonalSpaces/"))):
            raise ProtocolError("Offer thumbnail is not compatible with the shipped loader")
        return path

    def _thumbnail(self, kind, item_id, asset):
        if kind == "wardrobe":
            suffix = "/" + item_id + "Thumbnail.png"
            # A manifest may list the same ID under several folders; only the
            # row's own gender/category folder is its thumbnail.
            paths = [e[2] for e in asset.get("category_evidence", [])
                     if len(e) == 3 and e[2].endswith(suffix)
                     and (e[0], e[1]) == (asset.get("gender"), asset.get("category"))]
            prefixes = ("Assets/ResourcesART/Wardrobe_EAB/", "Assets/ART/ResourcesART/Wardrobe_EAB/")
            paths = [p[len(prefix):] for p in paths for prefix in prefixes if p.startswith(prefix)]
            if not paths and item_id in GENERIC_THUMBNAIL_ITEMS:
                return "Shops/shop.png"
            if len(set(paths)) != 1:
                raise ProtocolError("Shipped wardrobe thumbnail is ambiguous", 501)
            return self._checked_thumbnail(paths[0])
        if kind in ("companions", "locomotions"):
            thumbnails = asset.get("thumbnail_assets", [])
            if len(thumbnails) != 1:
                raise ProtocolError("Shipped resource thumbnail is ambiguous", 501)
            path = thumbnails[0].get("asset_path", "")
            marker = "/ResourcesART/"
            if marker not in path:
                raise ProtocolError("Shipped resource thumbnail path is invalid", 501)
            return self._checked_thumbnail(path.split(marker, 1)[1])
        if kind == "housing":
            # Housing manifests follow this exact sibling-thumbnail convention;
            # the catalog row has already proved the canonical table and ID.
            return self._checked_thumbnail(
                "Housing/" + asset["table"] + "/" + item_id + "/" + item_id + "Thumbnail.png")
        if kind == "personal_spaces":
            # EntryBase.setThumbnail loads PersonalSpaces/<id>/<id>Thumbnail
            # from shipped Resources; the same ID names its screenshots.
            return self._checked_thumbnail(asset["thumbnail_path"])
        raise ProtocolError("Bundle thumbnail must be explicitly configured")

    def _item(self, row, profile_gender=None, ambiguous=None):
        if row["kind"] == "wardrobe":
            table = row["category"]
        elif row["kind"] in ("companions", "locomotions"):
            table = self.resources.catalog.resolve(row["kind"], row["item_id"])["table"]
        elif row["kind"] == "housing":
            table = self.housing.catalog[row["item_id"]]["table"]
        elif row["kind"] == "personal_spaces":
            table = SPACE_TABLENAME
        else:
            table = "BUNDLES"
        gender = row["gender"] if row["kind"] == "wardrobe" else profile_gender
        if gender not in ("MALE", "FEMALE"):
            gender = "MALE"
        if row["kind"] == "personal_spaces":
            gender = SPACE_ITEM_GENDER
        if ambiguous is None:
            ambiguous = self._ambiguous_item_ids()
        client_id = row["offer_id"]
        if row["kind"] != "bundle" and row["item_id"] and row["item_id"] not in ambiguous:
            client_id = row["item_id"]
        return {"id": client_id, "name": row["name"],
                "imagePath": row["image_path"], "crystals": row["crystals"],
                "np": row["np"], "isBundle": row["kind"] == "bundle",
                "gender": "BundleMix" if row["kind"] == "bundle" else gender,
                "tablename": table}

    def _features(self, request):
        fields, profile = self._profile(request, 2)
        ambiguous = self._ambiguous_item_ids()
        rows = [self._item(dict(row), profile["gender"], ambiguous) for row in self.store.db.execute(
            "SELECT * FROM shop_offers WHERE active=1 AND featured=1 ORDER BY offer_id")]
        return self._list(fields[0], fields[1], rows, ITEM_DATA)

    def _shops(self, request):
        fields, _ = self._profile(request, 5)
        _bool(fields[2], "shop display flag")
        _bool(fields[3], "shop display flag")
        type_shop = _uint(fields[4], "shop type")
        rows = [{"id": row["shop_id"], "name": row["name"],
                 "desciption": row["description"], "url": row["url"]}
                for row in self.store.db.execute(
                    "SELECT * FROM shop_catalogs WHERE active=1 AND type_shop=? ORDER BY shop_id", (type_shop,))]
        return self._list(fields[0], fields[1], rows, SHOP_DATA)

    def _genders(self, request):
        fields, _ = self._profile(request, 3)
        rows = [{"genderID": row[0], "show": True} for row in self.store.db.execute(
            """SELECT DISTINCT gender_id FROM shop_offers o JOIN shop_catalogs s USING(shop_id)
               WHERE o.active=1 AND s.active=1 AND o.shop_id=? ORDER BY gender_id""", (fields[2],))]
        # GetGenderData's native callback consumes two flat tokens per row,
        # unlike every EntryData-backed list callback.
        values = []
        for row in rows:
            values.extend((str(row["genderID"]), "True" if row["show"] else "False"))
        return "#".join(("true", fields[0], fields[1], str(len(values)), *values))

    def _types(self, request):
        fields, profile = self._profile(request, 4)
        gender_id = _uint(fields[3], "shop gender ID")
        if gender_id in TYPE_LIST_GENDERS:
            # Only IDs with a native ItemTypeWindow icon, in client enum order;
            # an unknown ID would abort the client's whole category list.
            stored = [row[0] for row in self.store.db.execute(
                """SELECT DISTINCT type_id FROM shop_offers o JOIN shop_catalogs s USING(shop_id)
                   WHERE o.active=1 AND s.active=1 AND o.shop_id=? AND o.gender_id=?
                   ORDER BY type_id""", (fields[2], gender_id))]
            rows = [{"shopID": fields[2], "typeID": type_id, "gender": str(gender_id)}
                    for type_id in client_type_ids(stored)]
            return self._list(fields[0], fields[1], rows, TYPE_DATA)
        if gender_id in DIRECT_ITEM_GENDERS:
            ambiguous = self._ambiguous_item_ids()
            rows = client_item_order(self._item(dict(row), profile["gender"], ambiguous) for row in self.store.db.execute(
                """SELECT o.* FROM shop_offers o JOIN shop_catalogs s USING(shop_id)
                   WHERE o.active=1 AND s.active=1 AND o.shop_id=? AND o.gender_id=?
                   ORDER BY o.offer_id""", (fields[2], gender_id)))
            return self._list(fields[0], fields[1], rows, ITEM_DATA)
        if gender_id == 4:
            return self._list(fields[0], fields[1], [], ITEM_DATA)
        raise ProtocolError("Unsupported shop gender ID")

    def _items(self, request):
        fields, profile = self._profile(request, 5)
        gender_id = _uint(fields[3], "shop gender ID")
        # The client sends back the type ID it displayed (merged L/R slots,
        # RINGSL/R already stripped to RINGS); match every stored member.
        wanted = client_type_id(fields[4])
        ambiguous = self._ambiguous_item_ids()
        rows = client_item_order(self._item(dict(row), profile["gender"], ambiguous) for row in self.store.db.execute(
            """SELECT o.* FROM shop_offers o JOIN shop_catalogs s USING(shop_id)
               WHERE o.active=1 AND s.active=1 AND o.shop_id=? AND o.gender_id=?
               ORDER BY o.offer_id""", (fields[2], gender_id))
            if row["type_id"] == fields[4] or (wanted is not None and client_type_id(row["type_id"]) == wanted))
        return self._list(fields[0], fields[1], rows, ITEM_DATA)

    def _bundle(self, request):
        fields, profile = self._profile(request, 3)
        parent = self._client_offer(fields[2])
        if parent["kind"] != "bundle":
            raise ProtocolError("Offer is not a bundle")
        ambiguous = self._ambiguous_item_ids()
        rows = [self._item(dict(row), profile["gender"], ambiguous) for row in self.store.db.execute(
            """SELECT o.* FROM shop_bundle_items b JOIN shop_offers o
               ON o.offer_id=b.child_offer_id WHERE b.bundle_offer_id=? AND o.active=1
               ORDER BY b.ordinal,o.offer_id""", (parent["offer_id"],))]
        return self._list(fields[0], fields[1], rows, ITEM_DATA)

    def _info(self, request):
        fields, profile = self._profile(request, 2)
        wallet = self.wallet(fields[1])
        return "#".join(("true", fields[0], fields[1], profile["username"],
                         str(wallet["np"]), str(wallet["crystals"])))

    def _space_key(self, offer):
        if self.apartments is None:
            raise ProtocolError("Apartment ownership is not configured", 501)
        return self._resolve_asset("personal_spaces", offer["item_id"])["logical_space_key"]

    def _underlying_owned(self, ps4_id, offer):
        if offer["kind"] == "personal_spaces":
            # The binding is the entitlement: a staff-removed apartment can be
            # bought again even though its old purchase receipt remains.
            return self.apartments_owned(ps4_id, offer)
        if self.store.db.execute("SELECT 1 FROM shop_owned WHERE ps4_id=? AND offer_id=?",
                                 (ps4_id, offer["offer_id"])).fetchone():
            return True
        if offer["kind"] == "wardrobe":
            return any(row["item_id"] == offer["item_id"] and row["gender"] == offer["gender"]
                       and row["category"] == offer["category"] for row in self.store.inventory(ps4_id))
        if offer["kind"] in ("companions", "locomotions"):
            return any(row["item_id"] == offer["item_id"] for row in self.resources.list(ps4_id, offer["kind"]))
        if offer["kind"] == "housing":
            return any(row["item_id"] == offer["item_id"] for row in self.housing.inventory(ps4_id))
        children = self._children(offer["offer_id"])
        return bool(children) and all(self._underlying_owned(ps4_id, child) for child in children)

    def apartments_owned(self, ps4_id, offer):
        return self.apartments.owned(ps4_id, self._space_key(offer)) is not None

    def _children(self, offer_id):
        return [dict(row) for row in self.store.db.execute(
            """SELECT o.* FROM shop_bundle_items b JOIN shop_offers o
               ON o.offer_id=b.child_offer_id WHERE b.bundle_offer_id=?
               ORDER BY b.ordinal,o.offer_id""", (offer_id,))]

    def _grant(self, ps4_id, offer):
        if offer["kind"] == "bundle":
            children = self._children(offer["offer_id"])
            if not children:
                raise ProtocolError("Empty bundle cannot be granted", 409)
            for child in children:
                self._grant(ps4_id, child)
        elif offer["kind"] == "wardrobe":
            item = self.catalog.resolve(offer["item_id"], offer["gender"], offer["category"])
            self.store.grant(ps4_id, item, offer["name"])
        elif offer["kind"] in ("companions", "locomotions"):
            self.resources.grant(ps4_id, offer["kind"], offer["item_id"], offer["name"])
        elif offer["kind"] == "housing":
            self.housing.grant_item(ps4_id, offer["item_id"], offer["name"])
        elif offer["kind"] == "personal_spaces":
            # Same path as a starter or staff grant: binding plus managed instance.
            self.apartments.bind(ps4_id, self._space_key(offer))

    def _record_grant(self, ps4_id, offer, source, granted_by=None):
        with self.store.atomic():
            if self._underlying_owned(ps4_id, offer):
                return False
            self._grant(ps4_id, offer)
            self.store.db.execute("INSERT OR IGNORE INTO shop_owned VALUES(?,?,?,?,?)",
                                  (ps4_id, offer["offer_id"], source, granted_by, time.time()))
        return True

    def _buy(self, request):
        fields, _ = self._profile(request, 6)
        supplied_crystals = _uint(fields[3], "displayed crystal price")
        supplied_np = _uint(fields[4], "displayed NP price")
        option = _uint(fields[5], "purchase option")
        with self.store.atomic():
            if self.store.current_guid(fields[1]) != fields[0]:
                raise ProtocolError("Purchase requires the current account session", 403)
            # Recheck ownership and the wallet after BEGIN IMMEDIATE.  This is
            # the serialization point for idempotency and balance authority.
            offer = self._client_offer(fields[2], lambda row: (row["crystals"], row["np"])
                                       == (supplied_crystals, supplied_np))
            if (supplied_crystals, supplied_np) != (offer["crystals"], offer["np"]):
                raise ProtocolError("Displayed price no longer matches the configured offer", 409)
            if option == 0:
                column, cost, failure = "crystals", offer["crystals"], "NOCRYSTALS"
            elif option == 1:
                column, cost, failure = "np", offer["np"], "NOXP"
            else:
                raise ProtocolError("Unsupported local purchase option")
            if self._underlying_owned(fields[1], offer):
                missing_data("purchase_already_owned", offer_id=offer["offer_id"])
                return "#".join(("true", fields[0], fields[1], "ISPURCHASED"))
            self._ensure_wallet(fields[1])
            wallet = self.wallet(fields[1])
            if wallet[column] < cost:
                missing_data("purchase_insufficient_funds", offer_id=offer["offer_id"], currency=column)
                return "#".join(("true", fields[0], fields[1], failure))
            updated = self.store.db.execute(
                f"UPDATE shop_wallets SET {column}={column}-? WHERE ps4_id=? AND {column}>=?",
                (cost, fields[1], cost))
            if updated.rowcount != 1:
                raise ProtocolError("Wallet changed during local purchase", 409)
            self._grant(fields[1], offer)
            self.store.db.execute("INSERT OR IGNORE INTO shop_owned VALUES(?,?,?,?,?)",
                                  (fields[1], offer["offer_id"], "buy", None, time.time()))
        return "#".join(("true", fields[0], fields[1], "OK"))

    def _gift(self, request):
        fields, sender = self._profile(request, 5)
        target_name = _text(fields[3], "gift target")
        supplied_crystals = _uint(fields[4], "displayed gift price")
        target = self._gift_target(sender["ps4_id"], target_name)
        prefix = ("true", fields[0], fields[1])
        with self.store.atomic():
            if self.store.current_guid(fields[1]) != fields[0]:
                raise ProtocolError("Gift requires the current account session", 403)
            # Friendship, ownership and balance are re-read under the same
            # write transaction as debit, grants and the idempotency claim.
            offer = self._client_offer(fields[2], lambda row: row["crystals"] == supplied_crystals)
            if supplied_crystals != offer["crystals"]:
                raise ProtocolError("Displayed gift price no longer matches the configured offer", 409)
            target = self._gift_target(sender["ps4_id"], target_name)
            if self._underlying_owned(target["ps4_id"], offer):
                missing_data("gift_already_owned", offer_id=offer["offer_id"])
                return "#".join((*prefix, "ISPURCHASED", target_name, offer["offer_id"]))
            self._ensure_wallet(fields[1])
            wallet = self.wallet(fields[1])
            if wallet["crystals"] < offer["crystals"]:
                missing_data("gift_insufficient_funds", offer_id=offer["offer_id"], currency="crystals")
                return "#".join((*prefix, "NOCRYSTALS", target_name, offer["offer_id"]))
            updated = self.store.db.execute(
                "UPDATE shop_wallets SET crystals=crystals-? WHERE ps4_id=? AND crystals>=?",
                (offer["crystals"], fields[1], offer["crystals"]))
            if updated.rowcount != 1:
                raise ProtocolError("Wallet changed during local gift", 409)
            with gift_recipient_grant(self.store, sender["ps4_id"], target["ps4_id"]):
                self._grant(target["ps4_id"], offer)
            self.store.db.execute("INSERT OR IGNORE INTO shop_owned VALUES(?,?,?,?,?)",
                                  (target["ps4_id"], offer["offer_id"], "gift", fields[1], time.time()))
            if self.notifications is not None:
                # The ownership key makes an ambiguous client retry resolve to
                # the same durable notice instead of creating a second gift.
                dedupe = "shop-gift:" + fields[1] + ":" + target["ps4_id"] + ":" + offer["offer_id"]
                self.notifications.enqueue_gift(target["ps4_id"], fields[1],
                                                offer["name"], dedupe)
        return "#".join((*prefix, "OK", target_name, offer["offer_id"]))

    def _gift_target(self, sender_ps4_id, target_name):
        matches = []
        for row in self.store.db.execute(
                "SELECT * FROM profiles WHERE username=? ORDER BY ps4_id", (target_name,)):
            if "friend" in self.store.relation_kinds(sender_ps4_id, target_name, row["platform"]):
                matches.append(dict(row))
        if not matches:
            raise ProtocolError("Gift target is not a local friend", 403)
        if len(matches) != 1:
            raise ProtocolError("Gift target name is ambiguous across local platforms", 409)
        target = matches[0]
        sender = self.store.db.execute("SELECT username,platform FROM profiles WHERE ps4_id=?",
                                       (sender_ps4_id,)).fetchone()
        # Authored preservation policy: either account blocking the other
        # prevents a gift, even if a friend row remains. No relation edits.
        if (sender is None
                or "block" in self.store.relation_kinds(sender_ps4_id, target["username"], target["platform"])
                or "block" in self.store.relation_kinds(target["ps4_id"], sender["username"], sender["platform"])):
            raise ProtocolError("Gift is blocked by an account", 403)
        return target

    def _is_purchased(self, request):
        fields, _ = self._profile(request, 3)
        owned = self._underlying_owned(fields[1], self._client_offer(fields[2]))
        return "#".join(("true", fields[0], fields[1], "True" if owned else "False"))

    def _sync(self, request):
        fields, profile = self._profile(request, 5)
        # Recovered request fields are receipt-like client observations.  They
        # are intentionally non-authoritative and cannot mint local currency.
        _text(fields[2], "crystal receipt ID")
        _text(fields[3], "crystal receipt date", allow_empty=True)
        _uint64(fields[4], "consumed crystal count")
        wallet = self.wallet(fields[1])
        return "#".join(("true", fields[0], fields[1], profile["username"],
                         str(wallet["np"]), str(wallet["crystals"])))
