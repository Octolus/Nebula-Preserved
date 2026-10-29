"""Authorized Windows patcher acceptance on a disposable minimal fixture only.

Never launches a game/server. Originals are read-only. A real private-client
installation is deliberately outside this harness.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

EXPECTED_METADATA="76e10da141d2daacd99c0976f362ddbf9463321aeef69ea464230565202885fd"
sha=lambda b:hashlib.sha256(b).hexdigest()
def require(ok,message):
    if not ok:raise AssertionError(message)
def main(args):
    root=Path(__file__).resolve().parent.parent;out=Path(args.output).resolve()
    require(root in out.parents and not out.exists(),"Fixture must be new and inside this patcher workspace")
    originals=Path(args.originals).resolve();bundle=Path(args.bundle).resolve();tool=Path(args.patcher).resolve()
    expected_manifest=args.manifest_sha256
    require(len(expected_manifest)==64 and all(c in "0123456789abcdef" for c in expected_manifest),"Explicit lowercase manifest pin required")
    mb=(bundle/"manifest.json").read_bytes();require(sha(mb)==expected_manifest,"Unexpected release manifest")
    manifest=json.loads(mb);game=out/"Nebula Realms";game.mkdir(parents=True)
    original_hashes={};paths=[a["path"]for a in manifest["artifacts"]]
    for rel in ["Nebula Realms.exe"]+[a["path"]for a in manifest["artifacts"]if a["original_sha256"]]:
        src=originals/rel;dst=game/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);original_hashes[rel]=sha(dst.read_bytes())
    cases=[]
    def command(arguments,success=True,contains=None):
        result=subprocess.run([str(tool)]+arguments,capture_output=True,text=True)
        require((result.returncode==0)==success,f"Unexpected command outcome: {result.stdout} {result.stderr}")
        if contains:require(contains in result.stdout+result.stderr,"Expected diagnostic missing")
        cases.append({"command":arguments,"exit_code":result.returncode,"stdout":result.stdout.strip(),"stderr":result.stderr.strip()})
        return result
    patch=["patch","--game",str(game),"--bundle",str(bundle),"--manifest-sha256",expected_manifest,"--server","http://127.0.0.1:8080","--advertise-ip","127.0.0.1","--allow-provisional"]
    if args.originals:patch += ["--originals",str(originals)]
    state=game/".nebula-preservation";rp=state/"receipt.json";jp=state/"journal.json"
    def before():
        for rel in ["Nebula Realms.exe"]+paths:
            target=game/rel
            if rel in original_hashes:require(target.is_file()and sha(target.read_bytes())==original_hashes[rel],"Original fixture hash not restored: "+rel)
            else:require(not target.exists(),"New helper was not removed: "+rel)
    def after():
        receipt=json.loads(rp.read_text());require(len(receipt["entries"])==8,"Wrong entry count")
        require(receipt["entries"][-1]["path"]=="GameAssembly.dll","GameAssembly did not commit last")
        for e in receipt["entries"]:require(sha((game/e["path"]).read_bytes())==e["after"],"Installed hash mismatch")
        meta=game/"Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat"
        require(sha(meta.read_bytes())==EXPECTED_METADATA,"Rust endpoint recipe differs from reviewed default metadata")
        return receipt
    def journal(receipt,mode):
        jp.write_text(json.dumps({"format":"nebula-journal-v1","mode":mode,"receipt":receipt,"old_receipt":receipt["previous"] if mode=="patch"else None}))
    # Actual fixture install/idempotency/restore.
    command(patch);receipt=after();receipt_bytes=rp.read_bytes();command(patch,contains="Already installed");require(rp.read_bytes()==receipt_bytes,"Idempotent invocation rewrote receipt")
    command(["restore","--game",str(game)]);before()
    # Synthetic crash after commit/receipt but before journal removal.
    command(patch);receipt=after();journal(receipt,"patch");command(["recover","--game",str(game)]);before();require(not jp.exists()and not rp.exists(),"Recovery did not clear active state")
    # Partial commit: leave first three outputs installed, restore remaining
    # entries manually from the tool's hash-checked backups, then recover.
    command(patch);receipt=after()
    for e in receipt["entries"][3:]:
        target=game/e["path"]
        if e["before"] is None:target.unlink()
        else:
            data=(state/e["backup"]).read_bytes();require(sha(data)==e["before"],"Fixture backup mismatch");target.write_bytes(data)
    journal(receipt,"patch");command(["recover","--game",str(game)]);before()
    # Interrupted restore resumes an exact known scratch file.
    command(patch);receipt=after();entry=receipt["entries"][-1];target=game/entry["path"];scratch=target.with_suffix(".nebula-restore")
    data=(state/entry["backup"]).read_bytes();require(sha(data)==entry["before"],"Restore scratch source mismatch");scratch.write_bytes(data);journal(receipt,"restore")
    command(["recover","--game",str(game)]);before();require(not scratch.exists(),"Known restore scratch not consumed")
    # Unknown rollback scratch must fail before overwriting a target; replacing
    # it with the exact backup then allows recovery to resume.
    command(patch);receipt=after();entry=receipt["entries"][-1];target=game/entry["path"];scratch=target.with_suffix(".nebula-rollback");scratch.write_bytes(b"unknown fixture scratch");journal(receipt,"patch")
    snapshot=sha(target.read_bytes());command(["recover","--game",str(game)],False,"Unexpected rollback scratch contents");require(sha(target.read_bytes())==snapshot,"Refusal modified target")
    scratch.write_bytes((state/entry["backup"]).read_bytes());command(["recover","--game",str(game)]);before();require(not scratch.exists(),"Known rollback scratch not consumed")
    # Unknown installed hash must refuse during a dry-run, with the changed
    # file left untouched. Repair the fixture from the pristine source after.
    ga=game/"GameAssembly.dll"
    with ga.open("r+b")as f:old=f.read(1);f.seek(0);f.write(bytes([old[0]^1]))
    corrupt=sha(ga.read_bytes());command(patch+["--dry-run"],False,"Unrecognized installed state");require(sha(ga.read_bytes())==corrupt,"Unknown file overwritten")
    with ga.open("r+b")as f:f.write(old)
    before()
    for rel,pin in original_hashes.items():require(sha((originals/rel).read_bytes())==pin,"Steam original changed")
    report={"format":"nebula-patcher-fixture-acceptance-v2","fixture":str(game),"manifest_sha256":expected_manifest,"patcher_sha256":sha(tool.read_bytes()),"cases":cases,"commands_passed":len(cases),"restored_target_hashes":original_hashes,"steam_originals_unchanged":True,"game_executed":False,"server_executed":False,"private_client_modified":False,"fixture_final_state":"Pristine core/executable restored; newly installed helpers absent; backups retained for review"}
    (out/"acceptance-receipt.json").write_text(json.dumps(report,indent=2)+"\n");print(json.dumps({"commands_passed":len(cases),"receipt":str(out/"acceptance-receipt.json"),"receipt_sha256":sha((out/"acceptance-receipt.json").read_bytes())}))

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--manifest-sha256",required=True);p.add_argument("--originals",required=True);p.add_argument("--bundle",required=True);p.add_argument("--patcher",required=True);p.add_argument("--output",required=True);main(p.parse_args())
