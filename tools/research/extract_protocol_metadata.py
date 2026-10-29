"""Extract build-local protocol declarations from Il2CppDumper outputs.

This does not reconstruct implementation bodies or assert a wire encoding.
Run: python extract_protocol_metadata.py --dump PATH --script PATH --strings PATH --out DIR
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import hashlib
import json
import re
from pathlib import Path


def save(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_hash(text: str) -> int:
    result = 23
    encoded = text.encode("utf-16-le")
    for i in range(0, len(encoded), 2):
        result = (result * 31 + int.from_bytes(encoded[i:i + 2], "little")) & 0xFFFFFFFF
    return result


def parse_types(text: str):
    starts = list(re.finditer(r"^// Namespace: (.*)\r?\n", text, re.M))
    out = []
    source_line = text.count("\n", 0, starts[0].start()) + 1 if starts else 1
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        block = text[match.start():end]
        block_source_line = source_line
        source_line += block.count("\n")
        header = re.search(r"^(?P<decl>(?:public|private|internal|protected)[^\n]*?\b(?P<kind>class|struct|enum|interface) (?P<name>.+?)) // TypeDefIndex: (?P<id>\d+)\r?$", block, re.M)
        if not header:
            continue
        namebase = header.group("name").split(" : ", 1)
        name = namebase[0]
        namespace = match.group(1).strip()
        fields_part = block.split("// Fields", 1)[1].split("// Properties", 1)[0].split("// Methods", 1)[0] if "// Fields" in block else ""
        fields = []
        for line in fields_part.splitlines():
            line = line.strip()
            if not line or line.startswith("[") or line.startswith("//"):
                continue
            if ";" not in line:
                continue
            raw = line.split(";", 1)[0]
            lhs, *value = raw.split(" = ", 1)
            tokens = lhs.rsplit(" ", 1)
            field = {"declaration": raw + ";", "name": tokens[-1], "type_and_modifiers": tokens[0]}
            offset = re.search(r"// (0x[0-9A-Fa-f]+)", line)
            if offset:
                field["managed_layout_offset"] = offset.group(1)
            if value:
                field["constant_literal"] = value[0]
                if re.fullmatch(r"-?\d+", value[0]):
                    field["constant_value"] = int(value[0])
                elif value[0].startswith('"'):
                    try:
                        field["constant_value"] = json.loads(value[0])
                    except json.JSONDecodeError:
                        pass
            fields.append(field)
        methods = []
        for method in re.finditer(r"^\s*// RVA: (?P<rva>0x[0-9A-Fa-f]+|-1) Offset: (?P<offset>0x[0-9A-Fa-f]+|-1)(?: VA: (?P<va>0x[0-9A-Fa-f]+))?[^\n]*\n\s*(?P<decl>[^\n]+)", block, re.M):
            decl = method.group("decl").strip()
            if decl.startswith("//"):
                continue
            methods.append({k: v for k, v in method.groupdict().items() if v is not None})
        out.append({"name": name, "namespace": namespace, "full_name": f"{namespace}.{name}" if namespace else name, "kind": header.group("kind"), "type_def_index": int(header.group("id")), "declaration": header.group("decl"), "base_types": namebase[1] if len(namebase) > 1 else None, "source_line": block_source_line, "fields": fields, "methods": methods, "raw": block})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", type=Path, required=True)
    ap.add_argument("--script", type=Path, required=True)
    ap.add_argument("--strings", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    text = args.dump.read_text(encoding="utf-8-sig")
    types = parse_types(text)
    script = json.loads(args.script.read_text(encoding="utf-8-sig"))
    literals = json.loads(args.strings.read_text(encoding="utf-8-sig"))
    images = [(m.group(1), int(m.group(2))) for m in re.finditer(r"^// Image \d+: (.+?) - (\d+)\r?$", text, re.M)]
    for item in types:
        item["assembly"] = next((name for name, start in reversed(images) if start <= item["type_def_index"]), None)
    # DTO and constant containers are complete over this name boundary.
    manager = [x for x in types if x["name"] == "MANAGER_MSGS" or x["name"].startswith("MANAGER_MSGS.")]
    loadbalancer = [x for x in types if x["assembly"] == "loadbalancerConn.dll"]
    app = [x for x in types if (x["assembly"] in ("Assembly-CSharp.dll", "Assembly-CSharp-firstpass.dll") and re.search(r"^(?:NETGcloud|MANAGERLogin|LoginRemember|InitLoadAsign|IInstance|PresetGame|New$|AES$|EncryptDecryptNaeFiles$|NebulaMessage$|ManagerInstance$|NetworkClientManager$|NebulaPlayerSyncVars$|NebulaPlayerTransform(?:\.|$)|TCP|UDP|NET|NebulaNetwork)", x["name"])) or x["namespace"] == "TCPs" or x["namespace"].startswith("Assets.Scripts.TCPs")]
    mirror = [x for x in types if x["namespace"] in ("Mirror", "Telepathy", "kcp2k", "Mirror.SimpleWeb") and (x["kind"] in ("struct", "enum") or re.search(r"Transport|MessagePacking|NetworkMessages|NetworkWriter|NetworkReader|Batcher|Unbatcher|MultiplexTransport|TelepathyTransport|KcpTransport|^NetworkManager$|^NetworkServer$|^NetworkClient$|^NetworkBehaviour$|^NetworkIdentity$|^NetworkMessageDelegate$", x["name"]))]
    http = [x for x in types if x["namespace"].startswith("Assets.Scripts.HTTPs") or re.search(r"^(?:HTTPSender\.|HTTP\.HTTPErrorType|SteamManager(?:\.|$))", x["name"])]
    constants = [{"container": x["full_name"], "source_line": x["source_line"], "name": f["name"], "literal": f.get("constant_literal"), "value": f.get("constant_value")} for x in manager for f in x["fields"] if "constant_literal" in f]
    method_pattern = re.compile(r"NETGcloud|MANAGERLogin|ManagerInstance\$\$|NebulaMessage|NebulaPlayerSyncVars|NebulaPlayerTransform|Tcp|TCP|UDP|LoadBalancer|loadbalancer|Loadbalancer|MessagePacking|NetworkMessages|WriteString|ReadString|WriteNebula|ReadNebula|GeneratedNetworkCode.*(?:Message|Nebula)|TelepathyTransport|KcpTransport|Batcher|Unbatcher|^AES\$\$|EncryptDecryptNaeFiles|Assets.Scripts.HTTPs|SteamManager|^Mirror\.(?:NetworkManager|NetworkServer|NetworkClient|NetworkBehaviour|NetworkIdentity|Extensions|RemoteCalls.RemoteProcedureCalls)\$\$", re.I)
    methods = [{**m, "VA": hex(0x180000000 + m["Address"]), "RVA": hex(m["Address"])} for m in script["ScriptMethod"] if method_pattern.search(m["Name"])]
    selected_strings = [x for x in literals if re.search(r"^https?://[^\s]+$|^/(?:[A-Za-z][A-Za-z0-9_/-]*)$|[Ss]ervlet|Checking PC|ChannelGUID|loadbalanc|[Cc]hecker|[Nn]et[Ii]nfo|[Pp]layer[Pp]refs|appspot|^application/|^Content-Type$", x["value"])]
    def clean(items):
        return [{k: v for k, v in x.items() if k != "raw"} for x in items]
    save(args.out / "manager-message-schemas.json", clean(manager))
    save(args.out / "manager-message-constants.json", constants)
    save(args.out / "loadbalancer-schemas.json", clean(loadbalancer))
    save(args.out / "app-network-schemas.json", clean(app))
    save(args.out / "mirror-transport-schemas.json", clean(mirror))
    save(args.out / "http-task-schemas.json", clean(http))
    type_tcp = next(x for x in app if x["full_name"] == "TCPs.TypeTCP")
    save(args.out / "type-tcp-opcodes.json", [{"name": f["name"], "value": f["constant_value"]} for f in type_tcp["fields"] if "constant_value" in f])
    message_names = list(dict.fromkeys(x["full_name"] for x in app + mirror if x.get("base_types") == "NetworkMessage" and "." not in x["name"]))
    save(args.out / "mirror-message-id-candidates.json", [{"full_name": name, "stable_hash_32": stable_hash(name), "candidate_message_id": stable_hash(name) & 0xFFFF, "evidence_type": "derived from native stable hash loop plus matching upstream GetId source; runtime comparison pending"} for name in message_names])
    speed_signature = "System.Void Assets.Scripts.NebulaPlayers.NebulaPlayerSyncVars::SetSpeed(System.Single)"
    save(args.out / "rpc-hash-candidates.json", [{"method_signature": speed_signature, "stable_hash_32": stable_hash(speed_signature), "candidate_function_hash": stable_hash(speed_signature) & 0xFFFF, "registration_evidence": "NEB-STATIC-614850", "registration_requires_authority": True, "note": "RegisterCommand called with signature literal and r9b=1; functionHash candidate requires runtime or RegisterDelegate validation"}])
    save(args.out / "network-method-addresses.json", methods)
    save(args.out / "network-string-candidates.json", selected_strings)
    selected = {x["type_def_index"]:x for x in manager + loadbalancer + app + mirror + http}
    (args.out / "selected-declarations.cs").write_text("\n".join(x["raw"] for x in selected.values()), encoding="utf-8")
    manifest = {"source_game_assembly_sha256": "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac", "steam_appid": 919290, "steam_buildid": 11018722, "inputs": [{"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (args.dump, args.script, args.strings)], "counts": {"all_types_parsed": len(types), "manager_message_types": len(manager), "message_constants": len(constants), "loadbalancer_types": len(loadbalancer), "app_network_types": len(app), "mirror_transport_types": len(mirror), "method_address_candidates": len(methods), "string_candidates": len(selected_strings)}, "evidence_type": "static IL2CPP metadata reconstruction", "limitations": ["Class/member declarations do not establish runtime use or wire encoding.", "Managed field offsets are memory layout, not wire offsets.", "Each MANAGER_MSGS constant is scoped to its declaring type; numeric values repeat across subsystems.", "String candidates contain framework URLs and unused application literals; usage requires body/callsite confirmation.", "Il2CppDumper method stubs are not recovered C# bodies.", "Native VA assumes this artifact's image base 0x180000000; ASLR runtime addresses differ."]}
    save(args.out / "manifest.json", manifest)
    print(json.dumps(manifest["counts"], indent=2))


if __name__ == "__main__":
    main()
