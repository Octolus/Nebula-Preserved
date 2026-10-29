> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Native furniture controls and keyboard candidate

**Rotation already uses L1/R1, mapped to Q/R by the existing private button compatibility patch. L2/R2 are height controls, not rotation.** No additional rotation patch is justified by this static trace.

The new 50-axis candidate adds **1=lower, 2=raise** only. It is prepared at `work/patched-input-housing/globalgamemanagers`, SHA256 `94316afc2c49cda26f6cee95411cbba024f7848f490f2813a342da708063b100`. Nothing was copied to a live client or Steam installation, and no UI/game/server/connection execution was performed by this audit.

## Exact native dispatch

HousingInputMapperPlacingGround.Update (`0x6c2040`) contains the same native button handling as UpdateButtons (`0x6c1c20`). Its object chain is `mapper.manager+0x20 -> HousingManager.housingCamera+0x28 -> HousingCamera.currentController+0x60`.

| Input | Existing/new keyboard | IL2CPP vtable offset and slot | Native method |
|---|---|---|---|
| L1 | Q, existing | +0x1e8, slot11 | RotatePlacedObjectLeft, ground implementation0x6ba2c0 |
| R1 | R, existing | +0x1f8, slot12 | RotatePlacedObjectRight, ground implementation0x6ba410 |
| L2 | 1, candidate | +0x208, slot13 | LowerPlacedObject(float), ground implementation0x6b96d0 |
| R2 | 2, candidate | +0x218, slot14 | RaisePlacedObject(float), ground implementation0x6b9eb0 |

These slots are declared on HousingController (metadata TypeDef310). Native rotation reads the focused asset's euler angles and subtracts/adds **50*Time.deltaTime** from Y. The lower/raise implementations call CharacterController.Move along camera transform.up with signed speed **-7.5/+7.5**, deltaTime and supplied trigger intensity. The [bounded controller assembly](README.md#omitted-local-evidence) preserves these instructions and raw method hashes; the [contract JSON](keyboard-housing-compatibility.json) preserves constant bytes/addresses and all source hashes.

## Axis names, signs and gates

PadPS4.L2 (`0x6a94b0`) returns the float Input.GetAxis of static AXIS_L2_TRIGGER (`+0x60`), initialized to **joystick1_left_trigger**. It tail-jumps Input.GetAxis at0x6a9515. It does not take an absolute value.

PadPS4.R2 (`0x6a9810`) reads **joystick1_right_trigger** from static AXIS_R2_TRIGGER (`+0x68`), calls Input.GetAxis and clears its float sign bit (ANDPS0x6a98a5, mask0x7fffffff), equivalent to absolute value. Both return zero when PadPS4.isBlockedControls (`+0x10`) is set.

The HousingInputMapper standalone methods (`0x6c1b20`/`0x6c1ba0`) and combined update test the result against zero, reread it and pass that float into the corresponding controller slot. Positive keyboard input is therefore correct for both: positive L2 reaches the native negative lower speed, while positive R2 remains positive after abs and reaches raise speed. No bool/GetButtonDown fallback is appropriate here.

PS4Gamepad.cctor (`0x35dcb0`) native instructions load/store the left string at0x35df83/0x35df8a and right string at0x35dfba/0x35dfc1. Its Ghidra output truncates at earlier shared write-barrier-looking calls; the [bounded assembly](README.md#omitted-local-evidence) includes the subsequent stores. Ghidra's undefined8 return annotation for PadPS4 is also superseded by the native XMM float return and metadata float signatures.

## Candidate preservation and checks

The input is the exact reviewed 48-axis world-controls copy, SHA256 `70a141380052f0c2eb0d64c8bad71961648fe9791d79a6b2da37924b9bff4775`. It already contains physical controller trigger rows at indices4/5: joystick1_left_trigger axis8 and joystick1_right_trigger axis9, type2, joyNum1, dead0.19. The tool preserves those rows and every other existing row. It appends two type0 rows under the same logical names, positive buttons1/2, no negative buttons, no inversion, gravity/sensitivity1000 and dead0.001. These key choices are an authored compatibility policy; neither key is present in the source InputManager bindings or the reviewed PadPS4 button aliases. Global context exclusivity is not claimed.

Unity2021.3 documents that repeated axis names allow multiple devices and select the greatest absolute input. This supports additive aliases while retaining physical controller rows; equal-magnitude simultaneous input can tie. [Unity Input Manager manual](README.md#omitted-local-evidence).

Seven offline checks pass: source hash and unchanged source, exact48-row prefix and other InputManager fields, exact50-row result/positive aliases, all17 other serialized objects' raw hashes, deterministic serialization, rejection of altered/repatched inputs, and output/manifest path safeguards. Results: [offline validation](README.md#omitted-local-evidence); exact candidate manifest: [prepared keyboard height copy](README.md#omitted-local-evidence). Preparation refuses existing output files, source overwrite and any output path under steamapps.

Static serialization checks establish preservation and native dispatch expectations. They do not establish live rotation, height behavior or housing persistence. In particular, failure to rotate after Q/R should be investigated through active housing mode, PadPS4 controls gate and deployed keyboard wrapper state; adding the L2/R2 rows does not repair those rotation paths.
