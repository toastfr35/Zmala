# @test S-HLT-043
# @requirements HLR-SRV-HOST-028
# @environment linux-root
# @plan Run combined factory identity interruption, GPT startup gate and native environment transitions in private Linux namespaces on new regular files. Across two synthetic read-only ext4 roots, mount both application trees and operator bindings; chroot children as UID/GID 1000 and 1001, persist each component's bytes and reject cross-component state, operator and TLS reads/writes. Verify shared identity, slot-local defaults and cleanup after injected failures.
# @pass All namespace and actual permission assertions pass. Root-only skips are not passes; no actual Pi boot, application health or physical power-cut qualification is claimed.
from tests.support import (appliance_storage_namespace, device_identity_namespace,
                           boot_storage_namespace, boot_state_namespace)


class CombinedTests(appliance_storage_namespace.StorageNamespaceScenario,
                    device_identity_namespace.IdentityNamespaceScenario,
                    boot_storage_namespace.BootStorageNamespaceScenario,
                    boot_state_namespace.BootStateNamespaceScenario):
    role = 'combined'
