import shutil
import unittest

from zmala_images import security_refresh


@unittest.skipUnless(shutil.which('dpkg'), 'Debian version comparison requires dpkg')
class SecurityRefreshTests(unittest.TestCase):
    def test_only_new_security_versions_for_installed_packages_trigger(self):
        index = (
            'Package: openssl\nVersion: 3.5.7-1~deb13u3\n\n'
            'Package: libc6\nVersion: 2.41-12+deb13u4\n\n'
            'Package: unused\nVersion: 4.5\n'
        )
        installed = {'openssl': '3.5.7-1~deb13u2', 'libc6': '2.41-12+rpt1+deb13u4'}
        self.assertEqual(security_refresh.security_updates([index], installed),
                         {'openssl': '3.5.7-1~deb13u3'})

    def test_picks_highest_version_across_security_indexes(self):
        indexes = [
            'Package: example\nVersion: 1:3.5-1\n',
            'Package: example\nVersion: 3.6-1\n',
        ]
        self.assertEqual(security_refresh.security_updates(indexes, {'example': '3.4-1'}),
                         {'example': '1:3.5-1'})
