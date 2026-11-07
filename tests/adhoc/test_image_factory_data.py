"""Factory archive packaging checks, outside installed runtime requirements."""
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from zmala_images import factory_data, image_state, package_lock
from zmala_system import device_identity as identity


class FactoryDataTests(unittest.TestCase):
    def test_both_roles_emit_only_private_factory_marker_without_identity(self):
        for role in ('server', 'terminal', 'combined'):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as folder:
                output = Path(folder)/'output'
                result = factory_data.emit(role, output)
                self.assertEqual(result['data_tar_sha256'], package_lock.digest(output/'data.tar'))
                self.assertTrue(result['empty_factory_data'])
                self.assertFalse(result['device_identity_present'])
                self.assertFalse(result['device_data_initialized'])
                self.assertFalse(result['production_qualified'])
                self.assertEqual(json.loads((output/'READY.json').read_text()), result)
                with tarfile.open(output/'data.tar') as archive:
                    self.assertEqual([m.name for m in archive], ['.', identity.FACTORY])
                    record = archive.getmember(identity.FACTORY)
                    self.assertEqual((record.uid, record.gid, record.mode), (0, 0, 0o600))
                    self.assertEqual(json.load(archive.extractfile(record)), identity.factory_profile(role))
                second = Path(folder)/'second'
                self.assertEqual(factory_data.emit(role, second)['data_tar_sha256'], result['data_tar_sha256'])
                with self.assertRaises(ValueError):
                    factory_data.emit(role, output)
                self.assertEqual(package_lock.digest(output/'data.tar'), result['data_tar_sha256'])

    def test_invalid_role_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'output'
            with self.assertRaises(ValueError):
                factory_data.emit('wrong', output)
            self.assertFalse(output.exists())

    def test_wrong_role_extra_private_content_link_or_modes_fail_audit(self):
        for variant in ('wrong-role', 'private', 'link', 'mode', 'owner', 'missing', 'duplicate'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'data.tar'
                body = factory_data.content('terminal' if variant == 'wrong-role' else 'server')
                with tarfile.open(path, 'w') as archive:
                    root = image_state.added_member('.'); root.mode = 0o755 if variant == 'mode' else 0o700
                    archive.addfile(root)
                    record = image_state.added_member(identity.FACTORY, body); record.mode = 0o600
                    if variant == 'owner':
                        record.uid = 1000
                    if variant == 'link':
                        record.type, record.linkname, record.size = tarfile.SYMTYPE, '/outside', 0
                    if variant != 'missing':
                        archive.addfile(record, None if variant == 'link' else io.BytesIO(body))
                    if variant == 'duplicate':
                        archive.addfile(record, io.BytesIO(body))
                    if variant == 'private':
                        archive.addfile(image_state.added_member('identity/machine-id', b'private'), io.BytesIO(b'private'))
                with self.assertRaises(ValueError):
                    factory_data.audit(path, 'server')

    def test_archive_size_and_regular_file_are_checked_before_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'oversized'
            with path.open('wb') as stream:
                stream.truncate(factory_data.MAX_TAR_BYTES+1)
            with self.assertRaises(ValueError):
                factory_data.audit(path, 'server')
            if os.name != 'nt':
                fifo = Path(folder)/'fifo'; os.mkfifo(fifo)
                with self.assertRaises(ValueError):
                    factory_data.audit(fifo, 'server')
