#!/usr/bin/env python3
"""Extract a private preview pack from a locally installed, matching game build.

No game execution, downloads or uploads. Proprietary pixels stay outside Git.
"""
import argparse
import ast
import collections
import hashlib
import json
import string
import sys
from pathlib import Path

import UnityPy
import yaml
from PIL import Image, ImageDraw

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def logical(asset_path):
    if asset_path.startswith('"'):
        asset_path = ast.literal_eval(asset_path)
    marker = '/ResourcesART/'
    if marker not in asset_path:
        return None
    relative = asset_path.split(marker, 1)[1]
    if relative.startswith('Wardrobe_EAB/'):
        relative = relative.removeprefix('Wardrobe_EAB/')
    return relative


def extract_items():
    BASE.mkdir(parents=True, exist_ok=True)
    output = BASE / 'images'
    output.mkdir(exist_ok=True)
    service = Service(Store(BASE / 'state/catalog-evidence.sqlite'), Catalog(REPO / 'protocol'))
    inventory = CatalogInventory(service).items
    manifests = json.loads(SOURCE.read_text(encoding='utf-8'))
    lookup = collections.defaultdict(list)
    for manifest in manifests:
        for asset_path in manifest['assets']:
            if asset_path.startswith('"'):
                asset_path = ast.literal_eval(asset_path)
            path = logical(asset_path)
            if path and asset_path.lower().endswith('.png'):
                lookup[path].append((manifest, asset_path))
                full = asset_path.split('/ResourcesART/', 1)[1]
                if full != path:
                    lookup[full].append((manifest, asset_path))
    previous_rows = {}
    rows = []
    for index, item in enumerate(inventory):
        key = hashlib.sha256(json.dumps(identity(item), ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
        row = {k: item.get(k) for k in ['kind', 'item_id', 'gender', 'category', 'thumbnail_path', 'own_thumbnail_known']}
        old = previous_rows.get(tuple(row.get(k) for k in ['kind', 'item_id', 'gender', 'category']))
        if old and old['status'] in ('decoded', 'generic_fallback_no_own_thumbnail'):
            rows.append(old)
            continue
        row['preview_key'] = key
        candidates = lookup[item['thumbnail_path']]
        row['manifest_candidate_count'] = len(candidates)
        try:
            if item['thumbnail_path'] == 'Shops/shop.png':
                row['status'] = 'generic_fallback_no_own_thumbnail'
                rows.append(row)
                continue
            if len(candidates) > 1:
                equivalent = []
                for alternative, alternative_path in candidates:
                    alt_file = BUNDLES / alternative['bundle']
                    alt_env = UnityPy.load(str(alt_file))
                    expected = alternative_path.translate(str.maketrans(string.ascii_uppercase, string.ascii_lowercase))
                    alt_sprites = [obj for name, obj in alt_env.container.items() if name == expected and obj.type.name == 'Sprite']
                    if len(alt_sprites) != 1:
                        raise ValueError('duplicate manifest path has no unique Sprite')
                    alt_image = alt_sprites[0].read().image.convert('RGBA')
                    equivalent.append({'bundle': alternative['bundle'], 'bundle_sha256': digest(alt_file),
                                       'rgba_sha256': hashlib.sha256(alt_image.tobytes()).hexdigest(),
                                       'dimensions': list(alt_image.size)})
                if len({(r['rgba_sha256'], tuple(r['dimensions'])) for r in equivalent}) != 1:
                    raise ValueError('duplicate manifests resolve to different pixels')
                row['equivalent_duplicate_sources'] = equivalent
                candidates = candidates[:1]
            if len(candidates) != 1:
                raise ValueError('expected exactly one manifest resource mapping')
            manifest, asset_path = candidates[0]
            path = BUNDLES / manifest['bundle']
            row.update(bundle=manifest['bundle'], bundle_sha256=digest(path),
                       manifest_sha256=manifest['manifest_sha256'], asset_path=asset_path)
            env = UnityPy.load(str(path))
            expected = asset_path.translate(str.maketrans(string.ascii_uppercase, string.ascii_lowercase))
            pointers = [(name, obj) for name, obj in env.container.items() if name == expected]
            row['container_objects'] = [{'container_path': name, 'type': obj.type.name, 'path_id': obj.path_id}
                                        for name, obj in pointers]
            sprites = [obj for _, obj in pointers if obj.type.name == 'Sprite']
            if len(sprites) != 1:
                raise ValueError('expected exactly one container Sprite')
            sprite = sprites[0].read()
            image = sprite.image.convert('RGBA')
            row.update(sprite_path_id=sprites[0].path_id, sprite_name=sprite.m_Name,
                       texture_path_id=sprite.m_RD.texture.path_id,
                       texture_file_id=sprite.m_RD.texture.file_id,
                       source_dimensions=list(image.size))
            image.thumbnail((256, 256), Image.Resampling.LANCZOS)
            target = output / (key + '.webp')
            image.save(target, format='WEBP', quality=88, method=4)
            row.update(status='decoded', preview_file='images/' + target.name,
                       preview_sha256=digest(target), preview_bytes=target.stat().st_size,
                       preview_dimensions=list(image.size))
        except Exception as exc:
            row.update(status='error', error=type(exc).__name__ + ': ' + str(exc))
        rows.append(row)
        if index % 500 == 0:
            print(json.dumps({'processed': index + 1, 'total': len(inventory)}), flush=True)
    result = {'format_version': 1, 'unitypy_version': UnityPy.__version__,
              'manifest_extract_sha256': digest(SOURCE),
              'source_build': 11018722,
              'private_pixels_do_not_redistribute_without_authorization': True,
              'mapping': 'manifest asset path -> AssetBundle container exact normalized path -> Sprite object -> texture pointer',
              'summary': dict(collections.Counter(x['status'] for x in rows)),
              'by_kind': {kind: dict(collections.Counter(x['status'] for x in rows if x['kind'] == kind))
                          for kind in sorted({x['kind'] for x in rows})},
              'total_preview_bytes': sum(x.get('preview_bytes', 0) for x in rows),
              'rows': rows}
    (BASE / 'preview-evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    sheet_rows = []
    for kind in ['wardrobe', 'companions', 'locomotions', 'housing']:
        sheet_rows.extend([x for x in rows if x['kind'] == kind and x['status'] == 'decoded'][:8])
    sheet = Image.new('RGB', (8 * 160, 4 * 200), '#25282f')
    draw = ImageDraw.Draw(sheet)
    for i, row in enumerate(sheet_rows):
        image = Image.open(BASE / row['preview_file']).convert('RGBA')
        image.thumbnail((144, 144))
        x, y = (i % 8) * 160, (i // 8) * 200
        sheet.paste(image, (x + (160 - image.width) // 2, y), image)
        draw.text((x + 4, y + 148), row['kind'], fill='white')
        draw.text((x + 4, y + 164), row['item_id'][:18], fill='#ccd0d5')
    sheet.save(BASE / 'sample-sheet.jpg', quality=90)
    print(json.dumps({k: result[k] for k in ['summary', 'by_kind', 'total_preview_bytes']}), flush=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_key(resource):
    return hashlib.sha256(resource.replace('\\', '/').lower().encode('utf-8')).hexdigest()


def finalize_pack():
    PACK.mkdir(exist_ok=True)
    evidence = json.loads((BASE / 'preview-evidence.json').read_text(encoding='utf-8'))
    entries = {}
    for row in evidence['rows']:
        row['preview_key'] = canonical_key(row['thumbnail_path'])
        if row['status'] != 'decoded':
            continue
        key = row['preview_key']
        target = PACK / (key + '.webp')
        data = (BASE / row['preview_file']).read_bytes()
        if target.exists() and target.read_bytes() != data:
            raise ValueError('same resource key resolved to unequal pixels')
        target.write_bytes(data)
        row['pack_filename'] = target.name
        entries[key] = dict(key=key, filename=target.name, sha256=sha(target), bytes=len(data),
                            width=row['preview_dimensions'][0], height=row['preview_dimensions'][1],
                            resource_key=row['thumbnail_path'], source_kind='item_bundle_sprite',
                            source_bundle=row['bundle'], source_bundle_sha256=row['bundle_sha256'],
                            source_manifest_sha256=row['manifest_sha256'],
                            sprite_path_id=row['sprite_path_id'], texture_path_id=row['texture_path_id'])
    managers = UnityPy.load(str(GAME / 'globalgamemanagers'))
    manager = managers.file.objects[13]
    assert manager.type.name == 'ResourceManager'
    assert str(managers.file.externals[3].path).endswith('resources.assets')
    container = manager.read_typetree()['m_Container']
    source = UnityPy.load(str(GAME / 'resources.assets'))
    grouped = collections.defaultdict(list)
    for resource, pointer in container:
        if resource.startswith('shops/'):
            grouped[resource].append(pointer)
    source_hash = sha(GAME / 'resources.assets')
    manager_hash = sha(GAME / 'globalgamemanagers')
    texture_sidecars = {name: sha(GAME / name) for name in ['resources.assets.resS', 'resources.resource']}
    artwork = []
    for number, (resource, pointers) in enumerate(sorted(grouped.items())):
        row = {'resource_key': resource, 'resource_manager_path_id': 13,
               'resource_pointers': pointers, 'source_sha256': source_hash,
               'resource_manager_sha256': manager_hash, 'texture_sidecar_sha256': texture_sidecars}
        try:
            objects = [source.file.objects[p['m_PathID']] for p in pointers if p['m_FileID'] == 4]
            sprites = [o for o in objects if o.type.name == 'Sprite']
            textures = [o for o in objects if o.type.name == 'Texture2D']
            if len(sprites) == 1:
                sprite = sprites[0].read()
                image = sprite.image.convert('RGBA')
                object_kind = 'resource_manager_sprite'
                sprite_id = sprites[0].path_id
                texture_id = sprite.m_RD.texture.path_id
            elif len(sprites) == 0 and len(textures) == 1:
                image = textures[0].read().image.convert('RGBA')
                object_kind = 'resource_manager_texture'
                sprite_id = None
                texture_id = textures[0].path_id
            else:
                raise ValueError('expected one Sprite or an unambiguous texture-only resource')
            row['source_dimensions'] = list(image.size)
            image.thumbnail((256, 256), Image.Resampling.LANCZOS)
            key = canonical_key(resource)
            target = PACK / (key + '.webp')
            image.save(target, format='WEBP', quality=88, method=4)
            entry = dict(key=key, filename=target.name, sha256=sha(target), bytes=target.stat().st_size,
                         width=image.width, height=image.height, resource_key=resource,
                         source_kind=object_kind, source_bundle='resources.assets',
                         source_bundle_sha256=source_hash, source_resource_manager_sha256=manager_hash,
                         texture_sidecar_sha256=texture_sidecars,
                         sprite_path_id=sprite_id, texture_path_id=texture_id)
            if key in entries:
                raise ValueError('artwork and item resource key collision')
            entries[key] = entry
            row.update(status='decoded', preview_key=key, pack_filename=target.name,
                       sprite_path_id=sprite_id, texture_path_id=texture_id, source_kind=object_kind)
            if resource == 'shops/shop':
                generic_key = canonical_key('Shops/shop.png')
                generic_target = PACK / (generic_key + '.webp')
                generic_target.write_bytes(target.read_bytes())
                entries[generic_key] = {**entry, 'key': generic_key, 'filename': generic_target.name,
                                        'resource_key': 'Shops/shop.png', 'source_kind': 'explicit_generic_fallback',
                                        'source_resource_key': resource}
        except Exception as exc:
            row.update(status='error', error=type(exc).__name__ + ': ' + str(exc))
        artwork.append(row)
        if number % 200 == 0:
            print(json.dumps({'artwork_processed': number + 1, 'total': len(grouped)}), flush=True)
    for row in evidence['rows']:
        if row['status'] == 'generic_fallback_no_own_thumbnail':
            assert row['preview_key'] in entries
            row['pack_filename'] = entries[row['preview_key']]['filename']
    index = {'format_version': 1, 'private_proprietary_pixels': True,
             'key_algorithm': 'sha256(resource_key.replace(backslash, slash).lower().encode(utf-8))',
             'entries': list(entries.values())}
    (PACK / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    evidence['artwork_rows'] = artwork
    evidence['artwork_summary'] = dict(collections.Counter(r['status'] for r in artwork))
    evidence['pack_summary'] = {'unique_preview_files': len(entries),
                                'preview_bytes': sum(r['bytes'] for r in entries.values()),
                                'index_bytes': (PACK / 'index.json').stat().st_size}
    (BASE / 'preview-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    samples = []
    for kind in ['wardrobe', 'companions', 'locomotions', 'housing']:
        samples.extend([r for r in evidence['rows'] if r['kind'] == kind and r['status'] == 'decoded'][:8])
    sheet = Image.new('RGB', (1280, 800), '#25282f')
    draw = ImageDraw.Draw(sheet)
    for i, row in enumerate(samples):
        image = Image.open(PACK / row['pack_filename']).convert('RGBA')
        image.thumbnail((144, 144))
        x, y = i % 8 * 160, i // 8 * 200
        sheet.paste(image, (x + (160 - image.width) // 2, y), image)
        draw.text((x + 4, y + 148), row['kind'], fill='white')
        draw.text((x + 4, y + 164), row['item_id'][:18], fill='#ccd0d5')
    sheet.save(BASE / 'sample-sheet.jpg', quality=90)
    print(json.dumps({'item_summary': evidence['summary'], 'by_kind': evidence['by_kind'],
                      'artwork_summary': evidence['artwork_summary'], 'pack': evidence['pack_summary']}), flush=True)


def main():
    global BASE, PACK, GAME, BUNDLES, SOURCE, REPO, Catalog, Store, Service, CatalogInventory, identity
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True, help='Installed game folder, its Data folder, or game executable')
    parser.add_argument('--output', type=Path, required=True, help='Private pack directory outside this repository')
    args = parser.parse_args()
    REPO = Path(__file__).resolve().parents[1]
    PACK = args.output.resolve()
    if PACK == REPO or REPO in PACK.parents:
        parser.error('Output must be outside the source repository: it contains original game pixels')
    GAME = args.game.resolve()
    if GAME.is_file():
        GAME = GAME.parent
    if not (GAME / 'resources.assets').is_file():
        GAME = GAME / 'Nebula Realms_Data'
    if not (GAME / 'resources.assets').is_file():
        parser.error('Game resources.assets not found')
    expected = json.loads((REPO / 'protocol/catalog-recovery-provenance.json').read_text(encoding='utf-8'))['native_item_type_sprites']['source_sha256']
    if digest(GAME / 'resources.assets') != expected:
        parser.error('This resource build does not match the validated catalog; extraction stopped')
    PACK.mkdir(parents=True, exist_ok=True)
    if any(PACK.iterdir()):
        parser.error('Choose an empty output directory; existing packs are never overwritten')
    BASE = PACK / '_research'
    BASE.mkdir()
    BUNDLES = GAME / 'StreamingAssets/StandaloneWindows'
    SOURCE = BASE / 'bundle-manifests.json'
    thumbnail_dir = BUNDLES / 'th'
    manifest_files = sorted(thumbnail_dir.glob('*.manifest'))
    if not 1 <= len(manifest_files) <= 15000:
        parser.error('Expected between 1 and 15000 shipped thumbnail manifests')
    manifests = []
    for file in manifest_files:
        if file.is_symlink() or file.stat().st_size > 1024 * 1024:
            parser.error('Manifest must be a bounded regular file')
        parsed = yaml.safe_load(file.read_text(encoding='utf-8'))
        assets = parsed.get('Assets', [])
        if not isinstance(assets, list) or not all(isinstance(p, str) and p.startswith('Assets/') for p in assets):
            parser.error('Malformed manifest asset list')
        bundle = file.with_name(file.name.removesuffix('.manifest'))
        if bundle.is_symlink() or not bundle.is_file():
            parser.error('Thumbnail bundle missing or linked')
        manifests.append({'bundle': bundle.relative_to(BUNDLES).as_posix(),
                          'bundle_size': bundle.stat().st_size, 'manifest_sha256': digest(file),
                          'assets': assets, 'dependencies': parsed.get('Dependencies', [])})
    SOURCE.write_text(json.dumps(manifests, ensure_ascii=False), encoding='utf-8')
    sys.path.insert(0, str(REPO / 'backend'))
    from state import Catalog, Store
    from service import Service
    from catalog_inventory import CatalogInventory, identity
    extract_items()
    finalize_pack()
    evidence = json.loads((BASE / 'preview-evidence.json').read_text(encoding='utf-8'))
    if evidence['summary'].get('error', 0) or evidence['artwork_summary'].get('error', 0):
        parser.exit(1, 'Extraction incomplete: inspect _research/preview-evidence.json before deploying this pack\n')
    print('Private pack ready. Copy only index.json and root-level *.webp into a deployment archive.')


if __name__ == '__main__':
    main()
