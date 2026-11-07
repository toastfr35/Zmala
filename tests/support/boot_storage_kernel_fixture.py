"""Synthetic kernel attributes with controlled block-node stat for LLT only."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from zmala_system import boot_devices


@contextmanager
def kernel_tree():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        kernel = base/'kernel'; kernel.mkdir()
        parent = kernel/'mmcblk0'; parent.mkdir()
        (parent/'dev').write_text('179:0\n')
        links = base/'sys-block'; links.mkdir()
        nodes = base/'dev'; nodes.mkdir()
        node_info = {}
        for number in (4, 6):
            child = parent/('mmcblk0p'+str(number)); child.mkdir()
            (child/'partition').write_text(str(number)+'\n')
            (child/'dev').write_text('179:'+str(number)+'\n')
            (child/'size').write_text('65536\n')
            (child/'uevent').write_text(f'DEVNAME=mmcblk0p{number}\nDEVTYPE=partition\nPARTN={number}\n')
            (links/('179:'+str(number))).symlink_to(child, target_is_directory=True)
            node = nodes/child.name; node.touch()
            node_info[node] = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(179, number))
        actual = Path.lstat
        def modeled(path):
            return node_info[path] if path in node_info else actual(path)
        with patch.object(Path, 'lstat', modeled):
            yield SimpleNamespace(base=base, kernel=kernel, parent=parent, links=links,
                                  nodes=nodes, node_info=node_info,
                                  system=boot_devices.NativeBoot(device_root=nodes, sys_blocks=links,
                                                                sys_devices=kernel))
