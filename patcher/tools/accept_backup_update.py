"""Offline CLI acceptance on a NEW private fixture; never execute fixture game files.

Reads exact locally owned originals. Writes authored fake payloads and disposable
patched game copies outside originals/source/Steam. All clients must be closed.
"""
from pathlib import Path
import argparse,hashlib,json,os,shutil,struct,subprocess

BASE={
 'GameAssembly.dll':'c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac',
 'Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat':'c59807c2950c1051202ae7d96744d126be4c489c7719f7e2d8d207f8f75681c1',
 'Nebula Realms_Data/globalgamemanagers':'ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466',
 'Nebula Realms_Data/StreamingAssets/StandaloneWindows/s/charactereditor':'5d1713e79b4e5bab090a3d57eb4d4c4139999629bb4a2038412a6cb92d1b02e0'}
EXE='77bdecc37804194305c2402be5ac0851570f395bf9af3fb4ee03030c6d779d0d'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def require(ok,why):
 if not ok:raise AssertionError(why)
def write(path,raw):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
def main(a):
 originals=a.originals.resolve(strict=True);tool=a.patcher.resolve(strict=True);out=a.output.resolve()
 source=Path(__file__).resolve().parents[1]
 require(not out.exists()and not out.is_relative_to(originals)and not out.is_relative_to(source)and
   'steamapps'not in [p.lower()for p in out.parts],'NEW external private fixture outside originals/source/Steam required')
 original_pins={**BASE,'Nebula Realms.exe':EXE}
 for name,pin in original_pins.items():require(sha((originals/name).read_bytes())==pin,'Unsupported pristine input '+name)
 out.mkdir(parents=True);game=out/'fixture-game-DO-NOT-EXECUTE';game.mkdir();cases=[]
 for name in original_pins:write(game/name,(originals/name).read_bytes())
 def command(args,success=True,contains=None):
  proc=subprocess.run([str(tool),*args],capture_output=True,text=True,timeout=120)
  require((proc.returncode==0)==success,proc.stdout+proc.stderr)
  if contains:require(contains in proc.stdout+proc.stderr,'Expected diagnostic: '+contains+'; '+proc.stdout+proc.stderr)
  cases.append({'arguments':args,'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
  return proc
 editor=next(n for n in BASE if n.endswith('charactereditor'));view=out/'editor-view.PRIVATE'
 command(['bundle-view','--input',str(originals/editor),'--output',str(view)])
 views={name:(view.read_bytes()if name==editor else(originals/name).read_bytes())for name in BASE}
 bundles={}
 for profile in ('A','B'):
  folder=out/('fixture-bundle-'+profile);folder.mkdir();artifacts=[]
  for index,(name,original_pin)in enumerate(BASE.items()):
   common={'path':name,'original_sha256':original_pin,'accepted_existing':[],'payload':None,'payload_sha256':None,'payload_size':None,'source_view_sha256':None,'output_sha256':None}
   if name.endswith('global-metadata.dat'):common['operation']='metadata'
   else:
    data=views[name];extra=('NEBULA-OFFLINE-FIXTURE-'+profile).encode();target=data+extra
    delta=b'NBD1'+struct.pack('<IQ',2,len(target))+b'\0'+struct.pack('<QQ',0,len(data))+b'\1'+struct.pack('<Q',len(extra))+extra
    payload=f'payloads/core-{index}.nbd';write(folder/payload,delta)
    common.update(operation='unityfs_delta'if name==editor else'delta',payload=payload,payload_sha256=sha(delta),payload_size=len(delta),source_view_sha256=sha(data),output_sha256=sha(target))
   artifacts.append(common)
  for name in ('NebulaRegistryBridge.dll','NebulaAutomation.dll','NebulaPublicAccess.dll','steam_appid.txt'):
   raw=b'919290'if name=='steam_appid.txt'else('AUTHORED NONEXECUTABLE OFFLINE FIXTURE '+name+profile).encode()
   payload='payloads/'+name+'.fixture';write(folder/payload,raw)
   artifacts.append(dict(path=name,operation='owned_file',original_sha256=None,accepted_existing=[],payload=payload,payload_sha256=sha(raw),payload_size=len(raw),source_view_sha256=None,output_sha256=sha(raw)))
  manifest=dict(format='nebula-patch-v1',app_id='919290',build_id='11018722',status='provisional',review='Offline transaction fixture. Fake targets/helpers MUST NEVER be executed or distributed.',artifacts=artifacts)
  raw=json.dumps(manifest,indent=2).encode();write(folder/'manifest.json',raw);bundles[profile]=(folder,sha(raw))
 state=game/'.nebula-preservation';rp=state/'receipt.json'
 def snapshot():return {p.relative_to(game).as_posix():sha(p.read_bytes())for p in game.rglob('*')if p.is_file()}
 def receipt():return json.loads(rp.read_bytes())
 def patch(profile,endpoint,dry=False,explicit=False,success=True,contains=None):
  bundle,pin=bundles[profile];args=['patch','--game',str(game),'--bundle',str(bundle),'--manifest-sha256',pin,
   '--server',f'http://127.0.0.1:{endpoint}','--advertise-ip','127.0.0.1','--allow-provisional']
  if dry:args.append('--dry-run')
  if explicit:args+=['--originals',str(originals)]
  before=snapshot()if dry or not success else None
  command(args,success,contains)
  if before is not None:require(snapshot()==before,'Refused/dry-run operation changed fixture bytes')
  if success and not dry:
   for entry in receipt()['entries']:require(sha((game/entry['path']).read_bytes())==entry['after'],'Installed receipt mismatch')
 def restore_to(expected):
  command(['restore','--game',str(game)])
  require({name:sha((game/name).read_bytes())for name in BASE}==expected,'Restore did not recover exact preceding core state')
 # Real CLI: initial install -> endpoint repoint -> target/profile switch -> every prior state.
 patch('A',8080,dry=True);require(not state.exists(),'Initial dry-run created transaction state')
 patch('A',8080);first={name:sha((game/name).read_bytes())for name in BASE};r1=rp.read_bytes()
 patch('A',8081);second={name:sha((game/name).read_bytes())for name in BASE};require(first!=second,'Endpoint not repointed')
 patch('B',8082);third={name:sha((game/name).read_bytes())for name in BASE};require(second!=third,'Target/profile did not change')
 unchanged=rp.read_bytes();patch('B',8082,contains='Already installed');require(rp.read_bytes()==unchanged,'Idempotence rewrote receipt')
 restore_to(second);restore_to(first);restore_to(BASE);require(not rp.exists(),'Final restore left active receipt')
 for name in ('NebulaRegistryBridge.dll','NebulaAutomation.dll','NebulaPublicAccess.dll','steam_appid.txt'):require(not(game/name).exists(),'Helper not removed')
 # Every rejection below must occur before any staged/receipt/backup mutation.
 patch('A',8080);record=receipt();ga=next(e for e in record['entries']if e['path']=='GameAssembly.dll');backup=state/ga['backup'];raw=backup.read_bytes()
 backup.write_bytes(raw+b'tampered');patch('A',8081,dry=True,success=False,contains='Historical backup pin mismatch');backup.write_bytes(raw)
 saved=backup.with_name(backup.name+'.held');backup.rename(saved)
 patch('A',8081,dry=True,success=False);saved.rename(backup)
 stale=rp.read_bytes();record['entries'][-1]['after']=sha(b'stale receipt');rp.write_text(json.dumps(record),encoding='utf-8')
 patch('A',8081,dry=True,success=False,contains='Installed file changed since receipt');rp.write_bytes(stale)
 unbound=receipt();unbound['entries']=[e for e in unbound['entries']if e['path']!='GameAssembly.dll'];rp.write_text(json.dumps(unbound),encoding='utf-8')
 patch('A',8081,dry=True,success=False,contains='Active receipt is missing required source binding');rp.write_bytes(stale)
 helper=game/'NebulaAutomation.dll';good=helper.read_bytes();helper.write_bytes(b'edited-current')
 patch('A',8081,dry=True,success=False,contains='Installed file changed since receipt');helper.write_bytes(good)
 if os.name=='nt':
  link=state/'backups';parked=state/'backups-held';require(link.resolve().is_relative_to(out),'Backup path escaped fixture');link.rename(parked)
  proc=subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(parked)],capture_output=True,text=True)
  require(proc.returncode==0,proc.stdout+proc.stderr)
  try:
   require(link.is_junction()and link.resolve()==parked.resolve(),'Expected exact local junction')
   patch('A',8081,dry=True,success=False,contains='path rejected')
  finally:
   require(link.is_junction()and link.parent.resolve().is_relative_to(out),'Unsafe junction cleanup')
   os.rmdir(link);parked.rename(link)
 # Explicit originals retains precedence even if an old backup is damaged.
 backup.write_bytes(raw+b'bad-old-backup');patch('A',8081,explicit=True);restore_to(first);backup.write_bytes(raw)
 # A forged intermediate before-state must fail even when its own backup hash matches.
 patch('A',8081);saved_receipt=rp.read_bytes();record=receipt();entry=next(e for e in record['entries']if e['path']=='GameAssembly.dll')
 intermediate=state/entry['backup'];saved_backup=intermediate.read_bytes();intermediate.write_bytes(b'unreceipted');entry['before']=sha(b'unreceipted');rp.write_text(json.dumps(record),encoding='utf-8')
 patch('B',8082,dry=True,success=False,contains='Receipt history discontinuity')
 intermediate.write_bytes(saved_backup);rp.write_bytes(saved_receipt);restore_to(first);restore_to(BASE)
 for name,pin in original_pins.items():require(sha((originals/name).read_bytes())==pin,'Read-only Steam original changed')
 report={'format':'nebula-backup-update-cli-fixture-v1','patcher_sha256':sha(tool.read_bytes()),'cases':cases,'commands_passed':len(cases),
  'initial_patch_repoint_target_switch_three_restores_without_originals':True,'tampered_missing_redirected_backup_and_stale_current_receipt_rejected':True,
  'explicit_originals_precedence_preserved':True,'broken_lineage_rejected':True,'steam_originals_unchanged':True,
  'missing_active_source_binding_rejected':True,
  'fixture_final_state':'Exact pristine core and executable, project-owned fake helpers absent, backups retained privately',
  'game_executed':False,'server_contacted_or_executed':False,'live_client_modified':False,'fixture_game_files_must_never_be_executed':True}
 output=out/'acceptance-receipt.json';output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'receipt':str(output),'sha256':sha(output.read_bytes()),'commands_passed':len(cases)}))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('originals','patcher','output'):p.add_argument('--'+name,type=Path,required=True)
 main(p.parse_args())
