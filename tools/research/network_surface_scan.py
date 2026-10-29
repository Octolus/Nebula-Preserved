"""Static native network-surface census; never launches or contacts a target.

Reproducible scope: IL2CPP metadata/literals, x64 direct-call candidates in PE
executable sections, bounded instruction verification, existing Ghidra files.
No inference of runtime reachability, virtual/import call completeness or parity.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path
import bisect
import hashlib
import importlib.util
import ipaddress
import json
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path
import capstone
import pefile

ROOT=workspace()
OUT=ROOT/'results/protocol'
FUN=ROOT/'work/evidence/ghidra/functions'
SCRIPT=ROOT/'work/decompiled/script.json'
DUMP=ROOT/'work/decompiled/dump.cs'
STRINGS=ROOT/'work/decompiled/stringliteral.json'
BIN=ROOT/'work/evidence/GameAssembly.dll'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,data): (OUT/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
meta=json.loads(SCRIPT.read_text(encoding='utf-8-sig'))
literals=json.loads(STRINGS.read_text(encoding='utf-8-sig'))
methods=meta['ScriptMethod']
names=defaultdict(list)
for m in methods: names[m['Address']].append(m['Name'])
starts=sorted(names)

spec=importlib.util.spec_from_file_location('protocol_parser',ROOT/'results/tools/extract_protocol_metadata.py')
parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
dump=DUMP.read_text(encoding='utf8')
types=parser.parse_types(dump)
images=[(m.group(1),int(m.group(2))) for m in re.finditer(r'^// Image \d+: (.+?) - (\d+)\r?$',dump,re.M)]
type_by_name={}
for t in types:
    t['assembly']=next((name for name,start in reversed(images) if start<=t['type_def_index']),None)
    type_by_name[t['full_name']]=t

def owner(method):
    cls=method.split('$$')[0]
    t=type_by_name.get(cls)
    # Generic instantiations may spell type parameters concretely rather than T.
    if not t and '<' in cls: t=type_by_name.get(cls.split('<')[0])
    return t.get('assembly') if t else None

# These wrappers are confirmed to construct an OnSend coroutine whose body
# reaches UnityWebRequest.Get, rather than selected only by its method name.
proven_http_sender_owners=set()
for m in methods:
    if '.<OnSend>' not in m['Name'] or not m['Name'].endswith('$$MoveNext'): continue
    p=FUN/(f"{m['Address']:x}.c")
    if p.exists() and 'UnityEngine_Networking_UnityWebRequest__Get__1d9b350' in p.read_text(encoding='utf8'):
        proven_http_sender_owners.add(m['Name'].split('.<')[0])

def categories(n):
    out=[]
    if n.startswith('UnityEngine.Networking.UnityWebRequest$$') and n.split('$$')[1] in ('Get','.ctor','SendWebRequest'): out.append('unity_http')
    if n.startswith('UnityEngine.WWW$$') and n.split('$$')[1] in ('.ctor','LoadFromCacheOrDownload'): out.append('unity_www')
    if n.startswith(('UnityEngine.Networking.UnityWebRequestAssetBundle$$','UnityEngine.Networking.UnityWebRequestTexture$$','UnityEngine.Networking.UnityWebRequestMultimedia$$')): out.append('unity_remote_content')
    if n.startswith('UnityEngine.Video.VideoPlayer$$set_url'): out.append('unity_video_url')
    if n.startswith(('System.Net.WebRequest$$','System.Net.HttpWebRequest$$')) and n.split('$$')[1] in ('Create','GetResponse','GetResponseAsync','BeginGetResponse','GetRequestStream','BeginGetRequestStream'): out.append('dotnet_http')
    if n.startswith(('System.Net.Sockets.Socket$$','System.Net.Sockets.TcpClient$$','System.Net.Sockets.UdpClient$$')) and re.match(r'(?:Connect|Send|Receive|Bind|Listen|Accept)',n.split('$$')[1]): out.append('dotnet_socket')
    if n.startswith('System.Net.Dns$$') and re.match(r'(?:GetHost|Resolve|BeginGetHost)',n.split('$$')[1]): out.append('dns')
    if n.startswith(('Steamworks.SteamNetworking$$','Steamworks.SteamNetworkingSockets$$','Steamworks.SteamNetworkingMessages$$','Steamworks.SteamNetworkingUtils$$')): out.append('steam_networking')
    if n.startswith('Steamworks.SteamUser$$') and re.match(r'(?:GetAuthSessionTicket|BeginAuthSession|EndAuthSession|CancelAuthTicket|RequestEncryptedAppTicket|GetEncryptedAppTicket)',n.split('$$')[1]): out.append('steam_auth')
    if n.startswith(('Telepathy.Client$$','kcp2k.KcpClient$$','Mirror.SimpleWeb.WebSocketClient')) and 'Connect' in n.split('$$')[1]: out.append('transport_connect')
    # Its parameterless .ctor shares a no-op RVA with hundreds of unrelated
    # constructors, so it must not become a network target.
    if n.startswith('loadbalancerConn$$get_'): out.append('loadbalancer_configuration')
    if n.split('$$')[0] in proven_http_sender_owners and n.split('$$')[-1]=='OnSend': out.append('generic_http_sender')
    return out

targets={}
for m in methods:
    cats=categories(m['Name'])
    if cats:
        item=targets.setdefault(m['Address'],{'rva':hex(m['Address']),'names':[],'categories':[]})
        item['names'].append(m['Name']);item['categories']=sorted(set(item['categories']+cats))

pe=pefile.PE(str(BIN));base=pe.OPTIONAL_HEADER.ImageBase
raw_calls=[]
for section in pe.sections:
    if not section.Characteristics & 0x20000000: continue
    raw=section.get_data();pos=raw.find(b'\xe8')
    while pos>=0:
        if pos+5<=len(raw):
            rva=section.VirtualAddress+pos
            target=rva+5+struct.unpack_from('<i',raw,pos+1)[0]
            if target in targets:
                idx=bisect.bisect_right(starts,rva)-1
                if idx>=0:
                    start=starts[idx]
                    raw_calls.append({'call_rva':hex(rva),'target_rva':hex(target),'caller_rva':hex(start),'caller_names':names[start],'caller_assemblies':sorted({owner(n) or 'unknown' for n in names[start]}),'categories':targets[target]['categories']})
        pos=raw.find(b'\xe8',pos+1)

# Confirm candidates are instruction boundaries by decoding from metadata entry.
# This is still bounded static decoding, not a complete control-flow proof.
cs=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
verified_calls={}
for start in {int(c['caller_rva'],16) for c in raw_calls}:
    idx=bisect.bisect_right(starts,start)
    end=min(starts[idx] if idx<len(starts) else start+65536,start+65536)
    try: buf=pe.get_data(start,end-start)
    except Exception: buf=b''
    good={}
    for insn in cs.disasm(buf,base+start):
        if insn.mnemonic=='call' and insn.bytes[0]==0xe8 and len(insn.bytes)==5:
            target=insn.address-base+5+struct.unpack_from('<i',insn.bytes,1)[0]
            good[insn.address-base]=target
    verified_calls[start]=good
for c in raw_calls:
    c['instruction_boundary_verified']=verified_calls[int(c['caller_rva'],16)].get(int(c['call_rva'],16))==int(c['target_rva'],16)
    p=FUN/(c['caller_rva'][2:]+'.c')
    c['pseudocode_path']=str(p.relative_to(ROOT)).replace('\\','/') if p.exists() else None
    c['pseudocode_sha256']=sha(p) if p.exists() else None
    c['application_caller']=bool({'Assembly-CSharp.dll','Assembly-CSharp-firstpass.dll'} & set(c['caller_assemblies']))
    c['target_names']=targets[int(c['target_rva'],16)]['names']

url_literals=[]
for x in literals:
    v=x['value'];kind=None
    if re.fullmatch(r'https?://[^\s]+',v): kind='url_literal'
    elif re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v): kind='email_literal'
    else:
        try: ipaddress.ip_address(v);kind='ip_literal'
        except ValueError: pass
    if kind: url_literals.append({**x,'kind':kind,'native_references':[]})

http_sender_owners={n.split('.<')[0] for c in raw_calls if c['instruction_boundary_verified'] and c['application_caller'] and 'unity_http' in c['categories'] for n in c['caller_names'] if '.<OnSend>' in n}
sender_rvas={m['Address']:m['Name'] for m in methods if m['Name'].split('$$')[0] in http_sender_owners and m['Name'].split('$$')[-1]=='OnSend'}
literal_lookup={int(x['address'],16):x for x in literals}
route_argument_calls=[]
route_argument_addresses=set()
for p in FUN.glob('*.c'):
    text=p.read_text(encoding='utf8')
    for match in re.finditer(r'\b(\w+__OnSend__([0-9a-f]+))\s*\(\s*[^,]+,\s*([A-Za-z_]\w*)\s*,',text):
        callee=int(match.group(2),16)
        addrmatch=re.search(r'_([0-9a-f]{7,8})$',match.group(3))
        if callee not in sender_rvas or not addrmatch: continue
        address=int(addrmatch.group(1),16)
        if address not in literal_lookup:continue
        route_argument_addresses.add(address)
        route_argument_calls.append({'route':literal_lookup[address]['value'],'literal_address':hex(address),'sender_rva':hex(callee),'sender_name':sender_rvas[callee],'caller_rva':'0x'+p.stem,'caller_names':names.get(int(p.stem,16),[]),'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p)})
route_literals=[{**x,'native_references':[],'role':'proven generic HTTP sender route argument' if int(x['address'],16) in route_argument_addresses else 'route-shaped literal candidate'} for x in literals if int(x['address'],16) in route_argument_addresses or 'Servlet' in x['value'] or re.fullmatch(r'(?:N2[A-Z]\w+|CheckOwnGenericReward|GenericReward)',x['value'])]
literal_by_address={int(x['address'],16):x for x in url_literals+route_literals}
native=[]
source_cache={}
for p in FUN.glob('*.c'):
    text=p.read_text(encoding='utf8');source_cache[p.stem]=text
    refs=set(int(x,16) for x in re.findall(r'_([0-9a-f]{7,8})\b',text)) & literal_by_address.keys()
    if refs:
        source={'rva':'0x'+p.stem,'metadata_names':names.get(int(p.stem,16),[]),'assemblies':sorted({owner(n) or 'unknown' for n in names.get(int(p.stem,16),[])}),'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p)}
        for addr in refs: literal_by_address[addr]['native_references'].append(source)
    if any(x in text for x in ['UnityEngine_Networking_UnityWebRequest__Get__','UnityEngine_WWW___ctor','System_Net_Sockets_','loadbalancerConn__get_']):
        native.append({'rva':'0x'+p.stem,'names':names.get(int(p.stem,16),[]),'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p)})

cloud=[]
for t in types:
    if t['assembly'] not in ('Assembly-CSharp.dll','Assembly-CSharp-firstpass.dll','loadbalancerConn.dll'):continue
    if not re.search(r'NETG[Cc]loud|loadbalancer|^GCloud|^Gcloud',t['full_name']): continue
    rv=[int(m['rva'],16) for m in t['methods'] if m['rva']!='-1']
    cloud.append({'name':t['full_name'],'assembly':t['assembly'],'type_def_index':t['type_def_index'],'metadata_sha256':hashlib.sha256(t['raw'].encode()).hexdigest(),'method_count':len(t['methods']),'unique_rvas':len(set(rv)),'decompiled_rvas':sum((FUN/(f'{r:x}.c')).exists() for r in set(rv)),'routes':sorted({l['value'] for l in route_literals for ref in l['native_references'] if any(n.startswith(t['full_name']+'$$') for n in ref['metadata_names'])})})

category_counts={cat:{'target_rvas':sum(cat in t['categories'] for t in targets.values()),'verified_direct_calls':sum(c['instruction_boundary_verified'] and cat in c['categories'] for c in raw_calls),'verified_application_direct_calls':sum(c['instruction_boundary_verified'] and c['application_caller'] and cat in c['categories'] for c in raw_calls)} for cat in sorted({cat for t in targets.values() for cat in t['categories']})}
report={'format_version':1,'scope':'Bounded static inventory of network API direct calls, endpoint/route literals and additional cloud-client classes in this client build. No runtime/connection tests.','all_networking_parity_proven':False,'sources':[{'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p)} for p in [BIN,SCRIPT,DUMP,STRINGS]],'image_base':hex(base),'limitations':['Raw E8 candidates are validated only by bounded sequential decoding from nearest preceding metadata method entry; alias names and incomplete functions remain possible.','Direct E8 census does not include indirect virtual/interface/function-pointer calls, import calls, dynamically constructed URLs, native UnityPlayer.dll or Steam DLL internals, or asset/config endpoints.','Compiled SDK networking wrappers do not prove the game uses those APIs. Lack of a direct E8 application caller does not prove absence of runtime use.','Literal references prove compiled occurrence, not reachable code or original remote availability. Native pseudocode may be incomplete/incorrect and is not original C#.','Counts for HTTP task routes, legacy routes, TCP handlers and other surfaces overlap and must not be added as independent endpoints.'],'api_category_counts':category_counts,'network_api_targets':sorted(targets.values(),key=lambda x:int(x['rva'],16)),'direct_call_candidates':raw_calls,'endpoint_literals':url_literals,'route_literals':route_literals,'generic_http_route_argument_calls':route_argument_calls,'additional_cloud_types':cloud,'native_network_body_inventory':native}
save('network-surface-inventory.json',report)
print(json.dumps({'category_counts':category_counts,'endpoint_literals':len(url_literals),'route_literals':len(route_literals),'cloud_types':len(cloud),'application_callers':len({c['caller_rva'] for c in raw_calls if c['instruction_boundary_verified'] and c['application_caller']})},indent=2))
