> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Keyboard input compatibility

The private copy adds a bounded keyboard path to the client’s existing `PS4InputModule` configuration. It does not modify the Steam installation or emulate a PS4 controller. The world-control variant was installed in the private client and now has runtime evidence for Return, arrow navigation, and measured W movement.

## Why this patch is needed

The bootstrapped login screen has an active `EventSystem`, focus, navigation events, and a selected object, but its sole input module is `PS4InputModule`. The ordinary `StandaloneInputModule.Process` path is not running. Observational hooks did not see the login click or Submit handlers execute.

The recovered native bodies provide a narrower keyboard route:

- `PS4InputModule.SendSubmit` at RVA `0x4244c0` calls `Input.GetButtonDown` with the serialized Submit axis name.
- `PS4InputModule.GetRawMoveVector` at RVA `0x4236e0` calls `Input.GetAxisRaw` for the serialized horizontal and vertical names. It returns those values directly, so vertical navigation is positive for up and negative for down.
- The reviewed `Process` and `ProcessMouseEvent` bodies obtain mouse button state, but do not establish a complete `StandaloneInputModule`-style pointer dispatch path.

This supports an initial keyboard compatibility patch under the logical input names the module already consumes.

## Exact authored changes

The hash-bound source is the installed Unity 2021.3.9f1 `globalgamemanagers` file, SHA-256 `ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466`.

Only its single `InputManager` object is changed:

- the unique `Submit` row gains `positiveButton = return`;
- its existing `altPositiveButton = joystick 1 button 0` remains intact;
- one keyboard `dpad1_horizontal` row is appended with left/right buttons;
- one keyboard `dpad1_vertical` row is appended with down/up buttons;
- both appended rows are type 0 with gravity and sensitivity 1000 and dead zone 0.001;
- the original joystick-backed `dpad1_horizontal` and `dpad1_vertical` rows remain unchanged.

Unity’s Input Manager permits repeated logical names. `Input.GetAxisRaw("dpad1_horizontal")` and `Input.GetAxisRaw("dpad1_vertical")` can therefore retain the existing controller sources while gaining keyboard sources.

## Prepared private copy and verification

The generated copy is `work/patched-input/globalgamemanagers`, SHA-256 `54c632afc0db42a5b39af4084428efbb28de6241c0aea7401a74eaac1dc822c6`. Its machine-readable generation record is `../client-fixes/prepared-keyboard-input-copy.json`.

Static verification established:

- UnityPy reparses the serialized copy as Unity 2021.3.9f1;
- the axis count changes from 42 to exactly 44;
- every original axis row is identical except the requested Submit field;
- the two appended keyboard rows exactly match the authored policy;
- raw bytes of all 17 non-InputManager serialized objects hash identically before and after;
- the original installed file retains its reviewed SHA-256;
- five automated round-trip and fail-closed guard tests pass, including the optional world-control mode.

## World-control variant

Passing `--world-controls` retains the exact base changes and appends four more type-0 keyboard rows:

- `leftstick1horizontal`: A negative, D positive;
- `leftstick1vertical`: W negative, S positive;
- `rightstick1horizontal`: J negative, L positive;
- `rightstick1vertical`: I negative, K positive.

The vertical signs intentionally match the shipped physical joystick convention, where stick-up is negative. The native `PadPS4.LStick_Vertical` getter returns the configured input value without an added inversion. All original controller-backed stick rows remain intact.

The prepared copy is `work/patched-input-world/globalgamemanagers`, SHA-256 `70a141380052f0c2eb0d64c8bad71961648fe9791d79a6b2da37924b9bff4775`. Its manifest is `../client-fixes/prepared-keyboard-world-input-copy.json`. It reparses with 48 axes and preserves raw hashes for all 17 non-InputManager objects. That exact hash is installed in the current private integration client.

Add `--world-controls` to the command below and select the world-copy destination/manifest paths to generate this variant.

Generate a new copy with:

[Code/listing block omitted from the public research archive.]

