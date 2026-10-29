> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Mixed world interaction registries

This bounded audit reuses the complete shipped logic-prefab inventory and reopens only its failed MonoBehaviour references in seven relevant bundles. No game, target attach, UI, server, listener or connection was used. `mixed-world-registries.json` records source bundle/component hashes, native-body hashes and classifications; `tools/mixed_world_registry.py` reproduces the audit. The parent owns WorldState integration; this audit does not edit that module or establish runtime readiness.

## Correct ID assignment

Native `NebulaInteractor.ctor0x5df620` writes UInt64 `0xffffffffffffffff` at offset0x38. Metadata identifies two adjacent Int32 fields, `nextId` at0x38 and `nextGenericInteractableId` at0x3c. Both start−1. `Initialize0x5decf0` does not reset them. `AddGenericInteractable0x5deab0` preincrements the generic counter, then invokes the virtual Id setter. **The first assigned generic ID is0, and a baseline with N components uses0..N−1.** The earlier1..N count policy was incorrect and has been reported to the parent for source/test correction.

OnConnected's native state machine `0x5ea6e0` calls `FindObjectsOfType<GenericInteractable>` and initializes each returned array element in order. Generic wrapper `0x8951e0` passes `includeInactive=false` to `0x1b8b0f0`; the latter calls the Unity engine internal-call pointer. These recovered bodies do not expose the engine's mapping from instantiated Unity objects to array order. Serialized path IDs, bundle record order and hierarchy order are not wire IDs. A single typed active component establishes baseline ID0 without requiring an ordering between different subtypes; multiple mixed subtypes do not.

`HousingFurnishing.SaveAtServer0x6bdb40` also enumerates GenericInteractable children of placed housing objects and invokes the same Initialize. This advances the counter for later and repeated registrations. `ResetOccupables0x5df300` removes null occupables but does not reset the generic counter. Consequently a placed-object save can invalidate a static ID map even without changing the number of objects. Such IDs require a registration epoch/history, not merely an increased static upper bound.

## Missing scripts resolved as placeholders

All495 previously unresolved class reads in the audited bundles have the same precise structure:

- `m_Script={m_FileID:0,m_PathID:0}`.
- Serialized script type index−1.
- Script ID and old type hash both16 zero bytes.
- Exactly32 serialized bytes, containing only GameObject pointer, enabled flag, null script pointer and empty name/base fields.

These are missing-script placeholders. There is no nonzero MonoScript reference, script hash or external-file key to resolve through the global script map. Guessing their former classes from GameObject names would add unsupported behavior. Their exclusion from a typed GenericInteractable enumeration is a source-based inference rather than a running-client observation; the data no longer supports describing them as unknown recoverable generic subtypes.

| Scene | Null-script placeholders | Active ordinary generic | Active deferred generic | Static conclusion |
|---|---:|---:|---:|---|
|Bowling|449|0|0|Verified empty active generic baseline. Other minigame systems exist independently.|
|TheNebulian|21|1|0|DayNightBasicCycle/TimeControl at baseline ID0.|
|TheNebulianOpenHouse|21|0|0|TimeControl exists but its GameObject is initially inactive, so it is excluded by this enumeration.|
|LeafPark|4|0|0|Verified empty generic baseline; separately established boats and coffee remain.|
|CampSilverLake|0|8|1|Exact ordinary wire-ID map unresolved.|
|CutteridgeEstate|0|2|1|Exact ordinary wire-ID map unresolved; seven additional deferred candles are initially inactive.|
|SorcerersEyrie|0|1|11|Exact ordinary wire-ID map unresolved.|

No genuinely unresolved nonzero script reference remains in this audit. The JSON keeps every original failing object's source fingerprint and the evidence behind that conclusion. Original parser errors remain in the larger world inventory as historical provenance, with an explicit resolution audit attached in the main protocol report.

## Ordinary components must remain explicit requirements

CampSilverLake's ordinary components are five JG_CampSilverLake_Door instances plus Time, Weather and the chalet fireplace. Its Killer launcher is deferred. CutteridgeEstate's ordinary components are JG_DoorInteractable and JG_WeatherInteractable; its Ghost game and candles are deferred. SorcerersEyrie's ordinary component is JG_SorcerersEyrie_TimeInteractable; eight ingredients, two recipe controllers and one potion controller are deferred.

Every packet supplies only actor GUID, runtime numeric ID, Boolean and optional data strings. Camp/Cutteridge ordinary and deferred components all use zero data strings. Sorcerers Time and Potion both use zero; ingredients use one and recipe controllers two. Packet length therefore cannot safely identify the ordinary target in any of these mixed scenes. The native receiver also identifies an object by numeric ID, not the requested class or GameObject name.

Minigame deferral leaves **eleven ordinary active components** across these three scenes as a concrete restoration gap. The current count-only closure prevents accidental minigame activation but does not satisfy restoration of those ordinary interactions. The report does not relabel that closure as a completed feature.

## Source-bound per-ID allowlist design

A future integration can admit ordinary IDs through a trusted map of `wire_id → allowed extension count`, with the deferred IDs excluded. Admission must select this exact map for mixed scenes rather than accepting every ID below the total count. The existing count policy remains useful for fully ordinary static baselines. Mixed admission must require an independently audited mapping, matching binary/bundle hashes and the same registration epoch for every connected client. Neither an untrusted C2S claim nor a guessed order establishes authority.

The offline `bind` command provides structural validation for a supplied initial enumeration. It requires a complete mapping rather than a partial ordinary-only list, so omitted deferred components cannot silently shift ordinals. The input fields are:

| Field | Requirement |
|---|---|
|`format_version`|1|
|`registration_epoch`|`initial_scene`; dynamic housing is rejected by this version.|
|`scene_key`|An audited scene key from the report.|
|`binary_sha256`, `bundle_sha256`|Exact report source hashes.|
|`evidence_artifact_sha256`|SHA256 of a separately supplied enumeration-evidence file.|
|`entries`|Every active typed generic exactly once, in claimed native order. Each has integer `wire_id` equal to its zero-based array ordinal, `asset_file`, `component_path_id` as string, and exact `raw_sha256`.|

The evidence file is hashed, not interpreted as executable code. The validator verifies completeness, uniqueness, source fingerprints, consecutive zero-based IDs and classification, then emits separate ordinary allowlist and deferred denylist. It deliberately emits **`native_order_verified:false` and `ready_for_automatic_admission:false`**: structural checks cannot prove that the supplied array order is the engine's actual order or that different clients agree. No real binding was generated during this audit. The offline test uses a synthetic order solely to verify validation behavior, never as a proposed native mapping.

An audited deterministic client mapping hook or a validated native enumeration observation could later supply the missing authority. That would be a separate compatibility change with its own evidence. Activation changes, later/repeated housing registrations, mismatched clients or a source hash change must invalidate the mapping rather than reusing stale numeric permissions. This tool adds no client hook and no runtime telemetry.

## Validation

`tools/mixed_world_registry_checks.py` verifies all seven scene counts and495 null-script records, checks first-ID0, exercises an explicitly unverified synthetic binding, and rejects ten malformed binding variants: unsupported epoch, wrong binary/bundle/evidence hashes, incomplete enumeration, nonconsecutive or Boolean ID, wrong component hash, unknown component and duplicate component. These checks run only Python metadata/validation code. They do not execute Unity or a network protocol.

The canonical game binary SHA256 remains `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`. Parent-owned compilation and existing protocol tests remain separate. The fresh source audit removes false script-uncertainty closures for Bowling/OpenHouse/LeafPark and identifies TheNebulian ID0; it does not supply the still-missing mixed-scene numeric order.
