# Update protections and recovery limits

Implementation review: **9 November 2026**. This page describes the current
code and its limits; it does not qualify a particular SD image or deployed device.

| Installation | Implemented update path | Boundary |
| --- | --- | --- |
| Standalone image-managed Terminal | Signed RAUC bundle containing the inactive boot/root pair; local-midnight discovery and Settings requests | Implemented admission, installation and trial confirmation; integration and physical qualification remain incomplete |
| Image-managed Server or combined appliance | Shared A/B storage and boot-control infrastructure | No automatic Server/combined discovery, maintenance coordinator or joint health confirmation |
| Legacy installer-based Terminal | Separate signed application updater owned by ZmalaTerminal | Application rollback does not replace the OS, kernel or distribution packages |

The image builder masks ordinary APT timers, the vendor EEPROM-update service
and legacy application updaters. This prevents those paths from modifying the
appliance independently. **Standalone Terminal images also install and enable
the separate whole-system updater**; those masks do not disable it. The builder
requires the public RAUC certificate. Private signing keys stay in the release
workflow.

## Standalone Terminal update flow

1. Discovery checks the fixed release feed for a newer, trusted, slot-compatible
   verity bundle with a complete boot/root pair. It records scheduled checks once
   per local date and catches up after a missed day. Settings can request a check
   and accept the current offer.
2. The coordinator requests a fresh acknowledgement from the Terminal process.
   Calls, setup, workers and peripheral operations must permit maintenance.
   An explicit immediate request may waive the ordinary inactivity interval.
3. The downloaded bundle must match the authorized offer. RAUC writes the
   validated inactive pair with automatic slot activation disabled. The
   coordinator reads back both partition hashes before recording a trial.
4. The durable journal identifies the release and former slot. The loader
   consumes one trial attempt before launching it. Trial native probing uses
   disposable state; the trial UI has read-only persistent application state
   and defers calls and media.
5. Confirmation requires eight seconds of stable fresh health from the same
   trial process within a thirty-second confirmation attempt, followed by
   transaction and health revalidation. The confirmed candidate reboots into
   normal operation. An unhealthy or timed-out check requests reboot without
   confirmation; a consumed trial then selects the former confirmed slot.

An interrupted or rejected update is reconciled from its journal on the confirmed
slot. These safeguards are implemented, but the tests do not yet demonstrate
every authentication, installer/readback and executed candidate-health path.
See the [requirements evidence guide](requirements/README.md).

## Storage and boot protections

All three image roles use read-only A/B roots and separate persistent data.
Early boot checks the selected root, same-parent data partition, compatible
identity and declared mounts before admitting normal services. Unknown state
is not silently reformatted. The boot backend checks redundant confirmed/trial
records and verifies Linux mutations by readback; generic eligibility changes
cannot confirm a candidate.

Development confirmed boots stop the loader watchdog. Trials leave it armed
with the kernel's sixty-second userspace-open limit; PID1's runtime watchdog is
disabled. The complete loader/kernel/userspace recovery path still requires
physical qualification. A service graph or simulated reboot is not that evidence.

## Remaining qualification and recovery

Server-wide SIP/TURN admission, combined health, rollback-compatible migrations,
major-OS transitions, trust rotation and the complete physical power-cut matrix
remain unfinished. Prior prototype boots or isolated watchdog experiments do
not qualify a newly assembled artifact. Track exact artifact evidence in the
[image checklist](sd_card_imager_todo_left.md).

Keep a known-working card/image and a separate persistent-data backup before a
manual development-card test. Both slots share one SD card; reflashing the whole
card erases its data. A verified replacement image can recover a damaged software
installation when the hardware and boot firmware remain functional. Avoid
manual in-place package or firmware upgrades on the image-managed appliance.

See the [build and release guide](zmala_images/README.md) for signed artifacts and
the [Terminal repository](https://github.com/toastfr35/ZmalaTerminal/blob/main/docs/terminal.md)
for the separate legacy application updater. The
[original design plan](update_upgrade.md) is historical and prospective context;
the normative runtime contracts remain in [requirements/](requirements/README.md).
