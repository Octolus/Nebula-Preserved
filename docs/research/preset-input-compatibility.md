> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Preset name input compatibility

The blank dark rectangle is the shipped PC preset-name `InputField`, not a missing popup asset. The focus-only compatibility copy successfully produced a caret and accepted `PreservationTest`. A follow-up trace then showed Return finishing and deactivating the field without invoking its serialized `OnSavePreset` listener. The v2 private copy retains the focus action and migrates that legacy listener to the 2021 runtime end-edit field name.

## Shipped flow and failure

The CharacterEditor bundle is SHA-256 `5d1713e79b4e5bab090a3d57eb4d4c4139999629bb4a2038412a6cb92d1b02e0`. In `BuildPlayer-CharacterEditor`:

- `BTNMENU_SavePreset` is GameObject path `1603`; its Button component is path `22207`.
- The Button first calls the empty `CE_Menu.onClickBTNMENU_SavePreset`, then `SavePresetName.Show` on component path `38388`.
- `Show` at RVA `0x671220` disables the main EventSystem GameObject and activates `InputFieldSavePresetName` GameObject path `5152`.
- The editable `InputField` is component path `38565`. It is single-line, writable, initially empty, has no placeholder, and has no PC character limit.
- Its existing `onEndEdit` calls `SavePresetName.OnSavePreset`.

`Show` never selects the field and never calls `ActivateInputField`. Therefore the observed lack of caret is an actual focus failure. Pressing Escape does not visibly recover because `SavePresetName` has no cancel handler, and an empty `OnSavePreset` returns without hiding the rectangle.

The scene also contains an active `EventSystemPCSavePreset` at component path `15015`, whose first-selected GameObject is the name field. It was already active while that field was inactive, so the initial selection is not a reliable focus path and `Show` does not request it again.

## Minimal compatibility action

The candidate preserves both original Button actions and appends exactly one third persistent call:

[Code/listing block omitted from the public research archive.]

No EventSystem is reactivated. After `Show`, the dedicated PC-save EventSystem remains active. `ActivateInputField` sets the field’s next-update activation flag; `ActivateInputFieldInternal` then sees that current EventSystem, selects GameObject `5152`, and enables keyboard/caret state. Reactivating the main EventSystem would create competing active EventSystems and is unnecessary.

### 2018-to-2021 end-edit migration

The focus-only runtime trace recorded `InputField.KeyPressed` returning Finish, `DeactivateInputField` running, and input becoming inactive. `SavePresetName.OnSavePreset` was never called and no `N2SavePreset` request appeared.

The 2021 client declares:

- `m_OnSubmit` at offset `0x130`, with `FormerlySerializedAs` aliases including `m_OnEndEdit`;
- the distinct `m_OnDidEndEdit` event at offset `0x138`, which `DeactivateInputField` invokes.

The 2018 CharacterEditor type tree names its listener `m_OnEndEdit`. Type ID 85 is used only by preset InputField path `38565`. V2 therefore renames exactly that type-tree node to `m_OnDidEndEdit`. The UnityEvent payload and listener bytes remain unchanged, and every other node is identical. This is the smallest asset migration matching the runtime field actually consumed by deactivation.

The trace did not directly expose both deserialized event-field pointers, so this began as a causal inference. The V2 runtime result now validates the migration behaviorally: Return closes the field and the native save route executes.

The intended normal action sequence is:

1. Select Save Preset and press Return.
2. Type `PreservationTest`.
3. Press Return to finish the single-line edit.
4. The existing `onEndEdit` invokes `OnSavePreset`, which hides the field for a nonempty name, restores the Save button selection after one frame, and calls `ManagerPreset.Save` with the current gender.

The PS4-specific alternative is `DialogPS4.OpenIMESavePreset` at RVA `0x6a3fc0`. It returns on PC; otherwise it opens Sony IME titled `Save Preset`, with an empty initial value and a 16-character maximum. `PreservationTest` is exactly 16 characters.

## Prepared private copy

The v2 candidate is `work/patched-preset-input-v2/charactereditor`, SHA-256 `9a2cdcaa9ac356fe95df9b5a5ad5df6bba93330ad1591685553031729628d3c4`. Its manifest is `../client-fixes/prepared-preset-input-v2-copy.json`. The earlier `d5ed36e3…` focus-only copy and manifest remain retained as historical evidence.

The generator modifies only Button object path `22207`. An actual UnityPy bundle round trip proves:

- both original calls are byte-equivalent in the serialized tree and remain first;
- the new focus call is exactly third;
- all other 41,050 serialized-object and streamed-resource hashes are unchanged;
- the CharacterEditor serialized Unity version remains 2018.4.36f1;
- the original Steam bundle retains its reviewed hash;
- six fail-closed, schema-migration, and round-trip tests pass.

Generation command:

[Code/listing block omitted from the public research archive.]

The tool rejects unknown source hashes, existing outputs, aliases, invalid manifests, and destinations under `steamapps`.

## V2 runtime result

V2 passed the bounded native flow in an unhooked private client using bundle SHA-256 `9a2cdcaa…`:

- `PreservationTest` was entered with visible focus.
- Return closed the name panel and returned to the editor.
- `N2SavePreset` returned HTTP 200 with a nine-byte response.
- `ShowPresetsServlet` returned HTTP 200, and the visible list contained both `Default` and `PreservationTest`.
- Selecting `PreservationTest` produced the expected native `GetLoadPresetByName` request and a 10,183-byte HTTP 200 response.
- The post-save account checkpoint contains the male `PreservationTest` preset with stored `b73 = 100`, distinct from the Default preset’s `b73 = 0`.

The request-shape check was performed without recording account or session identifiers in this report. Screenshots are retained at `../runtime-screenshots/preset-name-entered.png` and `../runtime-screenshots/preset-load-list.png`; their exact hashes and request hashes are in the JSON report.

The named save, durable listing, and named load request are proven. The tester thought the avatar may have become shorter after loading but could not confirm the visual result, so exact morph reapplication is **not** claimed. Fresh-process reconnect persistence was also not separately retested in this bounded run.

The screenshot, exact native hashes, serialized fields, runtime evidence, and limitations are recorded in [preset-input-compatibility.json](preset-input-compatibility.json).
