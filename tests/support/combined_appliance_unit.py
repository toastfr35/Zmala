"""Combined-role policy assertions shared by the two component test plans."""
import json
import unittest
from zmala_system import host_layout, boot_layout, boot_state, device_identity


class CombinedPolicyScenario(unittest.TestCase):
    def test_exact_role_and_private_bindings(self):
        expected = host_layout.profile('combined')
        self.assertEqual((expected['terminal_uid'], expected['server_uid']), (1000, 1001))
        for key in ('terminal_uid', 'terminal_gid', 'server_uid', 'server_gid'):
            with self.assertRaises(ValueError):
                host_layout.decode_profile(json.dumps({**expected, key: True}).encode(), 'combined')
        bindings = {b.target: b for b in host_layout.bindings('combined')}
        for component, uid, target in [('terminal', 1000, 'var/lib/zmalacall'),
                                       ('server', 1001, 'var/lib/zmalacall-server')]:
            b = bindings[target]
            self.assertEqual((b.saved, b.uid, b.gid, b.mode), ('state/'+component, uid, uid, 0o700))
            b = bindings['etc/zmalacall/operator/'+component]
            self.assertEqual((b.saved, b.uid, b.gid, b.mode), ('host/operator/'+component, 0, uid, 0o750))
        self.assertNotIn('etc/zmalacall/operator', bindings)
        for target in ('etc/ssh/keys', 'etc/letsencrypt'):
            b = bindings[target]
            self.assertEqual((b.uid, b.gid, b.mode), (0, 0, 0o700))
        self.assertEqual(len(bindings), 11)
        self.assertEqual(len({b.saved for b in bindings.values()}), 11)
        for role in ('server', 'terminal'):
            self.assertEqual(host_layout.profile(role)['application_uid'], 1000)
            for decoder, builder in ((host_layout.decode_profile, host_layout.profile),
                                     (boot_layout.decode_profile, boot_layout.profile),
                                     (boot_state.decode_policy, boot_state.policy)):
                with self.assertRaises(ValueError):
                    decoder(json.dumps(builder(role)).encode(), 'combined')
                with self.assertRaises(ValueError):
                    decoder(json.dumps(builder('combined')).encode(), role)
            with self.assertRaises(ValueError):
                boot_state.decode(boot_state.encode(boot_state.State(role, 'A')), 'combined')
            with self.assertRaises(ValueError):
                boot_state.decode(boot_state.encode(boot_state.State('combined', 'A')), role)
            with self.assertRaises(ValueError):
                host_layout.decode_profile(json.dumps({'schema': 1, 'role': role}).encode(), 'combined', data=True)
        self.assertEqual(device_identity.factory_profile('combined')['role'], 'combined')
