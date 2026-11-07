"""Disposable namespace worker for offline application construction and target checks."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from zmala_system import host_storage
from . import application_inputs, application_provision as provision, application_ssh_check, package_lock
from .initramfs_worker import command, unpack_root


def unmount(root):
    errors = []
    for target in sorted(host_storage.NativeMounts.facts(), key=lambda p: len(p.parts), reverse=True):
        if target.is_relative_to(root):
            try:
                command(['umount', target], timeout=30)
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(error)
    if errors:
        raise errors[0]
    if any(p.is_relative_to(root) for p in host_storage.NativeMounts.facts()):
        raise ValueError('Application worker mounts remain active')


def validate_request(request, request_path):
    if (os.geteuid() != 0 or request.get('schema') != 1
            or set(request) != {'schema', 'role', 'source', 'root_sha256', 'applications',
                               'applications_sha256', 'output', 'host_namespaces'}):
        raise ValueError('Unsupported namespace worker invocation')
    namespaces = request['host_namespaces']
    if (set(namespaces) != {'user', 'mnt', 'pid', 'net'}
            or any(os.readlink('/proc/self/ns/'+name) == value for name, value in namespaces.items())):
        raise ValueError('Application worker needs separate user/mount/network/PID namespaces')
    inside, outside, length = map(int, Path('/proc/self/uid_map').read_text().splitlines()[0].split())
    if inside != 0 or outside == 0 or length != 1:
        raise ValueError('Expected subordinate user namespace, not host root')
    output = Path(request['output'])
    if (not output.is_absolute() or output.resolve() != output or output == Path('/')
            or Path(request_path).resolve().parent != output
            or package_lock.digest(request['source']) != request['root_sha256']):
        raise ValueError('Changed source or unsafe worker output')
    return output


def server_smoke(root, role):
    """Start target Node as its service UID with throwaway RAM data and loopback."""
    uid = 1001 if role == 'combined' else 1000
    data = host_storage.safe(root, 'var/lib/zmalacall-server')
    data.mkdir(mode=0o700, exist_ok=True)
    command(['mount', '-t', 'tmpfs', '-o', 'mode=0700,size=32M,uid='+str(uid)+',gid='+str(uid), 'tmpfs', data])
    command(['chroot', root, '/usr/bin/systemd-tmpfiles', '--create', '--prefix=/var/lib/zmalacall-server',
             '/usr/lib/tmpfiles.d/zmala-appliance.conf'])
    command(['ip', 'link', 'set', 'lo', 'up'])
    script = '''const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const {once} = require('node:events');
const deadline = setTimeout(() => { console.error('Server smoke timed out'); process.exit(2); }, 20000);
(async () => {
  const app = await require('/opt/zmalacall-server/current/zmala_server/main.js').start();
  if (!app.server.listening) await once(app.server, 'listening');
  const port = app.server.address().port;
  const response = await new Promise((resolve, reject) => {
    http.get({hostname:'127.0.0.1',port,path:'/ready'}, res => {
      let body = ''; res.on('data', chunk => body += chunk);
      res.on('end', () => resolve({status:res.statusCode,body}));
    }).on('error', reject);
  });
  assert.equal(response.status, 200);
  assert.deepEqual(JSON.parse(response.body), {ok:true,persistence:true});
  assert.ok(fs.statSync('/var/lib/zmalacall-server/bootstrap/terminal.json').size > 0);
  console.log('ARM64 service UID startup, bootstrap publication and HTTP readiness passed');
  clearTimeout(deadline); process.kill(process.pid, 'SIGTERM');
})().catch(error => { console.error(error); process.exit(1); });
'''
    try:
        command(['chroot', root, '/usr/bin/setpriv', '--reuid='+str(uid), '--regid='+str(uid), '--clear-groups',
                 '/usr/bin/env', 'NODE_ENV=production', 'VIDEOCALL_HOST=127.0.0.1',
                 'ZMALA_ADMIN_PASSWORD_FILE=/var/lib/zmalacall-server/admin-password.json',
                 'ZMALA_BOOTSTRAP_EXPORT_DIRECTORY=/var/lib/zmalacall-server/bootstrap',
                 '/usr/bin/node', '-e', script], timeout=60)
    finally:
        command(['umount', data], timeout=30)
    if any(data.iterdir()):
        raise ValueError('Smoke check must not leave factory application state')
    data.rmdir()


def terminal_smoke(root):
    """Exercise the real core with deferred media and no hardware device nodes."""
    data = host_storage.safe(root, 'var/lib/zmalacall')
    data.mkdir(mode=0o700, exist_ok=True)
    command(['mount', '-t', 'tmpfs', '-o', 'mode=0700,size=32M,uid=1000,gid=1000', 'tmpfs', data])
    script = '''import pathlib, sys, time
root = pathlib.Path('/opt/zmalacall/current')
sys.path.insert(0, str(root))
for path in (root/'zmala_terminal').rglob('*.py'):
    compile(path.read_bytes(), str(path), 'exec')
from zmala_terminal.common.engine import Engine
engine = Engine({}, lambda *args: None, lambda *args: None, profile='image-build-probe', defer_media=True)
try:
    for _ in range(10):
        engine.iterate(); time.sleep(.05)
finally:
    engine.close()
print('ARM64 terminal service UID native core startup, iteration and shutdown passed')
'''
    try:
        command(['chroot', root, '/usr/bin/setpriv', '--reuid=1000', '--regid=1000', '--clear-groups',
                 '/usr/bin/env', 'PYTHONDONTWRITEBYTECODE=1', '/usr/bin/python3', '-IB', '-c', script], timeout=90)
    finally:
        command(['umount', data], timeout=30)
    if any(data.iterdir()):
        raise ValueError('Terminal smoke check must not leave factory application state')
    data.rmdir()


def wifi_smoke(root):
    """Reject images that have NetworkManager but cannot start its Wi-Fi backend."""
    required = (
        'usr/sbin/wpa_supplicant',
        'usr/share/dbus-1/system-services/fi.w1.wpa_supplicant1.service',
        'usr/share/dbus-1/system.d/wpa_supplicant.conf',
        'usr/lib/systemd/system/wpa_supplicant.service',
    )
    if any(not (root/name).is_file() for name in required):
        raise ValueError('Terminal image lacks the Wi-Fi supplicant or its activation configuration')
    activation = (root/required[1]).read_text()
    if ('Name=fi.w1.wpa_supplicant1' not in activation
            or 'SystemdService=wpa_supplicant.service' not in activation):
        raise ValueError('Unexpected Wi-Fi D-Bus activation configuration')
    # Target execution catches missing shared libraries as well as missing files.
    command(['chroot', root, '/usr/sbin/wpa_supplicant', '-v'], timeout=30)
    command(['chroot', root, '/usr/bin/systemd-analyze', '--man=no', 'verify',
             'wpa_supplicant.service'], timeout=60)


def worker(request_path):
    request = json.loads(Path(request_path).read_text())
    output = validate_request(request, request_path)
    records, manifest = application_inputs.verify(request['applications'], request['applications_sha256'], request['role'])
    root = output/'root'
    root.mkdir(mode=0o700)
    role = request['role']
    try:
        command(['mount', '--make-rprivate', '/'])
        unpack_root(request['source'], root)
        for name, filesystem, options in (('proc', 'proc', 'nosuid,nodev,noexec'),
                ('dev', 'tmpfs', 'mode=0755,size=8M'), ('run', 'tmpfs', 'mode=0755,size=32M'),
                ('tmp', 'tmpfs', 'mode=1777,size=512M')):
            path = host_storage.safe(root, name)
            path.mkdir(exist_ok=True)
            command(['mount', '-t', filesystem, '-o', options, filesystem, path])
        for name in ('null', 'zero', 'random', 'urandom'):
            path = root/'dev'/name
            path.touch()
            command(['mount', '--bind', '/dev/'+name, path])
        result = provision.provision(root, records, role)
        application_ssh_check.check(root, role)
        native = {}
        if role in ('terminal', 'combined'):
            wifi_smoke(root)
            prefix = '/'+provision.TERMINAL
            command(['chroot', root, '/bin/sh', prefix+'/build_tools/linux/build-media.sh'], timeout=900)
            command(['chroot', root, '/usr/bin/env', 'ZMALA_OFFLINE_BUILD=1', 'PYTHONDONTWRITEBYTECODE=1',
                     '/usr/bin/python3', prefix+'/build_tools/linux/build-turn.py'], timeout=900)
            for name in ('zmala_terminal/linux/media/video/libzmala_video.so',
                         'zmala_terminal/linux/media/audio/libzmala_speech_audio.so',
                         'zmala_terminal/linux/turn-runtime/turn-fix.so'):
                path = root/provision.TERMINAL/name
                body = path.read_bytes()[:20]
                if body[:5] != b'\x7fELF\x02' or body[18:20] != b'\xb7\x00':
                    raise ValueError('Expected an ARM64 native application library')
                native[name] = package_lock.digest(path)
            # Loading libraries and Python UI dependencies does not instantiate
            # media devices or a display; this namespace contains no such devices.
            script = 'import ctypes, tkinter, PIL.Image, gi, cv2, websocket, cryptography\n'
            script += '\n'.join('ctypes.CDLL('+repr(prefix+'/'+name)+')' for name in native)
            command(['chroot', root, '/usr/bin/python3', '-IB', '-c', script], timeout=120)
            terminal_smoke(root)
        if role in ('server', 'combined'):
            prefix = '/'+provision.SERVER
            command(['chroot', root, '/usr/bin/node', prefix+'/build_tools/build-admin.cjs'])
            script = 'process.chdir('+json.dumps(prefix+'/zmala_server')+');'
            script += 'require(process.cwd()+"/main.js");'
            command(['chroot', root, '/usr/bin/node', '-e', script], timeout=120)
            server_smoke(root, role)
        command(['chroot', root, '/usr/bin/systemd-analyze', '--man=no', 'verify',
                 *result['units'], 'NetworkManager.service'], timeout=120)
        result.update(schema=1, application_installed=True, native_libraries=native,
                      target_application_imports_checked=True, target_unit_graph_checked=True,
                      source_commit=manifest['source_commit'],
                      components=manifest['components'],
                      applications_sha256=request['applications_sha256'],
                      server_namespace_readiness_checked=role in ('server', 'combined'),
                      terminal_namespace_core_checked=role in ('terminal', 'combined'),
                      target_wifi_supplicant_checked=role in ('terminal', 'combined'),
                      target_developer_ssh_checked=True,
                      hardware_services_started=False)
        provision.put(root, 'usr/lib/zmala-application-build.json', json.dumps(result, indent=2)+'\n')
        unmount(root)
        command(['tar', '--create', '--format=pax', '--numeric-owner', '--sort=name',
                 '--mtime=@'+os.environ['SOURCE_DATE_EPOCH'], '--pax-option=delete=atime,delete=ctime',
                 '--file', output/'root.tar', '--directory', root, '.'], timeout=300)
        (output/'worker-result.json').write_text(json.dumps(result, indent=2)+'\n')
    finally:
        primary_failed = sys.exc_info()[0] is not None
        try:
            unmount(root)
            if root.resolve() == root and root.parent == output and root.name == 'root':
                shutil.rmtree(root)
        except (OSError, ValueError, subprocess.SubprocessError):
            if not primary_failed:
                raise


if __name__ == '__main__':
    worker(sys.argv[1])
