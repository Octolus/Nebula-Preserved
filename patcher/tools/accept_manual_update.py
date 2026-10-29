"""Disposable actual patch/update/restore acceptance for a reviewed manual overlay.
Never launches a game/server or writes any Steam/private-client source file.
"""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path
sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
def require(ok,msg):
 if not ok:raise RuntimeError(msg)
def main(a):
 root=Path(__file__).resolve().parents[1];out=a.output.resolve();require(root in out.parents and not out.exists(),'New fixture directory under patcher required')
 originals=a.originals.resolve();tool=a.patcher.resolve();bundle=a.bundle.resolve();prior=a.prior_bundle.resolve()
 require(sha(bundle/'manifest.json')==a.manifest_sha256,'Final manifest pin mismatch');require(sha(prior/'manifest.json')==a.prior_manifest_sha256,'Prior manifest pin mismatch')
 profile=json.loads(a.manual_profile.read_text());manifest=json.loads((bundle/'manifest.json').read_text());entries={x['path']:x for x in manifest['artifacts']}
 require({x['path'] for x in profile['artifacts']}==set(entries),'Manual profile target set mismatch')
 for x in profile['artifacts']:
  require(sha(Path(x['source']))==x['sha256'],'Manual source pin mismatch')
  m=entries[x['path']];require(x['sha256'] in m['accepted_existing'] or x['sha256']==m['output_sha256'],'Manual state not explicitly accepted')
 game=out/'Nebula Realms';game.mkdir(parents=True);originalpins={}
 for rel in ['Nebula Realms.exe']+[x['path'] for x in manifest['artifacts'] if x['original_sha256']]:
  src=originals/rel;dst=game/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);originalpins[rel]=sha(src)
 cases=[]
 def run(args,ok=True):
  p=subprocess.run([str(tool)]+args,capture_output=True,text=True);cases.append({'args':args,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr});require((p.returncode==0)==ok,'Unexpected patch command result: '+p.stderr);return p
 def patch(b,pin):return ['patch','--game',str(game),'--bundle',str(b),'--manifest-sha256',pin,'--server','http://127.0.0.1:8080','--advertise-ip','127.0.0.1','--originals',str(originals),'--allow-provisional']
 state=game/'.nebula-preservation';rp=state/'receipt.json'
 run(patch(prior,a.prior_manifest_sha256));oldreceipt=json.loads(rp.read_text())
 for x in profile['artifacts']:
  target=game/x['path'];data=Path(x['source']).read_bytes();require(hashlib.sha256(data).hexdigest()==x['sha256'],'Manual source changed');target.write_bytes(data)
 before={x['path']:x['sha256'] for x in profile['artifacts']}
 def exact(pins):
  for n,h in pins.items():require(sha(game/n)==h,'Unexpected fixture target state: '+n)
 exact(before);run(patch(bundle,a.manifest_sha256)+['--dry-run']);exact(before);require(json.loads(rp.read_text())==oldreceipt,'Dry run changed receipt')
 run(patch(bundle,a.manifest_sha256));newreceipt=json.loads(rp.read_text());require({e['path']:e['before'] for e in newreceipt['entries']}==before,'Manual before-state not backed up exactly');require(newreceipt['previous']==oldreceipt,'Prior receipt audit chain lost')
 after={e['path']:e['after'] for e in newreceipt['entries']};exact(after);receiptbytes=rp.read_bytes();p=run(patch(bundle,a.manifest_sha256));require('Already installed' in p.stdout and rp.read_bytes()==receiptbytes,'Idempotency failed')
 run(['restore','--game',str(game)]);exact(before);require(json.loads(rp.read_text())==oldreceipt,'Previous historical receipt not retained')
 # A further restore cannot safely infer or overwrite historical manual changes.
 p=run(['restore','--game',str(game)],False);exact(before);require('Target modified since patch; restore refuses to overwrite' in p.stderr,'Expected historical-receipt mismatch refusal')
 for rel,pin in originalpins.items():require(sha(originals/rel)==pin,'Steam original changed')
 for x in profile['artifacts']:require(sha(Path(x['source']))==x['sha256'],'Manual source changed')
 r={'format':'nebula-manual-update-acceptance-v1','passed':True,'manifest_sha256':a.manifest_sha256,'prior_manifest_sha256':a.prior_manifest_sha256,'manual_profile_sha256':sha(a.manual_profile),'patcher_sha256':sha(tool),'cases':cases,'before_restored':before,'fixture':str(game),'source_files_unchanged':True,'game_launched':False,'server_launched':False,'private_client_modified':False,'restore_boundary':'First restore exactly reinstates the captured reviewed manual overlay and prior audit receipt. Second restore safely refuses stale historical receipt hashes; no inference or automatic reset of manual changes.'}
 p=out/'acceptance-receipt.json';p.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'passed':True,'receipt':str(p),'sha256':sha(p)}))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('originals','patcher','bundle','prior-bundle','manual-profile','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--manifest-sha256',required=True);p.add_argument('--prior-manifest-sha256',required=True);main(p.parse_args())
