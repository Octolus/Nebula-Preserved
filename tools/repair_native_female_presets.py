"""Review/apply explicitly pinned native female preset repairs; default is read-only.

Preparation does not mutate the DB. Applying requires the unchanged reviewed
plan hash and a new backup filename. It preserves selection, timestamps,
assets, position, every other preset field and every other row.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from avatar_native_save import normalize_original_native_save

ACCOUNT_SHA256 = ""
PINNED_BEFORE = {}  # Operator-supplied pins; no account/preset records shipped.
FIELDS = tuple("f_ch_" + bone + "_pectoral_jnt_" + operation + "_" + axis
               for bone, operation in (("r", "t"), ("l", "s")) for axis in "xyz")


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def readonly(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def select_account(connection):
    matches = [value for value, platform in connection.execute("SELECT ps4_id,platform FROM profiles")
               if platform == "StandaloneWindows" and value.isascii() and value.isdigit()
               and len(value) == 17 and digest(value) == ACCOUNT_SHA256]
    if len(matches) != 1:
        raise ValueError("Expected exactly one pinned native profile")
    return matches[0]


def prepare(connection):
    account = select_account(connection)
    changes = []
    for name, expected in PINNED_BEFORE.items():
        row = connection.execute("SELECT preset_json FROM presets WHERE ps4_id=? AND name=? AND gender='FEMALE'", (account, name)).fetchone()
        if row is None or digest(row[0]) != expected:
            raise ValueError("Pinned original preset changed or already repaired: " + name)
        before = json.loads(row[0])
        after = normalize_original_native_save(before, "FEMALE")
        serialized = json.dumps(after, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if {key for key in before if before[key] != after[key]} != set(FIELDS):
            raise ValueError("Repair must change precisely the six reviewed fields")
        changes.append({"name": name, "gender": "FEMALE", "before_json_sha256": expected,
                        "after_json_sha256": digest(serialized),
                        "before": {key: before[key] for key in FIELDS},
                        "after": {key: after[key] for key in FIELDS}})
    return {"format_version": 1, "policy": "original-build11018722-female-save-six-field-permutation-v1",
            "account_sha256": ACCOUNT_SHA256, "target_execution": False,
            "changes": changes, "preserve": ["updated_at", "preset_selection", "profiles", "assets_json", "position_json", "all_other_fields_and_rows"]}


def apply_reviewed(path, plan, expected_hash, backup):
    if digest(canonical(plan)) != expected_hash:
        raise ValueError("Reviewed plan hash does not match")
    backup = Path(backup).resolve()
    if backup == Path(path).resolve() or backup.exists():
        raise ValueError("Backup must be a new, distinct filename")
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if prepare(connection) != plan:
            raise ValueError("Current DB differs from reviewed plan")
        # The reserved lock prevents other writers while the second connection
        # snapshots the original committed state, including any WAL content.
        with backup.open("xb"):
            pass
        source = readonly(path)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        account = select_account(connection)
        for change in plan["changes"]:
            before = connection.execute("SELECT preset_json FROM presets WHERE ps4_id=? AND name=? AND gender='FEMALE'", (account, change["name"])).fetchone()[0]
            after = normalize_original_native_save(json.loads(before), "FEMALE")
            serialized = json.dumps(after, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if digest(serialized) != change["after_json_sha256"]:
                raise ValueError("Post-repair digest mismatch")
            cursor = connection.execute("UPDATE presets SET preset_json=? WHERE ps4_id=? AND name=? AND gender='FEMALE' AND preset_json=?", (serialized, account, change["name"], before))
            if cursor.rowcount != 1:
                raise ValueError("Concurrent preset update detected")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    global ACCOUNT_SHA256, PINNED_BEFORE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pins", type=Path, required=True, help="JSON with account_sha256 and preset_before_sha256 mapping; no defaults")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--plan-out", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reviewed-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    pins = json.loads(args.pins.read_text(encoding='utf-8'))
    ACCOUNT_SHA256 = pins['account_sha256']
    PINNED_BEFORE = pins['preset_before_sha256']
    if not isinstance(ACCOUNT_SHA256, str) or len(ACCOUNT_SHA256) != 64 or not PINNED_BEFORE or any(len(value) != 64 for value in PINNED_BEFORE.values()):
        parser.error('Explicit nonempty SHA256 pins required')
    if args.apply:
        if not all((args.reviewed_plan, args.expected_plan_sha256, args.backup)) or args.plan_out:
            parser.error("--apply requires --reviewed-plan, --expected-plan-sha256 and --backup; no --plan-out")
        plan = json.loads(args.reviewed_plan.read_text(encoding="utf-8"))
        apply_reviewed(args.db, plan, args.expected_plan_sha256, args.backup)
        print(json.dumps({"applied": True, "presets": list(PINNED_BEFORE), "backup": str(args.backup)}))
        return
    if any((args.reviewed_plan, args.expected_plan_sha256, args.backup)):
        parser.error("Apply-only arguments require --apply")
    connection = readonly(args.db)
    try:
        plan = prepare(connection)
    finally:
        connection.close()
    if args.plan_out:
        with args.plan_out.open("x", encoding="utf-8") as output:
            output.write(json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({"applied": False, "plan_sha256": digest(canonical(plan)), "plan": plan}, indent=2))


if __name__ == "__main__":
    main()

