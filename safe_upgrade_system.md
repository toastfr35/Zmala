# Safe updates and upgrades

Status: **7 November 2026**.

> **The automatic OS/package upgrade system is unfinished. The current SD image
> is ready for a manual installation test, not for automatic system upgrades.**
>
> **Automatic OS, package and application updates are disabled in this image.
> Its A/B layout does not yet provide a complete, qualified automatic rollback
> service. An unsuccessful manual OS/package upgrade may leave it unable to boot
> and require SD-card recovery. We do not claim that upgrades cannot brick it.**

The existing terminal application updater described below belongs to
installer-based systems. **Those application rollback protections are not enabled
in the new SD image and do not protect OS/package upgrades.**

An unbootable SD card is different from damaged hardware; software rollback
cannot guarantee recovery from failed storage or power hardware.

## Protections in place

**Existing terminal application updater (installer-based systems):**

- Checks trusted Ed25519 signatures, host compatibility, release sequence and exact
  package size/hash. Restricts archive paths/file types and prepares candidates
  offline in an unprivileged sandbox.
- Keeps confirmed and previous application slots. Its independent root-owned
  supervisor and privileged host helpers cannot be replaced by an app update.
  It does not run an OS installer or package manager.
- Waits for safe inactivity. A trial needs a stable, fresh UI health heartbeat;
  failure triggers rollback. Persistent app data is checkpointed before trial,
  with durable recovery markers and atomic restoration. Boot-time recovery
  selects the confirmed app before normal startup.

These are application protections, not general OS, package or server rollback.

**New development SD images:**

- Separate A/B boot and system slots provide space for a candidate alongside the
  working system. The active system is read-only; persistent identity/configuration
  and app data are separate, while routine temporary state uses RAM.
- Offline construction checks authenticated/pinned inputs, image hashes, boot
  payloads, partition geometry and filesystem readback.
- Early boot validates root/data topology and blocks normal services if storage
  preparation is incomplete. Unknown media is not silently reformatted or reset.
- Experimental boot control uses redundant confirmed/trial state, write readback
  and one durably consumed trial attempt. Confirmation must match the current slot
  and transaction. Automatic OS-slot activation and confirmation remain disabled.
- Automatic APT timers, the vendor EEPROM-update service and the legacy app
  updater are masked. **The current image does not automatically update its OS,
  packages or application.** An administrator can still override these masks.

## What is incomplete

- Signed system-update delivery and a complete inactive-slot install, trial,
  confirmation and rollback transaction.
- Product-health confirmation and watchdog handover for hang recovery. Development
  confirmed boots currently stop the loader watchdog.
- Call-safe/server-wide maintenance coordination and rollback-compatible data
  migrations.
- Slot-matched kernel/device-tree handling across OS generations. The current
  private Bluetooth workaround uses the firmware-provided tree and is not
  qualified for that transition.
- Real A→B→A upgrades, interrupted writes, physical power cuts and major-OS
  upgrades. Unit, namespace and file-image tests are not hardware qualification.

## Recovery today

Flash a verified image and complete write verification. Keep a known-working
card/image and a separate persistent-data backup: both A/B slots share one SD
card, and whole-card reflashing erases its data. Reflashing or replacing the card
can recover a broken card image when the Pi hardware and boot firmware remain
functional. Avoid manual in-place package/firmware upgrades on the development
appliance until the system-update path is qualified.

Details: [terminal app updater](docs/terminal.md#automatic-application-updates),
[image tools](zmala_images/README.md), [system-update plan](update_upgrade.md),
[remaining work](sd_card_imager_todo_left.md#6-broader-system-update-work-remains-separate).
Normative requirements remain in [requirements/](requirements/).
