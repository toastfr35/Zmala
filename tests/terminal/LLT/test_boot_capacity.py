# @test T-LLT-105
# @requirements LLR-TERM-MAINT-058
# @environment portable
# @plan Exercise compact GPT admission, wrong capacity/identity/geometry and checksum refusal, both slots, partial metadata writes at every boundary, readback failure and repeat no-op. Use controlled Linux facts to check factory-only admission, supported transport and capacity failure before identity/startup.
# @pass Named assertions pass; Linux-only adapter skips are not passes. Synthetic interruptions do not establish physical power-loss recovery or Pi boot.
from tests.support import boot_capacity_unit


class CapacityTests(boot_capacity_unit.CapacityScenario):
    role = 'terminal'
