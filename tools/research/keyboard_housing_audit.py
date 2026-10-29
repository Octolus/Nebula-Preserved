"""Emit source-hashed native furniture-input contracts and candidate boundaries."""

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path
import struct
import pefile

ROOT=workspace()
OUT=ROOT/'results/protocol'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
pe=pefile.PE(str(ROOT/'work/evidence/GameAssembly.dll'))
sources=['protocol/keyboard-housing-native.json','protocol/keyboard-housing-controller-native.json',
         'protocol/keyboard-housing-offline-validation.json',
         'client-fixes/prepared-keyboard-housing-input-copy.json',
         'tools/keyboard_housing_input_patch.py','tools/tests/test_keyboard_housing_input_patch.py',
         'tools/keyboard_buttons_patch.py']
evidence=[dict(path=x,sha256=sha(ROOT/'results'/x)) for x in sources]
for rva in [0x6a94b0,0x6a9810,0x35dcb0,0x6c1b20,0x6c1ba0,0x6c1c20,0x6c2040]:
    p=ROOT/f'work/evidence/ghidra/functions/{rva:x}.c'
    evidence.append(dict(path=str(p.relative_to(ROOT)),rva=hex(rva),sha256=sha(p)))
constants=[]
for rva,label in [(0x1dd3e84,'lower speed'),(0x1dd3e80,'raise speed'),(0x1dd2f18,'rotation degrees per second')]:
    raw=pe.get_data(rva,4)
    constants.append(dict(rva=hex(rva),label=label,raw_hex=raw.hex(),float32=struct.unpack('<f',raw)[0]))
manifest=json.loads((ROOT/'results/client-fixes/prepared-keyboard-housing-input-copy.json').read_text())
out=dict(scope='Static ground-furniture input contracts and separately prepared additive InputManager copy. No target/UI/runtime calls.',
         native_binary_sha256=sha(ROOT/'work/evidence/GameAssembly.dll'),
         metadata_dump_sha256=sha(ROOT/'work/decompiled/dump.cs'),
         pad=dict(L2=dict(rva='0x6a94b0',returns='float Input.GetAxis(PS4Gamepad.AXIS_L2_TRIGGER)',
                          name='joystick1_left_trigger',static_field_offset='0x60',zero_when='isBlockedControls+0x10 !=0'),
                  R2=dict(rva='0x6a9810',returns='float abs(Input.GetAxis(PS4Gamepad.AXIS_R2_TRIGGER))',
                          name='joystick1_right_trigger',static_field_offset='0x68',zero_when='isBlockedControls+0x10 !=0',
                          abs_instruction_rva='0x6a98a5',abs_mask_low32=hex(struct.unpack('<I',pe.get_data(0x1dd2e70,4))[0]))),
         cctor=dict(rva='0x35dcb0',
                    left_name_load='0x35df83',left_store='0x35df8a -> static+0x60',
                    right_name_load='0x35dfba',right_store='0x35dfc1 -> static+0x68',
                    limitation='Ghidra incorrectly truncates this initializer at shared write-barrier-looking calls; bounded native assembly preserves all later axis stores.'),
         dispatch=dict(caller='HousingInputMapperPlacingGround.Update 0x6c2040; UpdateButtons 0x6c1c20',
                       chain='mapper.manager+0x20 -> HousingManager.housingCamera+0x28 -> HousingCamera.currentController+0x60',
                       slots=[dict(input='L1',key='q',vtable_offset='0x1e8',slot=11,method='RotatePlacedObjectLeft',implementation='0x6ba2c0'),
                              dict(input='R1',key='r',vtable_offset='0x1f8',slot=12,method='RotatePlacedObjectRight',implementation='0x6ba410'),
                              dict(input='L2',key='1 (candidate)',vtable_offset='0x208',slot=13,method='LowerPlacedObject(float)',implementation='0x6b96d0'),
                              dict(input='R2',key='2 (candidate)',vtable_offset='0x218',slot=14,method='RaisePlacedObject(float)',implementation='0x6b9eb0')],
                       trigger_gate='Exactly nonzero float, reread and passed unchanged; not a bool/GetButtonDown trigger',
                       rotation_effect='Focused asset euler Y minus/plus 50*Time.deltaTime',
                       height_effect='CharacterController.Move along camera transform.up times -7.5/+7.5*Time.deltaTime*trigger speed',
                       rotation_patch_needed_by_static_contract=False),
         constants=constants,candidate=manifest,
         engine_semantics_source=dict(url='https://docs.unity3d.com/2021.3/Documentation/Manual/class-InputManager.html',
                                      claim='Duplicate named axes return the input with greatest absolute magnitude; positive keyboard buttons increase the virtual axis.'),
         evidence=evidence,
         limits=['No rotation, height, engine input or housing persistence runtime test was performed by this audit.',
                 'Native behavior is recovered from the reviewed shipped binary; current private binary deployment/probes are separate parent evidence.',
                 'The 1/2 binding is authored compatibility policy, not recovered original keyboard behavior.',
                 'Duplicate axes preserve controller row bytes, but equal-magnitude simultaneous keyboard/controller input may tie.',
                 'Existing Q/R keyboard wrappers already cover the recovered rotation callbacks; no new DLL rotation patch is justified by this static contract.'])
