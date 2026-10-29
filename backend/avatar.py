"""Validation and explicitly reconstructed neutral avatar fixtures."""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from avatar_entry_codec import build_id_assets_tablenames, decode_flat_preset

from wire import ProtocolError


def schema_fields(protocol_dir, gender):
    data = json.loads((protocol_dir / "bootstrap-response-contracts.json").read_text(encoding="utf-8"))
    name = "JsonClasses.Preset" + ("Male" if gender == "MALE" else "Female") + "Json"
    return next(x for x in data["json_and_enum_declarations"] if x["name"] == name)["fields"]


def validate_preset(protocol_dir, preset, gender):
    if gender not in ("MALE", "FEMALE") or not isinstance(preset, dict):
        raise ProtocolError("Invalid preset type")
    fields = schema_fields(protocol_dir, gender)
    if set(preset) != {x["name"] for x in fields}:
        raise ProtocolError("Preset does not contain every recovered field exactly once")
    for field in fields:
        value = preset[field["name"]]
        kind = field["type_and_modifiers"].removeprefix("public ")
        if kind == "string":
            if value is not None and not isinstance(value, str):
                raise ProtocolError("Non-string preset field " + field["name"])
        elif kind == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ProtocolError("Non-finite/invalid preset field " + field["name"])
        else:
            raise ProtocolError("Unreconstructed preset field type " + kind, 501)
    return preset


def neutral(protocol_dir, account_id, gender, name="Default"):
    if gender not in ("MALE", "FEMALE"):
        raise ProtocolError("Unsupported avatar gender")
    preset = json.loads((protocol_dir / ("avatar-neutral-" + gender.lower() + ".json")).read_text(encoding="utf-8"))
    preset["iduser"] = account_id
    preset["idpreset"] = "local-neutral-" + gender.lower()
    preset["presetname"] = name
    validate_preset(protocol_dir, preset, gender)
    defaults = json.loads((protocol_dir / "avatar-default-catalog.json").read_text(encoding="utf-8"))["defaults"][gender]["items"]
    assets = {"data": "!".join([x["item_id"] for x in defaults] + [x["category"] for x in defaults])}
    position = {"GUID": "", "PS4ID": account_id, "lastPosition_x": 0.0,
                "lastPosition_y": 0.0, "lastPosition_z": 0.0}
    return preset, assets, position


def decode_save(protocol_dir, text, gender):
    data = json.loads((protocol_dir / "bootstrap-response-contracts.json").read_text(encoding="utf-8"))
    try:
        preset = decode_flat_preset(text, gender, data["json_and_enum_declarations"])["preset"]
        validate_preset(protocol_dir, preset, gender)
        catalog = json.loads((protocol_dir / "avatar-asset-catalog.json").read_text(encoding="utf-8"))
        assets = build_id_assets_tablenames(preset, gender, catalog)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ProtocolError("Malformed or unsupported serialized avatar preset") from exc
    return preset, assets
