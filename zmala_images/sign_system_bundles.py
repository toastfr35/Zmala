"""Sign reviewed standalone Terminal input archives inside the release workflow."""
import argparse
from configparser import ConfigParser
from pathlib import Path
import shutil
import subprocess
import tarfile

from zmala_system import boot_capacity, update_discovery
from . import system_bundle

FILES = {'manifest.raucm': None, 'boot.vfat': boot_capacity.SIZES[1], 'root.ext4': boot_capacity.SIZES[3]}


def extract(path, directory):
    directory.mkdir()
    expected = FILES.copy()
    with subprocess.Popen(['zstd', '-dc', '--', str(path)], stdout=subprocess.PIPE) as decoder:
        try:
            with tarfile.open(fileobj=decoder.stdout, mode='r|') as archive:
                for member in archive:
                    name = member.name
                    if (name not in expected or not member.isfile() or
                            (name == 'manifest.raucm' and not 0 < member.size <= 4096) or
                            (name != 'manifest.raucm' and member.size != expected[name])):
                        raise ValueError('Invalid unsigned system bundle member')
                    del expected[name]
                    with archive.extractfile(member) as source, (directory/name).open('xb') as target:
                        shutil.copyfileobj(source, target, 1024**2)
        except BaseException:
            decoder.kill()
            raise
        # Drain the tar end marker and padding so the decoder can report errors.
        while decoder.stdout.read(1024**2):
            pass
        if decoder.wait(timeout=30) or expected:
            raise ValueError('Incomplete unsigned system bundle archive')


def sign(source, output, cert, key):
    output.mkdir()
    versions = None
    for slot in ('A', 'B'):
        directory = source/slot
        extract(source/(slot+'.tar.zst'), directory)
        manifest = (directory/'manifest.raucm').read_text(encoding='ascii')
        config = ConfigParser(interpolation=None)
        config.read_string(manifest)
        identity = config['update']['version'], config['meta.zmala']['terminal-version']
        if manifest != system_bundle.manifest(slot, *identity) or versions not in (None, identity):
            raise ValueError('Slot inputs do not describe the same hook-free release')
        versions = identity
        bundle = output/f'ZmalaTerminal-System-{slot}.raucb'
        subprocess.run(['rauc', f'--cert={cert}', f'--key={key}', 'bundle', str(directory), str(bundle)],
                       check=True, timeout=900)
        if bundle.stat().st_size > 2*1024**3:
            raise ValueError('Signed system bundle exceeds the appliance download budget')
        data = subprocess.check_output(['rauc', f'--keyring={cert}', 'info', '--output-format=json-2',
                                        str(bundle)], timeout=30)
        verified = update_discovery.release(data, slot, '0.0.0')
        if not verified or (verified['system_version'], verified['terminal_version']) != identity:
            raise ValueError('Signed bundle does not match the reviewed input')
        shutil.rmtree(directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'certificate', 'key'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    sign(args.source, args.output, args.certificate, args.key)
