# SD-card installation and automatic system updates and upgrades

Planning issue: [#138](https://github.com/toastfr35/ZmalaCall/issues/138).
Prepared against `main` at `c6aabe2109e8478c6c3b1e6c7564fb7d2f651d7f`
(Zmala 0.3.76), on 4 November 2026.

**Status: implementation started; feasibility and development tooling in progress.** This file records the intended
architecture, work sequence, unresolved engineering decisions and acceptance
evidence. It does not describe functionality already shipped. Its checklists are
uncompleted work, not passed verification. Product requirements remain exclusively
in `requirements/`; implementation changes will add or revise those records and
their direct LLT/HLT coverage before the corresponding behavior ships.

### Implementation log

7 November 2026 — current image acceptance decisions:

The latest [image acceptance contract](zmala_images/README.md#next-image-acceptance-contract)
and [remaining-work checklist](sd_card_imager_todo_left.md) supersede older
capacity, pending-build and optional-case notes below. Terminal and combined
images require the Argon ONE Pi 4 V2 case. The next test artifact targets both
16 GB and 32 GB cards with the compact 14,001,635,328-byte layout, permanent Wi-Fi
and QR feedback fixes, working Bluetooth behavior, call-only fan control,
restored boot artwork and server-triggered Developer Access while ordinary SSH
stays off. Generic images contain no login credentials; private test copies
use a separately recorded immutable public-key overlay in both system roots,
without changing factory data or relaxing first-identity admission. This lab
authorization does not survive replacement by a generic system image; supported
operator enrollment remains open. The accepted Wi-Fi/Argon
baseline has passed file-based capacity checks; the complete next candidate and
its physical checks remain pending. The user will flash manually after receiving
the verified artifact, checksum and Raspberry Pi Imager instructions; the agent
does not write the card. These are packaging and qualification gates,
not additional installer requirements in the runtime Doorstop baseline.

4 November 2026 — [#140](https://github.com/toastfr35/ZmalaCall/issues/140):

- Added `zmala_images/` source pins/acquisition, explicit role/package intent,
  minimal A/B boot-probe configuration, bounded read-only Pi inventory and offline
  root privacy inspection. Source downloads are verified before safe extraction;
  neither the sample backend nor a generic mark-good service is installed.
- Collected private read-only inventories from both current Pi roles. Both report
  Debian 13 ARM64. Terminal and server application trees occupy approximately
  0.97 GiB and 0.58 GiB respectively, including retained releases. Some private
  terminal data/checkpoint trees were unreadable without elevated access and are
  marked incomplete. These figures do not establish future root/card fit.
- Audited the pinned native backend: selector commit uses a temporary file/rename
  without explicit durability handling; its example mark-good unit precedes any
  Zmala health checks. Production adoption is blocked on a qualified replacement
  or demonstrated safe integration. The upstream A/B image layer also persists
  per-slot `/var` and enables persistent journals; do not adopt that policy unchanged.
- Selected reviewed imagegen/backend audit revisions in `sources.lock.json` and
  Debian RAUC `1.13-3+deb13u1` as the initial package candidate. Transitive package
  locking and upstream feature qualification are still pending.
- Verified both generated probe configurations through the pinned upstream
  configuration resolver in WSL. The probes do not include the Zmala application
  and have not been built/booted as complete images. Added tool regression checks
  and a CI profile-validation step; runtime requirements remain unchanged.
- Hardware available: spare SD card, no spare Pi. Later physical tests need an
  arranged card swap on an existing Pi, retaining the original card. No live
  installation, service restart, TV or USB power operation was performed.

Stages 0 and 1 are **not complete**. In particular, no production image, package
closure lock, hardware boot qualification or automatic system updater is claimed.

4 November 2026 — continuation of #140:

- Added offline probe-disk validation of primary/backup GPT checksums/agreement,
  partition bounds/identities/order, nonoverlap and equal A/B sizes. It reads only
  regular image files and explicitly does not qualify boot or payload integrity.
- Installed image-builder prerequisites in WSL and completed a real minimal ARM64
  probe image build under emulation (builder exit 0). The raw disk is
  22,590,541,824 bytes, with two 8 GiB roots, two 512 MiB boots, a 32 MiB selector
  and 4 GiB data. The compressed raw image is approximately 424 MiB. Primary and
  backup GPT/layout checks pass against that artifact. This is a common-base boot
  experiment with no Zmala application, not a Terminal/Server installer.
- Offline root inspection found the expected missing slot-local package database:
  the upstream A/B layer moved it into per-slot persistent `/var`. That confirms
  the documented production mount-policy blocker. The other implemented privacy
  subset checks reported no violations. No physical boot or power-cut test passed.
- The selected RAUC `1.13-3+deb13u1` installed successfully in the prototype. The
  upstream-generated update archive is not a Zmala RAUC bundle; there is no
  configured automatic system feed or adopted boot backend in this image.
- Observed that upstream's default Git-derived artifact version can inherit the
  parent checkout's tags. Probe configs now set an explicit unqualified artifact
  version. Production assembly still needs its full source/package/build identity.

4 November 2026 — [#143](https://github.com/toastfr35/ZmalaCall/issues/143):

- Implemented isolated download-only APT intake against explicit signed Debian
  and Raspberry Pi Trixie repositories. Host configuration/hooks and installed
  package state are separated from intake; no target or host package is installed.
- Verified actual intent closures: server 170 archives / 77,056,328 bytes;
  terminal 721 archives / 528,545,960 bytes. Host package database hashes were
  unchanged before/after both runs. Retained all archives and signed audit inputs
  privately; reviewed public lock metadata lives in `zmala_images/locks/`.
- Added mandatory external lock-digest verification and regression coverage for
  altered/missing/extra archives, trust metadata, traversal, download budgets,
  invalid signatures and overlapping archive-key rollover. SHA-256 is checked
  against authenticated package metadata, independently of optional legacy MD5
  fields in APT's URI output.
- Windows CI exposed Git CRLF translation changing lock-file byte digests. Added
  LF attributes for the content-addressed JSON and a checkout regression with
  `core.autocrlf=true`; lock bytes remain identical across Windows/Linux.
- These are requested dependency closures, not a complete factory image lock.
  Full base/toolchain/model/npm inputs, immutable remote retention and consuming
  the lock in a complete image build remain incomplete.

5 November 2026 — [#145](https://github.com/toastfr35/ZmalaCall/issues/145):

- Wrote a private diagnostic copy of the common-base probe to a spare
  31,266,439,168-byte card with Raspberry Pi Imager, including full read-back
  verification. Diagnostic SSH identities are private, unique to this lab copy
  and never part of the public build inputs or release artifacts.
- Before its first boot, found and masked the inherited stock
  `rpi-eeprom-update.service` in both system slots. Verified all changed ranges
  against the accepted preimage and read them back after writing. No EEPROM
  update was performed. Future probe projects emit a standalone offline mask
  hook; builders must use the project's `-S` directory. Root inspection now
  rejects the known updater without a mask or with uninspectable policy parents.
- On an available Pi 4, completed an initial slot-A boot, a one-shot tryboot into
  B, and an ordinary reboot back into A. Pinned diagnostic SSH and the recorded
  physical Pi identity matched on every boot. All three boot IDs differed;
  machine identity remained stable. The roots were read-only; resolved active
  roots in B and the final A boot matched their expected partitions. The EEPROM
  mask and RAUC 1.13 were confirmed in both slots. Initial Ethernet discovery
  became possible after the cable was connected.
- A watchdog device is present; supervision, early-boot recovery and power-cut
  safety have **not** been qualified. No permanent selector commit, signed RAUC
  installation, product call test or automatic system update was exercised.
  The original installation card was retained and not modified, then restored;
  its pinned identity and active terminal service were verified. This common-base
  experiment does not qualify either role's complete application image or final
  card budget. Native selector durability and the upstream mutable `/var` policy
  remain production blockers.

5 November 2026 — [#149](https://github.com/toastfr35/ZmalaCall/issues/149),
boot-state qualification in progress:

- The successful native A/B probe does not resolve the audited selector's FAT
  commit window. Prepared a separate **private, unbooted** U-Boot feasibility
  image; it does not replace the restored terminal installation or settle the
  production backend decision.
- Audited and cross-compiled official U-Boot `v2026.10`, Git commit
  `5508406582f6f7120dce0c4b3059819a41788db2`. Its stock Pi ARM64 configuration uses
  FAT environment storage and has no enabled legacy watchdog. An experimental
  configuration selects redundant raw MMC state. The actual pinned source uses
  `CONFIG_ENV_REDUNDANT`, `CONFIG_ENV_MMC_DEVICE_INDEX` and
  `CONFIG_ENV_MMC_EMMC_HW_PARTITION`; older integration examples use different
  names. Checking the resolved `.config` is mandatory; silently discarded old
  option names do not establish redundancy.
- Retained an authenticated ARM64 `libubootenv-tool`/library dependency closure.
  Ran the actual tools under emulation against regular files: a state change
  preserved the other valid copy, and corruption of the new copy caused reads to
  return the retained state. This checks the selected tool/library format only;
  it is **not** an SD power-cut result or a bootloader fallback result.
- The private candidate contains a fixed common firmware/loader area, two
  kernel/root groups and the existing diagnostic data. Its slot mapper and
  initramfs use the boot script's explicit slot argument, because a fixed common
  loader partition no longer identifies the selected Linux slot. Both roots
  retain the EEPROM mask. GPT and offline filesystem checks pass; no new candidate
  has been written to a card or booted. The build host/toolchain is not fully
  locked, and the private recipe has not been promoted to the public image tools.
  It still inherits the upstream `rw,nofail` common-boot mount request; a fixed
  loader area is not yet an enforced read-only production mount policy.
- Remaining gates: reproducible public assembly, firmware/kernel/DT compatibility,
  real reads/writes of both state copies, initial-state recovery, physical cuts,
  early-watchdog coverage and a reviewed production backend/layout decision.
  Factory persistence, runtime requirements, coordinator implementation and
  complete role qualification remain unfinished. The next hardware run requires
  the spare card back in the reader and an arranged terminal test window.

5 November 2026 — further offline evidence for #149:

- The real ARM64 environment tools also passed a multi-variable batch update
  against ordinary files, with both copies retaining valid CRCs. This selected
  tool version's script format is `key=value`; space-separated lines would be
  ignored. The test checks read-back values as well as command completion.
- Built a separate host-only U-Boot sandbox to exercise the command interpreter.
  Found a lab-script bug: `setexpr` stores hexadecimal text, while `test` uses
  automatic-base integer parsing. An initial `10` became `f`, which the later
  comparison treated as zero. Prepared a corrected script using the standard
  small attempt count of three. Its image header and payload CRCs are verified.
  Seven selection/counter/error cases pass in the actual interpreter: initial A, trial
  B, exhausted B falling back to A, a manual B count reset, and no attempts left.
  A failed state-save prevents kernel loading, and a missing B kernel falls back
  to A in the simulated command path. Filesystem loading, state persistence and
  reset commands were stubbed; none of
  these cases is a hardware boot or production health-confirmation result.
- On reinserting the previously booted spare card, its exact-preimage guard
  stopped before writing. Read-only comparison found changes confined to valid
  ext4 superblock write-time, written-KiB accounting and checksum fields among
  the eight compared 1 MiB ranges. All other compared bytes matched; this is not
  a whole-filesystem comparison. Reviewed and pinned those post-boot range
  hashes before retrying. A read-only mounted root should not be assumed to have
  a bit-identical raw image after startup filesystem handling.
- The new base image was written and fully read-back verified. It must receive
  the corrected boot script before first boot; the card was automatically
  unmounted/ejected and is awaiting reinsertion for that correction. The original
  compressed lab artifact is retained as an explicitly superseded base. A fresh
  complete image with the correction embedded is retained for future writes.
  The current card's provenance is its verified base plus the required file
  correction, not a claim that its FAT metadata matches the fresh image. No new hardware boot
  or power-cut result is claimed. The original terminal installation remains
  running separately.

5 November 2026 — common-loader preflight and hardware diagnosis for #149:

- The corrected three-attempt script was installed and verified after the full
  card write. The first U-Boot experiment nevertheless reached Linux without an
  explicit slot argument and could not resolve its active root. Both raw
  environment areas remained untouched. Inspection found the private 32 MiB
  common volume had been forced to FAT32 with only 64,496 data clusters, below
  FAT32's 65,525 minimum. Firmware bypass was a hypothesis, not a proven selector
  result from that run.
- Rebuilt only that common volume as valid FAT16, restored and checksum-verified
  all 427 boot files, and verified unchanged partition geometry and raw state.
  On the next hardware attempt, Ethernet and SSH appeared briefly before becoming
  unreachable and the user reported loss of HDMI signal. Read-only card inspection
  subsequently found two CRC-valid environment copies with successive A-slot
  counts of two and one. This establishes execution and persistence of the
  U-Boot script; the kernel recorded `rauc.slot=A`, and recovered journal entries show one
  boot reaching the multi-user target and SSH startup in about ten seconds.
  Subsequent network loss and stable operation remain under investigation. It is not a passed fallback,
  health-confirmation, watchdog or power-cut test.
- Recovered the dirty data filesystem journal on a disposable local copy,
  preserving the card and the original read-only snapshot. Both recorded boots
  failed the requested 512 MiB graphics CMA reservation and framebuffer setup;
  loss of HDMI alone does not prove that Linux stopped. Prepared a lab-only
  correction setting both `fdt_high` and `initrd_high` to the firmware/control FDT
  ceiling, retaining U-Boot's bounded relocation allocator. The FDT placement
  diagnosis is consistent with [the upstream Home Assistant fix](https://github.com/home-assistant/operating-system/pull/4954);
  the initrd additionally needs a placement policy in this probe. Eight actual
  hush tests pass with hardware commands stubbed. The corrected script is
  read-back verified on the spare; its next physical boot is still pending. A
  one-time lab script revision resets diagnostic attempts, not a production
  health check or automatically replenished retry policy.
- Added offline `inspect-bootfs` preflight for GPT plus the three FAT footprints.
  Tool regression tests cover the undersized FAT32 defect, valid FAT16/FAT32,
  invalid geometry/root/table capacity, both disk sector sizes and named-volume
  rejection. This is build tooling, so runtime requirements and user installation
  workflows remain unchanged. Production images still need file/payload checks
  and real boot qualification in addition to this preflight.
- The earlier compressed U-Boot artifacts remain superseded: even the artifact
  with corrected counters still needs the common-volume FAT16 correction. Do not
  treat either as a ready-to-flash installer. The physical spare has both
  corrections; original installation cards and server software remain untouched.


5 November 2026 — corrected U-Boot hardware feasibility sequence for #149:

- The memory-placement correction booted successfully. Pinned diagnostic SSH
  verified the expected physical Pi and common loader partition; the explicit
  A argument resolved to the read-only A root. Repeated readings retained the
  same boot identity through approximately 145 seconds. The full 512 MiB CMA pool
  was reserved and the connected HDMI output was enabled. Later kernel logs show
  successful framebuffer setup; the initrd was relocated above the low CMA window.
- Completed the sequence **A -> B -> A -> B -> B** on the private card. Staging B with
  one attempt booted the read-only B root and persisted a zero B count. An ordinary
  reboot without confirmation returned to A. Staging B again, explicitly resetting
  its count to three from userspace, then rebooting retained B with a count of two.
  Both redundant environment copies retained valid CRCs through these operations.
  Each checked boot matched its explicit slot/root, diagnostic identity and
  EEPROM mask. The B and fallback-A graphics checks also passed.
- This confirms hardware selection, attempt consumption, ordinary-reboot fallback
  and a **manual counter reset**, not the proposed application's health predicate.
  The watchdog remained inactive. No deliberate power cut, corrupted-state boot,
  failed-kernel recovery or automatic production health confirmation was tested.
  These remain blockers; the experimental loader is not an adopted RAUC backend.
- Assembled a fresh private whole-image artifact containing valid FAT16 and the
  corrected script; GPT/FAT checks, filesystem check and loader/script read-back
  checks passed. It contains diagnostic credentials and must never be published.
  Its GNU-created FAT16 geometry differs from the Windows-repaired physical card,
  despite matching loader/script contents; the new whole image itself has not
  been flashed or hardware-qualified. Earlier artifacts remain superseded.
- Reset the lab's next selection to A with three attempts and accepted a clean
  shutdown. Asked for the original terminal card to be restored. Verification of
  the original installation is pending that physical swap. No server deployment,
  EEPROM operation, camera test or product call was performed in this sequence.



5 November 2026 — watchdog handoff probe preparation for #149:

- Restored the original terminal installation and verified its pinned host and
  physical identity, absence of the lab marker and active terminal service. All
  three Verify jobs passed for the preceding feasibility/tooling commit.
- Cross-compiled a separate private U-Boot candidate with resolved `WDT`,
  `WDT_BCM2835`, `WATCHDOG`, `WATCHDOG_AUTOSTART` and `CMD_WDT` enabled and a
  15,000 ms timeout. The successful non-watchdog loader and its evidence remain
  retained. This candidate has not yet demonstrated watchdog operation on hardware.
- Inspected the exact offline probe kernel configuration: the BCM2835 driver and
  boot-enabled watchdog handling are built in, but its userspace-open timeout
  defaults to zero. [Kernel watchdog documentation](https://docs.kernel.org/watchdog/watchdog-parameters.html)
  defines that as an unlimited wait. Prepared a lab handoff using an explicit
  60-second kernel open deadline and PID 1 ownership with a 15-second runtime
  watchdog. Product health confirmation remains a separate, unimplemented check.
- Prepared an optional, bounded 120-second initramfs stall for a later fault test.
  This initramfs sources an explicit hook `ORDER` list, so an arbitrary new file
  would not run. Verified that only the existing ordered premount hook changes,
  that its prerequisite-query exit remains intact, its shell syntax is valid,
  and its sleep command resolves to an included executable. The fault is **not**
  installed in either boot slot; the first check must be a healthy watchdog boot.
- The handoff script passed eight actual hush cases with hardware operations
  stubbed. Offline root filesystem checks passed. Reviewed the ten affected
  1 MiB card ranges; differences from the reference were confined to valid
  superblock write-time, lifetime-written-KiB and checksum fields. Rechecked
  pinned device/partition/source identities and exact reviewed preimages before
  applying and read-back verifying the small root/loader/script correction.
  Both raw environment copies were preserved. This lab-only card patching is
  not the proposed production update transaction or a power-loss test.
- After renewed availability approval and a fresh idle check, the original Pi
  accepted shutdown for the next spare-card boot. The healthy watchdog test is
  pending the physical swap; reset, handoff and stalled-boot recovery remain
  unqualified. No production watchdog or system updater was deployed.



5 November 2026 — watchdog, redundant-state and first power-cut evidence for #149:

- Healthy A and B boots passed the private watchdog checks: a 15-second active
  device owned by PID 1, a 60-second kernel userspace-open deadline, expected
  read-only roots and identities, full graphics CMA and enabled HDMI. The first
  A boot stayed on the same identity across repeated observations; a later
  healthy A remained reachable beyond 180 seconds. No diagnostic tool opened the
  watchdog device; ownership checks used sysfs and PID 1's file descriptors.
- Installed the verified bounded stall into inactive B only, retained its healthy
  backup, staged one B attempt and commanded one ordinary reboot. The Pi returned
  automatically to a different healthy A boot after 104 seconds. B's count was
  zero, A's was two, both state CRCs were valid and the environment flags showed
  the two expected boot commits. Restored and read-back verified B's healthy
  initramfs immediately afterward. This exercises one ordered pre-root stall;
  it does not qualify every kernel/initramfs or later application failure.
- Wrote distinguishable baseline and newer state copies, then intentionally
  flipped only one CRC byte in the newer copy. The selected userspace library
  read the retained baseline. After reboot, the actual loader preserved its
  baseline marker and expected attempt count, proving it used that copy rather
  than factory defaults; both copies again had valid CRCs. This is one explicit
  single-copy checksum fault, not arbitrary media-corruption qualification.
- Ran a bounded commit-load loop with legal A-first state and a unique per-commit
  marker. The operator disconnected the Pi's power while the loop was active,
  waited and reconnected it. The transport ended during the load, after the host
  had received reports of 201 completed commits. The subsequent cold A boot
  retained that run's sequence 201 marker, both CRCs were valid, the root remained
  read-only and watchdog/graphics/SSH checks passed. This is **one power cut during
  repeated commit load**; its exact intersection with a card write is unknown.
  It does not establish the complete timing/card/controller power-loss matrix.
- Reset the lab selection to A with three attempts and shut it down cleanly.
  The operator restored the original card; its pinned/physical identity, absence
  of the lab marker and active terminal service were verified. The original
  installation and server received no experimental loader or watchdog policy.
- These results support continuing reproducible image/backend integration with
  the U-Boot candidate. Production adoption remains blocked on the remaining
  fault/power-loss matrix, firmware/common-loader recovery policy, bounded product
  health confirmation, complete data/image policy and the later plan stages.
  Runtime requirements and their LLT/HLT evidence must accompany that installed
  integration; private probe results are not product verification passes.



5 November 2026 — [#151](https://github.com/toastfr35/ZmalaCall/issues/151),
pinned bootloader probe build inputs:

- Added the immutable U-Boot candidate archive to source acquisition. Reviewed its
  SHA-256, 46,731,588 compressed bytes, 41,465 members and 264,670,480 expanded file
  bytes. Only this source receives the larger 64 MiB / 384 MiB / 50,000-member
  budgets; existing sources retain their previous limits. Safe path/link checks
  and full extracted-tree hashing passed against the real archive. Cached FIFOs,
  devices and links are rejected before archive reads, which are now bounded.
- Added a development-only Pi 4 SD profile that emits raw-state Kconfig settings
  and watchdog/kernel handoff examples into a new directory. It fences alignment,
  separation from GPT/partitions and bounded watchdog values, omits a boot script
  and marks its output uncompiled/incomplete/unqualified. The existing native
  `probe-config` and all deployed runtimes remain unchanged.
- Added inspection of the resolved Kconfig subset, including actual current
  option names, local-only default boot, redundancy, raw MMC locations and
  disabled alternate stores/location overrides. Missing or duplicate settings
  fail; a passing subset does not establish compilation or hardware behavior.
- In fresh Linux source/profile/build directories outside any repository,
  acquired and verified the pinned archive, applied the generated fragment,
  resolved Kconfig, passed the inspector, and cross-compiled an ARM64 ELF/binary.
  Retained compiler, source/config/binary hashes and source-commit build epoch
  privately. The complete resolved configuration matched the previously
  hardware-tested private candidate byte for byte. The complete toolchain is not
  locked and the resulting binary was
  not installed or boot-tested; this is not full reproducibility qualification.
- All 47 image-tool regressions passed in Linux; Windows passed 37 with ten
  explicit Linux-only skips. Ruff and profile/whitespace checks passed. These are
  build-tool changes outside the product runtime baseline; installed integration
  still requires its own runtime requirements, owning trace comments and LLT/HLT.


5 November 2026 — [#155](https://github.com/toastfr35/ZmalaCall/issues/155),
common-base input locking and local build repositories:

- Captured the selected clean pre-boot image's installed package ledger, with
  matching A/B copies and an externally anchored ledger digest. The strict parser
  retains exact installed versions, including a package whose desired action was
  purge; it rejects unfinished states, ambiguous/duplicate records, other
  architectures, scalar continuations and linked/special/oversized input files.
  The earlier private 258-selection inventory omitted that still-installed
  package and is superseded by the reviewed 259-selection capture.
- Authenticated and retained all 259 exact base selections and their 259-archive
  closure (164,614,914 bytes), using signed Debian/Raspberry Pi metadata and the
  same download-only isolation as role intake. Public intent and lock metadata
  are anchored in `locks/index.json`; raw ledgers/archives remain private.
  CI checks base/source/closure synchronization without downloading packages.
- Added build-only local file-repository assembly from externally hash-anchored
  caches, with combined budgets, conflict rejection, copied-archive readback and
  generated-index identity/hash/path checks. Failure never emits its completion
  marker. No private signing key or host APT configuration is involved; the local
  unsigned repository must remain a read-only build input, not a deployed or
  remotely served package source.
- Combined base/role inputs produced 312 server and 805 terminal archives. Actual
  isolated, file-only APT download runs consumed every exact selection for both
  roles; host dpkg database hashes were unchanged. This is APT consumer evidence,
  not complete image-builder consumption. The native `probe-config` still uses
  upstream resolution. Full builder/toolchain/npm/model inputs, remote retention,
  narrow persistent mounts, provisioning and the runtime coordinator remain
  unfinished. Stages 0/1 and role qualification remain incomplete.
- Reviewed impact: these are build tools, excluded from the runtime requirement
  baseline and tested under `tests/adhoc/`. Existing runtime requirements,
  implementation trace comments and end-user installation guides remain accurate;
  no deployed workflow or production image/update behavior changed. The image
  development guide and general implementation guide describe the new limits.

5 November 2026 — [#157](https://github.com/toastfr35/ZmalaCall/issues/157),
isolated locked OS-root construction:

- Added an explicitly unqualified ARM64 root-tar build path using only externally
  anchored common/role archive caches and exact installed selections. Builds run
  as an ordinary Linux user in subordinate-ID user/mount/network/PID namespaces,
  with no external network interfaces or host APT mutation. Service starts are
  inhibited. Copied public inputs need not weaken private cache/home permissions.
- Added a build-only, disposable-marker-gated factory cleanup hook: generated
  SSH keys, machine/build-host identity, entropy/network seeds, copied resolver and local APT sources
  are removed; factory passwords must be locked. Package state remains in its
  root slot. Known EEPROM/APT timers are masked only in this experimental root;
  this is not a production maintenance policy or runtime coordinator.
- Added non-extracting archive acceptance with raw-header/extended-header/member
  budgets, selected real-parent/ownership checks, factory identity/mask checks,
  and exact final package-version/architecture agreement. Incomplete builds have
  no READY record. The hook is emitted with LF endings on Windows checkouts.
  Successful records explicitly keep application, toolchain, production mounts
  and hardware qualification false. Scratch/log inputs remain private pending
  review; no factory root or SD image is published by these tools.
- A first disposable ARM64 server-root experiment completed with exactly 312
  reviewed installed selections and unchanged host dpkg state. The stricter
  network-isolated/cleaned server build also passed, producing a 765,826,560-byte
  root tar; the latest public archive/privacy audit passed against it as well.
  The public terminal-root build also passed with exactly 805 installed packages,
  producing a 2,366,328,320-byte tar. Both retained tar hashes and the latest public
  archive/privacy audits passed; host dpkg hashes remained unchanged. These tar
  sizes are not filesystem/partition budgets. Tool regressions pass on
  Linux (67) and Windows (52 passed, 15 explicit Linux-only skips).
- Runtime requirement/trace and user-guide impact was reviewed: this is offline
  experimental build tooling, tested under `tests/adhoc/`, not an installed
  service or a changed supported installation workflow. Production adoption of
  host storage/update policies still requires synchronized normative items and
  direct LLT/HLT plans before qualification. Technical guides describe the
  experimental boundary. Stages 0/1 remain incomplete; full role/application
  assembly, selected persistent mounts and provisioning are not implemented.

5 November 2026 — [#159](https://github.com/toastfr35/ZmalaCall/issues/159),
experimental shared host storage and offline root preparation:

- Added experimental image-managed product scope (`PROD017`) separately from the
  legacy application-only policy. Server HOST and terminal MAINT storage items
  have direct component LLT/HLT plans and owning shared-runtime `@llr` anchors.
  `zmala_system` is included in runtime source inventory; its installed policy is
  not hidden as installer tooling. Existing supported deployments are unchanged.
- Implemented a UI/media-independent shared helper accepting a marked read-only
  ext4 root, separate prevalidated writable ext4 data and RAM work. It checks
  bounded exact role/profile records, initialized identity, owners, modes, links,
  mount facts and a bounded variable-state seed before preparing mutable views.
  Physical data-device selection and first identity creation remain caller
  preconditions, not features claimed by this helper.
- Fresh `/etc` uses a private 64 MiB RAM upper area; `/var` and `/tmp` use bounded
  128 MiB RAM mounts. Package status/alternatives stay in the selected immutable
  slot. Fixed bindings preserve app, network/Bluetooth, host keys, operator and
  server certificate state. Only the operator subdirectory is bound under
  `/etc/zmalacall`, leaving new product defaults visible. Journals have a volatile
  32 MiB/4 MiB template. Existing incompatible state is rejected, not bulk-chowned.
- Preparation is serialized in private RAM; readiness is published atomically only
  after its complete status is flushed and closed. Status-sync, mount-inspection
  and marker-cleanup failures are exercised explicitly.
  Failures preserve the original error and attempt reverse cleanup of owned
  mounts, including a command that fails after actually mounting. Input root/data
  volumes are retained. No package, service, TV or media helper is invoked.
- Direct LLTs cover controlled data/metadata and operation failures. Real Linux
  root HLTs use new 32 MiB regular ext4 file images in private mount/network/PID
  namespaces. Both roles passed two synthetic root generations, app UID 1000
  permissions, stable selected bytes, fresh defaults, slot package/alternative
  state, actual RAM capacities, readonly identity, private keys and pre/post-mount
  failure cleanup. These are not physical boot, reboot or power-cut passes.
- Added portable `prepare-root` archive rewriting without extraction/mounting.
  It verifies reviewed raw-root bytes and package input, moves package state and
  the remaining variable-state seed into immutable slot paths, and packages the
  exact authored helper/profile/journal policy. Graph/parent/hard-link, ownership,
  privacy, byte and RAM-seed checks gate readiness; runtime payload hashes record
  the copied source. Build/packaging regressions stay under `tests/adhoc/`.
- Both actual role roots were prepared and re-audited: server 312 packages with
  133 seed entries / 3,713,014 bytes; terminal 805 with 404 / 3,902,775 bytes. Raw
  source archives remained unchanged. Output explicitly keeps early-boot
  integration, data initialization, app installation and hardware/production
  qualification false; no root archive or private data is published.
- Technical guides and CI root-namespace checks now describe/exercise this helper.
  Current end-user guides and SSH installers remain accurate because supported
  installation and user workflows have not changed. Remaining stage-1 work
  includes early-boot wiring, complete role provisioning and immutable build/source
  retention; stage 2 still owns initial identity/claim and migration. No new
  factory image or automatic system updater is claimed; stages 0/1 remain open.

5 November 2026 — [#161](https://github.com/toastfr35/ZmalaCall/issues/161),
durable first-device identity prerequisite:

- Added experimental server HOST and terminal MAINT first-device HLRs with three
  direct LLRs each: validated/serialized admission, kernel entropy and durable
  commit, and identity-preserving retry. Owning anchors and direct component
  LLT/HLT plans describe the actual helper boundary, separately from full boot.
- The shared `device_identity` helper accepts prevalidated separate writable
  ext4 data, explicit matching factory state and Linux UID/GID 0. It does not
  discover disks or format, expand, import or reset existing data. Fresh unknown
  files, invalid schemas/roles/owners/modes and unsafe links are rejected.
- A persistent zero-length private lock uses nonblocking `flock`; its inode is
  retained so competing invocations cannot lock different files. Kernel entropy
  supplies a 128-bit machine identifier and a derived role-specific hostname.
- Identity files and their private staging directory are synchronized before
  atomic directory publication, then the data parent is synchronized before
  publishing the initialized-data marker. Readiness follows final validation and
  directory synchronization. Retries preserve committed identity even if the
  final marker was interrupted. A short hostname write is not mistaken for a
  complete stage merely because its prefix is a valid DNS label.
- Both role LLTs passed entropy, admission, lock, mode/umask, ordered commit,
  partial-stage, missing-marker and injected write/rename/sync cases. Real
  namespace HLTs passed process exit/retry at eight actual synchronization
  boundaries per role on disposable ext4 file images, retaining committed
  identity/application bytes and refusing application-owned identity. These are
  not physical power-loss, reboot or complete boot qualification.
- `prepare-root` packages the initializer. The archive-only `factory-data` tool
  emits a private data root and exact role factory record without device identity,
  formatting or mount access. Its ad-hoc regressions check contents, deterministic
  bytes, permissions, role mismatch, tampering and bounded regular-file inputs.
- Both actual ARM64 role roots were regenerated with the final initializer and
  passed their complete runtime-byte, package and archive-graph audits. These
  remain private unqualified root archives; no new image was flashed or published.
- Early-boot invocation, correct data-device selection, data expansion, host-key
  generation, service/application provisioning, owner claim and migration remain
  unfinished. Current SSH installers/user workflows are unchanged; user guides
  need no workflow revision yet. Stage-2 initialization remains open until those
  integration and physical gates are met.

5 November 2026 — [#163](https://github.com/toastfr35/ZmalaCall/issues/163),
experimental early-boot storage integration:

- Added experimental boot HLRs and four direct LLRs per role, with owning code
  anchors and direct LLT/HLT plans. The fixed experimental layout is not a frozen
  production format. The helper accepts a marked read-only ext4 root and exactly
  one supported slot and canonical kernel root PARTUUID.
- Native discovery binds the actual root major/minor to kernel sysfs topology,
  GPT entry, filesystem identity and geometry. Data is only the unique declared
  sibling on that same parent. No global label search, guessed `mmcblk0` path,
  formatter, expansion or imported commands are used.
- The helper mounts only validated data, initializes compatible identity and
  prepares views in order. It generates a selected-root read-only `fstab` entry
  in the RAM overlay before publishing complete current-boot readiness. Cleanup
  preserves the input root, committed identity and original failure, retaining
  data if dependent views remain.
- The early Python entry blocks failure without printing saved/private values.
  A separate PID1 gate required before `sysinit.target` checks private current-boot
  records, mounted views, fixed bindings and committed identity; killed or missing
  early preparation cannot silently admit ordinary services. Actual PID1 boot is
  still a qualification gate, not proven by authoring unit dependencies.
- Forty direct Linux LLTs passed policy/argument parsing, native topology models,
  bounded probe processes, admission, ordered operations, dependency failures,
  cleanup and startup refusal. Two real GPT/loop namespace scenarios passed both
  root slots, same-parent data, stable identity/application bytes, root mount
  configuration, missing-readiness/binding gate refusal and injected mount failures.
  These use controlled boot command lines; they are not physical boot or power cuts.
- `prepare-root` packages the boot policy, role, runtime and PID1 gate, with an
  empty data mountpoint. The separate isolated `build-initramfs` path consumes a
  reviewed prepared-root hash and locked caches. Its worker refuses original host
  namespaces, uses only fixed harmless character-device binds, and creates
  temporary RAM state rather than starting services or initializing device data.
- The target's own initramfs tool copies bounded Python plus extension ELF
  dependencies and private mount/probe tools. Actual target import checks caught
  and resolved a missing extension dependency caused by copy ordering. Rootless
  extraction omits only anchored root `/dev` entries, preserving kernel driver
  subdirectories also called `dev`. The entry runs in `local-bottom`, before the
  locked Debian init script moves `/dev` away in `init-bottom`.
- Both ARM64 components built successfully: server 29,306,767 compressed bytes and
  terminal 33,750,541. Each checked ten copied runtime/role files and exact target
  executables, executed target Python imports plus entry `prereqs` inside its
  extracted image, and passed offline verification against the role's actual
  vendor-unit graph. Final combined checks passed 182 cases on Linux; Windows
  completed 176 cases with 64 explicit Linux-only skips. Requirements validation
  found 307 mapped source files, 291 code anchors, 274 test plans and no unmapped
  requirements. Failed build/audit outputs have no accepted marker; a pending
  image may remain for diagnosis.
- Complete role/card assembly, physical boot/watchdog qualification, data
  expansion, host keys, application/service provisioning, owner claim, signed
  update coordination and migration remain unfinished. Legacy deployed hosts and
  supported installation/user workflows are unchanged; no unqualified component
  is published as a system image or update candidate.

5 November 2026 — [#165](https://github.com/toastfr35/ZmalaCall/issues/165),
experimental confirmed/trial boot-control helper implementation:

- Added explicit confirmed/trial state, eligibility, a single remaining attempt,
  transaction identity and bounded generation. Linux parsing rejects incomplete,
  corrupt, duplicate, mismatched or inconsistent records without factory guesses.
  Staging is inactive-only from the confirmed system; confirmation requires the
  consumed current trial and matching transaction/generation. Generic eligibility
  changes cannot confirm product health.
- Authored a small shell-compatible U-Boot selector. It clears stale outputs and
  saves trial consumption before selecting the candidate. Save failure and a
  subsequent boot with no remaining attempt select the confirmed system. The
  caller must refuse an empty selection; common-loader/payload integration and
  actual U-Boot interpreter qualification remain pending.
- Added root-controlled Linux raw-environment transport, gated by current image
  readiness, exact role policy, Pi 4 SD topology, primary/backup GPT integrity,
  selected root/data identities and geometry, and fixed disjoint raw ranges.
  A private generated configuration, empty tool defaults, persistent lock inode,
  complete-state comparison, fixed bounded commands and exact readback fence
  mutations. No command accepts a disk, offset or arbitrary environment key.
- Integration review also caught and corrected a path-admission defect in the
  earlier startup gate: its actual default `/` root was rejected by a helper
  that had only been exercised with temporary root directories. A direct Linux
  regression now reaches policy validation using the installed default path;
  unsafe paths remain refused. This correction is still not a physical PID1 boot
  qualification.
- Added the custom backend and explicit stage/confirm/cancel operations. RAUC's
  unqualified `set-primary` is deliberately refused; eventual installation must
  disable automatic activation and the coordinator must stage only after its
  complete-pair, durable-transaction and admission checks. This is a helper API,
  not a functioning whole-system update coordinator or health evaluator.
- Packaged experimental policy and PID1 startup runtime-watchdog zero. Taking
  over a loader-armed watchdog at early PID1 startup would indefinitely pet a
  failed trial. The supported complete image must qualify a nonzero bounded
  kernel open deadline and later authenticated product-health transfer before
  enabling PID1 ownership. Neither handover nor physical recovery is claimed.
- Retained authenticated ARM64 environment-tool packages in both role closures.
  Fresh role resolution also selected newer Mesa userspace and Linux development
  headers for the terminal; these are unqualified build inputs, not deployed
  updates. The observed common-base intent and its exact package lock remain
  unchanged. The server root passed its audit with 314 exact installed selections;
  rebuilding the new terminal root is separate from runtime helper verification.
- Direct role LLTs cover typed contracts, transitions, authored selector adapters,
  block/transport refusal, serialization and command failures. Native Linux HLTs
  passed both roles on NEW regular GPT files: trial consumption, fallback,
  explicit confirmation in both directions, cancellation/stale-state refusal,
  one/two damaged copies, and unchanged bytes outside the environment ranges.
  These run actual `fw_printenv`/`fw_setenv`, with POSIX shell for the authored
  selector. A further 24 decision cases passed under the pinned U-Boot hush
  interpreter with `saveenv` explicitly substituted; this does not combine actual
  U-Boot with SD persistence. Actual Pi transport, boot loading, watchdog and
  physical power cuts remain separate gates.
- Final focused checks passed 78 runtime LLTs and all eight isolated HLTs on
  Linux. Offline image-tool regressions passed 82 cases on Linux; Windows
  completed those 82 with 18 platform-specific skips. Requirements validation
  found 313 mapped sources, 301 code anchors, 278 test plans and no unmapped
  requirements. The initial required portable, Windows and Android Verify jobs
  all passed; final PR/release evidence is recorded independently.
- The new server initramfs passed with 15 exact copied runtime/role files, target
  imports and entry execution, actual vendor-unit graph verification, and actual
  ARM64 Python/environment-tool read/write checks on new RAM-backed files. This
  is emulated component validation, not a complete image or physical boot pass.
  New terminal and combined image artifacts require their own recorded checks.
- No live Pi, original card, TV, USB device, supported installation workflow or
  user guide has changed. Complete card assembly, product provisioning, health,
  signed coordination, migration and release qualification remain unfinished.

5 November 2026 — continuation of [#167](https://github.com/toastfr35/ZmalaCall/issues/167):

- Added an explicit combined package/runtime role with a separately authenticated
  738-archive closure and 52 requested packages. Shared archive identities and the
  observed base remain unchanged.
- Combined terminal UID/GID 1000 and server UID/GID 1001 have separate private
  application and operator bindings. One combined host/boot identity is shared;
  exact policies reject implicit role conversion. Host keys remain root-private.
- Direct component LLT/HLT plans and CI cover combined identity, storage, GPT
  startup and boot-state transitions. Eight combined namespace HLTs, 240 runtime
  LLTs and 83 image-tool tests passed on Linux. Windows skips remain explicit.
- The previously pending standalone terminal root completed with 807 exact
  selections. Its updated initramfs passed target ARM64 checks. Combined
  root/component building is underway; neither result is a full application image.
- Service provisioning, matched loader/card assembly, onboarding and joint
  coordinator/health remain pending. Existing installation workflows and user
  guides remain accurate. No live host or card was changed.

6 November 2026 — [#170](https://github.com/toastfr35/ZmalaCall/issues/170),
offline applications and regular-file media assembly:

- Added committed-source application intake with bounded archives, exact npm
  integrity verification without lifecycle scripts, and pinned TURN source intake.
  Offline builders create locked role users and separate combined releases,
  compile native terminal libraries and validate target imports/service units.
  Server startup/readiness checks use its service UID, isolated loopback and RAM
  data; no factory credentials or initialized application data are retained.
- The server package intent now explicitly includes NetworkManager. Its revised
  authenticated root contains 333 installed selections; terminal and combined
  roots contain 807 and 822. Shared package identities remain consistent.
- Added pinned Pi 4 loader compilation and new regular-file six-partition assembly
  from exact root/initramfs/loader identities. Matching kernel/module/DT inputs,
  Pi-specific overlay handling, factory privacy, redundant explicit boot state,
  bounded payload memory windows and filesystem readback gate artifact readiness.
  No physical-device argument or flashing operation is provided.
- Default artifacts use minimal test geometry. An explicit exact-capacity option
  puts backup GPT at an independently measured target device end; merely writing
  a smaller GPT image to a larger card would fail the existing runtime admission
  checks. Automatic capacity discovery, card writing and data expansion remain
  outside this builder. Builder-source changes during assembly reject readiness.
- The development factory/confirmed path stops the loader watchdog because joint
  health transfer is absent; trials retain the bounded early-boot watchdog. This
  deliberately incomplete policy cannot qualify supported media or automatic
  updates. Hardware, graphics/CMA, power-cut, major-OS and data compatibility
  qualification remain required, as do secure owner onboarding and coordination.
- ARM64 execution here is QEMU user-mode CPU emulation with Linux namespaces,
  not board emulation. Build artifacts and exact check evidence are retained
  privately and summarized in `upgrade_system_status.md` and the implementation
  PR. A WSL backing-volume exhaustion interrupted assembly; physical-volume
  capacity is now checked in addition to Linux virtual free space.
- These changes concern build/packaging tooling and reuse existing runtime
  contracts and service templates. No new runtime requirement is claimed. User
  installers/workflows remain unchanged, so their Word guides remain accurate.

## Contents

- [Outcome and scope](#1-outcome-and-agreed-direction)
- [Existing implementation and impact](#3-existing-implementation-and-impact-inventory)
- [Architecture and ownership](#4-target-architecture-and-ownership)
- [SD-card layout and persistent state](#5-sd-card-layout-and-storage-policy)
- [Boot selection and power-loss recovery](#6-boot-selection-trial-and-power-loss-recovery)
- [Data compatibility and major OS upgrades](#7-data-compatibility-and-major-os-transitions)
- [Image creation and first boot](#8-first-install-image-build-and-first-boot)
- [Automatic scheduling and call protection](#9-automatic-maintenance-policy-and-call-protection)
- [Progress, health and recovery](#10-progress-health-and-recovery-experience)
- [Trust and diagnostics](#11-trust-feed-security-and-persistent-history)
- [Builds, promotion and distribution](#12-release-production-security-intake-and-distribution)
- [Legacy coexistence and migration](#13-coexistence-and-migration-from-todays-installations)
- [Requirements and documentation](#14-requirements-traceability-and-documentation-work)
- [Verification](#15-verification-strategy-and-acceptance-evidence)
- [Implementation stages](#16-ordered-implementation-stages)
- [Completion criteria](#17-completion-criteria)
- [Sources and outstanding decisions](#18-reference-sources-and-decisions-still-to-validate)

## 1. Outcome and agreed direction

Replace the normal SSH-based installation process with three complete, public,
ready-to-flash SD-card images:

- **Zmala Terminal:** Raspberry Pi OS, terminal application, media runtime,
  supported hardware integration, setup UI and automatic system maintenance.
- **Zmala Server:** Raspberry Pi OS, server application, required services,
  local first-run administration and automatic system maintenance.
- **Zmala Terminal + Server:** both components on one Pi and one OS, with separate
  application identities and one host maintenance transaction.

The installation experience becomes: download the correct image, flash and verify
the card with Raspberry Pi Imager, insert it into the Pi, power on, and complete
guided setup. A normal installer does not need an SSH client, Linux shell,
factory SSH password, package installation command or remote upload job.

Updates are automatic as soon as practical, without a per-device administrator
approval queue. The system updates the OS, distribution packages, dependencies and
Zmala application as a tested unit. That includes qualified transitions to later
major OS releases, not just packages within the current Debian release.

Use an A/B system layout and signed RAUC bundles: prepare the inactive system,
boot it as a bounded trial, and retain the last confirmed system until the new
one passes health checks. Keep device identity and user data outside the system
images. The engineering objective is unattended recovery from interrupted
updates, including power loss, within a documented and physically tested failure
model. Neither a second partition nor a signature alone proves that objective.

Initial implementation uses the existing Raspberry Pi OS/Debian base. There is
no initial move to Yocto, Buildroot, containers or another application runtime.
Evaluate those only if a concrete build or safety constraint requires it.

## 2. Scope and boundaries

### 2.1 Included

- Initial SD-card partitioning, reproducible build inputs and image assembly.
- Terminal and server first-boot identity, setup and recovery behavior.
- Signed automatic system updates, minor updates and major OS upgrades.
- Kernel, device-tree, modules and boot-partition firmware shipped as a matched
  system set; application/native dependency compatibility.
- Maintenance admission, call protection, progress, boot health, rollback,
  persistent history, key rotation and release withdrawal.
- Package/security update intake, candidate qualification and staged promotion.
- Migration from both current SSH-installed products to new cards.
- Replacement release downloads, installation guides, tests and requirement traces.
- Shared infrastructure with role-specific health and maintenance adapters.

### 2.2 Excluded from routine system-image installation

- Repartitioning an in-service card over the network.
- Updating the Pi EEPROM bootloader as an ordinary root-filesystem update.
- TV firmware, C10/C20 firmware, Presenter+ firmware and router firmware.
- Remote shell commands supplied by a release feed or administrator browser.
- Arbitrary unqualified packages/plugins installed onto a production root.
- Automatic factory reset or automatic erasure of enrollment after an error.
- Recovery from electrically failed/counterfeit storage, every possible SD
  controller failure, physical theft, or a compromised already-running root user.
- Guaranteeing service availability while the only server is rebooting.

EEPROM compatibility is checked during image qualification and first installation.
If an EEPROM change is necessary, provide a separate, explicitly qualified
procedure and recovery instructions. Root A/B rollback cannot undo a damaged
EEPROM. A future automatic EEPROM mechanism needs its own safety case.

## 3. Existing implementation and impact inventory

Review these owners before implementation. Reuse proven policies and tests where
possible; do not transplant assumptions from application-only updates unchanged.

| Current owner | Current behavior | Planned treatment |
| --- | --- | --- |
| `build_tools/windows_installer/`, `build_tools/server_installer/` | Windows GUI/headless tools upload and install over Ethernet SSH | Retire from the normal new-image installation path after migration qualification; retain historical release downloads |
| `build_tools/linux/install-kiosk.sh`, `install-server.sh` | Change a running OS, install packages, establish services and release symlinks | Extract declarative image provisioning from live-host installation; never run these whole scripts as first-boot installation |
| `build_tools/linux/dependencies.txt` | Terminal distribution dependencies | Become a locked image package input with exact resolved package inventory |
| `build_tools/linux/install-low-wear.sh` | RAM logs, RAM-only swap and storage settings | Retain policy in the image with tests for the new mounts |
| `build_tools/linux/install-ssh-guard.sh`, `install-developer-access.py` | Wired SSH restrictions and separate developer tunnel | Preserve security behavior; remove dependency on SSH for initial installation |
| `build_tools/linux/build-turn.py` and native build tools | Media/TURN corrections tied to the installed SDK | Build inside the matching target image environment and requalify ABI changes |
| `zmala_terminal/linux/update_*.py` | Application-only signed slots, leases, data checkpoints, independent supervisor/display | Reuse concepts and suitable components; image-installed terminals have one system update owner |
| `zmala_terminal/common/update_client.py` | App maintenance handshake and status | Adapt to the system-maintenance contract; legacy deployments continue using the old contract |
| `zmala_server/terminal-updates.js` | Cached app feed, terminal status and admission fencing | Add explicit installation-type/system status, preserving old terminal behavior during coexistence |
| `build_tools/release/{assemble,github_release,terminal_update}.py` | Exact release asset allowlist, notes, app-update signing | Introduce image/bundle/feed artifacts and role-aware publication validation |
| `.github/workflows/{verify,release}.yml` | PR verification and merge-triggered public releases | Add image candidate build/verification and separate qualified system-feed promotion |
| `docs/terminal-update-plan.md`, `docs/terminal-update-qualification.md` | Existing application-only design and evidence | Keep accurate as legacy scope; cross-link the replacement when implemented |

Both current Pi installers target Raspberry Pi OS Lite 64-bit, Debian 13 Trixie.
Terminal installation accepts Pi 4 Model B. Server installation accepts Pi 3 Model
B/B+ and Pi 4 Model B. This plan initially qualifies Pi 4 for all three image roles; Pi 3
server support is a separate explicit qualification gate, not silently withdrawn
or assumed from portable tests. Public compatibility labels must distinguish
legacy installer support from qualified new-image support.

Current durable terminal data is `/var/lib/zmalacall`; server data is
`/var/lib/zmalacall-server`. Current app-update state also uses
`/opt/zmalacall-updates`, `/var/lib/zmalacall-update-data` and
`/etc/zmalacall/updater.json`. Current roots are writable; `/tmp`, normal journals
and swap are deliberately volatile. The new design must not lose the small
amount of update history needed after a reboot.

The terminal TURN build currently checks MediaStreamer version `5.3.105`.
This is an actual compatibility dependency, not an instruction to freeze security
updates forever. A library change requires requalifying/replacing the patch and
rebuilding the complete image before promotion.

## 4. Target architecture and ownership

```mermaid
flowchart TD
    S[Reviewed source and locked package inputs] --> B[Role image build]
    B --> I[First-install SD image]
    B --> U[Signed RAUC update bundle]
    U --> Q[Automated and hardware qualification]
    Q --> F[Signed rollout metadata]
    F --> C[Local maintenance coordinator]
    C --> R[RAUC writes inactive system]
    R --> T[Safe idle and trial boot]
    T --> H{Local health checks}
    H -->|Pass| G[Confirm new system]
    H -->|Fail or timeout| O[Boot previous confirmed system]
    D[Persistent device and user data] --- T
    D --- O
```

Use four clear responsibilities:

1. **Image builder:** constructs known package and application states, public
   first-install images, unsigned candidate payloads and provenance.
2. **Release publisher:** verifies candidate evidence and signs bundles/rollout
   metadata using release-only credentials. It does not inherit trust from an
   untrusted PR artifact merely because its filename looks correct.
3. **Local system-maintenance coordinator:** discovers applicable updates,
   reserves resources, enforces idle/call policy, controls reboot/trial deadlines,
   and records results. An unprivileged application cannot choose raw devices,
   arbitrary URLs, hooks or shell commands for this service.
4. **RAUC and boot integration:** install the verified inactive slot group and
   perform narrowly defined boot selection/confirmation. Data migration and
   product readiness remain explicit Zmala responsibilities.

Prefer RAUC's D-Bus interface for service integration. Inspect the pinned RAUC
version before relying on optional facilities such as polling or adaptive
downloads; current upstream documentation is not proof those features exist in
the distribution package selected for the image.

Implement shared host maintenance outside the terminal UI package so the server
does not import Tk, camera, Bluetooth or TV code. Suggested organization, subject
to the first architecture PR:

```text
zmala_images/                 # Build configs, package locks, assembly
zmala_images/common/          # Shared appliance layers and mount policy
zmala_images/terminal/        # Terminal-specific image layers
zmala_images/server/          # Server-specific image layers
zmala_system/                       # Small common Pi system-maintenance runtime
  coordinator.py                    # State machine and bounded scheduling
  trust.py                          # Verified metadata and compatibility decisions
  storage.py                        # Fixed layout discovery and space budgets
  boot.py                           # Qualified boot backend adapter
  health.py                         # Shared trial/checkpoint coordination
  terminal.py                       # Terminal readiness and idle adapter
  server.py                         # Server readiness and call-drain adapter
tests/support/system_update/        # Fault injection and common fixtures
tests/adhoc/image_installer/         # Image/flash/build/deployment checks
```

These paths are proposals, not existing modules. Split further only where an
owner has a distinct trust boundary, lifecycle or independently testable policy.
Avoid one large root script and avoid frameworks that obscure boot decisions.

## 5. SD-card layout and storage policy

### 5.1 Proposed layout

Use one versioned partition schema for all three image roles, with role-specific contents.
The following is an initial sizing budget for a nominal 32 GB card, not a measured
fit guarantee:

| Partition | Initial budget | Contents and policy |
| --- | --- | --- |
| Boot selector/config | 64 MiB | Minimal boot-selection files; immutable except through the qualified commit mechanism |
| Boot A | 512 MiB | Slot A firmware, kernel/initramfs and matching command line |
| Boot B | 512 MiB | Slot B equivalents |
| Root A | 8 GiB | Complete OS, package database, Zmala and native artifacts |
| Root B | 8 GiB | Alternate complete system |
| Data | Remaining usable space | Identities, selected host state, application data, bounded update metadata/cache/checkpoints |

A nominal 32 GB card provides about 29.8 GiB before layout/filesystem overhead;
this example leaves roughly 12 GiB for data. Measure all three images, the largest
supported portrait/photo collection, bundle staging, migration checkpoints and
free-space reserve. Adjust budgets before freezing schema v1. Reject cards below
the measured minimum byte capacity even when their label says 32 GB.

RAUC treats the boot and root members of each system as a group. An update is
eligible for trial only after all members have been written and verified. Root
and boot members must not be mixed across slots. Root filesystem paths and boot
configuration use validated stable identifiers, not assumptions that every
device is `/dev/mmcblk0`.

The initial card format decision must resolve Pi 4 firmware compatibility with
the selected MBR/extended or GPT layout and six partitions. Do not copy a sample
GPT configuration without booting every supported board revision. Pin and test
the image tool's chosen format. Partition creation belongs to image generation,
not a field update.

### 5.2 Root and boot mount behavior

- Prefer read-only production roots and boot partitions in ordinary operation.
- Keep the inactive root and boot members unmounted except for controlled
  installation or inspection.
- Keep `/run`, `/tmp` and ordinary journals in RAM; retain RAM-only swap policy.
- Inventory services that write under `/var` or `/etc`. Give each an explicit
  persistent or temporary destination instead of sharing all of `/var` or `/etc`.
- Keep `/var/lib/dpkg`, package alternatives, installed libraries and package
  configuration defaults inside their own system slot. They must roll back
  together. Never bind-mount a shared package database into both systems.
- If read-only roots require an `/etc` overlay, use a slot-specific generated
  upper layer or narrow bind mounts. Never reuse an uncontrolled writable upper
  layer across major OS generations.
- Disable automatic card-expansion behavior that expands a root into the other
  slots. Only the final data filesystem may be expanded, using a resumable,
  separately tested first-boot step. Ship enough preformatted data capacity to
  recover if expansion has not completed.
- Measure write amplification, download/verification throughput and memory use
  on the lowest supported Pi, not only on the build host.

### 5.3 Persistent state inventory

Mount durable state below a single appliance data mount, for example `/data`,
with narrow bind mounts preserving established application paths.

| State | Planned persistence and recovery |
| --- | --- |
| Terminal enrollment, account token, settings, language, history | Preserve through updates; bind to `/var/lib/zmalacall`; versioned validation/checkpoints |
| Server accounts, groups, SIP credentials, portraits, callbacks, photos, admin credentials | Preserve through `/var/lib/zmalacall-server`; consistent backups and trial migration rules |
| Hostname and device identity | Generate once and persist; no shared machine identity in public images |
| NetworkManager Wi-Fi profiles and DHCP identity | Preserve explicitly with root-only permissions; regenerate version-specific representation when needed |
| Bluetooth pairing keys and remote identity | Preserve explicitly; validate BlueZ representation across major versions |
| SSH host keys and authorized recovery identities | Generate once per device; preserve so updates do not trigger host-key changes |
| TV pairing tokens, TV plugin configuration and case configuration | Preserve validated settings; new plugin code comes from the signed system image |
| Local TLS keys, certificate renewal accounts, mail credentials and push sender key | Root/service-restricted data; never in the factory image or public evidence |
| TURN/SIP relay configuration and credentials | Preserve selected secrets; regenerate service configuration for the new slot version |
| Device-managed display/audio/USB policy | Persist validated product settings, not arbitrary copied boot files |
| RAUC status and coordinator transaction records | Durable, bounded and writable only by their owning privileged services |
| Download cache, thumbnails, disposable logs | Bounded and evictable; no identity depends on their survival |

Preserve service UIDs/GIDs consistently across images and migrations. The current
terminal service account and developer tunnel account have different purposes;
do not merge their privileges when normalizing image accounts. Preserve the
server's existing unprivileged service ownership. Inventory every secret location
before deciding backup completeness.

## 6. Boot selection, trial and power-loss recovery

### 6.1 Boot backend decision and release gate

Prototype the Pi's native `tryboot` A/B mechanism first. It is closer to the
existing firmware boot path and avoids adding U-Boot without evidence it is
needed. There is a community RAUC custom backend for this mechanism, but it is
not a substitute for our own audit, pinning, tests and maintenance ownership.

**The shared boot selector is the critical qualification gate.** Native examples
commit a successful trial by updating `autoboot.txt` on FAT. Replacing that file
is not, by itself, demonstrated power-cut-safe storage. Filesystem rename and
`fsync` calls do not automatically prove firmware-readable recovery after a torn
FAT or SD-controller write.

Before choosing this backend for production:

1. Inspect all selector writes, ordering, flushes, fallback selection and
   interrupted-confirmation behavior in the pinned implementation.
2. Establish how firmware finds a valid boot target if the selector file or its
   metadata is damaged. Do not assume undocumented firmware fallback behavior.
3. Test physical interruption during selector creation, replacement and final
   confirmation, including repeated cuts across offsets/timings.
4. Demonstrate normal boot after removal and restoration of mains power, watchdog
   reset, warm reboot and crash, not only successful `reboot` commands.
5. Verify every supported Pi revision and minimum EEPROM version; read
   device-tree boot properties with their documented binary representation.

If this cannot meet the recovery contract, adopt a qualified RAUC-supported
bootloader configuration such as U-Boot with redundant, checksummed boot state,
or another demonstrated recoverable selector design. That alternative also needs
actual power-cut tests and a way to recover the bootloader itself. Do not claim
that adding U-Boot automatically solves all SD write failures.

No automatic stable rollout until this decision has supporting evidence. Factory
image development can proceed while boot safety is being investigated.

### 6.2 Trial sequence

1. Validate current slot identity, installed layout and confirmed-release record.
2. Reserve enough storage and verify a role/hardware-compatible signed bundle.
3. Mark only the inactive system unconfirmed and write its complete slot group.
4. Flush writes, complete integrity checks and durably record the candidate.
5. Obtain final maintenance admission; make/check data checkpoints as required.
6. Persist the intended trial and expected boot identity before requesting it.
7. Request a one-shot trial boot. Keep the old confirmed default until success.
8. An early boot service validates the actual boot/root pairing and mounts data
   before starting application writers. Establish watchdog coverage before the
   stages it is expected to protect.
9. Run bounded local health and migration checks under maintenance fencing.
10. Confirm the system using the qualified boot backend and reconcile the durable
    transaction. Only then remove maintenance and admit normal activity.
11. On failure or deadline, record the reason if possible and restart to the
    previous confirmed system. Reconcile data before that old application starts.

Configure RAUC so completing an inactive-slot installation does not immediately
make that candidate the permanent default. Verify the selected version's
activation/mark-primary semantics explicitly. Installation, one-shot trial and
durable confirmation are separate operations under the coordinator; generic
"mark good on every successful boot" services must not bypass the product health
and data transaction.

One candidate receives one boot trial per installation attempt initially. A
failed digest is quarantined locally and not reinstalled every hour. A signed
newer repair or an explicitly authorized signed retry policy may clear that state.

Confirmation is a transaction spanning boot state and coordinator metadata.
Specify which durable facts are authoritative at each interruption point. A
confirmed boot with an old coordinator record and a trial boot with a new record
must both recover deterministically; do not infer selection from one JSON file.

### 6.3 Watchdog ownership

RAUC/tryboot cannot reset a hung system merely by selecting another partition.
Use the Pi hardware watchdog with a single defined owner and bounded service
health supervision. Distinguish firmware/early-kernel, initramfs and userspace
coverage: systemd's runtime watchdog starts too late to prove recovery from every
earlier boot hang. Qualify a supported early-boot watchdog path or document and
close that gap before making a full unattended-boot-recovery claim.

Set trial, shutdown and runtime timeouts from measured worst-case startup on
supported hardware, including filesystem recovery. Initial budgets may start at
three minutes for a terminal trial and five minutes for a server trial, but are
tuning proposals. Bound each individual check and the overall trial. Never pet
the watchdog indefinitely while the candidate repeatedly restarts the same
failing service.

### 6.4 Failure behavior matrix

| Interruption or fault | Intended result | Evidence needed |
| --- | --- | --- |
| Download, network loss or cache full | Continue confirmed system; retain only safe partial cache | Bounded retry, no boot-selection change |
| Signature, role, board or compatibility mismatch | Reject before selecting candidate | Negative trust/compatibility fixtures |
| Inactive boot/root write fails or power disappears | Old confirmed system remains selectable; partial candidate never trialed | Inject errors/cuts during each member write |
| Power loss after candidate staging but before trial | Boot confirmed default; recover staged record without guessing | Restart at every transaction boundary |
| Trial boot kernel/init/service hang | Watchdog/reset returns to confirmed system within qualified bound | Real hangs at early and late boot stages |
| Trial data migration fails or is interrupted | Previous readable data and confirmed system restored before normal writers | Migration interruption matrix |
| Power loss while marking good | Resolve to one complete valid system using qualified commit semantics | Physical selector/metadata cut tests |
| Missing network, phone, TV, remote or camera | Product reports normal availability problems; avoid pointless OS rollback | External-fault health tests |
| Candidate fails after successful confirmation | Record degraded health; bounded recovery; automatic rollback only if retained data is still compatible | Post-confirmation compatibility scenarios |
| Shared data cannot mount or both roots are invalid | Enter minimal recovery state; do not format or reset identity | Recovery-media and diagnostics exercise |
| EEPROM or SD hardware failure | Follow separate bootloader/card recovery procedure | Documented limits and recoverable backup |

## 7. Data compatibility and major OS transitions

### 7.1 Default rule: rollback-readable persistent data

For ordinary unattended releases, both the candidate and previous confirmed
system can read data written during and after the transition. Prefer additive
fields, preserved unknown fields, versioned serialization and expand/contract
migrations. Delay removal of obsolete representations until no supported
rollback path needs them.

Compatibility covers host services too: NetworkManager, Bluetooth pairing, TLS
state, account permissions and relay configuration can change across OS versions
even if Zmala's own JSON schema does not.

Each signed system description records supported data schema ranges and any
migration generation. Test both directions with real fixtures from supported
source releases. A successful `/ready` or JSON parse is not sufficient proof that
the previous version can safely write the resulting data.

### 7.2 Exceptional incompatible migrations

An unattended upgrade with an unavoidable incompatible migration is eligible only
after a dedicated migration design and qualification. Proposed mechanism:

1. Freeze application mutations and drain owned jobs after maintenance admission.
2. Create a consistent, durable, validated checkpoint with enough free space for
   both the source and destination. Keep schema/version and transaction binding.
3. Migrate into a separate versioned data generation, leaving the old one intact.
4. Trial the candidate against its generation, with externally visible writes
   blocked until confirmation.
5. Commit the boot/data choice through a reconciled state machine; interrupted
   commits must identify the correct pair without destructive guessing.
6. After confirmation, permit normal writes. Retain the old generation for the
   documented recovery interval, but do not silently restore it later and lose
   newly created accounts, calls, callbacks or configuration.

If rollback after service reopening cannot preserve new data, do not advertise
automatic post-confirmation rollback for that release. Roll forward with a repair
or enter an explicit recovery procedure. Initial production support may reject
incompatible migration releases until this mechanism is implemented; that is a
reported eligibility failure, not a claim that major upgrades are supported.

Server backups must be consistent across its JSON files and media. Copying live
files independently while the server writes is not a valid checkpoint. No
restored console job, notification, callback delivery or queued developer command
is replayed merely because an OS rollback occurred.

### 7.3 Major OS release policy

- Build the next major OS in a fresh target root using new locked repositories;
  never change the running Pi's APT sources and run `dist-upgrade` remotely.
- Qualify the native media ABI, all kernel/device drivers, host-service state,
  updater protocol, data compatibility and boot sequence as a new system baseline.
- Express a supported source-version range. If a very old device needs an
  intermediate bridge image, publish a signed bounded upgrade path.
- Reject a bundle requiring a different partition layout; major OS support must
  not depend on in-field repartitioning. Supply a new-card migration if it cannot
  fit the frozen layout.
- Promote a major release only after canary/soak evidence. Once promoted, eligible
  devices upgrade automatically at safe idle; the owner does not approve each Pi.
- Continue providing current-baseline security candidates until the successor is
  qualified where practical. Expose end-of-support and blocked-upgrade conditions
  instead of leaving the fleet silently frozen.

## 8. First-install image build and first boot

### 8.1 Image builder

Use `rpi-image-gen` as the first candidate builder, pinned to a reviewed revision.
It supports customized Raspberry Pi images and provides useful A/B layers. Its
slot-mapping helpers are building blocks, not the entire RAUC safety policy.
Compare a minimal working image with our required six-partition format before
committing to its exact layers.

Prefer a clean native ARM64 Debian/Raspberry Pi OS build environment. An isolated
ARM64 CI worker or ephemeral builder is preferable to placing public PR jobs on
the production terminal/server. Cross-build/QEMU under Linux/WSL can help local
development, but qualifies as a build route only after repeatability tests. The
Windows PC remains a development/flashing host, not a live target needed for
every package installation.

Separate build-time package acquisition from first boot:

1. Resolve trusted Debian/Raspberry Pi repository metadata and selected package
   versions in an intake job, with authenticated repository signature validation.
2. Record the exact package inputs, repository snapshots or retained artifacts,
   hashes, image-builder revision and toolchain/container digest.
3. Build common and role layers with package maintainer scripts prevented from
   starting services against the build host or generating shared device identities.
4. Build native workers and TURN corrections in that exact target root environment.
5. Install the reviewed Zmala commit and runtime dependencies; compile admin
   assets through the normal generator. Exclude compilers, node_modules development
   dependencies and source caches where they are not needed at runtime.
6. Install mount rules, RAUC public trust, coordinator, health services, boot
   presentation, restricted helper interfaces and supported hardware defaults.
7. Generate an image manifest, software bill of materials and third-party notices;
   attach corresponding source locations/commit/package versions for license
   compliance. Verify redistributability of every image component.
8. Sanitize entropy seeds, machine IDs, SSH host keys, pairing data, enrollment,
   credentials, logs, local paths and private development content.
9. Assemble all three role images and matching slot payloads. Initially seed both slots
   with the same factory release so a newly installed device has a coherent fallback.
10. Inspect the mounted image offline and boot-test the exact assembled artifact.

Do not promise byte-for-byte reproducibility before verifying timestamps, filesystem
UUIDs and package behavior. At minimum make every build input pinned and the
outputs attributable; then add deterministic identifiers/timestamps and demonstrate
rebuild comparisons. Never reuse machine identities to obtain reproducible bytes.

### 8.2 Image versus update bundle

The first-install `.img.xz` contains a complete partition table and empty data
filesystem. Flashing it is destructive to the selected card and is a local,
explicit installation action. The `.raucb` contains only the applicable boot/root
slot payloads and authenticated metadata/hooks; it does not replace the data
partition or repartition a deployed device.

Sign/check first-install artifacts as well as update bundles. Use a trusted
download/verification path and publish signed checksums/provenance; a checksum
obtained from the same compromised untrusted page is not an independent trust
anchor. If Raspberry Pi Imager does not verify our signature itself, document the
supported companion verification step instead of claiming its write verification
authenticates the publisher.

### 8.3 Shared first-boot tasks

- Check hardware, layout version and board/EEPROM prerequisites before enabling
  unattended updates. Present a clear recovery message on unsupported hardware.
- Mount and validate persistent data; complete any resumable final-data expansion.
- Generate per-device machine identity, SSH host keys and required private tokens
  only after adequate entropy is available. Store with restrictive permissions.
- Initialize stable service ownership and minimal device-specific configuration.
- Establish an offline-safe default clock policy; acquire trusted time before
  time-sensitive TLS/update checks. An unset clock is a recoverable network/time
  condition, not permission to skip signatures or certificate validation.
- Apply factory state exactly once through durable stage markers. Interrupted
  first boot resumes without rotating a previously committed identity.
- Validate both seeded slot/data expectations. Do not enroll each slot as a
  different terminal or rerun factory setup after a successful system update.
- Keep production SSH disabled by default except for explicitly configured
  recovery/developer access, with the existing Ethernet restrictions enforced.
  No public universal password is enabled for remote login.

### 8.4 Terminal onboarding

Preserve the current user workflow: supported-language selection, C10/C20
connection, Presenter+ pairing and button verification, Wi-Fi QR setup when needed,
then terminal server-enrollment QR. Ethernet can provide initial networking but
is not required for an SSH installation stage.

Show Zmala boot/setup artwork immediately; setup stages resume after power loss.
Keep C10/C20-only media selection, per-model gain, separate call/ringtone/feedback
volume, TV plugins and optional Argon case policy. Do not start TV qualification
or power/input actions from an automatic update health check. A missing camera
or remote leads to normal setup/recovery guidance, not endless OS rollback.

Factory images contain no enrolled family accounts or uploaded private portraits.
Preserve the established green/red remote semantics and supported language list.
Do not add keyboard-only hints to the Pi image.

### 8.5 Server onboarding

The server image needs a local, browser-based bootstrap path that replaces the
options previously supplied by the Windows installer:

1. Boot on Ethernet and obtain DHCP; advertise a discoverable local hostname
   with a collision-safe identity. Explain DHCP reservation in the guide.
2. Provide a LAN-only claim/setup page. Resolve securely how the first owner proves
   possession: a one-time local setup code available from a temporary HDMI display
   or a physical setup medium is preferable to an internet-accessible unclaimed
   administrator page. Select and test one concrete flow before implementation.
3. Set the web admin password without exposing a shared factory password; consume
   the claim token durably and disable the bootstrap endpoint after completion.
4. Choose fresh setup or validate/import a private migration archive. Provide
   application-backup import and a separately authenticated full-appliance restore
   where host identity/keys are required. Do not pretend the current application
   backup contains all TLS, Wi-Fi, mail, push and relay state.
5. Configure advertised addresses, domain, TLS/certificate renewal, mail/push and
   secure-call relay parameters through validated local UI or a documented local
   provisioning file. Preserve private key handling and reject arbitrary commands.
6. Show actual listener/network readiness and the next step for creating accounts,
   groups and enrollment PDFs. LAN calls can be ready before internet calling.
7. Provide clear DNS/router-forwarding checks and generic forwarding instructions.
   The server cannot silently configure every router or assume a public IPv4.

The new image needs a complete supported secure-call service profile, including
the currently separate TLS/TURN/reverse-proxy/certificate-renewal provisioning
where applicable. Inventory the deployed configuration and turn it into reviewed
layers/options before declaring server migration complete. Do not embed a live
domain, sender key or administrator credential in the public image.

Keep administration LAN-only, developer shell entry restricted to wired local
subnets, and the separate tunnel endpoint unable to grant a server shell. The
public update download endpoint grants no administration capability. First-run
setup must enforce the same network boundary even before a domain is configured.

### 8.6 Combined appliance

Issue [#167](https://github.com/toastfr35/ZmalaCall/issues/167) adds the explicit
`combined` profile, displayed as **Zmala Terminal + Server**. Its authenticated
package intent is the union of the standalone roles against the same observed
base; shared archives stay identical across role locks. Role conversion is a
separate migration, never a normal candidate update.

One machine identity, network/Bluetooth configuration, boot selector and data
partition serve both components. Terminal UID/GID 1000 and server UID/GID 1001
own separate private application trees; standalone roles retain 1000. Operator
configuration is split by component. Root-private host SSH and server TLS keys
are not made readable by the terminal UI. The storage/boot policy implements
these boundaries; actual system-user and service provisioning remains pending.

Combined first boot needs both LAN-only server first-owner setup and normal
terminal QR enrollment, with host networking configured once. Qualify secure
local terminal-to-local-server registration with the correct TLS authority
without router NAT loopback. Review listener and account collisions, including
tunnel listeners versus developer shell access. Keeping the television in
standby or restarting the terminal UI must not stop the server.

## 9. Automatic maintenance policy and call protection

### 9.1 Proposed scheduling defaults

These are initial tunable engineering defaults, to be measured and represented
in validated policy rather than scattered constants:

| Operation | Proposed default |
| --- | --- |
| Check after boot | Once after five minutes if the local day has not been checked |
| Check for new qualified system release | Local midnight daily, plus Settings > Updates on demand |
| Resume interrupted transfer | Automatically after network/storage eligibility returns |
| Terminal activation eligibility | At least 2 minutes of genuine safe inactivity |
| Server activation eligibility | No owned ringing/connected calls, active relay allocations or protected jobs, then 2 minutes of stable idle |
| Low-space/network retry | Backoff; report a persistent blocked condition after 24 hours |
| Failed candidate | Quarantine exact identity; continue confirmed image |
| Stable update pending more than 48 hours | Report the blocker; keep trying at safe idle, never terminate a call to meet the target |

Download and inactive-slot writes may occur during normal use only within measured
CPU, memory and I/O budgets. Call quality takes priority: pause or defer heavy
verification/writes when a call starts or the host is under pressure. Background
preparation does not grant reboot permission.

### 9.2 Terminal maintenance admission

Reuse the existing admission concepts, extending them to system reboot:

- No ringing, outgoing, connected or terminating call and no pending call-start
  transition, including photo sharing and other call-owned work.
- No setup scan, remote pairing/test, TV setup/self-test, settings write, data
  import, owned command, held remote button or pending TV restoration.
- Revalidate through a fresh lease tied to actual process/call state immediately
  before application stop/reboot. A call that already started wins admission.
- After the lease, fence local dial/answer and new server call admission until
  readiness returns. A stale server view does not override local call protection.
- Avoid USB/camera wake and TV power/input changes solely for system maintenance.
- Preserve pre-update TV restoration/inactivity state durably. Reboot recovery
  must not interpret live TV as the terminal input and switch it off later.

The local lease remains the authority when the server is unreachable. Withdrawal
or expiry cannot create a brief unfenced interval during activation/recovery.

### 9.3 Server maintenance admission

The server needs its own call-drain owner, not just the terminal status predicate:

1. Prepare the candidate without stopping SIP/media while resources permit.
2. Inspect all authoritative call owners: incoming/outgoing/ringing SIP dialogs,
   forwarded transactions and owned RTP/RTCP relay sessions.
3. Include TURN allocations and other separately supervised media services where
   they can carry ongoing calls. An empty Node call map alone does not prove the
   whole appliance is idle. Establish a supported allocation/activity query or
   conservative idle policy; if this cannot be observed safely, activation is
   blocked rather than assuming zero calls.
4. Include backups/restores, account/data commits, certificate/key changes and
   developer tunnel activity that would be interrupted. The web page being open
   alone is not a permanent veto; an active protected mutation is.
5. Acquire a local global maintenance lease, reject new calls/allocations cleanly,
   and atomically recheck for a race. Complete existing calls before reboot.
6. Freeze writers, checkpoint data if needed, notify clients of temporary
   maintenance where supported, then stop services in dependency order.
7. During trial, bind/test services under admission fencing. Release the fence only
   after successful confirmation. Re-register/reconnect clients without duplicate
   notifications, stuck busy status or replayed callbacks.

There is no forced call deadline. If the service is continuously used, explain why
an update remains pending. Do not promote an urgent patch by silently dropping an
ongoing call.

### 9.4 Fleet coordination without a central dependency

Each Pi can recover and fetch signed publisher metadata independently of its local
Zmala server. A server being unavailable must not prevent a terminal from rolling
back, verifying an already downloaded release or later obtaining a repair.

When both are online, use advisory maintenance announcements to avoid simultaneous
server/terminal trials and reduce disruption. Prefer server readiness before a
dependent terminal activates, but use bounded scheduling and backward-compatible
protocol ranges so neither waits forever for the other. Compatibility manifests
define bridge releases when an upgrade order matters. The server cannot authorize
an unsigned release merely by forwarding a feed.

### 9.5 Combined admission and health

One coordinator owns RAUC and reboot. Activation waits for both terminal safe-idle
admission and server admission, including global SIP/TURN activity and protected
persistence operations. Calls win the final admission race. Confirmation covers
both local components, including valid unclaimed-server and terminal-setup waiting
states; external outages do not alone imply a broken candidate. No health probe
wakes camera or TV. Preserve both application data generations and TV restoration
state in the same transaction. These coordinator and health paths remain pending.

## 10. Progress, health and recovery experience

### 10.1 Terminal display

- Background checks, transfer and staging remain quiet.
- During activation, show a clear localized update/restart/checking message on
  terminal HDMI. Continue the message across restart as early as practical.
- Use the saved supported language and fonts, with English fallback for an invalid
  locale. Test CJK, RTL, long strings and large TV-safe margins.
- Show measured progress only for measurable stages. Use stage labels rather than
  a frozen percentage while rebooting or waiting for health.
- On rollback show a calm localized restoration message, followed by normal
  contacts when usable. Persistent failure exposes a short support code.
- Never wake the TV, select terminal HDMI or power up USB solely to display update
  progress. If someone selects the terminal source, the message is already there.

### 10.2 Server UI and status

Add a read-only system status area showing installed release, OS baseline, channel,
last successful check, available release, stage, last result, pending reason and
support code. Add equivalent system status to each terminal row/details page,
clearly distinguishing legacy app updates from system-image updates.

Show stale/offline state honestly with server-received timestamps. Do not turn an
unavailable Pi into a green successful update. No normal Approve/Install button
is needed. A support/recovery action, if added later, is explicit, authenticated,
idle-checked and cannot bypass signature or rollback eligibility.

A browser loses connection during a server reboot. A reconnecting progress page
may show cached release/stage and retry, but must not promise continuous live
progress or reveal private state from a public unauthenticated listener.

### 10.3 Health checks

Separate hard local boot failures from ordinary external availability problems.

| Role | Required local trial checks | External conditions that do not by themselves fail the OS trial |
| --- | --- | --- |
| Shared | Expected boot/root identity; readable data; valid state schema; bounded free space; required units; trust configuration; watchdog operation; migration completion | No internet, DNS/time synchronization pending, publisher unavailable |
| Terminal | Native modules load against shipped libraries; controller/UI heartbeat; setup or configured UI ready; no restart loop; maintenance/USB/TV policy intact | Missing/off TV; sleeping/disconnected C10/C20 or Presenter+; server offline; no phone |
| Server | Valid persistent application data; `/health` and `/ready`; expected local listeners; relay/TLS service configuration when enabled; no process restart loop; local access controls | Remote devices offline; WAN/TURN destination unavailable; DNS/router/certificate issuance temporarily unavailable |

Test optional service configuration locally without taking possession of the
camera, producing a beep, making a call or changing TV state. Do not auto-confirm
solely because PID 1 or the HTTP socket exists. Conversely, a temporary network
outage must not bounce forever between two healthy OS images.

Hardware/media qualification happens before release promotion and during explicit
support tests. Routine boot health is deliberately passive.

### 10.4 Recovery without ordinary SSH installation

Provide documented recovery levels:

1. Automatic fallback to last confirmed system and quarantined candidate.
2. Minimal local recovery page/screen with bounded diagnostics and supported
   backup/export or signed repair import, respecting LAN restrictions.
3. Verified rescue/new SD image plus private backup restore if both system slots
   or the data filesystem are unusable.
4. Developer SSH through the existing explicit restricted access path when needed.

Never expose a default-password shell or internet recovery admin page as a
shortcut. A broken data mount is not permission to format it automatically. A
factory reset remains a separate deliberate action with a clear warning.

## 11. Trust, feed security and persistent history

### 11.1 Signed software and metadata

RAUC bundle signatures authenticate the system payload. Add signed rollout
metadata describing which verified bundle is eligible now; TLS alone and an
editable GitHub release title are not sufficient authorization.

Bind at least:

- Product role, architecture, board family and partition-layout version.
- Unique release ID, application commit/version and system build ID.
- OS generation, minimum bootloader/updater contract and supported source range.
- Bundle byte length, cryptographic digest and bounded trusted download location.
- Data/protocol compatibility and any required intermediate release.
- Monotonic release sequence, channel/cohort eligibility and withdrawal state.
- Metadata revision/freshness and signing identity.

Resolve the metadata implementation in the security design stage. Prefer a
maintained TUF client if its measured footprint fits: it avoids inventing rollback,
freeze and key-delegation protocols. If extending the existing Ed25519 manifest
instead, explicitly specify equivalent threat decisions and get focused review.
This is a production gate, not an excuse to silently ship only unsigned feed JSON.

Keep anti-downgrade metadata distinct from boot fallback: automatic booting of the
exact retained confirmed system remains allowed after a failed trial. Installing
an arbitrary older bundle does not. Signed withdrawal instructions identify
eligible targets and compatibility; never implement a blanket downgrade switch.

### 11.2 Keys, clocks and network constraints

- Separate development and production signing trust. Development images cannot
  accidentally consume the production fleet feed or install onto enrolled devices
  without an explicit supported transition.
- Use a RAUC trust chain appropriate for CMS bundle verification; do not reuse an
  Android APK key or assume the existing terminal Ed25519 key signs RAUC bundles.
- Keep private keys confined to protected release jobs. PR/build jobs produce
  unsigned artifacts and cannot read production credentials. No private key in an
  image, repository, server database, public log or downloaded support ZIP.
- Document overlapping-key rotation so an offline device can traverse the trust
  transition. Test old and new roots, expired/revoked keys and emergency withdrawal.
- Define time behavior for Pis without a battery-backed clock: TLS and certificate
  expiry checks, signed freshness and long-offline recovery must agree. Do not
  disable certificate expiry merely to make a stale clock pass.
- Bound metadata sizes, nesting, URL redirects, partial responses, transfer times,
  disk allocation and decompression. Allow only expected HTTPS publishers; reject
  loopback/private-address redirection and never send enrollment tokens to GitHub.
- Resume downloads only with validated identity/length/ETag rules; verify the final
  complete artifact before trial. CDN/rate-limit/outage responses are retryable,
  not valid empty releases.

Bundle authenticity does not by itself establish secure boot or encrypted data.
Those are separate deployment properties. Document what a stolen card or an
attacker with local root could change.

### 11.3 Durable bounded diagnostics

Persist only the evidence needed for recovery: release IDs/digests, transaction
phases, slot identities, result categories, health reason, boot attempt, policy
revision and timestamps with clock-quality information. Keep a bounded history
(initially 50 transactions or 2 MiB, whichever comes first), flushing at state
boundaries rather than every progress tick. Never evict the active transaction or
the record needed to interpret the retained confirmed system.

Do not persist camera frames, call media, SIP passwords, Wi-Fi credentials,
developer passwords, TLS keys or complete enrollment QR contents in diagnostics.
Record UTC and display the user's/local admin timezone where appropriate.
Monotonic elapsed time controls deadlines within a boot; wall-clock adjustments
must not extend a trial or maintenance lease indefinitely.

## 12. Release production, security intake and distribution

### 12.1 Separate candidate publication from automatic fleet promotion

Retain the repository's issue/feature-branch/PR/Verify/merge workflow. Every merged
PR still advances the Android version and publishes a release under the current
repository policy, including documentation changes. That does not mean every
merged commit must immediately replace the OS on every Pi.

Use two distinct identities:

- **Zmala application/repository release:** current version/tag/commit convention.
- **Qualified system build:** role, hardware/layout baseline, OS generation,
  package-lock hash, image build sequence and matching application commit.

A documentation-only release can keep pointing to the previously qualified system
build through explicit metadata. It must not relabel old image bytes as newly
built from the documentation commit. An actual package/system build produces a new
immutable identity. Stable feed promotion consumes exact artifact digests and
qualification evidence, not merely whichever GitHub release is newest.

### 12.2 Package and security update intake

The standalone Terminal checks the signed Debian Trixie security index daily.
A newer security package in its installed package set triggers an automatic
refresh of the shared locks and the pinned build cache. The workflow stages the
resolved changes and system version on a review branch. Merging the verified
changes starts the system build and signing job.

Routine Terminal RAUC releases use Verify, the build audit and the signing
audit for release acceptance. The appliance still performs a one-shot boot
trial with health checks and fallback. Physical tests of the boot platform
and factory media are covered by their respective qualification plans.

Publish the signed bundle pair together. Terminals check and apply the release
under their local maintenance policy.

Disable production APT timers/unattended-upgrades and other competing package
writers in new images. APT operates while building candidate roots, not while
mutating the running appliance. Developers may inspect package state; unsupported
manual root/package changes mark the device modified and block ordinary automatic
promotion until a supported repair/return-to-image procedure resolves it.

### 12.3 CI pipeline and qualification infrastructure

- **PR verification:** existing portable/Windows/Android checks, plan/trace checks,
  coordinator tests, image configuration validation and installer regression tests.
- **Unsigned image build:** isolated ARM64 builder with no release keys or live
  device credentials; reproduce locked package roots and payloads.
- **Offline inspection:** partition/mount consistency, package manifest, missing
  dependencies, executable permissions, secret scan, license notices, no factory
  identities, no prohibited services and no generated-file drift.
- **Virtual tests:** state-machine failures and role services where emulation is
  representative; clearly mark unsupported GPU/USB/CEC behavior untested.
- **Hardware lab:** dedicated spare cards/Pis, not an unattended test on a family
  member's in-use terminal. Programmable power interruption and independently
  collected serial/network evidence for boot failures.
- **Protected signing/publication:** revalidate artifact provenance, role/layout
  compatibility, exact digest and qualification attestation, then sign/publish.
- **Promotion:** update signed stable metadata for cohorts; record promotion and
  withdrawal history. Hardware test credentials remain outside public jobs.

Initial rollout order: internal spare device, designated beta cohort, then stable
devices. Suggested starting soak is 48 hours on canaries and seven days for a new
major baseline, shortened only through an explicit qualified security process.
Health reports can inform promotion without uploading family names or call data.
Failure automatically stops further promotion where observable; already released
signed metadata needs a signed replacement/withdrawal, not deletion alone.

### 12.4 Release downloads and installer replacement

Current publication contains nine human-facing downloads plus two machine app
update assets, enforced by an eleven-file allowlist. Change that contract
deliberately; do not simply attach extra files and bypass validation.

Proposed final user downloads:

| Product | Files |
| --- | --- |
| Terminal | `ZmalaTerminal-Installation.pdf`, `ZmalaTerminal-Guide.pdf`, `ZmalaTerminal-Pi4.img.xz` |
| Server | `ZmalaServer-Installation.pdf`, `ZmalaServer-Guide.pdf`, `ZmalaServer-Pi4.img.xz` |
| Phone | `ZmalaPhone-Installation.pdf`, `ZmalaPhone-Guide.pdf`, `ZmalaPhone.apk` |

This preserves nine user-facing downloads while replacing both SSH `.exe`
installers. If Pi 3 server qualification is retained, choose an accurate shared
artifact name or an additional explicit board variant instead of misleading Pi 4
labels. Historical filenames remain valid on their historical releases.

Additional machine artifacts include role-specific signed `.raucb` bundles,
authenticated feed metadata and necessary trust/checksum/provenance/license
materials. Decide whether to attach them to the same release or a dedicated
immutable system-build release collection. Keep the app-only terminal feed
available for legacy installations during the supported transition. Do not
remove the files that already-deployed application updaters expect.

Measure compressed images and bundles against current hosting per-file limits
before choosing GitHub Releases as their only host. Use sparse/unallocated-space
handling and suitable compression. If an artifact exceeds the limit, use a tested
immutable object host or redesign the artifact; do not make users concatenate
arbitrary chunks as the normal installation experience. Keep image binaries out
of Git history. Avoid signed download URLs that expire before an offline Pi can
resume a transfer.

Raspberry Pi Imager's custom-image route is the baseline Windows/macOS/Linux
installer. Evaluate a custom Imager catalog only after this works; do not create
a new privileged Windows disk flasher without a demonstrated need. Document
whether Imager OS customization is supported, ignored or disabled: ordinary
Raspberry Pi first-run scripts must not overwrite our mount/identity/security
policy or expand the wrong partition.

## 13. Coexistence and migration from today's installations

### 13.1 Application updater transition

On the new appliance images, the RAUC system release owns the application, native
libraries, supervisor and host policies together. Disable the independent
application updater before starting the image-owned application. Keep suitable
maintenance/display/status primitives, but never run two installers with separate
locks against the same software/data.

Legacy SSH installations retain their existing app-only updater and compatibility
policy. The server recognizes installation type/capability and serves the correct
feed. A legacy updater cannot install a RAUC bundle; a new image cannot execute
an app tarball outside its OS slot.

During migration, do not import an old active-code symlink or compiled module from
`/opt/zmalacall-updates` into the new image. Import only validated durable device
state. Mark legacy update transaction paths as historical/imported or omit them
according to the migration format; never let them select code at the next boot.
This prevents OS rollback from loading a newer incompatible application binary.

### 13.2 Terminal migration procedure

1. Inventory identity, language, enrollment, remote pairing, Wi-Fi, TV pairing,
   sound/gain settings, case/USB policy and relevant history.
2. Export a private, versioned migration archive. Provide a normal supported
   workflow or local recovery export; SSH may be a development convenience during
   the transition, not the permanent installation method.
3. Validate the archive, permissions and completeness before shutting down the old
   terminal. Keep an off-device copy; do not depend on the new card holding the
   only backup.
4. Flash a spare card and import through a documented local provisioning medium or
   authenticated onboarding flow. Sensitive files left on a FAT setup volume need
   explicit protection/deletion guidance; deletion is not secure erasure.
5. Boot the new image with the old terminal offline. Verify the same identity and
   account association, remote, network, portraits, settings and TV pairing.
6. Check calls both ways with an app, audio routing/gain, first-video timing,
   callbacks, photo sharing, remote controls and TV restoration/inactivity.
7. Keep the original card untouched until acceptance. Do not power both enrolled
   copies simultaneously; they share device/SIP identity.

### 13.3 Server migration procedure

1. Inventory all application state plus TLS/private keys, renewal accounts,
   SIP/TURN secrets, domain/address configuration, push sender, mail credentials,
   developer-access settings, firewall rules and service ownership.
2. Prebuild/validate the new card and a private full-appliance export. Application
   backup alone is insufficient for restoring every host service.
3. Arrange a short maintenance window. Drain calls and stop mutations before the
   final consistent export. Preserve a recoverable original card and off-device
   backups; do not leave two live servers with the same identity/address.
4. Boot the new card, claim it locally, and validate/import state without exposing
   the server bootstrap publicly. Preserve DHCP/MAC behavior where applicable,
   advertised URL and device tokens so re-enrollment is unnecessary when possible.
5. Verify admin login, account/group/portrait comparisons, device registrations,
   domain/certificate/relay configuration, callback notifications, mail/push and
   secure remote calls. Verify the LAN-only admin and wired SSH boundaries.
6. Confirm that certificate renewal and safe automatic updates are operational;
   a successful fresh certificate is not evidence renewal is configured.
7. If reverting after the new server has accepted writes, reconcile/export the
   latest data before using the old card. The old card is not a license to discard
   new family data silently.

Do not use live partition shrinking or remote repartitioning as the standard
migration. Lost-power recovery during a destructive conversion is a different
problem from A/B system replacement.

## 14. Requirements, traceability and documentation work

### 14.1 Baseline impact review

The existing baseline remains accurate for the implementation shipped today.
In particular, `PROD016` deliberately limits the current feature to application
updates and excludes OS/packages. This plan proposes a replacement architecture;
it does not broaden that record or claim OS coverage prematurely.

During implementation, review these exact existing records/themes:

| Existing records | Review needed |
| --- | --- |
| `PROD013`, `PROD014`, `PROD016` | Persistence/failure recovery, controlled host resource use and distinction between legacy app-only and new system updates |
| `HLR-TERM-MAINT-021/023/025/027/029/031/033` and direct LLRs `022/024/026/028/030/032/034` | Recovery, payload trust, bounded trials, admission, independent updater, data preservation and status; determine what can be generalized and what remains legacy |
| `HLR-SRV-MAINT-021`, `LLR-SRV-MAINT-022` | Terminal system/legacy feed coexistence and maintenance reporting |
| `HLR-TERM-START-001/002`, `LLR-TERM-START-003/004/007` | Boot presentation, single startup owner, durable state and recovery |
| `HLR-TERM-SETUP-019/020/021` and direct LLRs | Resumable onboard setup, QR stage ownership and reset boundary |
| `HLR-TERM-NET-007/008`, `LLR-TERM-NET-006/009` | Wired SSH and controlled developer tunnel on immutable images |
| `HLR-TERM-POWER-008/009` and direct LLRs | No unintended USB wake, supported camera and optional case/USB policy |
| `HLR-SRV-START-001/002/003` and direct LLRs | Server independent startup, controlled shutdown, local liveness/readiness versus system trial health |
| `HLR-SRV-CALL-001/002` and direct LLRs | Whole-appliance call admission/drain, relay ownership and races |
| `HLR-SRV-HOST-001/002/006` and direct LLRs | SSH restrictions, storage policy, developer access and new host maintenance |
| `HLR-SRV-BACKUP-001/002` and direct LLRs | Application backup remains distinct from full host migration; restore/checkpoint compatibility |

Create a product-level system-maintenance item and component HLR/LLR children
for new runtime behavior where needed. Allocate IDs using
`build_tools/requirements.py --next-id <HLR|LLR> <SRV|TERM> <GROUP>`; never guess or
renumber IDs. Keep a single numbering sequence across both levels in each theme.

Add direct LLT plans/assertions for each LLR and direct HLT plans for each HLR.
Maintain reciprocal Doorstop references and standalone `@llr` comments at the
actual owner of policy. Shared code can have component-specific contracts/tests
without duplicating its implementation. New runtime regressions belong in product
LLT/HLT, not `tests/adhoc/`.

### 14.2 Artifact updates by stage

- `docs/general.md`: installation types, ownership, supported hosts, system versus
  application release identity, persistent state and distribution.
- `docs/terminal.md`: image first boot, maintenance adapter, passive health,
  localized progress, TV/USB preservation, update recovery and developer access.
- `docs/server.md`: bootstrap claim, migration inventory, self-maintenance/call
  drain, system/legacy terminal status, relay/TLS service ownership and recovery.
- `docs/android.md`: change only if server compatibility/temporary-maintenance
  responses or published installation links affect the app; Android installation
  and its updater are otherwise unchanged.
- `README.md` and developer guidance: replace normal SSH installer instructions
  when the new route is actually available; keep legacy links clearly labeled.
- `docs/terminal_prep.docx`, `terminal_config.docx`, `terminal_use.docx`,
  `server_prep.docx` and their authoring/build sources: flash the correct card,
  verify it, first-run setup, Wi-Fi QR, server claim, backup/import, upgrades and
  recovery. Update phone guide sources only for affected release links/workflows.
- `build_tools/release/guide_copy.py`, guide generation and setup/enrollment PDFs:
  keep downloadable instructions consistent with the image/bootstrap experience.
- `docs/terminal-update-plan.md` and qualification records: label which evidence
  belongs to legacy application updates and which qualifies system images.

Regenerate affected assets with existing tools. Render and inspect the Word/PDF
guides for readability, screenshots, links and print layout. Do not hand-edit
generated admin bundles. Do not commit `requirements/output/`.

The initial planning/build-tool changes leave current user guides and normative
runtime requirements unchanged because no installed workflow changes yet. Their
future updates are deliverables of the relevant implementation stages below.

## 15. Verification strategy and acceptance evidence

### 15.1 Unit and deterministic integration verification

Add role-linked LLT/HLT coverage for:

- Metadata authentication, source/board/layout/data/protocol compatibility,
  downgrades, key rotation, expiry, wrong clock and signed withdrawal.
- Download limits, digest/length mismatch, redirect policy, partial resume,
  low-space reservation, cleanup and corrupted cache.
- Slot identification, inactive-only writes, boot/root pairing, no block-device
  names accepted from untrusted metadata and no data-partition writes.
- Every transaction transition, stale records, torn/invalid JSON, reboot during
  pending/confirm/rollback reconciliation and exact candidate quarantine.
- Maintenance races with ringing/dial/answer, photo sharing, settings/backup/QR
  work, leases, server restart, stale status and active TURN allocations.
- Trial deadlines, watchdog ownership, restart loops and failure to mark good.
- Snapshot/generation integrity, migration interruptions, old-version readability,
  unknown-field retention, storage errors and no command/notification replay.
- Local status privacy, role authorization, stale state and bounded history.
- Terminal localization and passive TV/USB behavior.
- Server bootstrap claiming, token consumption, access boundaries and no shared
  factory identities/secrets.

Test plans begin with the existing stable `@test`, `@requirements`, `@environment`,
`@plan` and `@pass` comments described in `docs/general.md`. Assertions must match
the stated coverage; skipped hardware checks never become passed system tests.

### 15.2 Image/installation checks outside the product baseline

Keep partition generation, image contents, build determinism, Imager compatibility,
artifact allowlists and publishing/packaging checks under `tests/adhoc/` with an
independent CI step. Preserve existing installer tests while the legacy path
remains supported. Runtime first-boot identity/recovery/security behavior still
receives product LLT/HLT coverage even when exercised from an installed image.

### 15.3 Hardware qualification matrix

Record exact image digest, source commit, package inventory, board revision,
EEPROM version, SD make/capacity, peripherals, test procedure, actual results and
artifacts. Use separate test devices/cards where interruption risks data.

| Area | Minimum physical scenarios |
| --- | --- |
| Factory installation | All three image roles; fresh 32 GB card; minimum measured capacity; flash verification; interrupted first boot; unique identities across two cards |
| Board coverage | Pi 4 supported revisions; Pi 3 server only when explicitly retaining that image support |
| A/B transitions | A→B and B→A; repeated successful upgrades; already staged candidate; no-op release |
| Power interruption | Random and targeted cuts during download, each inactive write, data checkpoint/migration, reboot request, trial boot and selector/confirmation commit |
| Boot failure | Invalid candidate kernel/command line, bad initramfs, service hang, data incompatibility, boot/root mismatch, watchdog reset |
| Storage faults | Full cache/data, failed write/fsync, read-only/corrupt state, missing data mount; no autoformat |
| Network | No WAN, no DNS, captive portal, TLS/clock failure, slow/interrupted download; confirmed calls still available where network permits |
| Terminal behavior | C10 and C20, Presenter+, Argon profile, sleeping USB, off/live-TV/terminal-input states preserved; no update-caused beep/camera wake/source command |
| Calls | App↔terminal and terminal↔terminal; video/audio; incoming while preparing; activation race; callbacks and photo sharing; no call interrupted by maintenance |
| Server behavior | Active SIP/RTP/TURN traffic blocks reboot; all listeners return; TLS renewal, mail/push and admin restrictions survive |
| Major OS transition | Previous baseline→new baseline, failed trial→old baseline, data/config compatibility, bridge release and too-old source rejection |
| Migration | Realistic private export/import, offline original card, consistent identities, rollback with new writes and complete host secrets |
| Recovery | Failed candidate quarantined, rescue/new-card restore, long-offline trust update, withdrawn release and signing-key rotation |

Set a repeat count and randomization method before each campaign; do not select
only favorable runs afterward. A proposed starting selector/power-cut campaign is
at least 100 interruptions per role spread across all critical phases, with
additional targeted cuts at every identified commit window. Zero failures in that
sample is necessary evidence, not proof against every SD-controller failure.

Any unexplained unbootable result stops stable promotion until investigated. A
test interrupted by a missing cable, unavailable TV or unavailable phone is
incomplete, not passed. Never run disruptive tests on term2 merely because it is
reachable; arrange availability, preserve a backup and restore TV/power state.

## 16. Ordered implementation stages

Each stage has a GitHub issue/feature branch/PR as appropriate. Keep changes
reviewable and include the required Android patch/code bump above then-current
`main`, even for documentation work. Open PRs to `main`; merge through GitHub only
after required Verify checks are clean. Do not push or mirror commits onto `main`.

### Stage 0 — Feasibility and safety decisions

- [ ] Inventory shipped OS/boot/host state and service writes for all three image roles.
- [ ] Measure root sizes, data/checkpoint/cache budgets and minimum card capacity.
- [x] Boot a minimal `rpi-image-gen` A/B common-base probe on a spare card in an
      available Pi 4; A → trial B → ordinary A demonstrated. Complete role images
      and interrupted-update qualification remain separate gates.
- [ ] Resolve partition format and stable slot identity.
- [ ] Audit native tryboot backend and establish selector/early-watchdog safety;
      choose an alternative if necessary.
- [ ] Pin RAUC/image-builder versions and confirm required features exist.
- [ ] Decide metadata trust implementation and server first-owner claim flow.
- [ ] Resolve package mirrors/snapshots, build runner and artifact hosting limits.
- [ ] Write explicit acceptance criteria and allocate runtime requirement IDs.

Exit: reviewed architecture decisions and a working boot/rollback prototype;
power-cut weaknesses are resolved or clearly block production. No family-device
migration yet.

### Stage 1 — Common image foundation and artifact pipeline

- [x] Retain authenticated common/role package closures and exact input locks.
- [x] Build and audit isolated locked OS-root archives for both standalone roles.
- [ ] Complete and record the combined OS-root/component build.
- [ ] Complete factory application/host provisioning in the common/role layers.
- [ ] Extract reusable provisioning from current installation scripts.
- [ ] Establish read-only root, selected persistent mounts and low-write policy.
      Shared runtime, early-boot discovery and archive preparation are
      namespace-tested; actual complete-image boot/role enforcement remains pending.
- [ ] Package the common maintenance runtime, units and public trust.
- [ ] Generate and sanitize all three first-install images and slot payloads.
- [ ] Add provenance, notices, public digest/signature handling and ad-hoc checks.
- [ ] Demonstrate reproducible inputs and document remaining output nondeterminism.

Exit: all three image roles flash and boot on spare cards; no shared identities/secrets;
partition and permissions inspection passes; original deployment is untouched.

### Stage 2 — First boot and migration tooling

- [ ] Implement durable per-device initialization and resumable data expansion.
      Identity helper, boot invocation and namespace interruption checks exist;
      complete-image boot, expansion, keys and physical power-loss qualification
      are pending.
- [ ] Reuse terminal remote/camera/Wi-Fi/enrollment stages from the installed image.
- [ ] Implement server local claim, fresh setup and validated migration import.
- [ ] Add selected host-secret/config export/import separate from app backup.
- [ ] Preserve developer SSH restrictions and per-device host keys.
- [ ] Document supported Imager customization, first-run networking and recovery.

Exit: a non-developer can install either role without SSH; interrupted setup
resumes; realistic migration preserves identities and the original card remains
usable. Secure-call configuration is fully accounted for.

### Stage 3 — Signed A/B install, boot trial and rollback

- [ ] Implement role/layout/source/data compatibility checks and trusted feed use.
- [ ] Install only inactive slot groups with durable transaction records.
- [ ] Implement trial boot, bounded health, watchdog integration and confirmation.
      The experimental state/selector/native-backend boundary exists; complete
      loader integration, qualified health/watchdog handover and actual Pi trial
      qualification remain pending. Generic RAUC mark-good cannot bypass health.
- [ ] Implement deterministic recovery for every interrupted state.
- [ ] Implement quarantine, bounded cache/history and supported repair path.
- [ ] Validate normal and interrupted A→B→A transitions on spare hardware.

Exit: the recovery matrix passes deterministic tests and initial physical tests,
including the actual boot-selector commit. No stable automatic rollout yet.

### Stage 4 — Terminal system-maintenance integration

- [ ] Adapt the terminal lease and status protocol for system reboot.
- [ ] Preserve call/setup/held-input/TV-restoration and USB admission rules.
- [ ] Integrate localized progress through shutdown and trial startup.
- [ ] Disable the legacy app updater only on image-managed terminals.
- [ ] Verify calls/video/audio, remote behavior, callbacks and photo sharing.

Exit: all existing terminal behavior remains usable; preparation/activation races
are tested; TV and peripherals are not woken just to maintain the system.

### Stage 5 — Server self-maintenance and mixed fleet support

- [ ] Add authoritative global call/relay/TURN drain and protected-job fencing.
- [ ] Implement safe server trial under local admission fencing.
- [ ] Add read-only server/terminal system status and stale-state handling.
- [ ] Preserve legacy terminal app feeds and identify each installation type.
- [ ] Implement advisory fleet sequencing and signed protocol bridge paths.
- [ ] Verify server outage/reconnection, LAN admin restrictions and secure calls.

Exit: a server updates without interrupting active calls, then reconnects clients
without replayed work; old and new terminal types coexist safely.

### Stage 6 — Major upgrades and full failure qualification

- [ ] Measure combined 32 GB fit, RAM, CPU, thermals and calls under server relay load.

- [ ] Exercise a real different-major-OS candidate, not merely a new package label.
- [ ] Qualify media ABI and host config/network/Bluetooth/TLS migrations.
- [ ] Implement or explicitly reject incompatible data-generation transitions.
- [ ] Complete the physical power-cut, watchdog, storage and long-offline matrix.
- [ ] Test signed withdrawal, trust rotation and rescue/new-card restoration.
- [ ] Record exact hardware/software evidence and close all blocking findings.

Exit: automatic major upgrades and rollback satisfy the declared compatibility
and recovery scope. If a supported path is absent, document the limitation and
keep that source/target pair ineligible rather than declaring the feature done.

### Stage 7 — Distribution, guides and staged migration

- [ ] Update publication allowlists, release notes, download links and feed roles.
- [ ] Ship image downloads, bundle artifacts and verification materials.
- [ ] Regenerate/render/review affected Word guides, PDFs and setup instructions.
- [ ] Run a fresh installation using only the public guide and public downloads.
- [ ] Migrate designated beta hardware on spare cards, retain original cards and
      complete the canary/soak period.
- [ ] Promote stable metadata and monitor first automatic terminal/server updates.
- [ ] Retire normal SSH installer links only after new installation/migration is
      qualified. Keep historical downloads and a stated legacy support window.

Exit: users install without SSH, the release assets are internally consistent,
and the first real fleet updates have supporting evidence.

### Stage 8 — Ongoing maintenance and cleanup

- [ ] Extend daily security intake beyond the standalone Terminal and document
      promotion ownership.
- [ ] Establish end-of-support, CVE escalation and blocked-update reporting.
- [ ] Exercise rescue and key rotation periodically.
- [ ] Remove obsolete installer/runtime paths only after supported legacy devices
      have migrated; keep shared transport used by developer access if needed.
- [ ] Maintain current/previous system and migration compatibility fixtures.
- [ ] Review package roots and retained image/history sizes as dependencies grow.

## 17. Completion criteria

This work is complete only when all of the following have evidence:

1. A user can prepare Terminal, Server and Terminal + Server cards from the published downloads and
   guides without an SSH installation procedure.
2. Installed devices retain unique identities, enrollment, network/pairing state,
   private keys and application data across both update directions.
3. Routine package/security updates and at least one real major OS transition
   follow the signed qualified image path automatically at safe idle.
4. Calls and protected data operations prevent activation; no maintenance action
   terminates a call to meet a scheduling target.
5. Candidate failure, physical power loss and interrupted confirmation recover as
   specified, with boot-selector and early-watchdog limitations resolved.
6. Server and terminal trial checks distinguish local faults from external outages
   and do not wake the TV/camera or start qualification calls automatically.
7. The former app-only updater cannot compete with RAUC on a new image, while
   supported legacy installations continue receiving their correct feed.
8. Trust rotation/withdrawal, bounded history, data migration and rescue restore
   work with recorded tests; no production secret is present in public artifacts.
9. Doorstop, owning `@llr` comments, direct LLT/HLT plans, implementation guides,
   Word/PDF user guides and release download descriptions agree.
10. Required Verify checks, independent installer checks and requirements validation
    pass. Hardware evidence remains separately attributable to the exact tested
    image and environment.

## 18. Reference sources and decisions still to validate

Sources consulted on 4 November 2026. Upstream `latest` documentation changes;
pin the implementation and cite its exact version in qualification records.
The detailed behavior above is the proposed Zmala design, not a claim that these
tools provide the entire solution out of the box.

- [RAUC integration](https://rauc.readthedocs.io/en/latest/integration.html): storage
  bootstrap, slot/bootloader integration and watchdog considerations. RAUC does
  not create the initial SD layout.
- [Using RAUC](https://rauc.readthedocs.io/en/latest/using.html): signed bundle
  creation, service integration and boot confirmation interfaces.
- [RAUC reference](https://rauc.readthedocs.io/en/latest/reference.html): exact
  configuration, slot groups, bundle format, status and D-Bus contracts to validate
  against the selected version.
- [RAUC advanced topics](https://rauc.readthedocs.io/en/latest/advanced.html):
  signature trust, optional transport features and data migration trade-offs;
  shared-data migration is not automatic boot rollback.
- [Raspberry Pi boot configuration](https://www.raspberrypi.com/documentation/computers/config_txt.html):
  native tryboot A/B layout and default/trial boot selection.
- [Raspberry Pi hardware documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html):
  board/EEPROM-dependent boot behavior to qualify.
- [rpi-image-gen](https://github.com/raspberrypi/rpi-image-gen) and its
  [getting-started guide](https://github.com/raspberrypi/rpi-image-gen/blob/master/getting_started.adoc):
  custom image builds and supported host environment.
- [rpi-image-gen slot mapper](https://raspberrypi.github.io/rpi-image-gen/layer/rpi-ab-slot-mapper.html):
  example stable slot-device mapping; not a replacement for maintenance policy.
- [Community native Pi RAUC backend](https://github.com/Rtone/raspberrypi-firmware-rauc-bootloader-backend):
  candidate to audit rather than an adopted production dependency.
- [GitHub large-file distribution guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github):
  validate artifact hosting constraints at implementation time.

Release-blocking decisions: boot-selector power-loss semantics; early-boot
watchdog coverage; measured 32 GB fit; whole-server TURN activity visibility;
metadata freshness/key recovery; secure server first-owner claim; private host
migration completeness; and backward-compatible data behavior for a real major OS
upgrade. Resolve these explicitly during the relevant stages rather than leaving
them hidden behind a successful image build.
