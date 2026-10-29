"""Summarize the bounded static census without claiming complete networking."""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT=workspace()
OUT=ROOT/'results/protocol'
INV=OUT/'network-surface-inventory.json'
s=json.loads(INV.read_text(encoding='utf8'))
modern=json.loads((OUT/'http-task-command-candidates.json').read_text())
legacy=json.loads((OUT/'http-legacy-contracts.json').read_text())
modern_names={l['value'] for x in modern for l in x.get('referenced_literals',[])}
legacy_names={x['route'] for x in legacy['routes']}
known=modern_names|legacy_names
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ev(rva):
    p=ROOT/f'work/evidence/ghidra/functions/{rva:x}.c'
    return {'rva':hex(rva),'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p) if p.exists() else None,'status':'decompiled' if p.exists() else 'not_decompiled'}
additional=defaultdict(list)
for ref in s['generic_http_route_argument_calls']:
    if ref['route'] not in known:additional[ref['route']].append({'evidence_kind':'literal passed as route argument to a confirmed generic HTTP sender',**ref})
# These three complete body reads establish concrete formatted URL routes, not
# merely the presence of a path-shaped string in initialization metadata.
direct={0x4ec1c0:'AddToPoolFullGameServlet',0x4ecd80:'CheckIsAvailableToJoinFullGameServlet',0x46e360:'CheckIfSpaceStillExistServlet'}
for rva,route in direct.items():
    if route not in known:additional[route].append({'evidence_kind':'literal route template consumed by AES/URI-escaped UnityWebRequest.Get coroutine',**ev(rva)})

app=[c for c in s['direct_call_candidates'] if c['instruction_boundary_verified'] and c['application_caller']]
api_callers={cat:sorted({c['caller_rva'] for c in app if cat in c['categories']},key=lambda x:int(x,16)) for cat in ['unity_http','unity_www','dns','generic_http_sender','unity_video_url']}
missing={c['caller_rva']:c['caller_names'] for c in app if not c['pseudocode_path']}
families=defaultdict(lambda:{'classes':set(),'routes':set(),'sources':set()})
for route,refs in additional.items():
    for ref in refs:
        for n in ref.get('caller_names',[]):
            root=n.split('$$')[0].split('.<')[0]
            families[root]['classes'].add(root);families[root]['routes'].add(route);families[root]['sources'].add(ref['caller_rva'])
for root in families:
    families[root]={k:sorted(v) for k,v in families[root].items()}

surfaces=[
 {'name':'Modern HTTP task queue','known_scope':'40 native route identifiers; envelope/task response contracts are separate files.','contract':'http-task-command-candidates.json','status':'existing bounded audit; HTTP task count is not all HTTP'},
 {'name':'Login/Editor/Space direct HTTP','known_scope':f"{len(legacy_names)} route names in targeted legacy audit; overlaps modern tasks.",'contract':'http-legacy-contracts.json','status':'existing bounded audit'},
 {'name':'Additional generic cloud HTTP','known_scope':'Housing, shop/purchase/gift/crystals, full-game lobby/statistics/invites, gathering/events, archery/boat scoring, XP and maintenance clients. Native bodies encrypt request strings, URI-escape them, build GET ?data= URLs and consume AES response envelopes.','evidence':[ev(x) for x in [0x3bb330,0x3f5fa0,0x414760,0x447530,0x447a80,0x448270,0x4edf40,0x53ad70,0x577120,0x5a9100,0x6a0380]],'status':'transport bodies and concrete listed route arguments observed; per-route DTOs/field order/state effects remain separate unreviewed contracts'},
 {'name':'Dedicated full-game/space-liveness HTTP','known_scope':'AddToPoolFullGameServlet, CheckIsAvailableToJoinFullGameServlet and CheckIfSpaceStillExistServlet use dedicated coroutines rather than the generic HTTP sender.','evidence':[ev(x) for x in direct],'status':'concrete HTTP routes observed; pool/join/liveness rules and all payload fields not reconstructed by this audit'},
 {'name':'Shop image URL fetches','known_scope':'UIShopItemEntry.loadImage and wwwLoadImage construct Unity WWW from caller-provided URL; loadImage consumes downloaded texture.','evidence':[ev(0x4b2c40),ev(0x4b31b0)],'status':'dynamic fetch surface observed; URL origins, schemes, catalog links and cache policy not fully traced'},
 {'name':'Asset bundle URL/cache fetches','known_scope':'AssetBundleManager.LoadAssetBundleInternal concatenates static BaseDownloadingURL with assetBundleName; manifest uses new WWW, regular bundle uses WWW.LoadFromCacheOrDownload with manifest hash and CRC0. Existing/in-flight bundles are deduplicated.','evidence':[ev(0x647b50)],'status':'compiled fetch surface observed; actual configured URLs, local-vs-remote schemes and scene/bundle reachability are unproved'},
 {'name':'Cinema movie path','known_scope':'StreamingVideo.LaunchFilm concatenates Application.streamingAssetsPath + "/" + Platform.ToString() + "/f/" + filmName + ".mp4", assigns the result to one VideoPlayer and copies that URL to a second. Two verified direct set_url calls occur at RVAs0x55fd92/0x55fe34. The three path literals resolve at0x24e58e8,0x24e7c78,0x24e54a8.','evidence':[ev(0x55fa80)],'status':'native local StreamingAssets movie path established for this body; VideoPlayer API use here does not establish a remote movie service'},
 {'name':'Loadbalancer configuration and dynamic space hosts','known_scope':'loadbalancerConn getters return production104.196.60.146, development104.196.161.5 and port28000. PS4Info.Init assigns production getter result to field+0xf0. Space/host destinations may also arrive dynamically in backend responses.','evidence':[ev(0x12499a0),ev(0x12499d0),ev(0x1249a00),ev(0x42aa90)],'status':'constants and one native assignment observed; not proof of every active socket destination or restored loadbalancer policy'},
 {'name':'Local network-info DNS','known_scope':'PCNetInfoGetter.GetInternalIpAddress checks network availability, calls DNS.GetHostName and DNS.GetHostEntry for that local hostname, then selects an address. Process also has verified raw direct DNS calls, but its current Ghidra body removes blocks as possible PIC construction.','evidence':[ev(0x5e17e0),ev(0x5e1970)],'status':'local-host address discovery observed; do not treat these calls as evidence of another cloud endpoint'},
 {'name':'Mirror TCP/game replication and transport libraries','known_scope':'80 registered application TCP opcode handlers are covered by existing TCP/minigame audits; Mirror spawn/authority/SyncVar/command state and transport calls are additional layers. Telepathy/KCP/SimpleWeb code is compiled.','contracts':['tcp-dispatch-map.json','tcp-contracts.json','minigame-contracts.json','mirror-transport-schemas.json'],'status':'application opcode field recovery does not establish whole Mirror stream or server state parity'},
 {'name':'Steam networking/auth SDK wrappers','known_scope':'85 Steam networking wrapper RVAs and6 selected ticket/auth wrapper RVAs found in metadata. This bounded E8 scan found no direct application calls to those selected wrappers.','status':'SDK presence established; runtime use, inlined/PInvoke/indirect paths and Steam DLL internals remain outside this census'},
]
gaps=[
 'Additional routes listed here require their own request/response field, EntryData/JSON, success/error and side-effect contracts; observed generic AES framing does not supply their application semantics.',
 'Any bodies in missing_application_caller_pseudocode require native reads; compiled direct callsites already establish those API paths but not their complete payload or URL construction. The legacy avatar coroutine0x3b0040 reached a bounded30-second Ghidra decompile timeout; do not treat its missing pseudocode as absence of HTTP behavior.',
 'Asset bundle base URL setters, caller-provided image URLs, serialized asset/config URLs, dynamically returned server/space addresses and cinema/media URLs are not exhaustively traced.',
 'The raw direct-call census omits indirect virtual/interface/function-pointer calls, import calls and native UnityPlayer/Steam library internals. A zero direct call count cannot prove an API is unused.',
 'Several Ghidra constructor/Process bodies remove blocks after possible-PIC warnings. Endpoint literals referenced there do not prove URL branch selection; raw instruction review is needed before adopting constructor control flow.',
 'Original authentication/ownership binding, persistence, recipient policies, pricing/purchases, event progression, minigame adjudication and authoritative Mirror state are not recoverable merely by counting client handlers.',
]
data={
 'format_version':1,'scope':'Independent static network-surface coverage audit; this is an inventory and gap map, not a claim of complete reverse engineering.',
 'all_networking_parity_proven':False,'runtime_or_connection_tests_performed':False,
 'sources':[{'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p)} for p in [INV,OUT/'http-task-command-candidates.json',OUT/'http-legacy-contracts.json']],
 'coverage':{'modern_task_route_names':len(modern_names),'targeted_legacy_route_names':len(legacy_names),'known_route_union':len(known),'additional_concrete_route_names':len(additional),'minimum_combined_compiled_route_names':len(known|set(additional)),'implemented_backend_route_count':None,'application_unity_http_caller_bodies':len(api_callers['unity_http']),'application_www_caller_bodies':len(api_callers['unity_www']),'application_dns_caller_bodies':len(api_callers['dns']),'application_video_url_caller_bodies':len(api_callers['unity_video_url']),'application_generic_http_sender_callers':len(api_callers['generic_http_sender']),'route_literal_candidates_in_inventory':len(s['route_literals']),'endpoint_literal_candidates_in_inventory':len(s['endpoint_literals']),'missing_application_caller_bodies':len(missing),'note':'Route names overlap across code paths; counts are compiled client surface, not active endpoints, working features, implemented backend route count or server parity.'},
 'surfaces':surfaces,'additional_concrete_routes':[{'route':r,'evidence':refs,'payload_state_contract_status':'unreviewed in this surface audit'} for r,refs in sorted(additional.items())],
 'additional_route_families':dict(families),'missing_application_caller_pseudocode':[{'rva':r,'names':n} for r,n in missing.items()],
 'other_path_candidates':[{'route':'SavePresetServlet','reason':'Path-template literal appears in editor save bodies alongside N2SavePreset and possible-PIC warnings. This audit does not promote literal occurrence to an additional active route without control/data-flow confirmation.'}],
 'unreviewed_paths':gaps,'limitations':s['limitations'],
}
(OUT/'network-surface-findings.json').write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
lines=['# Network surface coverage audit','',f"The existing 40 HTTP task routes and 45 targeted legacy routes cover {len(known)} distinct names. This audit confirms **{len(additional)} additional compiled route names**, giving a minimum of **{len(known|set(additional))}** across these bounded audits. This count describes compiled client routes, not implemented backend routes or original server parity.",'','No game/server was launched and no network connection test was made. The inventory is derived from source-hashed metadata, native artifacts and bounded direct-call decoding.','',f"The census found {len(api_callers['unity_http'])} application UnityWebRequest caller bodies, {len(api_callers['unity_www'])} WWW/content caller bodies, {len(api_callers['dns'])} local DNS caller bodies and {len(api_callers['unity_video_url'])} video URL caller body. SDK API presence alone is not evidence of application runtime use.",'','## Additional surfaces','', '| Surface | Concrete observation | Review status |','|---|---|---|']
for item in surfaces:lines.append('| '+item['name']+' | '+item['known_scope']+' | '+item['status']+' |')
lines+=['','## Additional concrete routes','','All names below have literal route arguments passed to a confirmed generic HTTP sender, or a dedicated coroutine that consumes the URL template. Their full payload/state contracts remain unreviewed in this inventory.','']
for root,item in families.items():lines+=['`'+root+'`: '+', '.join('`'+r+'`' for r in item['routes'])+'.','']
family_routes={r for family in families.values() for r in family['routes']}
for route in sorted(set(additional)-family_routes):lines.append('- `'+route+'` (dedicated HTTP coroutine).')
lines+=['','## Remaining review boundaries','']
for gap in gaps:lines.append('- '+gap)
lines+=['',f"There are {len(missing)} verified application caller bodies still missing pseudocode in this snapshot. Their exact RVAs/names, every direct callsite, endpoint and route literal reference, and artifact hashes are in the JSON files.",'','Framework XML namespace URLs and SDK strings are retained as candidates, not classified as game backend endpoints. HTTP base literals include production App Engine and localhost; Ghidra constructor warnings prevent assuming every URL selection branch from pseudocode alone.','']
(OUT/'network-surface-findings.md').write_text('\n'.join(lines),encoding='utf8')
print(json.dumps(data['coverage'],indent=2))
