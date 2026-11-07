# @test T-HLT-051
# @requirements HLR-TERM-MAINT-044
# @environment linux-root
# @plan In a private mount/network/PID namespace create only a new regular GPT loop image and guarded private partition nodes. Use actual sysfs, ext4 and block probes with controlled slot command lines for both read-only terminal roots and their same-parent data. Assert initialized identity/data preservation, new defaults/package state, complete readiness and gate refusal without its RAM record or fixed identity binding. Reject a mismatched slot and pre/post-data or post-view mount failures with preserved input mounts and identity.
# @pass All selected-root, block, mount, readiness and cleanup assertions pass. Root-only skips are not passes; this is controlled-command-line namespace integration, not actual initramfs/PID1 boot or physical power-loss qualification.
from tests.support import boot_storage_namespace


class BootStorageTests(boot_storage_namespace.BootStorageNamespaceScenario):
    role = 'terminal'
