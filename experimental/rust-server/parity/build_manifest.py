"""Static inventory: no imports of reference code and no listeners."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re

from common import HERE, sha256, write_json
from cases import corpus
from policy_inventory import POLICIES

PRESERVATION = "mirror-server/UnityProject/Assets/Preservation/"


def stable_hash(text):
    value = 23
    encoded = text.encode("utf-16-le")
    for index in range(0, len(encoded), 2):
        value = (value * 31 + int.from_bytes(encoded[index:index + 2], "little")) & 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def source_ref(path, root, line=None, end=None):
    row = {"source": path.relative_to(root).as_posix(), "sha256": sha256(path)}
    if line:
        row.update(line=line, end_line=end or line)
    return row


def build(reference, research=None):
    service = reference / "backend/service.py"
    tree = ast.parse(service.read_text(encoding="utf-8-sig"))
    service_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Service")
    routes_node = next(node for node in service_class.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ROUTES" for t in node.targets))
    routes = sorted(ast.literal_eval(routes_node.value))
    if len(routes) != 92:
        raise ValueError("Reference Service.ROUTES changed; explicitly review the expected 92-route boundary")
    handlers, aliases, tests, methods = {}, {}, {}, {}
    for path in sorted((reference / "backend").glob("*.py")):
        parsed = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(parsed):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(path.name, node.name)] = source_ref(path, reference, node.lineno, node.end_lineno)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("route_"):
                handlers[node.name[6:]] = source_ref(path, reference, node.lineno, node.end_lineno)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id.startswith("route_"):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.startswith("route_"):
                        aliases[target.id[6:]] = node.value.id[6:]
    for alias, target in aliases.items():
        if target in handlers:
            handlers[alias] = {**handlers[target], "alias_of": target}
    shop_map = {"GetFeaturesServlet": "_features", "GetGenderDataShopServlet": "_genders",
                "GetItemAssetsDataServlet": "_items", "GetShopDataShopServlet": "_shops",
                "GetShopInfoPlayerShop": "_info", "GetShopTypeDataShopServlet": "_types",
                "NPShopBundleItemsServlet": "_bundle", "NPShopBuyItemServlet": "_buy",
                "NPShopGiftItemServlet": "_gift", "NPShopIsItemPurchasedServlet": "_is_purchased",
                "NPShopSyncCrystalsServlet": "_sync"}
    for route, method in shop_map.items():
        handlers[route] = {**methods[("shop.py", method)], "dispatch_method": method}
    for route in {"CheckIfSpaceStillExistServlet", "CheckOwnGenericReward", "CinemaInteractionNPServlet",
                  "GenericReward", "RewardClothServlet", "RewardConsumeServlet", "SKLPromoServlet",
                  "SKLPromoTriggerServlet", "checkRewardAvailableServlet"}:
        handlers[route] = {**methods[("rewards.py", "dispatch")], "dispatch_branch": route}
    for path in sorted((reference / "backend/tests").glob("test_*.py")):
        parsed = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(parsed):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                literals = {x.value for x in ast.walk(node) if isinstance(x, ast.Constant) and isinstance(x.value, str)}
                for route in set(routes).intersection(literals):
                    tests.setdefault(route, []).append({**source_ref(path, reference, node.lineno, node.end_lineno), "test": node.name, "status": "NOT_RUN_BY_THIS_HARNESS"})
    bootstrap = json.loads((reference / "protocol/bootstrap-response-contracts.json").read_text(encoding="utf-8"))
    original = {row["route"]: row for row in bootstrap["routes"]}
    protocol_docs = list(sorted((reference / "protocol").glob("*.json")))
    cases = corpus(routes)
    http = []
    for route in routes:
        evidence = []
        for path in protocol_docs:
            if route in path.read_text(encoding="utf-8"):
                evidence.append(source_ref(path, reference))
        row = {"id": "http:" + route, "route": route,
               "reference_handler": handlers[route],
               "reference_policy": "AUTHORED_PRESERVATION_NOT_ORIGINAL_SERVER",
               "client_evidence_documents": evidence,
               "static_reference_tests": tests.get(route, []),
               "planned_cases": [case["id"] for case in cases if case.get("route") == route],
               "required_dimensions": {name: "NOT_PROVEN" for name in ["success_reply", "malformed", "typed_durable_state", "account_isolation", "persistence", "failure_atomicity", "original_client_acceptance"]},
               "parity_status": "NOT_PROVEN"}
        if route in original:
            native = original[route]
            row["original_client_evidence"] = {"kind": "STATIC_CLIENT_CONSUMER_NOT_SERVER_BEHAVIOR",
                                               "document": source_ref(reference / "protocol/bootstrap-response-contracts.json", reference),
                                               "gameassembly_sha256": bootstrap["gameassembly_sha256"],
                                               "request_fields": native["request_fields"],
                                               "response_fields": native["response_fields"],
                                               "native_methods": [{key: method[key] for key in ("name", "kind", "rva", "bounded_native_sha256") if key in method} for method in native["methods"]]}
        else:
            row["original_client_evidence"] = {"kind": "CONSULT_ROUTE_SPECIFIC_STATIC_DOCUMENTS", "completeness": "NOT_PROVEN"}
        http.append(row)
    mirror_paths = [reference / (PRESERVATION + "NebulaInstanceServer.cs"), reference / "mirror-server/UnityProject/Assets/Mirror/Runtime/NetworkServer.cs"]
    mirror = []
    for full_name, payload, handler, auth in [
        ("Mirror.ReadyMessage", "empty", "NetworkServer.OnClientReadyMessage", True),
        ("Mirror.CommandMessage", "u32 netId,u8 componentIndex,i32 functionHash,bytes-and-size payload", "NebulaInstanceServer.Command (replaces default)", True),
        ("Mirror.NetworkPingMessage", "f64 clientTime", "NetworkTime.OnServerPing", False),
        ("Mirror.AddPlayerMessage", "empty", "NebulaInstanceServer.AddPlayer", True),
        ("NebulaMessage", "Mirror UTF8 string encrypted application payload", "NebulaInstanceServer.Message", False),
    ]:
        mirror.append({"id": "mirror:" + full_name, "full_name": full_name, "message_id_u16": stable_hash(full_name) & 0xFFFF,
                       "payload": payload, "handler": handler, "requires_mirror_authentication": auth,
                       "source_evidence": [source_ref(p, reference) for p in mirror_paths],
                       "parity_status": "NOT_PROVEN", "reason": "No reference Unity/Mirror runtime exercised by headless HTTP harness"})
    command_source = reference / (PRESERVATION + "NebulaMirrorCommands.cs")
    command_text = command_source.read_text(encoding="utf-8")
    commands = []
    native_commands = {}
    research_sources = []
    opcodes_native = []
    receive_dispatch = {}
    if research:
        for name in ("type-tcp-opcodes.json", "mirror-command-contracts.json", "tcp-dispatch-map.json", "tcp-contracts.json", "mirror-transport-schemas.json"):
            path = research / name
            if not path.is_file():
                continue
            research_sources.append({"source": "private-static-research/" + name, "sha256": sha256(path), "kind": "STATIC_ORIGINAL_CLIENT_EXTRACTION_METADATA"})
            doc = json.loads(path.read_text(encoding="utf-8"))
            if name == "type-tcp-opcodes.json":
                opcodes_native = doc
            if name == "tcp-dispatch-map.json":
                receive_dispatch = {row["opcode"]: row for row in doc["registrations"]}
            if name == "mirror-command-contracts.json":
                native_commands = {row["signature"]: row for row in doc["commands"]}
    for name, signature in re.findall(r'public const string (\w+)Signature = "([^"]+)";', command_text):
        native = native_commands.get(signature, {})
        commands.append({"id": "command:" + name, "name": name, "signature": signature,
                         "function_hash_signed_int32": stable_hash(signature),
                         "component_index": 1 if name == "Speed" else 0,
                         "authored_reference": source_ref(command_source, reference),
                         "original_client_evidence": {key: native[key] for key in ("rva", "payload", "channel", "requires_authority") if key in native},
                         "parity_status": "NOT_PROVEN"})
    instance_source = reference / (PRESERVATION + "NebulaInstanceServer.cs")
    instance_text = instance_source.read_text(encoding="utf-8")
    dispatch_body = instance_text[instance_text.index("private void Dispatch("):instance_text.index("private void Announce(")]
    core_cases = set(map(int, re.findall(r'case (\d+):', dispatch_body)))
    world_cases = {31, 44, 45, 46, 47, 93, 94}
    minigame_cases = {32, 33, 34, 35, 36, 37, 80, 81, 82, 84, 85, 86}
    opcode_rows = opcodes_native or [{"name": "UNRESOLVED_ENUM_NAME", "value": i} for i in range(97)]
    opcodes = []
    for row in opcode_rows + [{"name": "PreservationInteractionRegistryControl", "value": 97}]:
        value = row["value"]
        is_minigame = 32 <= value <= 43 or 48 <= value <= 91
        handling = "core" if value in core_cases else "world" if value in world_cases else "minigame" if value in minigame_cases else "control" if value == 97 else "no_c2s_transition"
        out = {"id": "application:" + str(value), "opcode": value, "name": row["name"], "minigame": is_minigame,
               "enum_origin": "AUTHORED_EXTENSION" if value == 97 else "STATIC_ORIGINAL_CLIENT_METADATA",
               "reference_dispatch": handling, "reference_source": source_ref(instance_source, reference),
               "parity_status": "NOT_PROVEN"}
        if value in receive_dispatch:
            original_row = receive_dispatch[value]
            out["original_client_receiver"] = {key: original_row[key] for key in ("handler", "process_rva", "direction_evidence") if key in original_row}
        if value in (45, 47, 93):
            out["authored_c2s_policy"] = "EXPLICITLY_REJECTED_CLIENTBOUND_ONLY"
        opcodes.append(out)
    groups = {
        "authority": ["ready/authenticated/spawned connection", "session and platform claim ownership", "netId and component command ownership", "historical session writer denial", "wardrobe interaction prohibition", "spoofed announcement and identity", "public account credential actor isolation", "TLS gateway binding and replay"],
        "world": ["scene inventory admission and unknown scenes", "seat occupancy conflict/release/disconnect", "semantic registry ready and mapping", "mixed scene unsupported subtype rejection", "generic state and ordered history replay", "boat grant/token/exit/duplicate/snapshot", "food/consumable receipt authority and replay", "chat range/block/silence/typing", "day cycle and animation parameters", "peer visibility, joins and disconnect cleanup"],
        "housing": ["explicit personal-space binding", "owner current allocation and presence", "visitor save denial", "canonical grants and placement limits", "original two sparse parts atomic commit", "reversed parts pending HTTP acknowledgement", "duplicates/conflicts/expiry and rollback", "partial save survives restart", "whole layout and entitlement persistence", "multiple connections/process contention"],
        "resources": ["canonical case-sensitive kind/item catalog", "zero default grants and empty DTO", "per-account grant isolation", "idempotent grant/regrant metadata", "durable selection current session/instance authority", "request/ack commit then broadcast", "revocation and stale snapshots", "restart/reconnect restoration and peer appearance"],
    }
    behavior_sources = {
        "authority": ["backend/public_access.py", "backend/remote_gateway.py", "backend/service.py", "backend/state.py", PRESERVATION + "NebulaInstanceServer.cs"],
        "world": [PRESERVATION + name for name in ["NebulaInstanceServer.cs", "NebulaWorldState.cs", "NebulaInteractionRegistry.cs", "NebulaSocialState.cs"]] + ["backend/consumables.py"],
        "housing": ["backend/housing.py", "backend/housing_atomic.py", "backend/service.py", "protocol/housing-placement-contracts.json", "protocol/housing-interaction-manifest.json"],
        "resources": ["backend/resources.py", "backend/resource_selection.py", "protocol/resource-entitlements.json", PRESERVATION + "NebulaResourceSelections.cs", PRESERVATION + "NebulaInstanceAccounts.cs"],
    }
    behavior = [{"id": group + ":" + str(index + 1), "area": group, "contract": text,
                 "reference_policy_kind": "AUTHORED_PRESERVATION_VALIDATION_AND_STATE_TRANSITIONS",
                 "evidence_sources": [source_ref(reference / source, reference) for source in behavior_sources[group]],
                 "required_test_dimensions": ["valid_transition", "malformed_edge", "authority_isolation", "restart_or_disconnect", "failure_rollback"],
                 "original_server_policy": "NOT_PROVEN", "parity_status": "NOT_PROVEN"}
                for group, names in groups.items() for index, text in enumerate(names)]
    sources = []
    paths = list((reference / "backend").glob("*.py")) + list((reference / "backend/tests").glob("test_*.py")) + protocol_docs + list((reference / (PRESERVATION)).glob("*.cs"))
    paths += [reference / "tools/avatar_entry_codec.py"]
    paths += [reference / "mirror-server/UnityProject/Assets/Mirror/Runtime" / name for name in ["Messages.cs", "MessagePacking.cs", "Extensions.cs", "NetworkServer.cs", "NetworkReaderExtensions.cs", "NetworkWriterExtensions.cs"]]
    for path in sorted(set(paths)):
        if path.is_file():
            sources.append(source_ref(path, reference))
    manifest = {"format_version": 1, "comparison_target": "AUTHORED_PRESERVATION_REFERENCE",
                "original_server_semantics": "NOT_PROVEN", "one_to_one_parity": "NOT_PROVEN",
                "reference_source_digest": __import__("hashlib").sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
                "reference_sources": sources, "private_static_research_sources": research_sources,
                "counts": {"http_routes": len(http), "bootstrap_native_route_contracts": len(original),
                           "mirror_inbound_registered": len(mirror), "mirror_command_hashes": len(commands),
                           "original_application_enum_values": len(opcode_rows), "authored_application_extensions": 1,
                           "nonminigame_application_entries_including_extension": sum(not row["minigame"] for row in opcodes),
                           "behavior_requirements": len(behavior), "planned_cases": len(cases)},
                "http_routes": http, "mirror_inbound": mirror,
                "mirror_unregistered_inbound": [{"name": "Mirror.EntityStateMessage", "policy": "NOT_REGISTERED_IN_CURRENT_REFERENCE; do not infer support from serializers", "parity_status": "NOT_PROVEN"}],
                "mirror_commands": commands, "application_opcodes": opcodes,
                "behavior_requirements": behavior,
                "completion_rule": "All listed non-minigame success, edge, authority, isolation, persistence, failure and original-client dimensions need tested evidence; codec or route framing passes cannot promote another contract."}
    write_json(HERE / "coverage-manifest.json", manifest)
    write_json(HERE / "case-corpus.json", cases)
    policy_document = {"format_version": 1, "reference_source_digest": manifest["reference_source_digest"],
                       "policy_origin": "AUTHORED_PRESERVATION_NOT_ORIGINAL_SERVER",
                       "policies": [{"id": area + ":" + key, "area": area, "policy": policy,
                                     "source_evidence": [source_ref(reference / source, reference) for source in paths],
                                     "original_server_semantics": "NOT_PROVEN", "parity_status": "NOT_PROVEN"}
                                    for area, entries in POLICIES.items() for key, policy, paths in entries]}
    write_json(HERE / "reference-policy-inventory.json", policy_document)
    normalization = {"format_version": 1, "http": [], "durable_state": []}
    # Each entry is tied to a known reference clock write, not a name wildcard.
    for table, column, source in [
        ("profiles", "created_at", "backend/state.py"), ("sessions", "created_at", "backend/state.py"),
        ("entitlements", "granted_at", "backend/state.py"), ("presets", "updated_at", "backend/state.py"),
        ("profile_state", "wardrobe_updated_at", "backend/service.py"),
        ("positions", "updated_at", "backend/service.py"), ("allocations", "allocated_at", "backend/service.py"),
    ]:
        normalization["durable_state"].append({"table": table, "column": column,
            "rule": "finite-positive-clock-to-sentinel-preserve-zero-null-and-numeric-type",
            "reason": "Reference writes wall-clock time; independently started probes have different clocks",
            "source": source_ref(reference / source, reference)})
    write_json(HERE / "normalization.json", normalization)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--research-protocol", type=Path)
    args = parser.parse_args()
    result = build(args.reference.resolve(), args.research_protocol.resolve() if args.research_protocol else None)
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
