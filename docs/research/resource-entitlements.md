> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Companion and locomotion entitlements

This reconstruction uses Steam919290 build11018722, Unity2021.3.9f1 IL2CPP. It is entirely static. No game, server, listener, live connection, payment or real account operation was performed. The original service's ownership, prices, labels and grant rules remain unknown.

## Exact HTTP fields

NETGCloudSpace.Send_GetCompanionsIDAssetsCoroutine.MoveNext RVA0x3fa400 and Send_GetLocomotionsIDAssetsCoroutine.MoveNext RVA0x3fbc20 create the logical request `SessionGUID#PS4ID`. Both call the same AES.Encrypt RVA0x6a32c0, which internally appends `#platformName` before UTF8 encoding and AES encryption. Windows wire plaintext is therefore `SessionGUID#PS4ID#StandaloneWindows`. The ciphertext is URI-escaped into GET `/GetCompanionsServlet?data={0}` or `/GetLocomotionsServlet?data={0}`. Existing Request.parse platform validation applies to these direct coroutines too.

Both decrypted response DTOs have the same plain string grammar:

[Code/listing block omitted from the public research archive.]

Empty inventory is exactly `true#SessionGUID`. The native reader splits on `#` with empty fields retained, requires field0 exact lowercase `true`, and requires field1 to equal local PS4Info.SessionGUID. Every nonempty field from index2 onward is an item ID. There is no JSON, count, display-name array, gender or nonempty trailer. Empty tokens are skipped. The menu must still be active before population; no IDs invokes its empty-state callback. Companions call MenuWheelPets.AddPetAssets RVA0x4bd390; locomotions call MenuWheelLocomotions.AddLocomotionAssets RVA0x4bbc90.

## Shipped IDs and assets

The generated `resource-entitlements.json` contains328 canonical prefabs:219 companions and109 locomotions. It records original-case IDs, actual asset paths, lowercase bundle filenames, thumbnails, dependencies and manifest hashes, with native source hashes. The current local policy accepts327 entries. One locomotion, `RRYfEeOcrt3MS0jtdiNvV02cnUKK630W`, has a canonical prefab but its direct thumbnail is in the unexpected bundle `th/rryfeeocrt3ms0jtdinvv02cnukk630wthumbnail1`; the unsuffixed thumbnail bundle contains a nested resource under another item. It is flagged and rejected pending loader-resolution evidence.

Canonical companion bundles use `02/{lowercaseID}` and locomotions use `03/{lowercaseID}`. NebulaPlayer.InstantiateCompanion.MoveNext RVA0x6eaee0 and NebulaPlayerAnim.InstantiateLocomotion.MoveNext RVA0x604760 request the original-case resource paths:

[Code/listing block omitted from the public research archive.]

The corresponding canonical manifest asset ends in `{category}/{itemID}/{itemID}.prefab`. The menu builds thumbnail resource paths `Wardrobe_EAB/COMPANIONS/{itemID}/{itemID}Thumbnail` or `Wardrobe_EAB/LOCOMOTIONS/{itemID}/{itemID}Thumbnail`. Dependency paths retain original developer build-drive prefixes; runtime resolution has not been exercised.

Seven resource-asset rows under these bundle prefixes are excluded: three companion dependency prefabs, one nested locomotion dependency prefab, and three wardrobe FBX resources placed under prefix03. A bundle prefix by itself does not establish an independently grantable companion/locomotion. No category is inferred for these excluded assets.

Run the static generator with `python outputs/nebula-preservation/tools/inspect_resource_catalog.py`. It reads the extracted bundle manifests and existing Ghidra pseudocode; it does not execute the target.

## Local SQLite module and administration

`backend/resources.py` creates a separate `resource_entitlements` table through the existing Store.db. Its key is `(ps4_id,kind,item_id)`; kinds are exactly `companions` and `locomotions`. Grants require a known, nonconflicting ResourceCatalog entry. There are no automatic grants. Local names default to the item ID; explicit names are reconstructed local labels. Regranting is idempotent, preserves the original grant timestamp and updates an explicitly supplied label. Wardrobe grants and real commerce are independent.

The API is:

[Code/listing block omitted from the public research archive.]

`response` validates the session/account binding and emits the exact collection DTO. `purchase_fields` supplies companions, companionsName, locomotions and locomotionsName for merging into the existing PurchasesData JSON. Each ID list has a parallel same-length label list. Constructing with a catalog revalidates stored IDs on read; catalog-less use assumes the persisted table contains grants previously validated by this module.

Offline CLI examples (the grant is an explicit local database mutation):

[Code/listing block omitted from the public research archive.]

These commands never start a service or contact Steam. `catalog` does not open a state database. The grant command can create the named local account using Store.account; it cannot process a commercial purchase or unlock an unknown asset.

The seven resource-specific offline tests forbid socket creation. They check canonical identity/casing, rejection of unknown/conflicting mappings, exact empty/populated native DTOs, account binding, persistence, parallel purchase labels, explicit regrant label updates and the AES-added platform trailer. This verifies the local implementation against static contracts, not successful in-game instantiation or multiplayer synchronization.
