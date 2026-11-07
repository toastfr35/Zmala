"""Disposable GPT loop fixtures. No function accepts a physical device input."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time

from tests.support import appliance_storage_fixture, device_identity_fixture
from zmala_system import boot_devices, boot_layout, host_storage


def command(args, text=None):
    return subprocess.run([str(value) for value in args], input=text, text=True,
                          capture_output=True, timeout=30, check=True).stdout.strip()


class PartitionedFixture:
    """Only the new regular backing file can be attached, formatted or detached."""
    def __init__(self, parent, role):
        self.parent, self.role = Path(parent), role
        self.image = self.parent/'new-fixture.img'
        self.loop = None
        self.nodes = {}
        self.root = self.parent/'root'
        self.ram = self.parent/'ram'
        self.area = self.ram/'host'
        self.cmdline = self.parent/'cmdline'

    def owned(self):
        assert self.loop and re.fullmatch('/dev/loop[0-9]+', self.loop)
        parent = Path('/sys/class/block')/Path(self.loop).name
        assert Path((parent/'loop/backing_file').read_text().strip()).resolve() == self.image.resolve()
        return parent

    def setup(self):
        assert self.parent.name.startswith('zmala-boot-storage-')
        assert self.parent.stat().st_mode & 0o777 == 0o700
        with self.image.open('xb') as stream:
            stream.truncate(128*1024**2)
        info = self.image.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        labels = ('bootconfig', 'boot_a', 'boot_b', 'system_a', 'system_b', 'persistent')
        rows, start = ['label: gpt', 'unit: sectors', ''], 2048
        for number, label in enumerate(labels, 1):
            size = 2048 if number <= 3 else 65536
            rows.append(f'start={start},size={size},type=L,name="{label}"'); start += size
        command(['sfdisk', self.image], '\n'.join(rows)+'\n')
        self.loop = command(['losetup', '--find', '--show', '--partscan', self.image])
        parent = self.owned()
        devices = self.parent/'dev'; devices.mkdir(mode=0o700)
        deadline = time.monotonic()+3
        while True:
            partitions = [child for child in parent.iterdir() if (child/'partition').exists()]
            if len(partitions) == 6:
                break
            if time.monotonic() >= deadline:
                raise AssertionError('New fixture loop partitions did not appear')
            time.sleep(0.025)
        for child in partitions:
            if not (child/'partition').exists():
                continue
            number = int((child/'partition').read_text())
            major, minor = map(int, (child/'dev').read_text().split(':'))
            node = devices/child.name
            os.mknod(node, stat.S_IFBLK | 0o600, os.makedev(major, minor))
            assert node.stat().st_rdev == os.makedev(major, minor)
            self.nodes[number] = node
            if number >= 4:
                self.owned()
                command(['mkfs.ext4', '-F', '-q', '-L', labels[number-1], node])
        assert set(self.nodes) == set(range(1, 7))
        self.root.mkdir(); self.ram.mkdir(mode=0o700)
        command(['mount', '-t', 'tmpfs', '-o', 'mode=0700,size=128M', 'tmpfs', self.ram])
        for slot, number in (('A', 4), ('B', 5)):
            command(['mount', self.nodes[number], self.root])
            try:
                appliance_storage_fixture.image(self.root, self.role, slot)
                appliance_storage_fixture.file(self.root/boot_layout.PROFILE,
                                               json.dumps(boot_layout.profile(self.role)).encode())
                appliance_storage_fixture.file(self.root/'usr/lib/zmala/role', (self.role+'\n').encode())
            finally:
                command(['umount', self.root])
        self.stage = self.parent/'stage-data'; self.stage.mkdir()
        self.mount_stage()
        try:
            device_identity_fixture.factory(self.stage, self.role)
        finally:
            command(['umount', self.stage])
        tools = {name: shutil.which(name) for name in ('mount', 'umount', 'blkid')}
        self.system = boot_devices.NativeBoot(device_root=devices, cmdline=self.cmdline, tools=tools)
        return self

    def mount_stage(self):
        self.owned()
        command(['mount', self.nodes[6], self.stage])

    def select(self, slot):
        number = 4 if slot == 'A' else 5
        self.owned()
        command(['mount', '-t', 'ext4', '-o', 'ro', self.nodes[number], self.root])
        record = boot_layout.probe_record(command(['blkid', '-p', '-o', 'export', self.nodes[number]]).encode())
        self.cmdline.write_text('root=PARTUUID='+record['PART_ENTRY_UUID']+' rauc.slot='+slot+' ro\n')

    def close(self):
        # Every mount beneath this exclusive fixture directory belongs to it.
        for point in sorted(host_storage.NativeMounts.facts(), key=lambda path: len(path.parts), reverse=True):
            if point.is_relative_to(self.parent):
                command(['umount', point])
        if self.loop:
            self.owned()
            command(['losetup', '--detach', self.loop])
            self.loop = None
