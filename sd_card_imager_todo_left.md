# SD-card images and Raspberry Pi Imager: work left

Source review: **9 November 2026**. This is an implementation and qualification
checklist, not a new product requirements baseline or a declaration that images
are ready for distribution. Runtime requirements remain in [requirements/](requirements/).

Use this as the short continuation list for a newly identified candidate. The
dated design and prototype log is in [update_upgrade.md](update_upgrade.md);
the old private `upgrade_system_status.md` catalogue is not part of this
repository. Current commands are in [the image guide](zmala_images/README.md),
and [the requirements guide](requirements/README.md) distinguishes implemented
behavior from missing verification. An unchecked item below requires evidence
for the selected artifact, even when its implementation already exists.

## Current position

- Offline package intake, application provisioning, initramfs construction and
  complete development-media assembly exist for terminal, server and combined roles.
- The hosted Terminal workflow builds both update slots from reviewed package
  caches and an identified Terminal commit. Its optional `include_sd_image`
  output comes from that same audited assembly; signing runs separately.
- Standalone Terminal midnight discovery, Settings requests, safe admission,
  partition readback and trial confirmation are implemented. Server/combined
  update coordination and joint health remain unfinished.
- **Terminal and terminal+server images always use the Argon ONE Pi 4 V2 case.**
  There is no optional image-build case flag. The fan policy remains off outside
  connected calls, 55% during calls and 100% at 65°C during calls. The image fix
  includes I2C access and boot configuration; physical fan transitions are unverified.
- Image provisioning includes Wi-Fi backend checks, the Plymouth theme,
  Server-approved Developer Access and the slot-tree Bluetooth flow-control fix.
  Validate all of them together on the actual candidate.
- Historical 7 November notes describe an older 32 GB-layout card with RAM
  Wi-Fi/QR repairs, a private Bluetooth tree adjustment and a separate compact
  file-image baseline. They are prototype evidence, not today's build recipe
  or qualification of a new card. The historical capacity figures below are
  retained for comparison. A running build or a merged application release does
  not qualify an SD image.

## 1. Finish the next terminal test candidate

- [ ] Accept the selected OS root only after its package-ledger audit, final
  `READY.json` and independently checked digest. Preserve failed logs and reject
  incomplete outputs. Reuse authenticated caches and unchanged accepted roots.
- [ ] Complete application provisioning, storage preparation, initramfs and disk
  assembly from one recorded source commit. Record package locks, builder/input
  hashes, application version, kernel and output hashes; explain any difference
  between the candidate source and subsequently merged documentation-only changes.
- [ ] Verify the target Wi-Fi supplicant loads with all its libraries, D-Bus policy
  and activation unit, and that NetworkManager can start it on an ordinary boot.
- [ ] Verify mandatory Argon configuration in the root, terminal account, module
  loading, device permissions, firmware configuration and both boot-slot trees.
- [ ] Verify the Zmala theme/artwork and script plugin inside the final initramfs,
  theme selection in the root and quiet splash arguments in the actual boot script.
- [ ] Verify ordinary SSH stays masked and no temporary Ethernet diagnostic is
  installed. Check the Developer Access units/helper, first-boot host keys and
  Server-approved `zmala` password flow. Verify password rotation, revocation and
  rejection of invalid credentials. Generic images must contain no login
  credentials or preseeded host keys; the former private public-key overlay is
  historical test context, not the current access recipe.
- [ ] Verify the selected slot's device tree retains firmware fixups and the
  onboard Bluetooth RTS/CTS adjustment. Qualify pairing and remote behavior on
  the affected Pi revision in both slots. Record any private diagnostic deviation
  with its separate hash; it cannot substitute for validating the normal image.
- [ ] Recheck GPT/FAT/ext4 structure, boot-slot payloads, initramfs dispatch and
  application/unit checks on the final artifact, rather than an earlier image.
- [ ] Confirm the final raw image fits the actual target card byte capacities.
  Validate the final image's first-boot GPT relocation on 16 GB and 32 GB media,
  unchanged partition extents/IDs and repeat-boot no-op behavior.

