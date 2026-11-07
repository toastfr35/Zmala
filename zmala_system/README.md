# Shared Pi host runtime

This package owns identity, storage and boot policy for the experimental image-managed
server, terminal and combined roles. It has no UI, media or image-build dependencies.

| Responsibility | Source |
| --- | --- |
| Role layouts and persistent paths | `host_layout.py`, `host_storage.py` |
| Durable first-device identity | `device_identity.py` |
| Boot media and selected-root validation | `boot_media.py`, `boot_devices.py`, `boot_layout.py` |
| Factory compact-card GPT relocation (fixed partition sizes) | `boot_capacity.py` |
| Confirmed/trial boot records and admission | `boot_state.py`, `boot_backend.py`, `boot_select.sh` |
| Early boot and startup gate | `boot_entry.py`, `boot_storage.py`, `boot_gate.py`, service/configuration files |

The [image builder](../zmala_images/README.md) packages this runtime into offline
roots and initramfs. A source move in the builder does not change installed Python
module names, host paths or service identities. Current SSH installations do not
opt into these experimental policies automatically.

Shared behavior links to both server and terminal requirements under
[`requirements/`](../requirements/). Direct unit/system plans remain under
[`tests/server/`](../tests/server/) and [`tests/terminal/`](../tests/terminal/);
shared fixtures are in `tests/support/`. Installer/image checks are ad-hoc tooling
regressions and do not qualify runtime hardware behavior.

See the [system overview](../docs/general.md#sd-images-and-shared-pi-runtime) for
status, [server guide](../docs/server.md#experimental-image-managed-storage) for
host integration and [image build sequence](../zmala_images/README.md#build-sequence-and-ownership)
for assembly and remaining qualification gates.
