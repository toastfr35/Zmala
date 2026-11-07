"""Check that only named regular cache members can enter a hosted build."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import terminal_build_cache


class TerminalBuildCacheTests(unittest.TestCase):
    def test_unpack_rejects_foreign_paths_links_and_duplicates(self):
        allowed = 'base/packages.lock.json'
        cases = (
            (('../outside', tarfile.REGTYPE),),
            ((allowed, tarfile.SYMTYPE),),
            ((allowed, tarfile.REGTYPE), (allowed, tarfile.REGTYPE)),
        )
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root/'cache.tar'
                with tarfile.open(source, 'w:') as archive:
                    for name, kind in entries:
                        entry = tarfile.TarInfo(name)
                        entry.type = kind
                        entry.size = 1
                        archive.addfile(entry, io.BytesIO(b'x'))
                with patch.object(terminal_build_cache, 'inventory',
                                  return_value=({}, {allowed: 1, 'terminal/packages.lock.json': 1})):
                    with self.assertRaisesRegex(ValueError, 'Unexpected or duplicate'):
                        terminal_build_cache.unpack(source, root/'output')
                self.assertFalse((root/'outside').exists())
