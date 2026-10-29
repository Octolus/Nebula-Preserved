"""Static source-vs-native shop audit. Never starts or connects to a runtime."""

from _research_paths import workspace, output_root, game_path
import argparse
import hashlib
import json
from pathlib import Path


ROOT = output_root()
WORKSPACE = workspace()
NATIVE = WORKSPACE / "work" / "evidence" / "ghidra" / "functions"
SOURCE = ROOT / "backend" / "shop.py"
DUMP = WORKSPACE / "work" / "decompiled" / "dump.cs"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(text, fragments, label):
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise RuntimeError(f"Evidence drift in {label}: missing {missing}")


def audit():
    source = SOURCE.read_text(encoding="utf-8")
    dump = DUMP.read_text(encoding="utf-8")
    bodies = {rva: (NATIVE / (rva + ".c")).read_text(encoding="utf-8") for rva in (
        "40bc30", "410d10", "410a50", "40e900", "40f230", "40fbb0",
        "40d630", "4aa380", "4a7f90", "4b8500", "4b7700", "413f20",
        "448fc0", "440cb0", "4b7670", "4b75e0", "4ab9c0", "4a8ae0",
        "4a90e0", "4a9790", "4ad0a0", "4adc20", "4acda0", "4acf20",
        "4acfe0",
    )}
    require(bodies["40bc30"], ("iVar6 = iVar6 / 2", "uVar13 = uVar13 + 2",
                                "System_Boolean__Parse"), "GetGenderData callback")
    require(dump, ("public Text name; // 0x38", "public Text np; // 0x40",
                   "public Text crystals; // 0x48"), "ShopManager field layout")
    require(bodies["410d10"], ("param_2 + 0x38", "param_2 + 0x40", "param_2 + 0x48"),
            "ShopInfo callback")
    require(bodies["410a50"], ("param_2 + 0x38", "param_2 + 0x40", "param_2 + 0x48"),
            "Sync callback")
    require(bodies["4aa380"], ("EntryBase__setThumbnail__4a7f90(param_1,param_2[5],param_2[3]",
                                "*(longlong *)(param_1 + 0x90) = param_2[8]",
                                "*(longlong *)(param_1 + 0x98) = param_2[9]"),
            "ItemData consumer")
    require(bodies["4a7f90"], ("System_String__Contains", "System_String__Substring",
                                "_COMPANIONS", "_LOCOMOTIONS", "_Housing"),
            "thumbnail consumer")
    require(bodies["40e900"], ("System_Int32__Parse", "EntryData__Deserialize",
                                "uVar10 = uVar10 + 1"), "bundle callback")
    require(bodies["40f230"], ("uStack_28 = 0", "uStack_10 = 1", "uStack_10 = 2"),
            "buy status callback")
    require(bodies["40fbb0"], ("uStack_28 = 0", "uStack_10 = 1", "uStack_10 = 3"),
            "gift status callback")

    findings = [
        {
            "id": "SHOP-SP-001", "severity": "critical", "state": "fixed",
            "subject": "GetGenderData nonempty response layout",
            "native_fact": "field 3 is the number of following scalar tokens; client divides it by 2 and consumes genderID,Boolean pairs",
            "implementation": "_genders emits the exact flat scalar pair layout",
            "fix": "emit true#guid#ps4_id#(2*N)#genderID#True...; keep empty form count 0",
            "source_match": "str(len(values)), *values" in source,
            "evidence": ["0x40bc30"],
        },
        {
            "id": "SHOP-SP-002", "severity": "critical", "state": "fixed",
            "subject": "ShopInfo display field order",
            "native_fact": "fields 3,4,5 populate ShopManager.name,np,crystals at offsets 0x38,0x40,0x48",
            "implementation": "returns authenticated profile username, NP, crystals",
            "fix": "return profile username, local NP, local crystals; remove level from the wire reply",
            "source_match": "profile[\"username\"],\n                         str(wallet[\"np\"]), str(wallet[\"crystals\"])" in source,
            "evidence": ["0x410d10", "dump.cs ShopManager"],
        },
        {
            "id": "SHOP-SP-003", "severity": "critical", "state": "fixed",
            "subject": "SyncCrystals display field order",
            "native_fact": "the same three offsets populate name,np,crystals",
            "implementation": "returns authenticated profile username, NP, crystals and accepts native Int64 consumedCount",
            "fix": "return profile username, local NP, local crystals; client receipt fields remain non-authoritative",
            "source_match": "def _sync" in source and "_uint64(fields[4]" in source,
            "evidence": ["0x410a50", "dump.cs ShopManager"],
        },
        {
            "id": "SHOP-SP-004", "severity": "high", "state": "fixed",
            "subject": "ItemData.imagePath",
            "native_fact": "EntryItem passes imagePath to a loader that classifies known path segments, removes a four-character extension, and may take the final 41 characters",
            "implementation": "non-bundle thumbnails derive from validated shipped manifests; bundles require a compatible explicit path",
            "fix": "derive and validate a compatible shipped thumbnail path; never invent or accept an unverified arbitrary path",
            "source_match": "derived_image = self._thumbnail" in source,
            "evidence": ["0x4aa380", "0x4a7f90", "0x413f20"],
        },
        {
            "id": "SHOP-SP-005", "severity": "info", "state": "match",
            "subject": "TypeShop enum",
            "native_fact": "CLOTHING=0, COMPANIONS=1, HOUSING=2, LOCOMOTIONS=3",
            "implementation": "shop type is restricted to 0 through 3",
            "source_match": "TYPE_SHOPS = range(4)" in source,
            "evidence": ["dump.cs ShopNETGcloud.TypeShop"],
        },
        {
            "id": "SHOP-SP-006", "severity": "info", "state": "match",
            "subject": "Bundle list framing",
            "native_fact": "field 3 is ItemData entry count and each entry occupies one serialized EntryData token",
            "implementation": "_bundle uses _list with ItemData and configured child order",
            "source_match": "return self._list(fields[0], fields[1], rows, ITEM_DATA)" in source,
            "evidence": ["0x40e900"],
        },
        {
            "id": "SHOP-SP-007", "severity": "medium", "state": "compatibility_note",
            "subject": "purchase statuses",
            "native_fact": "buy explicitly handles enum values 0/1/2 (OK/NOCRYSTALS/NOXP); gift handles 0/1/3 and requires six fields; buy does not present a dedicated ISPURCHASED branch",
            "implementation": "uses exact enum strings; idempotent buy returns ISPURCHASED and gift includes target plus a sixth compatibility field",
            "fix": "retain exact strings; test the ignored buy ISPURCHASED path separately from success UI",
            "source_match": all(token in source for token in ("OK", "NOCRYSTALS", "NOXP", "ISPURCHASED")),
            "evidence": ["0x40f230", "0x40fbb0"],
        },
        {
            "id": "SHOP-SP-008", "severity": "high", "state": "fixed",
            "subject": "gift target identifier",
            "native_fact": "FriendEntry.OnClick copies displayed friend name into giftNameFriendTarget; OnClickGift sends only that string",
            "implementation": "resolves an exact displayed username across local platforms and requires one unambiguous friend relation",
            "fix": "retain ambiguity rejection because the wire carries no platform discriminator",
            "source_match": "def _gift_target" in source,
            "evidence": ["0x4ab9c0", "0x4b7700"],
        },
        {
            "id": "SHOP-SP-009", "severity": "critical", "state": "fixed",
            "subject": "gender IDs and symbolic fields",
            "native_fact": "EntryItem compares ItemData.gender with TypeGender.ToString; selected IDs 0/1 parse TypeData while 2/3/5/6 parse ItemData directly",
            "implementation": "wardrobe items emit MALE/FEMALE and GetShopTypeData selects the native DTO by selected ID",
            "fix": "keep ID 4 empty because its native callback branch does not deserialize rows",
            "source_match": "DIRECT_ITEM_GENDERS = (2, 3, 5, 6)" in source,
            "evidence": ["0x40d630", "0x4a9790", "0x4ad0a0"],
        },
    ]
    files = {str(path.relative_to(WORKSPACE)).replace("\\", "/"): sha256(path)
             for path in [SOURCE, DUMP, *[NATIVE / (rva + ".c") for rva in bodies]]}
    return {"format_version": 1, "method": "static source-vs-native comparison",
            "runtime_used": False, "findings": findings, "source_sha256": files}


def markdown(report):
    lines = ["# Shop second-pass audit", "",
             "Static comparison only: no game, UI, listener, connection, or process attachment.", ""]
    for finding in report["findings"]:
        lines += [f"## {finding['id']} — {finding['subject']}", "",
                  f"- Severity/state: `{finding['severity']}` / `{finding['state']}`",
                  f"- Native fact: {finding['native_fact']}",
                  f"- Current implementation: {finding['implementation']}",
                  f"- Action: {finding.get('fix', 'No change required.')}",
                  f"- Evidence: {', '.join(finding['evidence'])}", ""]
    lines += ["## Evidence hashes", ""]
    lines += [f"- `{path}`: `{digest}`" for path, digest in sorted(report["source_sha256"].items())]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write protocol JSON and Markdown")
    args = parser.parse_args()
    report = audit()
    if args.write:
        protocol = ROOT / "protocol"
        (protocol / "shop-second-pass.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        (protocol / "shop-second-pass.md").write_text(markdown(report), encoding="utf-8")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