## 2. Run the next physical card test

- [ ] Deliver the verified artifact, SHA-256 checksum and Raspberry Pi Imager
  custom-image instructions. The user will flash the SD card manually; agent work
  stops at artifact preparation and verification. Preserve the known working
  card/backup and have the user confirm the actual target capacity and storage
  selection before writing; a previous drive letter is not sufficient.
- [ ] Have the user flash and verify the exact candidate with Imager. Record the
  image hash, actual medium capacity and reported verification result. Keep
  private diagnostics out of any image intended for public distribution.
- [ ] Cold-boot **a real 16 GB card and a real 32 GB card**, recording each result.
  A sparse-file capacity test is not a physical SD-card or power-loss test.
- [ ] Confirm setup without the temporary RAM repairs: Bluetooth pairing/remote,
  Wi-Fi join, a current HTTPS server QR, TV/display, camera, microphone and speaker.
- [ ] Confirm the Zmala logo is visible during graphical boot.
- [ ] Enable Developer Access from the existing server, pin the device host key
  and connect as `zmala` with the password shown in the admin dialog. Activate it
  again to verify password rotation, disable it and verify the session closes and reconnection
  fails. Reboot and repeat. Keep ordinary Ethernet/Wi-Fi SSH closed throughout;
  this is the main further-debugging path, not the expired temporary SSH window.
  Run `sudo -n id -u` through that controlled connection and require output `0`.
  ARM64 emulation checks SSH authentication and sudo configuration/file modes,
  but cannot establish the actual setuid transition under the emulator.
- [ ] Test the QR guide colour change and specific failure feedback for invalid
  QR, missing SSID and rejected credentials, then retry successfully. Do not
  treat every authentication failure as proof of a wrong password.
- [ ] Make and end a real call. Confirm fan off during setup/idle, on during the
  call and off after hangup. Cover service shutdown/restart and the temperature
  threshold separately; a passed unit test is not physical fan evidence.
- [ ] Reboot and power-cycle again. Confirm saved Wi-Fi/server enrollment and
  Bluetooth state persist, setup does not restart unexpectedly, and no SSH
  diagnostic or RAM repair is needed for ordinary operation.
- [ ] Record kernel/storage errors and voltage/throttling state during tests.
  Earlier undervoltage was observed; its significance is not yet established.

## 3. Measure actual storage and capacity margins

Current compact layout: **14,001,635,328 raw bytes**, with a 32 MiB common boot
partition, two 512 MiB slot boot partitions, two 4 GiB root partitions and a fixed
4 GiB data partition, plus alignment/GPT allowances. Extra space on larger cards
stays unallocated. GPT relocation does not expand a partition or filesystem.

The historical 7 November Wi-Fi/QR/Argon baseline (source `7589fd8`, image SHA-256
`b397645917f82a296b27eedd2c3243c68c3412f10d2cc195068e18bb5b3351e2`)
has **2,494,590,976 allocated bytes including metadata** and **1,800,376,320
free bytes per 4 GiB system slot**. Its 4 GiB data partition has **151,318,528
allocated bytes** and **4,143,648,768 free bytes**. Evidence is retained privately
in `terminal-fan-capacity-checks.json`. Disposable older combined filesystems
fitted 4 GiB with **1,675,853,824 free bytes**. These are baseline measurements;
repeat them for each current artifact after changes to host services, artwork,
Bluetooth policy or application/package inputs.

- [ ] Measure allocated/used/free bytes in every filesystem of each newly built
  terminal, server and combined artifact, including both root slots.
- [ ] Record raw and compressed download sizes, package/source version and actual
  16 GB/32 GB card capacities. Marketed card sizes are not exact byte guarantees.
- [ ] Measure peak persistent-data usage during staging, download, verification,
  rollback-compatible migration, diagnostics and retained history. Confirm update
  headroom on the smallest supported card, not just factory-image fit.
