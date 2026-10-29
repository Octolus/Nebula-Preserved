> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Wardrobe removal sentinels

The native character editor removes an equipped optional category through a normal wardrobe tile. It is not a storage/delete action and it has no separate controller shortcut.

`Utils::.ctor` at RVA `0x4e3030` builds a fixed 30-ID list in field `+0x18`. `CW_Wardrobe::ImgOnclickPS4` at `0x49a8f0` checks that list before ordinary asset loading; a match enters the category-removal branch. The tile's ordinary submit/click listener therefore is the intended unequip action. `paintAssets` creates the tile dynamically from the `GetInfoServlet` response, while the shipped CharacterEditorV2 bundle contains no static empty-item tile.

The service emits all 30 native list members. Twenty are validated as ordinary wearable-manifest entries through `avatar-asset-catalog.json`. The other ten are removal controls with no FBX/Maps asset; each is instead bound to its exact shipped thumbnail bundle, manifest digest, gender, category, and `.../<ID>/<ID>Thumbnail.png` path. That distinction matters: the native removal branch runs before prefab loading, so a removal control needs its renderable thumbnail but is not itself wearable equipment.

Removal tiles have status `1`, item type `1`, and display label `Remove`. They are appended only to ordinary wardrobe view `0`. They are never inserted into `entitlements`, purchases, storage view `1`, or deleted view `2`. Existing sentinel rows are filtered from every inventory-backed view, and `WardrobeOptionItemServlet` rejects favorite/storage/delete mutations for every sentinel before touching the database. The existing preset save validator continues to reject a sentinel as unowned equipment; the native removal branch instead deletes the current category from the locally composed preset before save.

Twenty-four controls also occur in Utils field `+0x10`, so `CW_Item::onUpdateSelected` suppresses their Triangle options menu. The torso-apparel and left/right hand-item controls for both genders occur only in `+0x18`; their ordinary submit still removes the category, but Triangle can open the generic menu. The service-side mutation guard makes that menu harmless for these response-only controls.

The originally observed male HAT control is `G4q7p8V2H2W23CPU285X2d6r05vU0aCY`. Selecting it and submitting takes the native removal branch. A subsequent `N2SavePreset` contains no sentinel and no removed hat, while ownership of the real hat is preserved.

## Verification

`test_wardrobe_removal.py` has six offline cases. It verifies all 30 controls and their ordinary/storage/deleted behavior, cross-checks the 20 wearable rows against the avatar catalog and the ten thumbnail-only rows against the exact raw shipped bundle manifests, rejects all four menu-triggered status mutations for every control, filters a simulated historical sentinel entitlement, rejects sentinel-as-equipment, and saves/reloads a removed male HAT while preserving the real hat entitlement and wallet.

This is static/native-source and offline service evidence. Native runtime verification of the expanded 30-control response remains pending a service restart by the integration owner.
