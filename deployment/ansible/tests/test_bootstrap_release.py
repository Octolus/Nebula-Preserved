"""Self-contained release integrity tests; no elevated operations or network."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('release_installer', ROOT / 'deployment/bootstrap/deploy.py')
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='nebula-release-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / 'input-images.tar'
        self.report = self.root / 'input-report.json'
        self.images = ['nebula-server:reviewed', 'nebula-panel:reviewed', DEPLOY.NGINX.split('@')[0]]
        self.write_archive()
        self.report.write_text(json.dumps({'exit_code': 0, 'elf64_x86_64': True,
            'target': 'StandaloneLinux64', 'subtarget': 'Server',
            'executable_sha256': '1' * 64, 'managed_assembly_sha256': '2' * 64,
            'networking_parity_proven': False}))
        self.release = self.root / 'release'

    def write_archive(self, tags=None, duplicate=False, link=False):
        tags = tags or self.images
        with tarfile.open(self.archive, 'w') as stream:
            def member(name, data):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                stream.addfile(info, io.BytesIO(data))
            values = []
            for index, tag in enumerate(tags):
                data = json.dumps({'image': index, 'architecture': 'amd64', 'os': 'linux'}).encode()
                config = hashlib.sha256(data).hexdigest() + '.json'
                member(config, data)
                values.append({'Config': config, 'RepoTags': [tag], 'Layers': []})
            member('manifest.json', json.dumps(values).encode())
            if duplicate:
                member('manifest.json', b'[]')
            if link:
                info = tarfile.TarInfo('unwanted-link')
                info.type = tarfile.SYMTYPE
                info.linkname = '/etc/passwd'
                stream.addfile(info)

    def prepare(self):
        return DEPLOY.prepare(self.release, self.archive, self.report, *self.images[:2])

    def write_oci_archive(self, change=None):
        files, legacy, roots, expected, leaves = {}, [], [], {}, {}
        def blob(value, media):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            digest = 'sha256:' + hashlib.sha256(data).hexdigest()
            files['blobs/sha256/' + digest.split(':')[1]] = data
            return {'mediaType': media, 'digest': digest, 'size': len(data)}
        configs = [blob({'image': index, 'architecture': 'amd64', 'os': 'linux'},
                        'application/vnd.oci.image.config.v1+json') for index in range(3)]
        for index, tag in enumerate(self.images):
            layer = blob(f'authored layer {index}'.encode(), 'application/vnd.oci.image.layer.v1.tar')
            config = configs[1] if change == 'wrong_config' and index == 0 else configs[index]
            manifest = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                             'config': config, 'layers': [layer]},
                            'application/vnd.oci.image.manifest.v1+json')
            leaves[tag] = manifest['digest']
            manifest['platform'] = {'architecture': 'amd64', 'os': 'linux'}
            children = [manifest]
            if change == 'wrong_platform' and index == 0:
                manifest['platform']['architecture'] = 'arm64'
            if change == 'ambiguous_platform' and index == 0:
                children.append(dict(manifest))
            # A foreign platform/attestation can be advertised but is never an
            # admissible loaded-image ID, and need not be saved for this platform.
            children.append({'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                             'digest': 'sha256:' + 'a' * 64, 'size': 123,
                             'platform': {'architecture': 'unknown', 'os': 'unknown'}})
            root = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                         'manifests': children}, 'application/vnd.oci.image.index.v1+json')
            root['annotations'] = {'io.containerd.image.name': 'docker.io/library/' + tag}
            if change == 'wrong_tag' and index == 0:
                root['annotations']['io.containerd.image.name'] = 'docker.io/library/unrelated:foreign'
            if change == 'wrong_size' and index == 0:
                root['size'] += 1
            if change == 'wrong_digest' and index == 0:
                name = 'blobs/sha256/' + root['digest'].split(':')[1]
                files[name] = files[name].replace(b'"schemaVersion": 2', b'"schemaVersion": 3', 1)
            roots.append(root)
            layer_name = 'blobs/sha256/' + layer['digest'].split(':')[1]
            if change == 'wrong_layer' and index == 0:
                files['unrelated-layer'] = b'not selected'
                layer_name = 'unrelated-layer'
            legacy.append({'Config': 'blobs/sha256/' + configs[index]['digest'].split(':')[1],
                           'RepoTags': [tag], 'Layers': [layer_name]})
            expected[tag] = sorted([configs[index]['digest'], root['digest']])
        files['manifest.json'] = json.dumps(legacy).encode()
        files['index.json'] = json.dumps({'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': roots}).encode()
        with tarfile.open(self.archive, 'w') as stream:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                stream.addfile(member, io.BytesIO(data))
        return expected, leaves

    def test_portable_release_derives_all_pins_and_verifies_without_private_source_paths(self):
        result = self.prepare()
        self.assertTrue(result['release_prepared'])
        manifest = DEPLOY.verify(self.release)
        self.assertEqual('1' * 64, manifest['runtime_pins']['nebula_server_sha256'])
        self.assertEqual(3, len(manifest['image_ids']))
        self.assertNotIn(str(self.root), (self.release / 'release.json').read_text())
        self.assertIn('deployment/ansible/files/manage-public-tls.py', manifest['files'])
        self.assertTrue(all(len(ids) == 1 and ids[0].startswith('sha256:')
                            for ids in manifest['image_ids'].values()))

    def test_containerd_and_legacy_ids_are_bound_to_exact_tagged_linux_amd64_closure(self):
        expected, leaves = self.write_oci_archive()
        found = DEPLOY.image_ids(self.archive, [*self.images[:2], DEPLOY.NGINX])
        self.assertEqual(expected, found)
        for tag, identities in found.items():
            self.assertEqual(2, len(identities))
            self.assertNotIn(leaves[tag], identities)
            self.assertNotIn('sha256:' + 'a' * 64, identities)
        self.prepare()
        self.assertEqual(found, DEPLOY.verify(self.release)['image_ids'])

    def test_oci_tag_platform_config_layer_and_hash_mismatches_fail_closed(self):
        for change in ('wrong_tag', 'wrong_platform', 'ambiguous_platform', 'wrong_config',
                       'wrong_layer', 'wrong_size', 'wrong_digest'):
            with self.subTest(change=change):
                self.write_oci_archive(change)
                with self.assertRaises(ValueError):
                    DEPLOY.image_ids(self.archive, [*self.images[:2], DEPLOY.NGINX])

    def test_existing_output_is_never_overwritten(self):
        self.release.mkdir()
        marker = self.release / 'keep.txt'
        marker.write_text('unchanged')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.prepare()
        self.assertEqual('unchanged', marker.read_text())

    def test_optional_private_pack_is_pinned_verified_and_not_required(self):
        # Empty packs are useful for consciously clearing a previously installed pack.
        pack = self.root / 'private-pack.tar'
        data = b'{"format_version":1,"entries":[]}'
        with tarfile.open(pack, 'w') as stream:
            member = tarfile.TarInfo('index.json')
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
        DEPLOY.prepare(self.release, self.archive, self.report, *self.images[:2], catalog_preview_pack=pack)
        manifest = DEPLOY.verify(self.release)
        self.assertEqual(DEPLOY.sha256(pack), manifest['files']['catalog-previews.tar']['sha256'])
        copied = self.release / 'catalog-previews.tar'
        copied.write_bytes(b'invalid replacement')
        with self.assertRaisesRegex(ValueError, 'hash/size mismatch'):
            DEPLOY.verify(self.release)

    def test_invalid_optional_pack_is_rejected_before_output_creation(self):
        pack = self.root / 'private-pack.tar'
        with tarfile.open(pack, 'w') as stream:
            member = tarfile.TarInfo('../escape')
            member.size = 1
            stream.addfile(member, io.BytesIO(b'x'))
        with self.assertRaisesRegex(ValueError, 'Unsafe preview'):
            DEPLOY.prepare(self.release, self.archive, self.report, *self.images[:2], catalog_preview_pack=pack)
        self.assertFalse(self.release.exists())

    def test_bad_build_report_fails_before_output_creation(self):
        self.report.write_text('{"exit_code":1}')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.release.exists())

    def test_missing_or_ambiguous_image_metadata_is_refused(self):
        self.write_archive(tags=self.images[:2])
        with self.assertRaisesRegex(ValueError, 'absent'):
            self.prepare()
        self.write_archive(duplicate=True)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.prepare()

    def test_outer_archive_links_are_refused_without_extraction(self):
        self.write_archive(link=True)
        with self.assertRaisesRegex(ValueError, 'Linked/special'):
            self.prepare()
        self.assertFalse((self.root / 'unwanted-link').exists())

    def test_tampered_payload_is_rejected_before_package_install_or_service_actions(self):
        self.prepare()
        (self.release / 'deployment/ansible/site.yaml').write_text('tampered')
        with patch.object(DEPLOY.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'hash/size'):
                DEPLOY.install(self.release, '1.1.1.1', 'public_acme')
            run.assert_not_called()

    def test_unexpected_release_files_are_refused(self):
        self.prepare()
        (self.release / 'password.txt').write_text('not allowed')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            DEPLOY.verify(self.release)

    def test_path_escape_inventory_and_duplicate_json_fields_are_refused(self):
        self.prepare()
        path = self.release / 'release.json'
        original = path.read_text()
        value = json.loads(original)
        value['files']['../outside'] = {'sha256': 'a' * 64, 'bytes': 0}
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            DEPLOY.verify(self.release)
        path.write_text(original.replace('"format":', '"format": "duplicate", "format":', 1))
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            DEPLOY.verify(self.release)

    def test_rewritten_runtime_pin_or_image_id_does_not_override_real_artifacts(self):
        self.prepare()
        path = self.release / 'release.json'
        original = json.loads(path.read_text())
        for key in ('runtime_pins', 'image_ids'):
            value = json.loads(json.dumps(original))
            first = next(iter(value[key]))
            value[key][first] = '0' * 64
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                DEPLOY.verify(self.release)

    def test_invalid_image_references_and_reserved_public_ip_are_refused(self):
        for name in ('server;id', '-bad', 'server image', 'http://server?secret'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                DEPLOY.prepare(self.release, self.archive, self.report, name, self.images[1])
        with patch.object(DEPLOY.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'globally routable'):
                DEPLOY.install(self.release, '192.0.2.10', 'public_acme')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
