# Shared Pi host runtime

A manual Terminal OTA handover has a 12-second admission deadline. On refusal,
the owner publishes a matching error with authenticated bounded blocker codes
and does not automatically retry that release in the same process. A fresh
verified offer and Apply can retry it. A different automatic release remains
eligible. Diagnostic heartbeats use normal file/process/nonce/freshness validation;
only a ready, eligible, maintenance-fenced acknowledgement can authorize installation.

This package owns identity, storage and boot policy for the experimental image-managed
server, terminal and combined roles. The storage and boot core has no UI, media
or image-build dependencies. The standalone Terminal update health probe loads
the candidate Terminal runtime inside its isolated service.

| Responsibility | Source |
| --- | --- |
| Role layouts and persistent paths | `host_layout.py`, `host_storage.py` |
| Durable first-device identity | `device_identity.py` |
| Boot media and selected-root validation | `boot_media.py`, `boot_devices.py`, `boot_layout.py` |
| Factory compact-card GPT relocation (fixed partition sizes) | `boot_capacity.py` |
| Confirmed/trial boot records and admission | `boot_state.py`, `boot_backend.py`, `boot_select.sh` |
| Early boot and startup gate | `boot_entry.py`, `boot_storage.py`, `boot_gate.py`, service/configuration files |
| Standalone Terminal update discovery, installation and trial confirmation | `update_discovery.py`, `update_ipc.py`, `update_install.py`, `update_coordinator.py`, `update_health.py` |

The [image builder](../zmala_images/README.md) packages this runtime into offline
roots and initramfs. A source move in the builder does not change installed Python
module names, host paths or service identities. Current SSH installations do not
opt into these experimental policies automatically.

The [standalone Server factory image](../zmala_images/README.md#standalone-server-factory-image)
uses native Pi boot and one writable root, bypassing this A/B preparation path.
The experimental Server role helpers and tests below do not describe that
factory image's installed storage or recovery behavior.

Shared behavior links to both server and terminal requirements under
[`requirements/`](../requirements/). Direct unit/system plans remain under
[`tests/server/`](../tests/server/) and [`tests/terminal/`](../tests/terminal/);
shared fixtures are in `tests/support/`. Installer/image checks are ad-hoc tooling
regressions and do not qualify runtime hardware behavior.

## Installed state and service boundaries

| Location or service | Purpose |
| --- | --- |
| `/usr/lib/zmala/` | Immutable role, storage, boot and capacity policies; standalone Terminal release identity and public update keyring |
| `/data/identity/` | Durable machine ID and hostname shared by both slots |
| `/data/state/terminal/`, `/data/state/server/` | Role-specific application data, exposed through the declared private bindings |
| `/data/host/ssh/` | Persistent host keys generated after storage initialization |
| `/run/zmala-host/` | Current-boot readiness records and volatile storage working area |
| `zmala-host-storage.service` | Startup gate that checks completed early-boot preparation |
| `zmala-system-update-check.timer` | Standalone Terminal local-midnight discovery and boot catch-up |
| `/data/host/update-discovery/status.json` | Last scheduled discovery date and outcome |
| `/data/host/system-updates/journal.json` | Standalone Terminal installation/trial recovery record |
| `/run/zmalacall-updater/` | Volatile maintenance requests, progress and trial state |

The boot helpers require validated mounts and role policies supplied by the
image boot path. They are not commands for repairing an arbitrary live root or
converting a legacy installation. Preserve persistent identity and journals when
collecting diagnostics; editing them is not a supported recovery procedure.

For the update sequence, watchdog limits and card-recovery boundary, read
[update protections](../safe_upgrade_system.md). The private records above may
be absent on legacy installations or roles that do not install the updater.

See the [requirements guide](../requirements/README.md) for implemented boundaries
and missing verification, the [engineering guide](../docs/general.md) for checks,
and the [image build sequence](../zmala_images/README.md#build-sequence-and-ownership)
for assembly. Server and combined update coordination and physical qualification
remain unfinished.
