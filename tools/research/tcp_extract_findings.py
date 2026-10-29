"""Extract auditable TCP handler registration records from annotated native code."""

from _research_paths import workspace, output_root, game_path
import json
import re
from pathlib import Path

root = output_root() / "protocol"
data = json.loads((root / "tcp-handlers-native.json").read_text())
method = next(m for m in data["methods"] if "ManagerInstance$$SetTCPClient" in m["names"])
last_type = None
edx = None
rows = []
for i in method["instructions"]:
    if i["op"] == "mov" and i["args"].startswith("rcx, qword ptr [rip") and i["annotations"]:
        candidate = i["annotations"][0]
        if "Processors." in candidate and candidate.endswith("_TypeInfo"):
            last_type = candidate.removesuffix("_TypeInfo")
    if i["op"] == "xor" and i["args"] == "edx, edx":
        edx = 0
    match = re.fullmatch(r"edx, \[r9 \+ (0x[0-9a-f]+|\d+)\]", i["args"])
    if i["op"] == "lea" and match:
        edx = int(match[1], 0)
    match = re.fullmatch(r"edx, (0x[0-9a-f]+|\d+)", i["args"])
    if i["op"] == "mov" and match:
        edx = int(match[1], 0)
    if i["op"] == "call" and "TCPs.TCPClient$$RegisterHandler" in i["annotations"]:
        process = next((m for m in data["methods"] if last_type+"$$Process" in m["names"]), None)
        rows.append({"opcode":edx,"handler":last_type,"process_rva":process["rva"] if process else None,"registration_call_va":i["va"],"direction_evidence":"clientbound: registered in client receive dispatch table"})
dump = (workspace() / 'work/decompiled/dump.cs').read_text(encoding="utf-8-sig")
enum = dump.split("public enum TypeTCP //",1)[1].split("\n}",1)[0]
opcodes = [{"name":name,"opcode":int(value)} for name,value in re.findall(r"public const TypeTCP (\w+) = (\d+);",enum)]
for row in rows:
    row["enum_name"] = next(x["name"] for x in opcodes if x["opcode"]==row["opcode"])
report = {"evidence":"tcp-handlers-native.json ManagerInstance.SetTCPClient RVA 0x439f60","scope":"Direct allocation TypeInfo and immediate opcode arguments at every TCPClient.RegisterHandler call within this method; no runtime observation.","registrations":rows,"opcodes_without_client_handler":[x for x in opcodes if x["opcode"] not in {r["opcode"] for r in rows}],"unknown":"No client handler does not alone prove a serverbound opcode; confirm send construction before assigning direction."}
(root/"tcp-dispatch-map.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps({"registered":len(rows),"unregistered":len(report["opcodes_without_client_handler"])}))
for row in rows:
    print(row["opcode"],row["enum_name"],row["handler"],row["process_rva"])
print("Unregistered:", report["opcodes_without_client_handler"])
