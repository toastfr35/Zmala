# @test T-HLT-049
# @requirements HLR-TERM-MAINT-035
# @environment linux-root
# @plan In a private Linux mount/network/PID namespace, create only temporary ext4 file images for two synthetic read-only terminal roots and separate persistent data plus RAM work. Run the real helper, use chroot and app UID 1000 to check state/identity/key permissions and slot package records, change RAM views, then prepare the second root and assert persistent bytes survive while defaults/package state change and volatile edits vanish. Reject wrong-role/linked identity inputs and inject pre/post-mount failures to verify cleanup and truthful readiness.
# @pass All kernel mount, chroot, permission and cleanup assertions pass; root-only skips are not passes. This is synthetic namespace integration, not physical boot, power-cut or updater qualification.
from tests.support import appliance_storage_namespace


class StorageTests(appliance_storage_namespace.StorageNamespaceScenario):
    role = 'terminal'
