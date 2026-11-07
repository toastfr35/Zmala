"""Read the host policy shipped for both Pi runtimes, without changing this host."""
import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def assert_storage_policy(test):
    journal = configparser.ConfigParser()
    journal.read(ROOT/'build_tools/linux/low-wear-journal.conf')
    test.assertEqual(journal['Journal']['Storage'], 'volatile')
    test.assertEqual(journal['Journal']['RuntimeMaxUse'], '64M')
    test.assertEqual(journal['Journal']['ForwardToSyslog'], 'no')
    swap = configparser.ConfigParser()
    swap.read(ROOT/'build_tools/linux/low-wear-swap.conf')
    test.assertEqual(swap['Main']['Mechanism'], 'zram')
    test.assertEqual(swap['Zram']['RamMultiplier'], '1')
    test.assertEqual(swap['Zram']['MaxSizeMiB'], '2048')
    # Effective mounts and persistence across reboot need an installed-host HLT.
