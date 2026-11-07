"""Shared role assertions for the experimental boot-control boundary."""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zmala_system import boot_backend, boot_environment, boot_media, boot_state
from tests.support.gpt_fixture import image

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = '1'*64
OTHER = '2'*64


def select(fields, save=True):
    # The authored script is sourced verbatim. These two functions emulate only
    # U-Boot's environment commands, not its selection logic or interpreter.
    code = '''setenv() { key=$1; shift; if test "$#" = 0; then unset "$key"; else export "$key=$1"; fi; }
calls=0
saveenv() { calls=$((calls+1)); test "$save_ok" = 1; }
. "$1"
printf '%s|%s|%s|%s' "$zm_selected" "$zm_is_trial" "$calls" "$zm_left"
'''
    result = subprocess.run(['/bin/sh', '-c', code, 'selector-fixture', str(ROOT/'zmala_system/boot_select.sh')],
                            env={'PATH': '/usr/bin:/bin', 'save_ok': str(int(save)),
                                 'zm_selected': 'stale', 'zm_is_trial': 'stale', **fields},
                            capture_output=True, text=True, timeout=5, check=True)
    return result.stdout.split('|')


class MemoryEnvironment:
    def __init__(self, state):
        self.state, self.commits = state, []

    def read(self):
        return self.state

    def commit(self, expected, candidate):
        assert self.state == expected
        self.commits.append(candidate); self.state = candidate


