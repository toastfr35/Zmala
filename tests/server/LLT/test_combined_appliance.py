# @test S-LLT-073
# @requirements LLR-SRV-HOST-029
# @environment portable
# @plan Assert exact combined policy, separate component owners and private binding paths, and reject standalone/combined policy substitution. Execute factory identity, startup gate and boot-state transition unit scenarios with the combined role, including selector fallback and explicit confirmation. POSIX-only cases report skips separately.
# @pass All named assertions pass; controlled adapters and skipped cases do not establish hardware or actual mount isolation.
from tests.support import combined_appliance_unit, device_identity_unit, boot_storage_unit, boot_state_unit


class CombinedTests(combined_appliance_unit.CombinedPolicyScenario,
                    device_identity_unit.IdentityScenario,
                    boot_storage_unit.BootStorageScenario,
                    boot_state_unit.BootStateScenario):
    role = 'combined'
