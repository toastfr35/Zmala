"""Shared assertions for both products' SSH transport and job-monitor contract."""
import hashlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from build_tools.windows_installer import ssh_transport as backend


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class SSHContract:
    # The concrete LLT supplies its own product Deployment class.
    def deployment(self):
        return self.deployment_class('test.invalid', emit=Mock())

    def test_empty_and_whitespace_hosts_never_connect(self):
        for host in ('', ' ', 'pi other'):
            with self.subTest(host=host), self.assertRaises(backend.InstallError):
                self.deployment_class(host)

    def test_connection_closes_old_session_and_pins_verified_key(self):
        d = self.deployment(); old = Mock(); d.client = old; d.key = 'SHA256:pinned'
        d.wired_address = '192.0.2.1'
        with patch.object(backend.paramiko, 'SSHClient') as factory:
            client = factory.return_value
            client.get_transport.return_value.get_remote_server_key.return_value.asbytes.return_value = b'key'
            d.connect()
            old.close.assert_called_once()
            self.assertEqual(client.set_missing_host_key_policy.call_args.args[0].expected, 'SHA256:pinned')
            client.connect.assert_called_once_with('192.0.2.1', username=d.user, password=d.password,
                timeout=10, auth_timeout=10, banner_timeout=10, look_for_keys=False, allow_agent=False)
            client.get_transport.return_value.set_keepalive.assert_called_once_with(10)
            self.assertTrue(d.key.startswith('SHA256:'))
            d.close(); d.close(); client.close.assert_called_once(); self.assertIsNone(d.client)
            client.connect.side_effect = OSError('offline')
            with self.assertRaisesRegex(OSError, 'offline'): d.connect()
            self.assertEqual(client.close.call_count, 2)
            self.assertIsNone(d.client)

    def test_identity_pin_accepts_first_contact_and_rejects_changed_key(self):
        key = Mock(); key.asbytes.return_value = b'original'
        backend.TargetKeyPolicy(None).missing_host_key(None, 'pi', key)
        policy = backend.TargetKeyPolicy(backend.fingerprint(key))
        policy.missing_host_key(None, 'pi', key)
        key.asbytes.return_value = b'changed'
        with self.assertRaisesRegex(backend.InstallError, 'identity changed'):
            policy.missing_host_key(None, 'pi', key)

    def test_package_digest_checked_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'payload.tgz'; archive.write_bytes(b'archive')
            checksum = archive.with_name(archive.name + '.sha256')
            digest = hashlib.sha256(b'archive').hexdigest()
            checksum.write_text(digest + '  payload.tgz\n', encoding='ascii')
            self.assertEqual(backend.verify_payload(archive), digest)
            archive.write_bytes(b'corrupt')
            with self.assertRaisesRegex(backend.InstallError, 'damaged'):
                backend.verify_payload(archive)

    def test_remote_inventory_uses_observed_eth_addresses_and_ssh_endpoint(self):
        from build_tools.windows_installer import remote_probe as probe
        reads={'/etc/os-release':'ID=debian\nVERSION_CODENAME="trixie"\nignored',
               '/proc/device-tree/model':'Raspberry Pi 4 Model B', '/etc/rpi-issue':'Raspberry Pi reference',
               '/sys/class/net/eth0/operstate':'up','/proc/sys/kernel/random/boot_id':'newboot'}
        with patch.object(probe,'read',side_effect=lambda path:reads.get(path,'')), \
                patch.object(probe.subprocess,'check_output',side_effect=['[{"addr_info":[{"local":"192.0.2.1"},{"local":"fd00::1"}]}]','arm64\n']), \
                patch.object(probe.socket,'gethostname',return_value='pi'), patch.object(probe.platform,'machine',return_value='aarch64'), \
                patch.dict(probe.os.environ,{'SSH_CONNECTION':'192.0.2.2 4321 192.0.2.1 22'}), \
                patch.object(probe.os.path,'ismount',return_value=True), patch.object(probe.shutil,'disk_usage',return_value=SimpleNamespace(free=123)), \
                patch.object(probe.Path,'is_dir',return_value=True):
            result=probe.inventory()
        self.assertEqual(result['ethernet_addresses'],['192.0.2.1','fd00::1'])
        self.assertEqual(result['ssh_address'],'192.0.2.1'); self.assertTrue(result['ethernet_up'])
        self.assertEqual(result['architecture'],'arm64'); self.assertEqual(result['os']['VERSION_CODENAME'],'trixie')
        self.assertEqual(result['free_boot'],123); self.assertEqual(result['boot_id'],'newboot')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model'; path.write_text(' Pi\x00\n',encoding='utf-8')
            self.assertEqual(probe.read(path),'Pi'); self.assertEqual(probe.read(path.with_name('missing')),'')

    def test_command_streams_all_bytes_before_status_and_closes_channel(self):
        d = self.deployment(); d.client = Mock()
        channel = d.client.get_transport.return_value.open_session.return_value
        channel.recv_ready.side_effect = [False, True, True, False]
        channel.exit_status_ready.side_effect = [False, True]
        channel.recv.side_effect = [b'first ', b'last\xff']
        channel.recv_exit_status.return_value = 0
        clock = Clock()
        with patch.object(backend, 'time', clock):
            self.assertEqual(d.command('python3 -', 'script', sudo=True), 'first last\ufffd')
        channel.exec_command.assert_called_once_with('sudo -S -k -p "" python3 -')
        channel.sendall.assert_called_once_with((d.password + '\nscript').encode())
        channel.shutdown_write.assert_called_once(); channel.close.assert_called_once()
        d.emit.assert_not_called()  # Password/input is never copied to progress logs.

    def test_command_error_timeout_and_send_error_always_close(self):
        for failure in ('status', 'timeout', 'send'):
            with self.subTest(failure=failure):
                d = self.deployment(); d.client = Mock()
                channel = d.client.get_transport.return_value.open_session.return_value
                channel.recv_ready.return_value = False
                channel.exit_status_ready.return_value = failure != 'timeout'
                channel.recv_exit_status.return_value = 23
                if failure == 'send': channel.sendall.side_effect = OSError('broken pipe')
                with patch.object(backend, 'time', Clock()), self.assertRaises((backend.InstallError, OSError)) as error:
                    d.command('operation', 'input' if failure == 'send' else '', timeout=.1)
                self.assertIn({'status':'exit 23','timeout':'Timed out','send':'broken pipe'}[failure], str(error.exception))
                channel.close.assert_called_once()

    def test_reconnect_retries_transport_loss_but_never_identity_failure(self):
        d = self.deployment(); d.connect = Mock(side_effect=[OSError(), EOFError(), None])
        clock = Clock()
        with patch.object(backend, 'time', clock): d.reconnect(20)
        self.assertEqual(d.connect.call_count, 3); self.assertEqual(clock.now, 6)
        d.connect = Mock(side_effect=backend.InstallError('identity changed'))
        with patch.object(backend, 'time', clock), self.assertRaisesRegex(backend.InstallError, 'identity changed'):
            d.reconnect(20)
        d.connect.assert_called_once()
        d.connect.side_effect = OSError()
        with patch.object(backend, 'time', clock), self.assertRaisesRegex(backend.InstallError, 'continues independently'):
            d.reconnect(10)

    def monitor_fixture(self, contents):
        d = self.deployment(); d.client = MagicMock()
        sftp = d.client.open_sftp.return_value.__enter__.return_value
        streams = []
        def open_log(*args):
            stream = io.BytesIO(next(contents)); streams.append(stream); return stream
        sftp.open.side_effect = open_log
        return d

    def test_monitor_resumes_offset_and_drains_final_tail_after_reconnect(self):
        d = self.monitor_fixture(iter([b'one', b'one two', b'one two END']))
        d.command = Mock(side_effect=[EOFError(), 'ActiveState=active\nSubState=exited\nExecMainStatus=0\nResult=success'])
        d.reconnect = Mock()
        with patch.object(backend, 'time', Clock()): d.monitor('unit', '/progress.log')
        d.reconnect.assert_called_once_with(120)
        output = ''.join(c.args[0] for c in d.emit.call_args_list)
        self.assertEqual(output.count('one'), 1); self.assertEqual(output.count('two'), 1)
        self.assertTrue(output.endswith(' END'))

    def test_monitor_rejects_inactive_failed_and_unsuccessful_exit(self):
        for state in ('ActiveState=failed', 'ActiveState=inactive',
                      'ActiveState=active\nSubState=exited\nExecMainStatus=0\nResult=timeout',
                      'ActiveState=active\nSubState=exited\nExecMainStatus=2\nResult=success'):
            with self.subTest(state=state):
                d = self.monitor_fixture(iter([b'failure', b'failure tail']))
                d.command = Mock(return_value=state)
                with patch.object(backend, 'time', Clock()), self.assertRaises(backend.InstallError):
                    d.monitor('unit', '/progress.log')
                if 'exited' not in state:
                    self.assertEqual(''.join(c.args[0] for c in d.emit.call_args_list), 'failure tail')

    def test_monitor_timeout_does_not_retry_install(self):
        import itertools
        d = self.monitor_fixture(itertools.repeat(b''))
        d.command = Mock(return_value='ActiveState=activating\nSubState=start')
        with patch.object(backend, 'time', Clock()), self.assertRaisesRegex(backend.InstallError, 'may still be running'):
            d.monitor('unit', '/progress.log')
        self.assertEqual(d.command.call_count, 1800)
