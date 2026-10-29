> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# PadPS4 keyboard-button compatibility candidate

## Result

A separate exact-build `GameAssembly.dll` candidate adds keyboard fallbacks to
ten `PadPS4` button methods while preserving their original controller behavior.
It is layered on the existing wardrobe, rapid-exit, and notification-text
private copy. No installed game file was changed.

Candidate SHA-256:
`3ddc1eb903eda90be06cc7079e2afa584d250b4430455b86564150fa05949703`.

## Static native evidence

The recovered native bodies for Cross, Circle, Square, Triangle, L1, R1, L3,
R3, Share, and Options all have the same policy:

1. return false when `PadPS4.isBlockedControls` at `this+0x10` is true;
2. select the original PS4 gamepad key;
3. use held-state input when `_bResetGameKey` is false;
4. use down-this-frame input when `_bResetGameKey` is true.

The managed declarations pin `UnityEngine.Input.GetKeyDownInt` to RVA
`0x1BD8730` and `GetKeyInt` to RVA `0x1BD8770`. Their recovered native bodies
corroborate the down and held native-input dispatch paths. `dump.cs` also pins
all keyboard `KeyCode` integer values used below.

Capstone decoding of the exact input candidate establishes that all ten target
entries begin with the same complete five-byte instruction:

[Code/listing block omitted from the public research archive.]

Each entry also has a matching existing PE runtime-function record whose range
continues beyond `entry+5`. This permits a bounded trampoline to reproduce the
stolen instruction and resume the untouched original function at `entry+5`.
There is no RIP-relative operand in the stolen bytes.

## Controller-first fallback policy

Every wrapper calls the entire original method first with the original `this`,
reset flag, and `MethodInfo` arguments. If the original returns true, the
wrapper immediately returns true and never polls the keyboard. After an
original false result, the wrapper rechecks `this+0x10`; blocked controls return
false without polling the keyboard.

Only the remaining false/unblocked path polls the mapped keyboard key. A true
reset flag calls `GetKeyDownInt`; false calls `GetKeyInt`. Both receive a null
IL2CPP `MethodInfo`, matching the direct static-helper ABI.

| PadPS4 method | Keyboard key | KeyCode |
|---|---:|---:|
| Cross | E | 101 |
| Circle | Escape | 27 |
| Square | Tab | 9 |
| Triangle | F | 102 |
| L1 | Q | 113 |
| R1 | R | 114 |
| L3 | Left Shift | 304 |
| R3 | C | 99 |
| Share | P | 112 |
| Options | M | 109 |

The patch does not synthesize a controller or replace the original joystick
checks. It does not change UI code, listener behavior, attachment logic,
identity, purchases, rewards, chat, or security checks.

## PE and ABI verification

- The input hash is fixed to the prior private candidate
  `13158d2f...7fcb`.
- Existing `.nbp` and `.nbn` sections remain present; the new `.nbk` section is
  read+execute and not writable.
- All 138,031 pre-existing runtime-function records are preserved byte-for-byte
  as records. One generated record covers the shared wrapper.
- Generated unwind metadata exactly describes three nonvolatile pushes and a
  48-byte stack allocation.
- All 416 authored code bytes decode completely. Relocations are restricted to
  the two Unity helpers and ten original `entry+5` continuations.
- Only the ten reviewed entry instructions, required PE headers/directory, and
  checksum change inside the existing image; all other existing bytes remain
  unchanged.
- Path guards reject existing outputs, input aliases, and any `steamapps`
  destination before writing.

The pure Python decoded-instruction model passes 120 cases: all ten buttons,
six controller/blocked/down/held outcomes, and two synthetic image bases. It
checks original-first ordering, exact keycodes, helper choice, original and
helper `MethodInfo` values, Win64 call alignment, volatile poisoning,
nonvolatile preservation, and balanced stack behavior.

## Subsequent unhooked runtime observation

After preparation, the same candidate ran without Frida and reached Nexus.
Three of the ten wrappers now have direct UI coverage:

- `M` opened the settled Options menu through `PadPS4.Options`. Evidence is `runtime-screenshots/options-settled.png`, SHA-256 `9e2cb9e8ba694119048bcffb03c116ed54227e63c77fe2407afe042e7cfd6059`.
- `C` exposed the chat UI through `PadPS4.R3`.
- The earlier attribution of chat focus to Left Shift through `PadPS4.L3` is retracted. A later discriminating read-only probe after an explicit Computer Access `Shift_L` press recorded `Chat.isFocused=0`, `Chat.isTyping=0`, and all observed manager/pad gates clear. This does not prove that a physical keyboard Left Shift can never work. Return then started input through the separate InputManager Submit row without requiring proof of an L3 focus transition. The completed Linux public-chat round trip remains valid Return/chat evidence and is visible in `runtime-screenshots/linux-public-chat.png`, SHA-256 `db9b7c1cdbe7abafbb3862ebe9c13b3543448ca8cfb715800fb5247bb440f5bb`. A later deliberate F8-for-L3 compatibility copy did focus chat in native runtime; see [keyboard-focus-compatibility.md](keyboard-focus-compatibility.md).

Cross/E, Circle/Escape, Square/Tab, Triangle/F, L1/Q, R1/R, and Share/P remain
runtime-untested. Arrow/Return UI navigation and W movement belong to the
separate InputManager configuration and do not add coverage for those seven
wrappers. The later preset save/load, purchase, wardrobe, and fresh-login
persistence results likewise do not imply more button-wrapper coverage.

For chronology, the earlier UI stage reached the character editor, changed the
height slider, then showed a blank Save Preset rectangle and only a short W
response. Later V2 preset-input and repeated-W tests superseded those blockers,
but they remain separate from this wrapper report.

An earlier Frida-instrumented run failed while an IL2CPP
`NullReferenceException` crossed the null-helper interception trampoline. The
source-bound analysis is in
[instrumented-exception-failure.md](README.md#omitted-local-evidence). The
dump does not support a `.nbk` native fault, and the exception-helper hooks are
retired from further live use.

No original game instruction, Unity helper, UI action, listener, socket,
synthetic input, or game process executed during offline preparation. Later
networked runtime work is a distinct follow-up and exercised Options, R3, and
L3. It did not stress all Windows exception/unwind paths through the entry
stubs, trampolines, and generated unwind metadata. Full runtime unwind behavior
remains unproven.

