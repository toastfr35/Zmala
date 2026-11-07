"""Fresh synthetic factory data, never copied from an installed device."""
import json

from zmala_system import device_identity as identity, host_storage as storage


def factory(data, role):
    data.mkdir(mode=0o700, exist_ok=True)
    data.chmod(0o700)
    path = data/identity.FACTORY
    path.write_text(json.dumps(identity.factory_profile(role)))
    path.chmod(0o600)
    return data


class Facts:
    """Controlled mount facts for LLT; HLT uses actual kernel mount facts."""
    def __init__(self, data):
        self.table = {data: storage.Mount(data, '7:91', frozenset({'rw'}), 'ext4')}

    def facts(self):
        return dict(self.table)
