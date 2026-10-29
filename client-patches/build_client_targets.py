"""Reconstruct both provisional client profiles from exact locally owned originals.

This maintainer build writes a NEW output tree. It never installs, loads a game
DLL, launches a client, changes Steam, chooses a server, or publishes a bundle.
The separate Rust patcher locates Steam and applies source-referenced deltas with
the endpoint supplied by the end user. Complete scratch game files stay private.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import pefile

HERE = Path(__file__).resolve().parent
SOURCE = HERE
LOCK = "4399d7a031de47a1870feddd7c6299c6a56a4e7a73d047ec1a2867a794b9bf62"
BASE = "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac"
COMPOSED = "0ec5e89f91010e205b19ee4de29a4167c1deb7312a45733a866dbebec64a13ab"
DEFAULT_JOIN = "d59155564b142aa24dcfab03a47290d43261dccbfd55ea3a06543fffe65fda04"
DEFAULT_HELPER = "c880fb8df3265da1432ff3e6683156e2941abf972ad23df8e15699f38fea6e19"
FREE = "6fc2fcdf0e4178b96069f25e4f2e8fcacf8af3c33fb68c4f144ae6a5fd4dd4df"
FREE_JOIN = "39ad8c096357f4a1e56b90524175f67b8e6cc88dcedf2c3bc0fbf87178271e3b"
FREE_HELPER = "68415abf23ee90cbc3e9c6294097c0387eea8b29ddae42eb1fbc290739573083"
BRIDGE = "e493d6fa9af94df6626e950ee8e4483ede10d94fc81405b394090dd0e047ef10"
PUBLIC_ACCESS = "8d6d812dbff42bd38cd5763dbbb969609125d5540af9a38745b76f2d3f0d79b5"
METADATA = "Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat"
MANAGER = "Nebula Realms_Data/globalgamemanagers"
EDITOR = "Nebula Realms_Data/StreamingAssets/StandaloneWindows/s/charactereditor"
ORIGINALS = {"GameAssembly.dll":BASE, METADATA:"c59807c2950c1051202ae7d96744d126be4c489c7719f7e2d8d207f8f75681c1",
    MANAGER:"ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466",
    EDITOR:"5d1713e79b4e5bab090a3d57eb4d4c4139999629bb4a2038412a6cb92d1b02e0",
    "Nebula Realms.exe":"77bdecc37804194305c2402be5ac0851570f395bf9af3fb4ee03030c6d779d0d"}
UNITS = ("automation.cpp", "automation_store.cpp", "frame_capture_module.cpp", "economy_store_module.cpp",
         "economy_v16_adapter.cpp", "economy_callback_generations.cpp", "social_module.cpp",
         "resource_ui_module.cpp", "resource_navigation_module.cpp", "join_queue_gate.cpp")
sha = lambda data: hashlib.sha256(data).hexdigest()

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

def read(path, pin):
    data = Path(path).read_bytes()
    require(sha(data) == pin, "Pinned source differs: " + str(path))
    return data

def load(relative):
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location("client_stage_" + path.stem, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result

def helper(a, baseline, out, ga_pin):
    tree = out / "helper-source"
    tree.mkdir(parents=True)
    for name, pin in baseline["source"].items():
        (tree / name).write_bytes(read(SOURCE / "native-automation" / name, pin))
    header = tree / "movement_profile.h"
    old = header.read_bytes()
    require(old.count(FREE_JOIN.encode()) == 1, "Profile header differs")
    header.write_bytes(old.replace(FREE_JOIN.encode(), ga_pin.encode()))
    for name, pin in baseline["source"].items():
        if name != "movement_profile.h":
            read(tree / name, pin)
    dll = out / "NebulaAutomation.dll"
    subprocess.run([str(a.cxx), "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-exceptions", "-fno-rtti",
        "-shared", "-static", "-static-libgcc", "-static-libstdc++",
        "-Wl,--no-insert-timestamp,--image-base,0x180000000,--strip-all", "-I", str(tree), "-o", str(dll),
        *[str(tree / unit) for unit in UNITS], "-lbcrypt"], check=True)
    pe = pefile.PE(str(dll))
    require(sorted(r.dll.decode() for r in pe.DIRECTORY_ENTRY_IMPORT) == baseline["imports"], "Helper imports differ")
    require(sorted(r.name.decode() for r in pe.DIRECTORY_ENTRY_EXPORT.symbols if r.name) == baseline["exports"], "Helper exports differ")
    if ga_pin == FREE_JOIN:
        read(dll, FREE_HELPER)
    elif ga_pin == DEFAULT_JOIN:
        read(dll, DEFAULT_HELPER)
    else:
        raise ValueError("Unreviewed helper profile")
    return dll

def free_mouse(data):
    require(sha(data) == COMPOSED, "Optional cursor recipe needs exact original-cursor composed stage")
    pe = pefile.PE(data=data)
    result = bytearray(data)
    for rva, end in ((0x6a93e0,0x6a93fb), (0x1b6b7d0,0x1b6b801), (0x1b6b810,0x1b6b843)):
        row = [r.struct for r in pe.DIRECTORY_ENTRY_EXCEPTION if r.struct.BeginAddress == rva]
        require(len(row) == 1 and row[0].EndAddress == end, "Cursor function extent differs")
        at = pe.get_offset_from_rva(rva)
        if rva == 0x6a93e0:
            require(data[at:at+4] == bytes.fromhex("4883ec28"), "Cursor prologue differs")
            code = data[at:at+4] + b"\x90"*14 + bytes.fromhex("4883c428c3")
        else:
            require(data[at:at+6] == bytes.fromhex("40534883ec20"), "Cursor prologue differs")
            code = data[at:at+6] + bytes.fromhex("4883c4205bc3")
        result[at:at+end-rva] = code.ljust(end-rva,b"\x90")
    require(sha(result) == FREE, "Optional free-mouse stage differs")
    return bytes(result)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--originals", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cc", type=Path, required=True)
    p.add_argument("--cxx", type=Path, required=True)
    p.add_argument("--public-access", type=Path, required=True, help="Reviewed separately built PublicAccess DLL, exact pin required")
    a = p.parse_args()
    originals = a.originals.resolve(strict=True)
    out = a.output.resolve()
    require(not out.exists() and not out.is_relative_to(originals) and not out.is_relative_to(SOURCE)
            and "steamapps" not in [x.lower() for x in out.parts], "Fresh output outside sources and Steam required")
    lock = json.loads(read(SOURCE / "source-lock.json", LOCK))
    for name, pin in lock["files"].items():
        read(SOURCE / name, pin)
    for name, pin in ORIGINALS.items():
        read(originals / name, pin)
    public = read(a.public_access, PUBLIC_ACCESS)
    baseline = lock["helper_baseline"]
    out.mkdir(parents=True)
    scratch = out / "private-build-scratch-DO-NOT-DISTRIBUTE"
    scratch.mkdir()
    shared = out / "shared"
    shared.mkdir()
    (shared / "NebulaPublicAccess.dll").write_bytes(public)
    (shared / "steam_appid.txt").write_bytes(b"919290")
    registry_dll = shared / "NebulaRegistryBridge.dll"
    subprocess.run([str(a.cxx), "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-static",
        "-Wl,--no-insert-timestamp", "-Wl,--image-base,0x180000000", "-o", str(registry_dll),
        str(SOURCE / "native-registry/interaction_registry_bridge.cpp")], check=True)
    bridge = read(registry_dll, BRIDGE)
    original = (originals / "GameAssembly.dll").read_bytes()
    world, _ = load("recipes/keyboard_input_patch.py").prepare((originals / MANAGER).read_bytes(), world_controls=True)
    require(sha(world) == "70a141380052f0c2eb0d64c8bad71961648fe9791d79a6b2da37924b9bff4775", "World input differs")
    manager, manager_report = load("recipes/keyboard_housing_input_patch.py").prepare(world)
    require(sha(manager) == "94316afc2c49cda26f6cee95411cbba024f7848f490f2813a342da708063b100", "Housing input differs")
    (shared / "globalgamemanagers").write_bytes(manager)
    editor, editor_report = load("recipes/preset_input_patch.py").prepare((originals / EDITOR).read_bytes())
    require(sha(editor) == "9a2cdcaa9ac356fe95df9b5a5ad5df6bba93330ad1591685553031729628d3c4", "Editor recipe differs")
    (shared / "charactereditor").write_bytes(editor)
    stages = []
    current = original
    def stage(name, value, pin):
        nonlocal current
        require(sha(value) == pin, "Intermediate stage differs: " + name)
        stages.append(dict(stage=name, source_sha256=sha(current), output_sha256=pin, bytes=len(value)))
        current = value
        print(json.dumps(stages[-1]), flush=True)
    def obj(assembly, name, pin):
        target = scratch / (name + ".o")
        subprocess.run([str(a.cc), "-c", str(SOURCE / assembly), "-o", str(target)], check=True)
        return read(target, pin)
    wardrobe = load("recipes/make_client_copy.py")
    data = bytearray(current)
    require(data[wardrobe.OFFSET:wardrobe.OFFSET+2] == wardrobe.BEFORE, "Wardrobe branch differs")
    data[wardrobe.OFFSET:wardrobe.OFFSET+2] = wardrobe.AFTER
    stage("wardrobe-loop", bytes(data), wardrobe.PATCHED_SHA256)
    for name, recipe, assembly, object_pin, target in (
        ("rapid-exit","rapid_boat_patch.py","rapid_boat_exit.s","24fc28d939cb1dda6c74662ecd53a22d2d3923d6573a6adddf194fbe19a83608","ce1a74588e74499e282699e160b966439ffb4c278e8bcef791951e28a57b0dd0"),
        ("notification-text","notification_text_patch.py","notification_text.s","9e65a06832343882297fee3763159d502e3eea330f7ea5252cfd8051479eacb7","13158d2f08c9511c9cc283a6dda680081c5e1f6142bb86ddde1bfbd039de7fcb"),
        ("keyboard-buttons","keyboard_buttons_patch.py","keyboard_buttons.s","d6fc963f20d236473ce8d60b5e2e2cac257086e195e8d9303907eae578bbcf93","3ddc1eb903eda90be06cc7079e2afa584d250b4430455b86564150fa05949703"),
    ):
        value, _ = load("recipes/" + recipe).build(current, obj("shims/" + assembly, name, object_pin))
        stage(name, value, target)
    value, _ = load("recipes/keyboard_focus_patch.py").build(current, original, world)
    stage("keyboard-focus-f8", value, "ec6f909d3af35c89cd287a2803b86839cd5d1b168bc1f76517eed2494c85e01b")
    registry = load("recipes/interaction_registry_patch.py")
    value, _ = registry.build(current, obj("shims/interaction_registry_bridge.s", "registry", registry.OBJECT_SHA), bridge)
    stage("registry-save-snapshot", value, "3001b2e4cf014a7ec961c370b50a947c9b6d6f4be86446f3e5d4bffe203353e3")
    for name, recipe, target in (
        ("neck-thin-load","neck_thin_load_patch.py","af25cec2ba6a9496f7c34b5ea8224f4ef5ab9f596bda6ae35bcb44197f30b195"),
        ("settings-preservation","settings_preservation_patch.py","c11dc93f3f67bb09781d9c097ce85cc2e497af9bf83efabaf279ec2b03b0f3d5"),
        ("eyes-lifetime","eyes_lifetime_patch.py","cd82cde50b71ea203fc09dc87153579f6cb504f1e9dfb74417408d602c704a74"),
    ):
        value, _ = load("recipes/" + recipe).build(current)
        stage(name, value, target)
    pump = load("recipes/steam_update_pump_patch.py")
    value, _ = pump.build(current, obj("shims/automation.s", "pump", pump.OBJECT_SHA256))
    stage("steam-update-pump", value, "8460554e5287fe8e3c5fe475f65379da971bcccf2f21f716f2ca82d6e029b9fd")
    layered = scratch / "GameAssembly.layered.dll"
    layered.write_bytes(current)
    free_tree = out / "free-mouse"
    free_tree.mkdir()
    free_helper = helper(a, baseline, free_tree, FREE_JOIN)
    plan = dict(format="nebula-pe-input-v1", status="profile-handshake", review="Exact pinned source-chain reconstruction; provisional native acceptance pending",
        source=str(layered), automation=str(free_helper), automation_sha256=FREE_HELPER,
        public_access=str(shared / "NebulaPublicAccess.dll"), public_access_sha256=PUBLIC_ACCESS)
    atomic_plan = scratch / "atomic-plan.json"
    atomic_plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    composer = load("pe-composition/compose_iat_corrected.py")
    atomic = scratch / "atomic-75-hooks"
    composer.compose(SimpleNamespace(plan=atomic_plan, output=atomic, cc=a.cc))
    stage("corrected-atomic-75-hooks", read(atomic / "GameAssembly.dll", COMPOSED), COMPOSED)
    original_cursor = current
    join = load("pe-composition/join_queue_patch.py")
    shim = obj("pe-composition/join_queue_shim.s", "join", "e613b788a7017f5d23613a8be374a98bb735465d44758aaecc70a1d5102cb9c6")
    profiles = {}
    for profile in ("default", "free-mouse"):
        tree = out / profile
        tree.mkdir(exist_ok=(profile == "free-mouse"))
        base = original_cursor if profile == "default" else free_mouse(original_cursor)
        data, join_report = join.compose(base, shim)
        require(sha(data) == (DEFAULT_JOIN if profile == "default" else FREE_JOIN), "Final GameAssembly tuple differs")
        if profile == "free-mouse":
            require(sha(data) == FREE_JOIN, "Optional join profile differs")
            dll = free_helper
        else:
            dll = helper(a, baseline, tree, sha(data))
        (tree / "GameAssembly.dll").write_bytes(data)
        profiles[profile] = dict(ga_sha256=sha(data), helper_sha256=sha(dll.read_bytes()), join=join_report,
            cursor_safe_for_automation=(profile == "free-mouse"), original_cursor_preserved=(profile == "default"),
            helper_source_delta=[] if profile == "free-mouse" else ["movement_profile.h"], native_runtime_accepted=False)
        artifacts = []
        for relative, target, pin in (
            ("GameAssembly.dll",tree/"GameAssembly.dll",sha(data)),
            (MANAGER,shared/"globalgamemanagers",sha(manager)),
            (EDITOR,shared/"charactereditor",sha(editor)),
            ("NebulaRegistryBridge.dll",registry_dll,BRIDGE),
            ("NebulaAutomation.dll",dll,sha(dll.read_bytes())),
            ("NebulaPublicAccess.dll",shared/"NebulaPublicAccess.dll",PUBLIC_ACCESS),
            ("steam_appid.txt",shared/"steam_appid.txt",sha(b"919290")),
        ):
            artifacts.append(dict(path=relative,target=str(target.resolve()),target_sha256=pin,accepted_existing=[pin]))
        artifacts.insert(1,dict(path=METADATA, accepted_existing=["69cf396cfb86d1e22ae110c032b7fa707250b6aec3978f42d0b5197f9956248b"]))
        release = dict(format="nebula-release-input-v1",app_id="919290",build_id="11018722",status="provisional",
            review="Exact source reconstruction; independent final source review and native acceptance pending. Never label frozen.",
            originals=str(originals),review_evidence=[],artifacts=artifacts)
        (out / ("release-input-"+profile+".json")).write_text(json.dumps(release,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"profile":profile,**{k:v for k,v in profiles[profile].items() if k in ("ga_sha256","helper_sha256")}}),flush=True)
    for name,pin in ORIGINALS.items():
        read(originals / name,pin)
    record = dict(format="nebula-authored-client-stage-reconstruction-v1",source_lock_sha256=LOCK,
        stages=stages,profiles=profiles,default="default",optional="free-mouse",public_access_input_sha256=PUBLIC_ACCESS,
        manager_report=manager_report,editor_report=editor_report,source_originals_unchanged=True,
        complete_game_scratch_private=True,installed=False,game_launched=False,published=False,
        native_runtime_accepted=False,independent_source_review_pending=True,
        toolchain={"cc_sha256":sha(a.cc.read_bytes()),"cxx_sha256":sha(a.cxx.read_bytes())})
    (out / "build-receipt.LOCAL-DO-NOT-COMMIT.json").write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8")

if __name__ == "__main__":
    main()
