"""Probe build-input checks; no claim of compiled or installed runtime behavior."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import bootloader, sources


def config_file(path, replacements=None, removed=()):
    values = bootloader.required(bootloader.profile())
    values.update(replacements or {})
    for name in removed:
        values.pop(name)
    path.write_text(''.join(f'# {k} is not set\n' if v == 'n' else f'{k}={v}\n'
                            for k, v in values.items()), encoding='utf-8')


class BootloaderProfileTests(unittest.TestCase):
    def test_emission_is_only_unqualified_build_input_with_lf_and_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'profile'
            bootloader.emit(output)
            status = json.loads((output/'status.json').read_text())
            self.assertFalse(status['production_qualified'])
            self.assertFalse(status['complete_image'])
            self.assertFalse(status['compiled'])
            self.assertNotIn('boot.scr', {p.name for p in output.iterdir()})
            for name, digest in status['files'].items():
                data = (output/name).read_bytes()
                self.assertNotIn(b'\r', data)
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
            self.assertEqual((output/'fw_env.config').read_text().splitlines(),
                             ['/dev/mmcblk0 0x100000 0x10000', '/dev/mmcblk0 0x500000 0x10000'])
            self.assertIn('watchdog.open_timeout=60', (output/'kernel-handoff.txt').read_text())
            self.assertIn('RuntimeWatchdogSec=15s', (output/'watchdog-probe.conf').read_text())
            with self.assertRaisesRegex(ValueError, 'new bootloader'):
                bootloader.emit(output)

    def test_geometry_rejects_overlap_gpt_partition_and_unaligned_offsets(self):
        for offsets in ([0, 5242880], [1048576, 1049088], [1048576, 8388608],
                        [1048576, 5242881], [True, 5242880], [1048576]):
            value = copy.deepcopy(bootloader.profile())
            value['environment']['offsets'] = offsets
            with self.subTest(offsets=offsets), self.assertRaises(ValueError):
                bootloader.validate(value)

    def test_profile_cannot_select_network_boot_unbounded_handoff_or_production(self):
        cases = ((('qualification',), 'production'), (('boot_command',), 'dhcp; bootm'),
                 (('environment', 'hardware_partition'), 1), (('environment', 'bytes'), 131072),
                 (('watchdog', 'userspace_open_timeout_seconds'), 0),
                 (('watchdog', 'runtime_seconds'), 16),
                 (('watchdog', 'hardware_timeout_ms'), 60000))
        for keys, replacement in cases:
            value = copy.deepcopy(bootloader.profile())
            target = value
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = replacement
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                bootloader.validate(value)

    def test_audit_detects_silently_dropped_legacy_names_and_location_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'.config'
            config_file(path)
            result = bootloader.audit(path)
            self.assertEqual(result['violations'], [])
            self.assertFalse(result['compilation_verified'])
            self.assertFalse(result['hardware_boot_verified'])
            config_file(path, {'CONFIG_SYS_REDUNDAND_ENVIRONMENT': 'y'}, ('CONFIG_ENV_REDUNDANT',))
            self.assertIn('CONFIG_ENV_REDUNDANT', bootloader.audit(path)['violations'])
            for key, value in (('CONFIG_ENV_MMC_USE_DT', 'y'), ('CONFIG_ENV_MMC_USE_SW_PARTITION', 'y'),
                               ('CONFIG_ENV_IS_IN_FAT', 'y'), ('CONFIG_ENV_IS_IN_NAND', 'y'),
                               ('CONFIG_WATCHDOG_AUTOSTART', 'n'), ('CONFIG_WDT_BCM2835', 'n'),
                               ('CONFIG_ENV_OFFSET_REDUND', '0x100000')):
                config_file(path, {key: value})
                with self.subTest(key=key):
                    self.assertIn(key, bootloader.audit(path)['violations'])

    def test_config_parse_and_size_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'.config'
            for text, message in (('CONFIG_WDT=y\nCONFIG_WDT=y\n', 'Duplicate'),
                                  ('not a resolved setting\n', 'Malformed')):
                path.write_text(text)
                with self.assertRaisesRegex(ValueError, message):
                    bootloader.audit(path)
            path.write_bytes(b'x'*(1024**2+1))
            with self.assertRaisesRegex(ValueError, 'bounded regular'):
                bootloader.audit(path)

    @unittest.skipIf(os.name == 'nt', 'Linux builder symlink policy')
    def test_linked_config_is_not_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path, link = Path(folder)/'.config', Path(folder)/'link'
            config_file(path)
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, 'regular Kconfig'):
                bootloader.audit(link)


class BootloaderIntakeTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Linux source-cache FIFO policy')
    def test_cached_fifo_is_rejected_without_opening_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pin = sources.pins()['bootloader_audit']
            os.mkfifo(root/('bootloader_audit-'+pin['commit']+'.tar.gz'))
            with self.assertRaisesRegex(ValueError, 'non-regular'):
                sources.acquire('bootloader_audit', root, opener=lambda *a, **k: self.fail('unexpected download'))

    def test_member_count_and_expansion_are_checked_before_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            path, destination = Path(folder)/'source.tar.gz', Path(folder)/'tree'
            with tarfile.open(path, 'w:gz') as tar:
                for name in ('tree/a', 'tree/b'):
                    member = tarfile.TarInfo(name)
                    member.size = 4
                    tar.addfile(member, io.BytesIO(b'data'))
            for options, message in (({'max_members': 1}, 'Too many'), ({'max_tree': 7}, 'budget')):
                with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                    sources.unpack(path, destination, **options)
                self.assertFalse(destination.exists())

    def test_larger_candidate_budget_does_not_relax_small_source_intake(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with io.BytesIO() as stream:
                with tarfile.open(fileobj=stream, mode='w:gz') as tar:
                    for name in ('tree/a', 'tree/b'):
                        member = tarfile.TarInfo(name)
                        member.size = 4
                        tar.addfile(member, io.BytesIO(b'data'))
                data = stream.getvalue()
            self.assertGreater(len(data), 64)
            pin = {'repository': 'fixture/source', 'commit': 'a'*40,
                   'sha256': hashlib.sha256(data).hexdigest()}
            class Response(io.BytesIO):
                def geturl(self):
                    return 'https://codeload.github.com/fixture/source/tar.gz/'+'a'*40
            with (patch.object(sources, 'pins', return_value={'imagegen': pin, 'bootloader_audit': pin}),
                  patch.object(sources, 'MAX_ARCHIVE', 64), patch.object(sources, 'MAX_TREE', 7),
                  patch.object(sources, 'MAX_MEMBERS', 1),
                  patch.object(sources, 'BOOTLOADER_LIMITS', {'archive': 1024, 'tree': 8, 'members': 2})):
                with self.assertRaisesRegex(ValueError, 'download exceeds budget'):
                    sources.acquire('imagegen', root/'small', opener=lambda *a, **k: Response(data))
                destination = sources.acquire('bootloader_audit', root/'large', opener=lambda *a, **k: Response(data))
                self.assertEqual((destination/'a').read_bytes(), b'data')
                self.assertEqual((destination/'b').read_bytes(), b'data')


if __name__ == '__main__':
    unittest.main()