class BootStateScenario(unittest.TestCase):
    role = None

    def state(self, confirmed='A'):
        return boot_state.State(self.role, confirmed)

    def test_complete_canonical_state_round_trip_and_exact_policy(self):
        for confirmed in ('A', 'B'):
            initial = self.state(confirmed)
            self.assertEqual(boot_state.decode(boot_state.encode(initial), self.role), initial)
            candidate = initial.stage(confirmed, 'B' if confirmed == 'A' else 'A', IDENTITY)
            self.assertEqual(boot_state.decode(boot_state.encode(candidate), self.role), candidate)
        policy = boot_state.policy(self.role)
        self.assertEqual(boot_state.decode_policy(json.dumps(policy).encode(), self.role), policy)
        for key, value in (('activate_installed', True), ('automatic_confirmation', 0),
                           ('pid1_startup_watchdog_seconds', False), ('schema', True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                boot_state.decode_policy(json.dumps({**policy, key: value}).encode(), self.role)
        with self.assertRaises(ValueError):
            boot_state.decode_policy(b'{"schema":1,"schema":1}', self.role)

    def test_reject_missing_duplicate_extra_encoding_and_size_without_defaults(self):
        body = boot_state.encode(self.state())
        bad = (b'', b'x'*4097, body+b'\0', body+b'unknown=1\n', body+b'zm_schema=1\n',
               body.replace(b'zm_role=', b'\xff='), b'\n'+body, body[:-1], body.replace(b'\n', b'\r\n'))
        for value in bad:
            with self.subTest(value=value[:30]), self.assertRaises(ValueError):
                boot_state.decode(value, self.role)
        for key in boot_state.KEYS:
            with self.subTest(missing=key), self.assertRaises(ValueError):
                boot_state.decode(b'\n'.join(line for line in body.splitlines()
                                             if not line.startswith(key.encode()+b'=')), self.role)

    def test_reject_noncanonical_and_inconsistent_fields(self):
        initial = self.state()
        for changes in ({'role': 'other'}, {'confirmed': 'C'}, {'a_good': False}, {'b_good': 1},
                        {'left': True}, {'left': 2}, {'left': 1}, {'generation': True},
                        {'generation': -1}, {'generation': 2**64}, {'transaction': '0'*64},
                        {'transaction': IDENTITY},
                        {'trial': 'A'}, {'trial': 'B'}, {'trial': 'B', 'transaction': IDENTITY}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(initial, **changes)
        for key, value in (('zm_schema', '2'), ('zm_left', '00'), ('zm_a_good', 'true'),
                           ('zm_generation', '0'), ('zm_generation', 'A'*16), ('zm_role', 'other')):
            fields = initial.fields(); fields[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                boot_state.decode(''.join(k+'='+v+'\n' for k, v in fields.items()).encode(), self.role)

    def test_stage_consumed_trial_confirm_and_fallback_in_both_directions(self):
        for current, candidate in (('A', 'B'), ('B', 'A')):
            initial = self.state(current)
            pending = initial.stage(current, candidate, IDENTITY)
            self.assertEqual((pending.confirmed, pending.primary, pending.left), (current, candidate, 1))
            consumed = replace(pending, left=0)
            self.assertEqual(consumed.primary, current)
            confirmed = consumed.confirm(candidate, IDENTITY, pending.generation)
            self.assertEqual((confirmed.confirmed, confirmed.trial, confirmed.left), (candidate, '-', 0))
            self.assertEqual(confirmed.generation, pending.generation+1)
            self.assertEqual(confirmed.transaction, IDENTITY)

    def test_refuse_ineligible_staging_and_unbound_or_stale_confirmation(self):
        initial = self.state(); pending = initial.stage('A', 'B', IDENTITY)
        for state, current, candidate, identity in (
                (initial, 'B', 'A', IDENTITY), (initial, 'A', 'A', IDENTITY),
                (pending, 'A', 'B', OTHER), (replace(initial, transaction=IDENTITY, generation=1), 'A', 'B', IDENTITY),
                (initial.eligibility('B', False), 'A', 'B', IDENTITY)):
            with self.subTest(state=state), self.assertRaises(ValueError):
                state.stage(current, candidate, identity)
        consumed = replace(pending, left=0)
        for state, current, identity, generation in (
                (pending, 'B', IDENTITY, 1), (consumed, 'A', IDENTITY, 1),
                (consumed, 'B', OTHER, 1), (consumed, 'B', IDENTITY, 0),
                (consumed, 'B', IDENTITY, True), (initial, 'A', IDENTITY, 0)):
            with self.subTest(current=current, generation=generation), self.assertRaises(ValueError):
                state.confirm(current, identity, generation)
        with self.assertRaises(ValueError):
            replace(initial, generation=boot_state.LIMIT).stage('A', 'B', IDENTITY)

    def test_eligibility_and_cancellation_do_not_confirm_a_trial(self):
        initial = self.state(); pending = initial.stage('A', 'B', IDENTITY)
        self.assertIs(pending.eligibility('B', True), pending)
        bad = pending.eligibility('B', False)
        self.assertEqual((bad.confirmed, bad.trial, bad.primary, bad.b_good), ('A', '-', 'A', False))
        self.assertEqual(pending.cancel('A', IDENTITY).trial, '-')
        for current, identity in (('B', IDENTITY), ('A', OTHER)):
            with self.assertRaises(ValueError):
                pending.cancel(current, identity)
        with self.assertRaises(ValueError):
            pending.eligibility('A', False)

    def test_backend_results_explicit_stage_confirmation_and_argument_refusal(self):
        environment = MemoryEnvironment(self.state())
        self.assertEqual(boot_backend.execute(['get-current'], environment, 'A'), 'A')
        self.assertEqual(boot_backend.execute(['get-primary'], environment, 'A'), 'A')
        self.assertEqual(boot_backend.execute(['get-state', 'B'], environment, 'A'), 'good')
        boot_backend.execute(['stage', 'B', IDENTITY], environment, 'A')
        boot_backend.execute(['set-state', 'B', 'good'], environment, 'B')
        self.assertEqual(len(environment.commits), 1)
        self.assertEqual(environment.state.confirmed, 'A')
        environment.state = replace(environment.state, left=0)
        boot_backend.execute(['confirm', IDENTITY, '0000000000000001'], environment, 'B')
        self.assertEqual(environment.state.confirmed, 'B')
        self.assertEqual(json.loads(boot_backend.execute(['snapshot'], environment, 'B')),
                         environment.state.fields())
        for args in ([], ['bad'], ['get-primary', 'A'], ['get-state', 'C'],
                     ['set-state', 'B', 'maybe'], ['stage', 'B', 'bad'], ['cancel', IDENTITY, 'extra'],
                     ['confirm', IDENTITY, '1'], ['set-primary', 'A']):
            with self.subTest(args=args), self.assertRaises(ValueError):
                boot_backend.execute(args, environment, 'B')

    def test_cli_rejects_arguments_before_control_access_and_masks_internal_errors(self):
        with patch.object(boot_environment, 'open_control') as opened, patch('sys.stderr', new_callable=io.StringIO) as output:
            self.assertEqual(boot_backend.main(['stage', 'B', 'bad']), 1)
            opened.assert_not_called()
            opened.side_effect = ValueError('private environment and device details')
            self.assertEqual(boot_backend.main(['get-primary']), 1)
            self.assertNotIn('private', output.getvalue())

    @unittest.skipUnless(os.name == 'posix', 'Requires POSIX shell, not an actual U-Boot qualification')
    def test_authored_selector_consumes_once_then_falls_back_and_handles_failed_save(self):
        for current, candidate in (('A', 'B'), ('B', 'A')):
            initial = self.state(current)
            self.assertEqual(select(initial.fields()), [current, '0', '0', '0'])
            pending = initial.stage(current, candidate, IDENTITY)
            self.assertEqual(select(pending.fields()), [candidate, '1', '1', '0'])
            self.assertEqual(select(pending.fields(), save=False), [current, '0', '1', '0'])
            self.assertEqual(select(replace(pending, left=0).fields()), [current, '0', '0', '0'])

    @unittest.skipUnless(os.name == 'posix', 'Requires POSIX shell')
    def test_authored_selector_rejects_invalid_decision_fields_and_stale_outputs(self):
        for key, value in (('zm_schema', ''), ('zm_role', 'other'), ('zm_confirmed', 'C'),
                           ('zm_a_good', '0'), ('zm_b_good', '2'), ('zm_trial', 'A'),
                           ('zm_trial', 'C'), ('zm_left', '2'), ('zm_left', '1')):
            fields = self.state().fields(); fields[key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(select(fields)[0], '')

    def test_packaged_policy_does_not_enable_health_or_automatic_activation(self):
        from zmala_images import image_state
        payload = image_state.payloads(self.role)
        policy = boot_state.decode_policy(payload[boot_state.PROFILE], self.role)
        self.assertFalse(policy['activate_installed'])
        self.assertFalse(policy['automatic_confirmation'])
        self.assertFalse(policy['health_handover_implemented'])
        self.assertIn(b'RuntimeWatchdogSec=0', payload['usr/lib/systemd/system.conf.d/99-zmala-trial.conf'])

    def test_native_commit_rejects_stale_generation_and_readback_mismatch(self):
        initial = self.state(); candidate = initial.stage('A', 'B', IDENTITY)
        with tempfile.TemporaryDirectory() as folder:
            tool = boot_environment.ToolEnvironment(folder, self.role)
            with patch.object(tool, 'read', return_value=candidate), \
                    patch.object(boot_environment.subprocess, 'run') as run, self.assertRaises(ValueError):
                tool.commit(initial, candidate)
            run.assert_not_called()
            if os.name == 'posix':
                with patch.object(tool, 'read', side_effect=[initial, initial]), \
                        patch.object(boot_environment.subprocess, 'run') as run, self.assertRaises(ValueError):
                    tool.commit(initial, candidate)
                self.assertEqual(run.call_args.kwargs['timeout'], 15)
                self.assertFalse((Path(folder)/'change.env').exists())
                with patch.object(tool, 'read', return_value=initial), \
                        patch.object(boot_environment.subprocess, 'run', side_effect=OSError('write failed')), \
                        self.assertRaisesRegex(OSError, 'write failed'):
                    tool.commit(initial, candidate)
                self.assertFalse((Path(folder)/'change.env').exists())

    @unittest.skipUnless(os.name == 'posix', 'Requires Linux private-file flags')
    def test_native_read_uses_fixed_keys_config_defaults_and_bounded_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            tool = boot_environment.ToolEnvironment(folder, self.role)
            with patch.object(boot_environment.boot_devices, 'bounded_probe', return_value=boot_state.encode(self.state())) as probe:
                self.assertEqual(tool.read(), self.state())
            args = probe.call_args.args[0]
            self.assertEqual(args, ['/usr/bin/fw_printenv', '-c', str(Path(folder)/'fw_env.config'),
                                    '-f', str(Path(folder)/'no-default-env'), *boot_state.KEYS])
        with patch.object(boot_environment.platform, 'system', return_value='Windows'), self.assertRaises(ValueError):
            with boot_environment.open_control():
                self.fail('Unsupported platform admitted')

    @unittest.skipUnless(os.name == 'posix', 'Requires Linux privilege and topology adapters')
    def test_startup_gate_refusal_prevents_any_lock_or_raw_environment_access(self):
        with patch.object(boot_environment.platform, 'system', return_value='Linux'), \
                patch.object(boot_environment.os, 'geteuid', return_value=0), \
                patch.object(boot_environment.boot_gate, 'verify', side_effect=ValueError('not ready')), \
                patch.object(boot_environment, 'lock') as locked, \
                patch.object(boot_environment, 'medium') as medium, self.assertRaises(ValueError):
            with boot_environment.open_control():
                self.fail('Missing current boot readiness was admitted')
        locked.assert_not_called(); medium.assert_not_called()

    def test_reserved_ranges_refuse_partition_overlap_and_unsupported_geometry(self):
        table = {'sector_bytes': 512, 'metadata_end': 34*512, 'backup_metadata_start': 32*1024**2-34*512,
                 'partitions': [{'first_lba': 16384}]}
        self.assertEqual(boot_media.environment_ranges(table), ((1048576, 1114112), (5242880, 5308416)))
        for changed in ({'sector_bytes': 4096}, {'metadata_end': 1048577},
                        {'partitions': [{'first_lba': 2048}]}, {'backup_metadata_start': 8388608}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                boot_media.environment_ranges({**table, **changed})

    def test_gpt_checks_both_headers_arrays_ids_slots_sizes_and_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'new.img'
            image(path, first_lba=16384)
            with path.open('rb') as stream:
                table = boot_media.inspect(stream, path.stat().st_size)
            self.assertEqual(len(table['partitions']), 6)
            self.assertEqual(table['partitions'][3]['uuid'], '00000000-0000-0000-0000-000000000004')
            self.assertEqual(boot_media.environment_ranges(table)[0], (1048576, 1114112))
            for options in ({'overlap': True}, {'unequal': True}, {'backup_differs': True}):
                image(path, **options)
                with path.open('rb') as stream, self.subTest(options=options), self.assertRaises(ValueError):
                    boot_media.inspect(stream, path.stat().st_size)
            image(path)
            saved = path.read_bytes()
            for location in (446, 450, 454, 458, 462, 510, 512, 512+16,
                             2*512+16, len(saved)-512+16, len(saved)-1024):
                body = bytearray(saved); body[location] ^= 1
                with self.subTest(location=location), self.assertRaises(ValueError):
                    boot_media.inspect(io.BytesIO(body), len(body))
            for size, sector in ((0, 512), (4096, 512), (len(saved), 513), (True, 512)):
                with self.subTest(size=size, sector=sector), self.assertRaises(ValueError):
                    boot_media.inspect(io.BytesIO(saved), size, sector)

    @unittest.skipUnless(os.name == 'posix', 'Requires Linux root lock metadata; UID modeled only for LLT')
    def test_root_lock_refuses_links_bad_modes_and_contention_without_unlink(self):
        from tests.support.appliance_storage_unit import controlled_ownership
        with tempfile.TemporaryDirectory() as folder, controlled_ownership(), \
                patch.object(boot_environment.os, 'geteuid', return_value=0):
            area = Path(folder)/'state'
            with boot_environment.lock(area):
                inode = (area/'lock').stat().st_ino
                with self.assertRaises(BlockingIOError):
                    with boot_environment.lock(area):
                        self.fail('Concurrent lock admitted')
            with boot_environment.lock(area):
                self.assertEqual((area/'lock').stat().st_ino, inode)
            (area/'lock').write_bytes(b'x')
            with self.assertRaises(ValueError):
                with boot_environment.lock(area):
                    self.fail('Nonempty lock admitted')
            (area/'lock').unlink(); (area/'lock').symlink_to(area/'other')
            with self.assertRaises(OSError):
                with boot_environment.lock(area):
                    self.fail('Linked lock admitted')
            (area/'lock').unlink(); area.chmod(0o755)
            with self.assertRaises(ValueError):
                with boot_environment.lock(area):
                    self.fail('Public state directory admitted')

    @unittest.skipUnless(os.name == 'posix', 'Requires Linux topology and block-node stat adapters')
    def test_medium_binds_gpt_to_kernel_parent_geometry_uuid_and_supported_transport(self):
        from tests.support.boot_storage_kernel_fixture import kernel_tree
        from zmala_system import boot_layout
        with kernel_tree() as fixture:
            parent = fixture.parent
            for name, body in {'uevent': 'DEVTYPE=disk\nDEVNAME=mmcblk0\n',
                               'size': '65536\n', 'device/type': 'SD\n',
                               'queue/logical_block_size': '512\n'}.items():
                path = parent/name; path.parent.mkdir(exist_ok=True); path.write_text(body)
            for number in (4, 6):
                (parent/f'mmcblk0p{number}/start').write_text(str(16384+number*2048)+'\n')
            node = fixture.nodes/'mmcblk0'; node.touch()
            fixture.node_info[node] = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(179, 0))
            root = fixture.system.partition('179:4'); data = fixture.system.partition('179:6')
            model = fixture.base/'model'; model.write_bytes(b'Raspberry Pi 4 Model B Rev 1.5\0')
            parts = [{'index': number, 'first_lba': 16384+number*2048,
                      'bytes': 65536*512, 'type': boot_layout.LINUX_PARTITION,
                      'uuid': f'00000000-0000-0000-0000-{number:012d}'} for number in range(1, 7)]
            table = {'sector_bytes': 512, 'metadata_end': 34*512,
                     'backup_metadata_start': 100*1024**2, 'partitions': parts}
            stream = io.BytesIO(); stream.fileno = lambda: 99
            def read(path, limit=256):
                body = path.read_bytes()
                self.assertLessEqual(len(body), limit)
                return body
            with patch.object(boot_environment.boot_devices, 'read', side_effect=read), \
                    patch.object(boot_environment.os, 'open', return_value=99) as opened, \
                    patch.object(boot_environment.os, 'fdopen') as wrapped, \
                    patch.object(boot_environment.os, 'fstat', return_value=fixture.node_info[node]), \
                    patch.object(boot_media, 'inspect', return_value=table), \
                    patch.object(fixture.system, 'probe', side_effect=lambda item: {
                        'PART_ENTRY_UUID': parts[item.number-1]['uuid']}):
                wrapped.return_value.__enter__.return_value = stream
                self.assertEqual(boot_environment.medium(fixture.system, root, data, parts[3]['uuid'], 'A', model_path=model), node)
                self.assertEqual(opened.call_args.args[0], node)
                for path, value in ((parent/'device/type', 'MMC\n'),
                                    (parent/'queue/logical_block_size', '4096\n'),
                                    (parent/'mmcblk0p6/start', '1\n')):
                    previous = path.read_bytes(); path.write_text(value)
                    with self.subTest(path=path), self.assertRaises(ValueError):
                        boot_environment.medium(fixture.system, root, data, parts[3]['uuid'], 'A', model_path=model)
                    path.write_bytes(previous)
                with self.assertRaises(ValueError):
                    boot_environment.medium(fixture.system, root, data, parts[4]['uuid'], 'A', model_path=model)
                model.write_bytes(b'Raspberry Pi 5 Model B\0')
                with self.assertRaises(ValueError):
                    boot_environment.medium(fixture.system, root, data, parts[3]['uuid'], 'A', model_path=model)
