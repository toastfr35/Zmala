"""Development image assembly regressions; no hardware boot qualification."""
import gzip
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from zmala_images import build_space, image_assembly, image_payload, image_state, image_worker, package_lock
from tests.adhoc.test_image_root_build import SELECTED
from tests.adhoc.test_image_state import fixture
from zmala_system import boot_media, boot_state


class ImageAssemblyTests(unittest.TestCase):
    def test_exact_media_capacity_is_bounded_and_sector_aligned(self):
        minimum = image_payload.disk_bytes()
        self.assertEqual(minimum, 14001635328)
        self.assertEqual(image_payload.disk_bytes(32*1024**3), 32*1024**3)
        for capacity in (True, '32000000000', minimum-512, minimum+1, 129*1024**3):
            with self.assertRaises(ValueError):
                image_payload.disk_bytes(capacity)

    @unittest.skipUnless(os.name == 'posix', 'POSIX command adapters; actual hush evidence is separate')
    def test_boot_script_pairs_slots_and_fails_closed_before_handoff(self):
        adapters = '''setenv() { key=$1; shift; if [ "$#" -eq 0 ]; then unset "$key"; else export "$key=$*"; fi; }
saveenv() { test "$SAVE" = 1; }
part() { setenv zm_rootuuid fixture-uuid; }
fatload() { test "$LOAD" = 1 || return 1; setenv filesize 1234; }
fdt() { true; }
wdt() { echo "WATCHDOG=$*"; test "$WATCHDOG" = 1; }
booti() { echo "BOOT=$zm_selected,$zm_bootpart,$zm_rootpart ARGS=$bootargs HANDOFF=$*"; exit 0; }
reset() { echo RESET; exit 0; }
'''
        for role in ('terminal', 'server', 'combined'):
            for confirmed, candidate in (('A', 'B'), ('B', 'A')):
                state = boot_state.State(role, confirmed)
                trial = state.stage(confirmed, candidate, '1'*64)
                cases = [(state.fields(), '1', '1', '1', confirmed, 'stop'),
                         (trial.fields(), '1', '1', '1', candidate, 'start 15000'),
                         (trial.fields(), '0', '1', '1', confirmed, 'stop'),
                         (state.fields(), '1', '0', '1', None, None),
                         (state.fields(), '1', '1', '0', None, None),
                         ({**state.fields(), 'zm_schema': 'bad'}, '1', '1', '1', None, None)]
                for fields, save, load, watchdog, selected, action in cases:
                    with self.subTest(role=role, confirmed=confirmed, selected=selected, load=load, watchdog=watchdog):
                        result = subprocess.run(['/bin/sh', '-c', adapters+image_payload.boot_script()],
                                                env={**fields, 'SAVE': save, 'LOAD': load, 'WATCHDOG': watchdog},
                                                capture_output=True, text=True, check=True, timeout=5)
                        if selected:
                            pair = ',2,4' if selected == 'A' else ',3,5'
                            self.assertIn('BOOT='+selected+pair, result.stdout)
                            self.assertIn('root=PARTUUID=fixture-uuid', result.stdout)
                            self.assertIn('rauc.slot='+selected, result.stdout)
                            self.assertIn('HANDOFF=0x00080000 0x02100000:1234 0x05600000', result.stdout)
                            self.assertIn('WATCHDOG='+action, result.stdout)
                        else:
                            self.assertNotIn('BOOT=', result.stdout)
                            self.assertIn('RESET', result.stdout)

    @unittest.skipUnless(os.name == 'posix', 'POSIX command adapters')
    def test_boot_script_restores_bluetooth_flow_control_only_for_known_layout(self):
        adapters = '''setenv() { key=$1; shift; export "$key=$*"; }
part() { setenv zm_rootuuid fixture-uuid; }
fatload() { setenv filesize 1234; }
fdt() {
    case "$1" in
        addr) address=$2 ;;
        get)
            if [ "$address" = "$fdt_addr" ]; then
                case "$5" in
                    brcm,pins) setenv "$3" "$FIRMWARE_PINS" ;;
                    brcm,pull) setenv "$3" 00000002000000000000000000000002 ;;
                esac
            else
                case "$5" in
                    brcm,pins) setenv "$3" "$SLOT_PINS" ;;
                    brcm,pull) setenv "$3" 0000000000000002 ;;
                esac
            fi ;;
        set) echo "FDT=$address $3 $4"; test "$EDIT_OK" = yes ;;
    esac
}
wdt() { true; }
booti() { echo "BOOT=$3"; exit 0; }
reset() { echo RESET; exit 0; }
'''
        firmware_pins = '0000001e0000001f0000002000000021'
        slot_pins = '0000002000000021'
        for firmware, slot, edit_ok, expected in (
            (firmware_pins, slot_pins, 'yes', 'fix'),
            (slot_pins, slot_pins, 'yes', 'boot'),
            (firmware_pins, firmware_pins, 'yes', 'boot'),
            (firmware_pins, slot_pins, 'no', 'reset'),
        ):
            with self.subTest(firmware=firmware, slot=slot, edit_ok=edit_ok):
                result = subprocess.run(
                    ['/bin/sh', '-c', adapters+image_payload.boot_script()],
                    env={**boot_state.State('terminal', 'A').fields(), 'fdt_addr': '0x100000',
                         'FIRMWARE_PINS': firmware, 'SLOT_PINS': slot, 'EDIT_OK': edit_ok},
                    capture_output=True, text=True, check=True, timeout=5,
                )
                lines = result.stdout.splitlines()
                boot = 'BOOT=0x05600000'
                pins = 'FDT=0x05600000 brcm,pins <30 31 32 33>'
                pulls = 'FDT=0x05600000 brcm,pull <2 0 0 2>'
                if expected == 'fix':
                    self.assertEqual(lines, [pins, pulls, 'Enabled firmware Bluetooth UART flow control', boot])
                elif expected == 'reset':
                    self.assertEqual(lines, [pins, 'RESET'])
                else:
                    self.assertEqual(lines, [boot])

    def test_wsl_capacity_is_limited_by_physical_backing_volume(self):
        with patch.object(build_space.shutil, 'disk_usage', return_value=SimpleNamespace(free=10**12)), \
                patch.object(build_space.Path, 'is_file', return_value=True), \
                patch.object(build_space.Path, 'read_text', return_value='microsoft-standard-WSL2'), \
                patch.dict(os.environ, {'WSL_DISTRO_NAME': "build'quoted"}), \
                patch.object(build_space.shutil, 'which', return_value='/path/powershell.exe'), \
                patch.object(build_space.subprocess, 'check_output', return_value='123456\n') as query:
            self.assertEqual(build_space.available('/tmp'), 123456)
            self.assertIn("'build''quoted'", query.call_args.args[0][-1])
            query.return_value = 'unavailable'
            with self.assertRaises(ValueError):
                build_space.available('/tmp')

    def test_kernel_memory_bound_architecture_and_compression(self):
        body = bytes(56)+b'ARMd'+bytes(68)
        for encoded in (body, gzip.compress(body)):
            self.assertEqual(image_payload.kernel_image(encoded), body)
        for encoded in (b'not a kernel', bytes(128), gzip.compress(bytes(33*1024**2))):
            with self.assertRaises(ValueError):
                image_payload.kernel_image(encoded)

    def test_factory_environment_crc_redundancy_and_complete_state(self):
        for role in ('server', 'terminal', 'combined'):
            for flag in (0, 1):
                body = image_payload.environment('bootcmd=local only\n', role, flag)
                self.assertEqual(len(body), boot_media.ENV_BYTES)
                self.assertEqual(body[4], flag)
                self.assertEqual(struct.unpack('<I', body[:4])[0], zlib.crc32(body[5:]))
                fields = dict(row.decode().split('=', 1) for row in body[5:].split(b'\0\0')[0].split(b'\0'))
                self.assertEqual({k: v for k, v in fields.items() if k.startswith('zm_')},
                                 boot_state.State(role, 'A').fields())
                self.assertEqual(fields['bootcmd'], 'local only')
        for initial in ('zm_schema=1\n', 'key=one\nkey=two\n', 'key=bad\0data\n', 'key='+'x'*65536):
            with self.assertRaises(ValueError):
                image_payload.environment(initial, 'terminal', 1)

    def test_component_digest_and_link_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            # Windows runners may expose TEMP through an 8.3 path alias.
            root = Path(folder).resolve(); marker = root/'READY.json'; marker.write_text('{"schema":1}')
            checksum = package_lock.digest(marker)
            self.assertEqual(image_assembly.component(root, checksum), {'schema': 1})
            with self.assertRaises(ValueError):
                image_assembly.component(root, '0'*64)
            if os.name != 'nt':
                marker.rename(root/'actual.json'); marker.symlink_to('actual.json')
                with self.assertRaises(ValueError):
                    image_assembly.component(root, checksum)

    def test_host_root_and_windows_refused_before_inputs_or_output(self):
        for system, uid in (('Windows', 1000), ('Linux', 0)):
            with patch.object(image_assembly.platform, 'system', return_value=system), \
                    patch.object(image_assembly.os, 'geteuid', return_value=uid, create=True), \
                    patch.object(image_assembly.local_repo, 'inputs') as inputs, self.assertRaises(ValueError):
                image_assembly.build('server', 'src', 'hash', 'init', 'hash', 'loader', 'hash', 'base', 'role', 'out')
            inputs.assert_not_called()

    def test_application_marker_survives_preparation_and_incomplete_records_fail(self):
        good = {'schema': 1, 'role': 'server', 'application_installed': True,
                'target_application_imports_checked': True, 'target_unit_graph_checked': True,
                'joint_health_implemented': False}
        for change in ({}, {'role': 'combined'}, {'target_application_imports_checked': False},
                       {'joint_health_implemented': True}, {'application_installed': False}):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); source = root/'source.tar'
                fixture(source, {'usr/lib/zmala-application-build.json': ('file', json.dumps({**good, **change}).encode())})
                if not change:
                    self.assertTrue(image_state.prepare(source, package_lock.digest(source), SELECTED,
                                                        'server', root/'out')['application_installed'])
                else:
                    with self.assertRaises(ValueError):
                        image_state.prepare(source, package_lock.digest(source), SELECTED, 'server', root/'out')
                    self.assertFalse((root/'out/READY.json').exists())

    @unittest.skipUnless(hasattr(os, 'SEEK_DATA'), 'Linux sparse regular-file extent support')
    def test_sparse_copy_preserves_bytes_and_refuses_partition_overflow(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'fs'; target = root/'image'
            length = 4*1024**2; offset = boot_media.FIRST_PARTITION_BYTES
            with source.open('xb') as stream:
                stream.truncate(length); stream.seek(12345); stream.write(b'filesystem fixture')
            with target.open('x+b') as destination:
                destination.truncate(offset+length)
                image_worker.sparse_copy(source, destination, offset, length)
                destination.seek(offset)
                self.assertEqual(destination.read(), source.read_bytes())
                with self.assertRaises(ValueError):
                    image_worker.sparse_copy(source, destination, offset+512, length)
                with self.assertRaises(ValueError):
                    image_worker.sparse_copy(source, destination, 0, length)


if __name__ == '__main__':
    unittest.main()