The tool refuses an unknown source hash, an existing output, source/output aliases, non-JSON or aliased manifests, and any destination or manifest under `steamapps`.

## Unhooked runtime evidence

The private Windows client used `GameAssembly.dll` SHA-256 `3ddc1eb903eda90be06cc7079e2afa584d250b4430455b86564150fa05949703` with `globalgamemanagers` SHA-256 `70a141380052f0c2eb0d64c8bad71961648fe9791d79a6b2da37924b9bff4775`, without Frida hooks.

The first UI stage established that Return completed login, arrow keys changed focused UI icons, and Return activated selections. Those inputs opened the character editor and clothing view, selected an owned torso, and a single Right increment visibly moved the height slider and made the avatar taller. At that dated intermediate stage Save Preset displayed a blank rectangle, retained as `../runtime-screenshots/preset-save-blank.png` (SHA-256 `d114cb10b5e6c2c213067ff8f0c2d5702e355dc711149e40b2f58065cf3f83d2`), and one short W press produced only a visible orientation/response. Those observations are preserved as history, not current blockers.

Subsequent unhooked evidence supersedes those two limits:

- 20 discrete W presses translated the native avatar `5.131479731560391` world units. No held-key API was used, so this proves repeated W-axis consumption and translation, not held-key behavior. The source-bound record is `windows-native-core-flows.json` (SHA-256 `2d1b43296505f0c4d622957463760f0de734c1549c3a66f5b19cf598879f84dd`); `../runtime-screenshots/native-walking.png` has SHA-256 `f9169df94c07f0dc488f5d3750a514fade4bfcc67c7d9ea2c674c193d352f798`.
- The V2 preset-input compatibility copy allowed a named preset to be saved, listed, and loaded. `../runtime-screenshots/preset-load-list.png` has SHA-256 `bb3c95f99ad003064df1a2aaabaa9ceeeb4cd312510c0677f6a3dd7690b52697`.
- C exposed chat through the separate `PadPS4.R3` fallback, and Return started input through the InputManager Submit row. The earlier attribution of chat focus to Left Shift is retracted: a later discriminating read-only probe after an explicit Computer Access `Shift_L` press recorded `Chat.isFocused=0`, `Chat.isTyping=0`, and all observed manager/pad gates clear. Return can start input independently, so the completed public-chat round trip remains valid evidence for Return and the broader chat path, but not for a successful LeftShift/L3 fallback. The round trip is visible in `../runtime-screenshots/linux-public-chat.png`, SHA-256 `db9b7c1cdbe7abafbb3862ebe9c13b3543448ca8cfb715800fb5247bb440f5bb`.
- The same broader flow bought the red jacket for 25 crystals, equipped and saved it, and a fresh Linux-backed login restored the jacket, 475 crystals, 200 NP, Music `0.9`, and the owned offer. This is end-to-end preservation evidence, not evidence for additional keyboard aliases. The bounded screenshots are `../runtime-screenshots/red-jacket-equipped.png` (`8a304e57ac183841ceb7a1f2346a4b4668f84c235fee8f6d403ae1070d353f47`) and `../runtime-screenshots/linux-settings-wallet.png` (`808282d93e2682f83c9333aff53b24b1fce2c70a35327da5b849f8b1adb6dcb0`).

M and C successfully exercised separate native `PadPS4` wrappers and are documented in [keyboard-buttons-compatibility.md](keyboard-buttons-compatibility.md). The Computer Access `Shift_L` attempt exercised the L3 test surface but did not toggle chat focus; this does not establish that a physical keyboard Left Shift can never work. The later F8 compatibility mapping did focus chat in native runtime, with exact evidence in [keyboard-focus-compatibility.md](keyboard-focus-compatibility.md). Return, arrows, and W are the direct InputManager evidence here. A/S/D, I/J/K/L camera behavior, mouse pointer dispatch, held-W behavior, controller emulation, and full input parity remain unproven.

Machine-readable evidence, exact fields, native source hashes, and limitations are in [keyboard-input-compatibility.json](keyboard-input-compatibility.json).
