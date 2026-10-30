# Private catalog image pack

The dashboard can show actual item previews extracted from a matching local game installation. Images are optional private deployment data; they are not included in the source repository or Docker image. The extractor does not launch the game, contact a server, download assets, or change the installation.

Use Python 3.11 or newer and install the extraction dependencies:

```sh
python -m pip install -r tools/requirements-catalog-previews.txt
python tools/extract_catalog_previews.py --game "/path/to/Nebula Realms" --output "/private/catalog-preview-pack"
```

On Windows, quote paths with spaces. `--game` accepts the installed game directory, its `Nebula Realms_Data` directory, or the game executable. `--output` must be an empty directory outside this repository. Keep the generated pixels out of Git. Extraction checks the resource build against the validated protocol catalog and stops for an unsupported resource hash.

The extractor reads shipped thumbnail manifests, resolves each exact AssetBundle container entry to its Sprite and texture reference, and decodes the actual image. It also resolves shop artwork through the original ResourceManager object pointers. It does not guess product identity from a filename. Unicode item IDs remain exact; the shipped Unity container lowercases ASCII while retaining non-ASCII case.

The validated catalog covers 7,688 ordinary items: 6,210 wardrobe items, 219 companions, 108 locomotions and 1,151 furniture items. There are 7,686 recovered item previews; the two known wardrobe items without their own thumbnail use an explicitly labeled generic shop icon. All 1,205 shop artwork resources can be decoded, including two texture-only resources. Duplicate manifest entries are accepted only when their decoded dimensions and RGBA pixels agree.

The completed pack contains root-level `index.json` and `<64-hex-key>.webp` files, plus `_research/` evidence and a sample contact sheet. Item keys are SHA-256 of the exact shop thumbnail path after replacing backslashes with slashes and lowercasing, preserving the `.png` suffix. Artwork keys use the exact resource key after the same normalization, without adding an extension. The index records dimensions, output hashes, source bundle hashes and object references; it contains no installation path or machine account name.

Previews are at most 256 pixels on either side. The validated pack has 8,892 distinct WebP files, approximately 61 MiB of image data and 8 MiB of index metadata. The generic image is shared by its two item references. Original item names, original prices and historical item-to-store membership remain unknown; image recovery does not establish those commercial records.

For deployment, archive **only** `index.json` and the root-level `*.webp` files, with regular files at archive root. Exclude `_research/`, sample sheets and local databases. The private preview pack is separate from ordinary source and image publication. Follow the deployment documentation for the configured private pack installation and authenticated dashboard delivery.

The extractor records failures rather than substituting a different item's picture. Inspect `_research/preview-evidence.json`: expected item summary is `decoded: 7686` and `generic_fallback_no_own_thumbnail: 2`; expected artwork summary is `decoded: 1205`. Native game acceptance is a separate test; decoding previews does not prove purchases or equipping work in a running client.
