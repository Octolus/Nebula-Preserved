"""Shop identities of the shipped personal spaces (apartments).

protocol/personal-space-shop.json maps each shipped apartment shop ID (the
``PersonalSpaces/<id>/`` thumbnail and screenshot resources) to its navigator
name. The client has no such table; the mapping was inferred from the shipped
images and scene bundles (see that file). Home has no shop ID: it is the native
default apartment. This module opens nothing but that JSON file.
"""
import json
from pathlib import Path
import re

SHOP_FILE = Path(__file__).resolve().parents[1] / "protocol" / "personal-space-shop.json"
SPACE_GENDER_ID = 4          # GenderWindow "Spaces" tab (EntryGender.OnClick switch case 4)
SPACE_TYPE_ID = "PERSON"     # typeID the client sends in GetItemAssetsData for that tab
SPACE_TABLENAME = "PERSON"   # ItemData.tablename; never a try-on table
# ItemData.gender for apartments. EntryItem.OnClick (0x4a9790) only starts the 3D
# try-on when this equals the avatar gender, so a non-avatar value keeps the
# native screenshot carousel instead. Authored compatibility value.
SPACE_ITEM_GENDER = "PersonalSpace"
_ID = re.compile(r"[A-Za-z0-9]{32}\Z")


def _load():
    document = json.loads(SHOP_FILE.read_text(encoding="utf-8"))
    if document.get("format_version") != 1 or not isinstance(document.get("spaces"), list):
        raise ValueError("Unsupported personal-space shop evidence")
    by_id, by_space = {}, {}
    for row in document["spaces"]:
        item_id, key = row.get("item_id"), row.get("logical_space_key")
        if (not isinstance(item_id, str) or not _ID.fullmatch(item_id) or not isinstance(key, str)
                or key == "Home" or item_id.lower() in {i.lower() for i in by_id} or key in by_space
                or row.get("thumbnail_path") != "PersonalSpaces/" + item_id + "/" + item_id + "Thumbnail.png"):
            raise ValueError("Invalid personal-space shop entry")
        by_id[item_id] = dict(row)
        by_space[key] = item_id
    return by_id, by_space


SHOP_SPACES, SHOP_ID_BY_SPACE = _load()