- [ ] Set and document a minimum supported device capacity from those results.
  Decide whether later optional data expansion is useful; it is not part of the
  current compact candidate and must not be implied by the 32 GB compatibility claim.

## 4. Remove development-only boot and onboarding gaps

- [ ] Qualify the implemented slot-matched DTB/overlay and Bluetooth flow-control
  adjustment. Check UART RTS/CTS and firmware fixups on the supported Pi revisions
  instead of relying on the historical full-tree diagnostic.
- [ ] Qualify both boot slots, payload mismatch/failure handling, common-loader
  compatibility and firmware fixups across supported OS generations.
- [ ] Build and boot the corrected **server-only** and **terminal+server** images.
  Combined package/runtime foundations exist; complete role-specific hardware
  qualification and resource measurements still remain.
- [ ] Finish server first-owner claiming, HTTPS/TLS and network onboarding without
  an ordinary SSH installation step. Verify combined onboarding, separate private
  state and recovery after interrupted setup.
- [ ] Qualify the implemented Terminal Developer Access lifecycle and finish the
  remaining Server onboarding/recovery path without a shared factory password
  or private key. The old one-boot Ethernet SSH window is not a release feature.

## 5. Deliver images through Raspberry Pi Imager

- [ ] Produce compressed, immutable, role-labelled terminal/server/combined image
  artifacts with checksums, authenticity verification, provenance and licences.
  Keep image binaries out of Git and signing credentials in the release workflow.
- [ ] Test Raspberry Pi Imager's **custom-image** route end to end, including
  write verification and first boot. This is the planned baseline; a custom
  Imager catalogue is later work, not a prerequisite for another private card test.
- [ ] Test/document Imager behaviour on Windows, macOS and Linux. Decide which
  OS-customisation settings are supported, ignored or disabled so they cannot
  overwrite appliance users, networking, mount policy or partition geometry.
- [ ] Measure compressed artifacts against the chosen host's current limits and
  verify download/resume/integrity behaviour. Select a suitable immutable host
  if needed; avoid a normal user workflow that requires joining arbitrary chunks.
- [ ] Update release collection/validation for all three image choices and their
  trust materials. Account for existing app-update assets and the leaflet ZIP;
  do not silently break legacy clients or assume a fixed nine-file release.
- [ ] Regenerate the affected Word/PDF installation guides and authoring sources
  for download, Imager, card selection, first boot and recovery. Validate fresh
  installation using only published artifacts and those instructions.
- [ ] Retain supported legacy installers until the replacement workflow and
  migration/rollback procedure are qualified. Then change the public download
  links deliberately; do not present current development images as ready releases.

## 6. Broader system-update work remains separate

A flashable first-install image does not finish the OS-upgrade project. Track the
following in [the detailed update plan](update_upgrade.md), without holding up
another clearly identified development-card test:

- [ ] Complete integration and physical qualification of the implemented signed
  Terminal feed, bounded staging and inactive-slot install/trial/confirm/fallback
  transaction. Direct acknowledgement, device admission and readback failure
  checks remain verification gaps; trust rotation remains additional work.
- [ ] Qualify the implemented Terminal native/UI trial health and watchdog path,
  including normal offline/setup conditions. Finish Server and combined health
  and the remaining watchdog handover work.
- [ ] Qualify Terminal safe admission, progress and passive-media restoration.
  Implement Server-wide SIP/TURN idle admission and combined coordination.
- [ ] Rollback-readable data migration, retained-card/import recovery, real A→B→A
  tests, interrupted writes/power cuts and at least one different-major-OS upgrade.
- [ ] Three-role soak, thermal/performance/storage qualification and controlled
  beta promotion before broad distribution or automatic fleet updates.

## Evidence and completion discipline

For each checked item, retain the exact source/artifact identity, environment,
procedure and result. Link actual hardware results separately from QEMU user-mode,
namespace, mocked and regular-file tests: no full Raspberry Pi board simulator
is currently qualifying these images. Keep packaging checks in `tests/adhoc/`
and runtime verification linked to the existing requirements. Do not mark a
planned, skipped or manual hardware scenario as passed.
