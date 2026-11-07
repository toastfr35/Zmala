"""Read-only regular-image GPT audit; never open a block device."""
import os
from pathlib import Path
import stat

from zmala_system.boot_media import inspect


def audit(path, sector=512):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Expected a regular image file, never a device or symlink')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError('Image changed while opening')
        result = inspect(stream, info.st_size, sector)
        if os.fstat(stream.fileno()).st_size != info.st_size:
            raise ValueError('Image length changed during inspection')
    partitions = [{key: value for key, value in row.items() if key != 'uuid'}
                  for row in result['partitions']]
    return {'schema': 1, 'checks': 'probe-gpt-integrity', 'image_bytes': info.st_size,
            'sector_bytes': sector, 'partitions': partitions, 'production_qualified': False}