(OUT/'keyboard-housing-compatibility.json').write_text(json.dumps(out,indent=2)+'\n')
md=f'''# Native furniture controls and keyboard candidate

**Rotation already uses L1/R1, mapped to Q/R by the existing private button compatibility patch. L2/R2 are height controls, not rotation.** No additional rotation patch is justified by this static trace.

The new 50-axis candidate adds **1=lower, 2=raise** only. It is prepared at `work/patched-input-housing/globalgamemanagers`, SHA256 `{manifest['copy_sha256']}`. Nothing was copied to a live client or Steam installation, and no UI/game/server/connection execution was performed by this audit.

## Exact native dispatch

HousingInputMapperPlacingGround.Update (`0x6c2040`) contains the same native button handling as UpdateButtons (`0x6c1c20`). Its object chain is `mapper.manager+0x20 -> HousingManager.housingCamera+0x28 -> HousingCamera.currentController+0x60`.

| Input | Existing/new keyboard | IL2CPP vtable offset and slot | Native method |
|---|---|---|---|
| L1 | Q, existing | +0x1e8, slot11 | RotatePlacedObjectLeft, ground implementation0x6ba2c0 |
| R1 | R, existing | +0x1f8, slot12 | RotatePlacedObjectRight, ground implementation0x6ba410 |
| L2 | 1, candidate | +0x208, slot13 | LowerPlacedObject(float), ground implementation0x6b96d0 |
| R2 | 2, candidate | +0x218, slot14 | RaisePlacedObject(float), ground implementation0x6b9eb0 |

These slots are declared on HousingController (metadata TypeDef310). Native rotation reads the focused asset's euler angles and subtracts/adds **50*Time.deltaTime** from Y. The lower/raise implementations call CharacterController.Move along camera transform.up with signed speed **-7.5/+7.5**, deltaTime and supplied trigger intensity. The [bounded controller assembly](keyboard-housing-controller-native.json) preserves these instructions and raw method hashes; the [contract JSON](keyboard-housing-compatibility.json) preserves constant bytes/addresses and all source hashes.

## Axis names, signs and gates

PadPS4.L2 (`0x6a94b0`) returns the float Input.GetAxis of static AXIS_L2_TRIGGER (`+0x60`), initialized to **joystick1_left_trigger**. It tail-jumps Input.GetAxis at0x6a9515. It does not take an absolute value.

PadPS4.R2 (`0x6a9810`) reads **joystick1_right_trigger** from static AXIS_R2_TRIGGER (`+0x68`), calls Input.GetAxis and clears its float sign bit (ANDPS0x6a98a5, mask0x7fffffff), equivalent to absolute value. Both return zero when PadPS4.isBlockedControls (`+0x10`) is set.

The HousingInputMapper standalone methods (`0x6c1b20`/`0x6c1ba0`) and combined update test the result against zero, reread it and pass that float into the corresponding controller slot. Positive keyboard input is therefore correct for both: positive L2 reaches the native negative lower speed, while positive R2 remains positive after abs and reaches raise speed. No bool/GetButtonDown fallback is appropriate here.

PS4Gamepad.cctor (`0x35dcb0`) native instructions load/store the left string at0x35df83/0x35df8a and right string at0x35dfba/0x35dfc1. Its Ghidra output truncates at earlier shared write-barrier-looking calls; the [bounded assembly](keyboard-housing-native.json) includes the subsequent stores. Ghidra's undefined8 return annotation for PadPS4 is also superseded by the native XMM float return and metadata float signatures.

## Candidate preservation and checks

The input is the exact reviewed 48-axis world-controls copy, SHA256 `70a141380052f0c2eb0d64c8bad71961648fe9791d79a6b2da37924b9bff4775`. It already contains physical controller trigger rows at indices4/5: joystick1_left_trigger axis8 and joystick1_right_trigger axis9, type2, joyNum1, dead0.19. The tool preserves those rows and every other existing row. It appends two type0 rows under the same logical names, positive buttons1/2, no negative buttons, no inversion, gravity/sensitivity1000 and dead0.001. These key choices are an authored compatibility policy; neither key is present in the source InputManager bindings or the reviewed PadPS4 button aliases. Global context exclusivity is not claimed.

Unity2021.3 documents that repeated axis names allow multiple devices and select the greatest absolute input. This supports additive aliases while retaining physical controller rows; equal-magnitude simultaneous input can tie. [Unity Input Manager manual](https://docs.unity3d.com/2021.3/Documentation/Manual/class-InputManager.html).

Seven offline checks pass: source hash and unchanged source, exact48-row prefix and other InputManager fields, exact50-row result/positive aliases, all17 other serialized objects' raw hashes, deterministic serialization, rejection of altered/repatched inputs, and output/manifest path safeguards. Results: [offline validation](keyboard-housing-offline-validation.json); exact candidate manifest: [prepared keyboard height copy](../client-fixes/prepared-keyboard-housing-input-copy.json). Preparation refuses existing output files, source overwrite and any output path under steamapps.

Static serialization checks establish preservation and native dispatch expectations. They do not establish live rotation, height behavior or housing persistence. In particular, failure to rotate after Q/R should be investigated through active housing mode, PadPS4 controls gate and deployed keyboard wrapper state; adding the L2/R2 rows does not repair those rotation paths.
'''
(OUT/'keyboard-housing-compatibility.md').write_text(md,encoding='utf-8')
print(json.dumps(dict(copy_sha256=manifest['copy_sha256'],rotation='Q/R existing',height='1/2 candidate',runtime_proof=False)))
