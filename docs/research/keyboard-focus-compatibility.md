> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Keyboard focus compatibility: F8 as the L3 fallback

Status: prepared, offline-validated, and narrowly runtime-validated on 2026-10-28.

## Purpose

The Computer Access surface available for the current UI trial exposes a discrete `press_key` action but no held-modifier action. Two explicit `Shift_L` attempts left `Chat.isFocused=0` while the observed chat/menu gates remained clear. This does not establish an original game bug. It motivates a reversible compatibility mapping that a discrete-key surface can express.

The prepared copy replaces only the existing keyboard fallback for `PadPS4.L3`: LeftShift (`KeyCode 304`) becomes F8 (`KeyCode 289`). The original PadPS4 method is still called first, so physical controller L3 behavior is unchanged. The existing `isBlockedControls` guard and reset-sensitive `GetKeyDownInt`/`GetKeyInt` choice are also unchanged. LeftShift is not retained as a second keyboard mapping because doing so would require new wrapper logic; in this candidate F8 replaces the keyboard LeftShift fallback.

## Exact candidate

- Baseline: `work/patched-client-keyboard-buttons/GameAssembly.dll`, SHA-256 `3ddc1eb903eda90be06cc7079e2afa584d250b4430455b86564150fa05949703`
- New scratch copy: `work/patched-client-keyboard-focus/GameAssembly.dll`, SHA-256 `ec6f909d3af35c89cd287a2803b86839cd5d1b168bc1f76517eed2494c85e01b`
- Creation-time manifest: `work/evidence/keyboard-focus-prepared-copy.json`, SHA-256 `ddf57425aae16cfe6a9c49d80e11be3e87ee25394d3b01b09537a1d23b3e64ec`. Its `target_executed=false` field remains an accurate record of preparation time and was not rewritten after runtime testing.
- Authoring tool: `outputs/nebula-preservation/tools/keyboard_focus_patch.py`, SHA-256 `cb8156a3cc4ab0f0114ae5736ad18a10086e220abf8b00e89767a0d46eb0a955`
- Offline tests: `outputs/nebula-preservation/tools/keyboard_focus_offline_tests.py`, SHA-256 `87813a249b9d1eade38866200e4eec652767adb28a755d6e342890fbcca050d7`

At `.nbk` L3 stub RVA `0x2e3d05d`, `41 ba 30 01 00 00` (`mov r10d,304`) becomes `41 ba 21 01 00 00` (`mov r10d,289`). This changes one semantic file byte at `0x2b82c5f`; the only other changed bytes are the PE checksum at file offset `0x180`.

## Bounded F8 reservation check

The reviewed `dump.cs` defines `F7=288`, `F8=289`, and `F9=290`. A Capstone scan of the original native image (SHA-256 `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`) found two direct calls to `UnityEngine.Input.GetKeyInt` / `GetKeyDownInt`; their recovered immediate arguments were 273 and 274, not 289. The installed 48-axis InputManager copy (SHA-256 `70a141380052f0c2eb0d64c8bad71961648fe9791d79a6b2da37924b9bff4775`) contains no case-insensitive `f8` string in its named or positive/negative binding fields.

This is deliberately bounded evidence. It does not exclude indirect or reflection-based consumers that do not expose an immediate argument or serialized binding.

## Offline verification

Eight tests passed. They establish deterministic output, strict source-hash rejection, existing/aliased/Steam-path refusal, the controller-first policy model, the single-byte semantic diff, and preservation of all ten entry redirects, the other nine fallback key codes, every PE section header, all 138,032 runtime-function records, and the exception-directory bytes. No game, UI, listener, runtime attachment, native function, synthetic input, or network operation was used.

## Narrow runtime result

The exact candidate hash above was launched as native PID 25748 and reached Nexus with the restored jacket. The start record is `work/integration-state/native-nonmini-f8-start.json`, SHA-256 `dca23fe14a5b1ce4a842474b457efbd1568b5705cb1cb3fcb1a786be6b612868`. After one native F8 press, a closed read-only field probe recorded `Chat.isFocused=1`, `Chat.isTyping=0`, a non-null selected `GameObject`, active `PS4InputModule`, and all observed menu/pad gates clear. That record is `work/integration-state/chat-focus-f8-first-native-press.json`, SHA-256 `65dc9cae764ab84e329dbe12a866cb2bb24c68b61df194e8a4118865993e345d`.

This passes the narrow intended mapping: F8 activates the pre-existing L3 fallback and focuses chat. It does not by itself validate every downstream tab, notification, submit, controller-coexistence, or exception-unwind path. Those remain separately evidenced concerns.
