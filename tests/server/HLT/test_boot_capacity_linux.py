# @test S-HLT-044
# @requirements HLR-SRV-HOST-030
# @environment linux-root
# @plan Create new sparse compact GPT files with native sfdisk, extend to 16 GB and 32 GB, and run actual relocation/fsync/readback for both selected slots and every durable-write interruption. Check partition IDs/extents, boot-gap and partition sentinels, repeat no-op and native sfdisk verification.
# @pass All native-file assertions pass without skipped cases. These fixtures contain metadata/sentinels rather than bootable filesystems; actual Pi boot and physical power cuts remain unqualified.
from tests.support import boot_capacity_linux


class CapacityTests(boot_capacity_linux.CapacityLinuxScenario):
    role = 'server'
