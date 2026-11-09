# Appliance image development tools

See [the staged system-update plan](../update_upgrade.md). These tools are
build/deployment tooling, not an installed updater. **There is no production SD
installer or automatic system-update feed yet.**

## Build sequence and ownership

Run commands from the repository root with `python3 -m zmala_images`. The builder
has its own top-level package; old development commands using
`python3 -m build_tools.images` need the new module name. Output/cache paths under
`build_tools/tmp/` remain usable, and committed input-lock bytes are unchanged.

| Stage | Command/module | Result and boundary |
| --- | --- | --- |
| Check reviewed inputs | `check`, `project.py`, `sources.py` | Source pins and base/role lock consistency; no package install |
| Retain external inputs | `fetch`, `lock-base`, `lock-packages`, `application-inputs` | Authenticated OS archives and pinned component packages/dependencies |
| Build package root | `build-root`, `root_build.py` | Locked OS root tar; no application or bootable media yet |
| Add applications | `provision-applications`, `application_build.py` | Offline role-specific application root |
| Add host runtime | `prepare-root`, `image_state.py` | Packages `zmala_system/` policy and role seed into the root |
| Build boot components | `build-initramfs`, `build-loader` | Checked target runtime and pinned loader manifests |
| Assemble development media | `assemble-image`, `image_assembly.py` | New regular-file A/B image plus READY/digest evidence |
| Inspect independently | `inspect-root`, `inspect-disk`, `inspect-bootfs` | Bounded structural/privacy checks, not physical boot qualification |

The [complete application/media walkthrough](#offline-applications-and-development-media)
shows the dependent build order and required digests. Earlier sections describe
individual stages and the smaller `probe-config` experiment; the probe is not
an alternative production image recipe. Each build uses a new output directory.
A READY record is accepted only with independently checked input/output hashes.

Module responsibilities follow the stage names. `*_worker.py` executes inside
isolated Linux namespaces; its parent validates inputs and completion before
publishing READY. `application_inputs.py` accepts bounded file-only archives and
rejects traversal, links, file/parent conflicts and Windows drive/stream or
trailing-dot/space path aliases. Build/runtime policy is deliberately separate:
installed identity, storage and boot admission live in `../zmala_system/` and
are traced to product requirements there. Builder regressions live in
`../tests/adhoc/test_image_*.py` and do not count as runtime verification.

For a fast local check, run `python3 -m zmala_images check`, then
`make test-adhoc`. Linux CI exercises namespace/filesystem cases unavailable on
Windows. No command in this guide qualifies a physical card, TV or power-loss run.

## Current commands

Run from the repository root:

```sh
python3 -m zmala_images check
python3 -m zmala_images probe-config terminal --output build_tools/tmp/terminal-probe
python3 -m zmala_images probe-config server --output build_tools/tmp/server-probe
python3 -m zmala_images fetch imagegen --cache build_tools/tmp/image-sources
python3 -m zmala_images fetch backend_audit --cache build_tools/tmp/image-sources
python3 -m zmala_images fetch bootloader_audit --cache /path/to/new/outside-checkout-cache
python3 -m zmala_images bootloader-config --output /path/to/new/bootloader-profile
python3 -m zmala_images inspect-bootloader /path/to/resolved-build/.config
python3 -m zmala_images inspect-root /path/to/offline/root
python3 -m zmala_images inspect-disk /path/to/uncompressed-probe.img
python3 -m zmala_images inspect-bootfs /path/to/uncompressed-probe.img
python3 -m unittest tests.adhoc.test_image_foundation -v
python3 -m unittest tests.adhoc.test_image_disk -v
python3 -m unittest tests.adhoc.test_image_boot -v
python3 -m unittest tests.adhoc.test_image_bootloader -v
python3 -m unittest tests.adhoc.test_image_eeprom -v
```

Use Linux for source extraction/building. Windows can validate profiles and emit
configurations, but source trees contain Unix symlinks and may fail extraction
without additional privileges. WSL Ubuntu 24.04 is available for development;
native ARM64 remains the preferred eventual image builder. `python3-debian` and
`python3-yaml` are needed for the upstream metadata/configuration command. Full
image generation needs upstream's other build dependencies too.

`sources.lock.json` fixes upstream commit IDs and archive SHA-256 hashes. Fetch
checks the digest before extraction, bounds archive expansion, rejects traversal,
hard links, device nodes and escaping links, and checks the extracted source tree.
It never executes a downloaded script. Destinations must be new; an interrupted
extraction is deliberately not reused. Use a new cache or remove only the known
incomplete extraction directory before retrying. Source-cache changes are not
silently accepted as a new upstream version.

The separately pinned `bootloader_audit` source is U-Boot `v2026.10` at the exact
commit/digest in `sources.lock.json`. Its reviewed archive contains 41,465 members
and 264,670,480 expanded file bytes. Only that source receives larger budgets:
64 MiB compressed, 384 MiB expanded and 50,000 members. The other two sources keep
their 32 MiB / 160 MiB / 10,000-member limits. Individual files remain capped at
32 MiB, and the same path, link, hash and tree-verification rules apply. Cached
archives must be regular files; FIFOs/devices/links are rejected before reading.

`profiles.json` records the common base and role package **intent**, not a complete
resolved package lock. The terminal intent reuses the existing dependency list;
it explicitly includes `wpasupplicant` because the isolated APT intake disables
recommendations. The combined role inherits that dependency. Offline application
validation executes the target supplicant version command and checks its D-Bus
activation/policy files and systemd unit, catching missing backend libraries
before a root is accepted. These packaging checks do not claim a real Wi-Fi join.

Server npm/build dependencies and full secure-relay provisioning remain to be
separated into build/runtime sets. The selected RAUC package is Debian Trixie's
`1.13-3+deb13u1`; its role dependency closures are now retained and reviewed.
Complete builder/toolchain inputs and use of the locks in factory builds still
need to be established before production builds.

The emitted `probe.yaml` is a minimal Pi 4 A/B **boot experiment**. It does not
install Zmala, a bootloader backend, production keys or an update coordinator.
`package-intent.txt` is separate from the minimal probe package list. Its adjacent
`status.json` explicitly records missing package locking, product provisioning,
boot safety and hardware qualification. Nothing here publishes or promotes it.
Probe artifact versions are explicitly `unqualified-<role>-probe1`; they do not
inherit a misleading release version from the parent checkout's Git tags. This
lab label is not a reproducible package/build identity for production.

After fetching, the upstream configuration resolver can check each probe:

```sh
# Replace <commit> with the imagegen commit in sources.lock.json.
build_tools/tmp/image-sources/imagegen-<commit>/rpi-image-gen config \
  build_tools/tmp/terminal-probe/probe.yaml \
  --write-to build_tools/tmp/terminal-probe/resolved.env
```

Build with the emitted project as the explicit source directory, so imagegen
discovers its executable customization hook:

```sh
build_tools/tmp/image-sources/imagegen-<commit>/rpi-image-gen build \
  -S build_tools/tmp/terminal-probe \
  -c build_tools/tmp/terminal-probe/probe.yaml -B /path/to/new/lab-build
```

The project's `layer/zmala-probe-eeprom.d/hooks/customize99-zmala-eeprom-scope`
is a standalone copy of
`eeprom_policy.py`, emitted with Unix line endings. It masks the known
`rpi-eeprom-update.service` in the offline root, before A/B assembly, without
executing systemctl, chroot or firmware utilities. **Do not omit `-S`.** The
configuration requires this project-local layer, so a missing source directory
fails layer resolution instead of silently assembling an unmasked image. The
unqualified upstream probe otherwise inherits the stock EEPROM updater, which
is outside this work's scope. The hook refuses the host filesystem root, linked
policy parents and existing operator overrides; rerunning an existing correct
mask is harmless. Inspect the resulting root before writing any card.

Masking this known OS service is not a full firmware safety audit: inspect the
actual boot payloads too, and never substitute a recovery/EEPROM image for this
probe. It neither upgrades EEPROM nor establishes that an old EEPROM supports
the intended boot path. Existing installed devices are not changed by this tool.

The upstream `image-rota` probe layer uses its own selector partition size and
persistent `/var` policy. Those are acceptable subjects of a boot experiment,
not adopted production storage policy. In particular, its per-slot persistent
package database cannot be reused unchanged across replacement root images.
The custom narrow persistent mounts and qualified selector are still required.

`inspect-bootfs` first validates both GPT copies and the probe layout, then reads
the FAT BIOS Parameter Block in each of the three boot volumes. It rejects
inconsistent geometry, a filesystem larger than its partition, invalid root
directory geometry and FAT tables too small for their data clusters. In particular,
a forced FAT32 volume with fewer than 65,525 data clusters is rejected, even when
its signature and GPT are valid. The private 32 MiB common-loader experiment
exposed that case; use a valid FAT16 footprint there or qualify a larger FAT32
volume. Do not infer the actual FAT type from a volume label or formatting flag.
The command reads regular image files only; it does not flash, mount or repair
anything. Geometry validation does not check file chains, payload signatures,
firmware selection or successful boot. Its result remains explicitly unqualified.

## Read-only deployment inventory

Run the standalone collector on an existing Linux Pi:

```sh
python3 inventory.py --role terminal > terminal-inventory.json
python3 inventory.py --role server > server-inventory.json
```

Use only the appropriate role. It reads fixed OS/package/service/mount facts and
counts selected application/data trees. It does not invoke sudo, restart a
service, access a camera/audio device, scan a network, or request TV/USB power.
The tree walk is bounded and does not follow links or cross filesystems. An
unreadable, missing or partial tree is recorded explicitly. Sizes are allocated
bytes, not the minimum size of a future image.

Keep raw inventory private: host paths and installed software can reveal local
details even though passwords, network addresses, hostnames, MACs, SSH keys and
service environment/command lines are not deliberately collected. Review before
publishing a sanitized summary. A package inventory of a live Pi is evidence of
that installation, not a trusted reproducible package source lock.

## Offline root inspection

`inspect-root` does not mount disks or execute image code. Supply an already
unpacked/mounted **offline** tree. It reports selected factory identities,
passwords, enrollment/imported data and private configuration, plus unexpected
special files, a missing slot-local package database and the known vendor EEPROM
update service without a `/dev/null` mask. Linked policy parents are reported as
uninspectable. It does not read through
symlinked sensitive parents. A passing report covers this privacy subset only;
it always records `production_qualified: false`. A correct EEPROM service mask
does not authenticate arbitrary boot/recovery firmware. It cannot establish boot safety,
all possible secret locations, services, artifact signatures or call readiness.

## Offline probe disk inspection

`inspect-disk` accepts a regular uncompressed image file, never a disk-device
path or symlink. It reads the protective MBR, verifies primary and backup GPT
header/array CRCs and agreement, bounds table allocation and validates the pinned
six-partition probe labels/order, unique partition identities, nonoverlap and
equal boot/root slot sizes. Use `--sector-size 4096` for a 4 KiB-sector image;
the default is 512. It does not modify the image or inspect filesystem contents.
CRC checks detect corruption, not a maliciously signed/unsigned image. Passing
this subset remains explicitly `production_qualified: false` and does not prove
that either system can boot. Future production layout/schema validation is a
separate gate.

## Authenticated package intake and retained closures

On Linux, download a role's package intent into a **new** isolated cache:

```sh
python3 -m zmala_images lock-packages server \
  --output /path/to/new/server-intake \
  --debian-keyring /usr/share/keyrings/debian-archive-keyring.gpg \
  --raspberrypi-keyring /path/to/verified/imagegen/keydir/raspberrypi-archive-keyring.gpg

python3 -m zmala_images verify-packages /path/to/new/server-intake \
  --expected-lock-sha256 <reviewed-lock-file-digest>
```

Use `terminal` for the terminal intent. Supply trusted **public** archive keyrings;
the tool records their hashes and never uses a private release key. Debian and
Raspberry Pi repositories are explicit HTTPS/Trixie sources. APT's state, empty
package-status file, sources, archive cache, configuration and logs are isolated.
`APT_CONFIG` suppresses loading host configuration/hooks before APT initializes.
No package is installed: the only install-subcommand invocation uses
`--download-only`; `dpkg-deb` reads control metadata without running maintainer
scripts. Run as an ordinary user, not with sudo.

The tool verifies signed InRelease metadata, records verified signer fingerprints,
bounds the resolved download count/bytes and checks each retained archive's
SHA-256 against authenticated package metadata. Legacy URI output may include an
MD5 field or omit it; that field is never the authenticity decision. During
archive-key rollover, one valid, unexpired signature from the selected keyring
can coexist with additional unknown signing keys. Unknown-only, bad, expired,
revoked or malformed signature results are rejected.

Keep the accepted lock digest in a reviewed build input. Verification requires
that external digest; a replaced manifest cannot authenticate itself. Retain the
**whole** cache (archives, copied public keyrings, signed metadata and lock file)
immutably. The verifier rejects missing/extra/changed archives or changed audit
metadata. Build from retained bytes after verification, rather than resolving the
same names against today's mirror. APT failure leaves an incomplete directory
without an accepted lock; do not reuse it as a completed intake.

This locks the requested dependency closure only. It does **not** lock every
future image file, build-toolchain/npm/model inputs, provide long-term remote
archive retention or qualify a production image. Those remain separate stages
in the plan. Large downloaded
caches stay outside Git; lock metadata is suitable for review after checking
provenance and policy. Do not publish raw operator logs without review.

Reviewed candidate metadata is retained in `locks/server.json` and
`locks/terminal.json`, anchored by `locks/index.json`. The normal `check` command
rejects dependency intent that has drifted from those reviewed locks, changed
lock bytes, or inconsistent archive counts/sizes. Keep the binary caches outside
Git. A future build must verify its cache using the corresponding reviewed
`sha256` from that index. New intake is a reviewable dependency change, not an
automatic overwrite of the accepted lock.
Git attributes force LF checkout for these content-addressed JSON files on every
platform. Keep those bytes intact; CRLF conversion changes their lock digests.

## Clean-base capture and local build repositories

`capture-base` reads a clean **offline** dpkg status ledger whose SHA-256 the
caller already knows. Review the ledger's image provenance first; a hash alone
does not prove that it came from the selected builder or covers every image file.
Never substitute a live Pi inventory. The parser requires complete installed
records with exact versions and `arm64`/`all` architecture; duplicate packages,
fields, scalar continuations and unfinished package states are rejected. Dpkg's
desired action is distinct from installed state: `purge ok installed` remains an
installed package and is retained. Linked/special/oversized ledger files are
refused before reading. Output creation is exclusive.

```sh
python3 -m zmala_images capture-base /path/to/clean/status \
  --expected-ledger-sha256 <reviewed-ledger-digest> --output /path/to/new/base-intent.json
python3 -m zmala_images lock-base --output /path/to/new/base-intake \
  --debian-keyring /usr/share/keyrings/debian-archive-keyring.gpg \
  --raspberrypi-keyring /path/to/verified/imagegen/keydir/raspberrypi-archive-keyring.gpg
python3 -m zmala_images local-repo \
  --cache /path/to/base-intake <base-lock-sha256> \
  --cache /path/to/server-intake <server-lock-sha256> \
  --output /path/to/new/server-repository
python3 -m unittest tests.adhoc.test_image_base_inputs -v
```

The reviewed capture in `locks/base-intent.json` comes from the selected imagegen
probe's pre-boot ledger. Both original slot ledgers matched. The base lock
anchors the retained authenticated archives in `locks/index.json`. The
scheduled security refresh can resolve newer versions of the captured
package names while retaining the original ledger record.
`check` rejects changed intent/lock bytes, mismatched source commits, inconsistent
counts/sizes or a closure missing a captured package. The raw ledger remains
private. An intake refresh is reviewed explicitly; it never updates an accepted
lock silently. The capture is observed intent, not proof of full build closure.

`local-repo` verifies one to three caches using their **external reviewed lock
digests**, rejects conflicting versions/architectures/content and total budgets,
then copies archives into a new directory. It rehashes copies and uses Linux
`dpkg-scanpackages` to generate an index; package identity, path, size and SHA-256
must agree with the locks. Identical dependencies are deduplicated. Archive
copies are separate files, not hard links into mutable caches. A successful
directory contains `Packages`, deterministic `Packages.gz`, `Release`, a
`build-only.list` and `READY.json`; failures have no READY marker and their
incomplete directory must not be consumed. Simple absolute Linux paths are
required so the source line cannot contain injected APT options.

The source uses `trusted=yes` **only for these verified local `file:` inputs**;
the retained upstream intake remains signed. Do not expose this unsigned
repository over HTTP, put its source in a deployed device, or change host APT
configuration. Keep the generated repository read-only during a build and verify
the original caches again before regenerating it. `READY.json` is a completion
record, not a signature or a continuing integrity monitor. No release private
key is used. Combining the reviewed base with each role produced 312 server and
805 terminal archives. Real isolated, file-only APT download tests consumed all
exact selections for both roles without changing host dpkg state. This proves
local APT consumption, **not yet full image-builder consumption**; `probe-config`
still resolves from upstream repositories and is explicitly unqualified.

## Isolated locked-root construction

`build-root` constructs an **unqualified OS-package root tar**, not an SD image,
slot payload or Zmala installer. It does not install the application, provision
devices, assemble A/B partitions or provide the production mount/update runtime.
Do not flash or distribute the tar as a product release. The host toolchain is
not fully locked yet; an exact package ledger does not make every output byte
reproducible or qualify a complete appliance.

```sh
python3 -m zmala_images build-root server \
  --base-cache /path/to/reviewed/base-intake \
  --role-cache /path/to/reviewed/server-intake \
  --output /path/to/new/server-root-build
python3 -m unittest tests.adhoc.test_image_root_build -v
```

Use `terminal` with its corresponding reviewed role cache for the terminal root.
Both caches must match `locks/index.json`; this command offers no arbitrary lock
digest override. Run as an ordinary Linux user with working subordinate UID/GID
maps, `unshare`, `mmdebstrap` and `dpkg-scanpackages`. Cross-building also needs
configured ARM64 binfmt/QEMU support. The file-mirror hook directory shipped with
mmdebstrap must be present. Namespace/tool failures stop the build. Do not run
with sudo or weaken the host's namespace policy to make an unsupported builder
pass; select an appropriately isolated builder. Keep output on a Linux filesystem
with at least 32 GiB free, and provide that much free space on `/tmp` too: package
copies/caches, the expanded root and output tar can coexist. Full ARM64 emulation is substantially slower than a
native ARM64 build, particularly kernel/module and Python setup.

The command verifies caches and creates a separate local repository containing
only authenticated public package bytes and build hooks. Its scratch directory
is traversable by the build namespace's service UIDs without changing private
cache/home permissions. The repository is bind-mounted read-only. An outer
unprivileged user/mount/network namespace supplies subordinate IDs and no external
network interfaces; mmdebstrap supplies the disposable root/PID isolation. Every
package is requested at its exact reviewed version with a custom empty variant,
file-only sources, no recommendations/suggestions and service starts inhibited
by mmdebstrap. No host APT configuration or installed package state is changed.
The host dpkg database hash is compared before/after, and child termination is
requested if the supervising namespace exits. A failure retains diagnostic
output and never writes `READY.json`.

The standalone build cleanup hook requires a disposable bootstrap marker and
refuses the host root or linked policy parents. It removes generated SSH host
keys, machine/build-host identity, entropy/NetworkManager seeds, copied resolver state and build-only APT
sources/options; all factory account passwords must already be locked. The
package database remains inside the root. Known EEPROM and APT timers are masked
in this experimental root so a later lab boot cannot silently update packages or
EEPROM before those policies are implemented. These masks are not the production
updater or a complete firmware safety audit. The hook is copied with LF endings
even when invoked from a Windows checkout; it is not installed on devices or
offered as an in-place cleanup/migration tool.

Before accepting output, the builder bounds raw tar headers (including extended
headers), member count and expansion, then reads the archive without extraction.
It rejects unsafe/duplicate paths, linked policy parents, wrong selected-file
ownership, unlocked passwords, retained temporary keys/sources, missing masks
and any package-version/architecture difference from the reviewed selections.
This is a selected factory-boundary audit, not proof of every possible secret
location or filesystem property. Success writes `root.tar`, `build.log` and a
`READY.json` with its digest, package count, bootstrap version and explicit missing
application/toolchain/mount-policy/hardware qualification. Keep logs and artifacts
private until reviewed. Retained public scratch inputs are left for diagnosis;
only remove a known inactive build directory after checking its resolved path.

Both role experiments completed under ARM64 emulation with unchanged host dpkg
state: the cleaned server tar contains exactly 312 locked packages and is
765,826,560 bytes; the terminal tar contains exactly 805 and is 2,366,328,320 bytes.
Both retained hashes and the current archive acceptance checks passed. These are
raw tar sizes, not partition-capacity measurements or boot/call qualification.

## Preparing experimental image-managed storage

`prepare-root` consumes a reviewed `build-root` tar and the matching verified
base/role caches. It rewrites a **new tar without extracting or mounting it**:

```sh
python3 -m zmala_images prepare-root server \
  --source /path/to/server-root-build/root.tar \
  --expected-root-sha256 <digest-from-reviewed-root-build-record> \
  --base-cache /path/to/reviewed/base-intake \
  --role-cache /path/to/reviewed/server-intake \
  --output /path/to/new/server-storage-root
python3 -m unittest tests.adhoc.test_image_state -v
```

Use `terminal` and its role cache for that root. The tool checks source bytes,
package versions/architecture and the raw factory privacy subset first. It moves
`/var/lib/dpkg` into `/usr/lib/zmala/slot-dpkg`, moves the remaining `/var` into a
small immutable seed, and inserts the seed's package-db link. Runtime Python
files, the exact fixed role profile and the bounded volatile-journal template are
copied from authored `zmala_system` sources with LF endings. It does not import
operator/device data or create accounts/keys. The original archive is unchanged.

Archive acceptance checks unique canonical paths and real directory parents,
hard-link targets/metadata, ownership ranges, complete runtime bytes, slot package
identity and the variable-state RAM budget. Seed aliases into unlisted `/data`
paths are refused. Incomplete output has no `READY.json`. The success record
includes both root digests and runtime payload hashes, while explicitly keeping
early-boot integration, device initialization, application installation, hardware
qualification and production eligibility false. Retain those boundaries: this
archive is not a ready-to-flash image or update candidate.

The runtime helper is requirement-traced under experimental `PROD017` with direct
server/terminal LLT/HLT plans. Its real mount-namespace integration scenarios use
only temporary ext4 file images; see `docs/general.md`. Build/archive regressions
remain ad-hoc tooling checks. The current SSH installers do not launch this
helper. Experimental same-parent data discovery and initramfs packaging are now
available below; complete role setup, assembled image boot qualification and the
update coordinator remain unfinished.

## Empty factory data and first-device identity

```sh
python3 -m zmala_images factory-data server --output /path/to/new/server-data
python3 -m zmala_images factory-data terminal --output /path/to/new/terminal-data
python3 -m unittest tests.adhoc.test_image_factory_data -v
```

This emits a deterministic `data.tar` containing only a root-owned private data
directory and the role's `.zmala-factory.json` record. The adjacent status explicitly
reports that no device identity exists and data initialization/production
qualification remain false. It never formats, mounts or opens a device. The
archive is an input to future image assembly, not a migration archive.

`prepare-root` also packages `zmala_system.device_identity`. Its Linux-root CLI
accepts `--data` and `--role`, but must only be invoked by boot integration after
the correct separate writable ext4 volume has been validated. It accepts marked
factory data or fully initialized compatible state, never arbitrary existing
data. A nonblocking persistent lock prevents competing initializers. Blocking
kernel entropy supplies a 128-bit machine identifier and derived default hostname.
The helper synchronizes a private staging directory and its files, publishes
identity atomically, synchronizes its parent, then publishes the initialized-data
marker. Retries validate and retain committed identity, including when its final
marker was interrupted; unexpected state is rejected without resetting it.

The helper does not generate SSH keys, expand data, claim the server owner or
start services. Current installers never call it. Direct LLT/HLT plans exercise
both roles, including process exits at eight real synchronization boundaries on
temporary ext4 file images. Those are process-interruption checks, not physical
power-loss or full boot qualification. The experimental early-boot path below now
invokes this helper after validating its data partition.

## Experimental early-boot component

`boot_layout` describes the current experimental six-partition format, not a
frozen production layout. The runtime accepts exactly one `rauc.slot=A` or `B`
and a canonical `root=PARTUUID=...`. It checks the mounted read-only root's kernel
major/minor, GPT entry, filesystem metadata and selected slot, then locates only
partition 6 under that same kernel parent. It does not use a global label lookup
or assume a name such as `mmcblk0`. Missing, ambiguous or mismatched state fails
before data initialization. No filesystem is formatted or expanded.

The helper mounts the validated data, initializes identity, prepares bounded
views, and writes the selected root's read-only mount entry into the RAM `fstab`.
Partial failures attempt reverse owned cleanup and preserve committed identity;
data is retained when dependent views remain. The early entry blocks on failure.
A separate required PID1 gate checks current-boot RAM records, mounted views,
fixed bindings and identity before `sysinit.target`; missing/killed early
preparation does not silently allow ordinary services to start.

`prepare-root` includes these runtime sources, role/policy and PID1 unit/drop-in.
Its data mountpoint must be empty. The root's stock initramfs still needs rebuilding:

```sh
python3 -m zmala_images build-initramfs server \
  --source /path/to/reviewed/server-storage-root/root.tar \
  --expected-root-sha256 <digest-from-prepared-root-record> \
  --base-cache /path/to/reviewed/base-intake \
  --role-cache /path/to/reviewed/server-intake \
  --output /path/to/new/outside-checkout/server-initramfs
python3 -m unittest tests.adhoc.test_image_initramfs -v
```

Use an ordinary Linux user with subordinate UID/GID mappings, user/mount/PID/network
namespaces, GNU tar, mount/chroot tools and configured ARM64 binfmt/QEMU support.
Retained package caches and a reviewed prepared-root digest are required. Keep at
least 32 GiB free. The worker refuses the caller's original namespaces and uses a
new target root; it receives only fixed harmless character devices, not host disks
or USB devices. Temporary target `/var` reconstructs the slot-local package seed;
build `/tmp` and `/run` are bounded RAM mounts. Only root `/dev` entries are omitted
from extraction, preserving kernel driver directories also named `dev`.

The target's own `mkinitramfs` builds the component. Its hook copies the bounded
Python 3.13 tree, ELF extension dependencies and authored runtime, plus fixed
private mount/probe binaries with special permission bits removed. Before invoking
`mkinitramfs`, the worker registers a shell entry in
`/etc/initramfs-tools/scripts/local-bottom/zmala-host`; it delegates to the isolated
Python runtime. The vendor ordering generator resolves source entries and checks
shell syntax, so copying a Python file only into the generated tree is insufficient.
The entry runs in `local-bottom`, before `init-bottom` moves `/dev`. The output audit accepts the
locked extractor's direct or `main` layout, checks exact runtime/tool bytes and
modes, requires exactly one invocation in the generated `ORDER`, and executes
target Python imports and the entry's `prereqs` through the real vendor dispatcher
in the extracted initramfs. `target_dispatch_checked` records that limited check.
No data initialization or ordinary services run during build. Issue #174 records
the first physical boot failure caused by an omitted dispatch entry; earlier
presence/import-only audits do not establish that the entry ran during boot.

`READY.json` appears only after successful checks and worker cleanup. A failed
inspection can retain `initramfs.pending.img` for diagnosis without accepting it.
Outputs explicitly remain incomplete, hardware-unverified and production-unqualified.
This command does not assemble slot boot files, generate a flashable card, install
an updater, publish artifacts or change existing Pi installations. Whole-system
boot/watchdog and power-loss qualification are still separate gates.

## Bootloader probe inputs and configuration audit

`bootloader-config` emits a Kconfig fragment, raw-environment settings and the
watchdog/kernel-handoff examples from `bootloader-profile.json`. It writes only a
new ordinary directory. It does not compile, mount, flash, write raw state or
install a watchdog policy. It deliberately omits `boot.scr`, product health
confirmation and factory provisioning; this output is not a bootable image.
The ordinary `probe-config` still uses the upstream native boot experiment and
does **not** incorporate this candidate automatically.

The profile fences the two 64 KiB environment copies to nonoverlapping aligned
ranges before the probe's first partition. It uses the actual pinned source's
`ENV_REDUNDANT` and MMC index/hardware-partition names and disables FAT storage,
device-tree location overrides and software-partition location overrides. Its
compiled default boot command loads only the local common partition's script.
The watchdog fragment enables the BCM2835 driver, servicing and autostart; its
matching handoff examples bound the kernel's wait for userspace and select PID 1
as the runtime owner. These are experimental inputs, not an installed recovery
contract. Qualify the complete firmware/kernel/initramfs/userspace chain.

Use fresh absolute **Linux** cache/build directories outside any Git checkout,
so an ancestor repository cannot supply an unrelated build version. Work as an
ordinary user in the isolated builder, without signing/deployment credentials.
After acquiring the pinned source and emitting the profile, run from that source:

```sh
make O=/path/to/new-build CROSS_COMPILE=aarch64-linux-gnu- rpi_arm64_defconfig
scripts/kconfig/merge_config.sh -m -O /path/to/new-build \
  /path/to/new-build/.config /path/to/bootloader-profile/probe.config
make O=/path/to/new-build CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
```

Back in Zmala's repository, run `inspect-bootloader` on the resolved `.config`
before compiling with `make -j4 O=... CROSS_COMPILE=aarch64-linux-gnu-`. The
inspector detects missing/discarded settings, legacy-name substitutions,
contradictory state stores and address overrides. It checks a bounded regular
Kconfig file, rejects duplicates, and returns a nonzero status on violations.
A passing subset audit does not prove compilation, source provenance, binary
identity or hardware boot; its result states those limits explicitly.

Record the source commit/digest, resolved config, compiler identity, build log,
binary hash and reviewed source-commit `SOURCE_DATE_EPOCH` together. The complete
host toolchain/dependency closure is not locked by this command. Emitting fixed
settings and pinning source bytes is a step towards repeatable builds, not a
claim of end-to-end reproducibility or production qualification.

## Experimental confirmed/trial boot control

`prepare-root` now packages the exact `boot-control.json` role contract, Linux
state/transport/backend modules, the authored `boot_select.sh`, an executable
`/usr/lib/zmala/bin/boot-backend`, and a PID1 startup watchdog setting of zero.
Role locks retain the authenticated ARM64 `libubootenv-tool` dependency closure;
the observed clean-base inventory is unchanged. The offline GPT audit shares
its bounded parser with runtime admission while still refusing block devices.

The adapter implements `get-current`, `get-primary`, `get-state A|B`, and
`set-state A|B good|bad`. Generic `set-primary` deliberately fails: it cannot
identify a product transaction. Candidate installation must use RAUC 1.13
`activate-installed=false`; the later coordinator calls `stage A|B TRANSACTION`
only after installation, durable transaction recording and safe admission.
`snapshot` returns the fixed boot fields; `confirm TRANSACTION GENERATION`
requires the current consumed trial and exact 16-character hexadecimal
generation. `cancel TRANSACTION` is permitted only on the confirmed system.
The backend neither verifies candidate contents nor decides product health.

The selector clears stale outputs and sets only `zm_selected=A|B` and
`zm_is_trial=0|1`. The payload loader must refuse an empty selection and use
only those fixed slot values. A pending trial gets one attempt, persisted by
`saveenv` before selection. Save failure selects the confirmed system; a later
boot with no attempt remaining falls back without writing. Compiled fallback
environments must contain **none** of the `zm_*` contract fields. Runtime readers
use an empty explicit default file and never initialize corrupt environments.
Factory creation must seed both redundant copies explicitly, retaining the
reviewed loader's unrelated default addresses/settings. The development
`assemble-image` command now performs that seeding in a new regular image file.

Raw access is unavailable on legacy installations. Admission requires complete
current image readiness, a marked exact role contract, the supported Pi 4 SD
transport, selected root/data topology, primary/backup GPT checksums and the
fixed disjoint 64 KiB ranges at 1 MiB and 5 MiB before the first partition at
8 MiB. Root-private generated configuration, a nonblocking lock inode, fixed
tools/keys, bounded operations, complete expected-state comparison and exact
readback protect Linux mutations. No command accepts a device or offset.

LLTs execute the authored selector using POSIX environment-command adapters;
HLTs use actual native Linux environment tools on new regular GPT files in
private namespaces. A separate development check passed 24 decision cases under
the pinned U-Boot hush interpreter, explicitly substituting `saveenv`. The
initramfs build also executes actual target ARM64 environment-tool read/write
operations on new RAM-backed fixture files. These checks do not establish the
combined U-Boot/SD persistence path, actual Pi transport, physical power-loss
recovery, complete boot/root pairing or product health. Full image wiring and
hardware qualification remain required before any system image release.

PID1 must not pet an unhealthy trial indefinitely. Its runtime watchdog remains
disabled until a separate qualified product-health handover. Kernel
`watchdog.handle_boot_enabled=1` and a nonzero `watchdog.open_timeout` can bound
the gap after a loader-armed watchdog; the actual complete image and supported
kernel must qualify that behavior. The final handover can use systemd 257's
writable `RuntimeWatchdogUSec` property, but no backend command invokes it here.
See the [kernel watchdog parameters](https://docs.kernel.org/watchdog/watchdog-parameters.html)
and [systemd 257 manager implementation](https://github.com/systemd/systemd/blob/v257/src/core/dbus-manager.c).
The earlier `bootloader-config` output is a diagnostic probe with its own
watchdog takeover settings, not this product trial policy.

## Source audit decisions

The native Pi backend at the pinned audit commit uses a temporary file and `mv`
to commit `autoboot.txt` (`set_primary_persistent`), without explicit file/directory
sync or a redundant durable selector. Its sample `rauc-mark-good.service` calls
`rauc status mark-good` after `local-fs.target` without Zmala health/data checks.
Neither file is installed by these tools. The backend remains an audited reference
candidate, **not production-qualified**. Physical power-cut behavior, early
watchdog coverage and confirmation recovery remain release blockers.

The exact reviewed upstream files can be inspected from the acquired trees:

- `bootloader-custom-backend` and `rauc-mark-good.service` in the backend source.
- `image/gpt/ab_userdata/image.d/hooks/preimage10-slots` in imagegen, including its
  per-slot `/var` and persistent journal behavior, which differs from Zmala's plan.

The alternative boot-state investigation is tracked in
[#149](https://github.com/toastfr35/Zmala/issues/2). A private U-Boot experiment
has compiled and completed an A/B selection, fallback and manual counter-reset
sequence on a Pi. Further private checks exercised healthy watchdog handoff,
a controlled pre-root stall, one newer-copy CRC fault and one operator power cut
during repeated commits. See the plan for measured scope and remaining gates.
It is not included by `probe-config`, acquired by `fetch`, or
adopted as the production backend. The current source's configuration names differ
from older RAUC examples; validate the resolved settings, not just a fragment.
Source references for that investigation:

- [U-Boot v2026.10 environment configuration](https://github.com/u-boot/u-boot/blob/5508406582f6f7120dce0c4b3059819a41788db2/env/Kconfig).
- [U-Boot v2026.10 Pi ARM64 defaults](https://github.com/u-boot/u-boot/blob/5508406582f6f7120dce0c4b3059819a41788db2/configs/rpi_arm64_defconfig).
- [RAUC 1.13 bootloader integration](https://rauc.readthedocs.io/en/v1.13/integration.html#u-boot).

Deterministic environment-library tests using ordinary files do not demonstrate
physical SD durability, the bootloader's selection, early-watchdog recovery, or
firmware/kernel compatibility. The private hardware checks add initial recovery evidence,
but do not establish the complete power-cut matrix or product health-confirmation
recovery. Those
remain hardware and architecture gates.

The private kernel handoff also exposed low-memory fragmentation: U-Boot's default
placement split the graphics CMA window, leaving too little contiguous memory for
the framebuffer. Setting explicit bounded FDT and initrd relocation ceilings
restored the full pool and HDMI in that experiment. Future image integration must
qualify the complete memory map and payload sizes on supported boards, rather than
copy an address from one Pi. See the implementation log for measured scope.

Experimental runtime requirements and direct LLT/HLT plans cover the implemented
helper boundaries. Supported user installation guides remain unchanged until a
qualified image installation flow exists. Image-tool regressions live under
`tests/adhoc/` and run independently of requirement-based runtime tests.


## Standalone Server factory image

Build a `server` root and provision the reviewed Server package using the
commands below. The Server package selection excludes RAUC after authenticating
the shared locks. Assemble the application-bearing root directly:

```sh
python3 -m zmala_images.server_single --application /path/to/server-application \
  --manifest-sha256 SHA256_OF_APPLICATION_READY_JSON \
  --base-cache /path/to/base-cache --role-cache /path/to/server-cache \
  --output /path/to/new/server-image
```

The 8 GiB candidate uses an MBR partition table, a FAT32 firmware partition and
one writable ext4 root. Pi 4 firmware starts the matched native kernel, device
tree and vendor initramfs. The image keeps the standard signed Debian and
Raspberry Pi APT sources for manual OS maintenance. It has no RAUC package,
update bundle or slot switching. A Pi boot and real Server setup are separate
qualification steps.

## Combined Terminal + Server build inputs

All role-taking build commands also accept `combined`, displayed as **Zmala
Terminal + Server**. Its 52 requested packages are the exact union of the two
standalone intents. The separately retained authenticated closure contains 738
archives; common package identities match the reviewed standalone locks. `check`
rejects conflicting shared versions or hashes. The observed base remains unchanged.
Use the combined cache for `build-root`, `prepare-root` and `build-initramfs`;
never substitute a terminal or server cache or relabel an existing prepared root.
`factory-data combined` emits an empty combined marker without shared identities.

Combined runtime storage uses terminal UID/GID 1000 and server UID/GID 1001,
separate private application and operator bindings, and one host identity and
confirmed/trial boot record. Exact role checks reject standalone data/boot records.
Offline application provisioning now creates the service users and installs both
applications; regular-file assembly supplies a complete development disk layout.
Joint health/admission and hardware boot qualification remain unfinished.
Current installer workflows and release downloads are unchanged; user-guide
changes belong with the eventual qualified installation workflow.

## Offline applications and development media

Images built with a compatible Terminal package install the Pi 4 USB power
helper from that package and enable the service capability. The pinned
Terminal package closure supplies `uhubctl` and `fuser`. The application user
can request only the helper's fixed on/off commands. The service restores power
on shutdown unless an update maintenance fence is active. Always on is the
Terminal's default setting. The standalone Server image does not install the
Terminal USB helper or service policy.

Download the versions in [the reviewed component lock](../components.lock.json)
from [Server releases](https://github.com/toastfr35/ZmalaServer/releases)
and [Terminal releases](https://github.com/toastfr35/ZmalaTerminal/releases).
For another development input set, copy [the lock template](../components.lock.example.json)
and record each package's exact version, release commit and archive SHA-256.
Then retain the packages and their build dependencies:

```sh
python3 -m zmala_images application-inputs combined --components-lock components.lock.json \
  --packages downloads --output application-inputs
```

Choose `server` or `terminal` to use a single component. Intake checks the
archive digest and embedded component identity against the lock. It retains the
public npm archives named in the v3 lock and checks their SHA-512 integrity
without running npm lifecycle scripts. Terminal intake retains the two TURN SDK
source files against their source pins. Downloads occur during input intake.
The resulting `READY.json` records each component identity and the digest
needed for offline provisioning.

After `build-root`, run `provision-applications ROLE --source ROOT_TAR
--expected-root-sha256 SHA256 --applications APPLICATIONS_TAR
--expected-applications-sha256 SHA256 --base-cache BASE --role-cache ROLE_CACHE
--output NEW_DIR`. Like the root/initramfs builders, this needs an ordinary Linux
user with subordinate UID/GID namespaces and ARM64 binfmt support on x86 hosts.
The worker has separate network, mount, PID and user namespaces. It installs
existing application service templates declaratively, compiles the native
video/audio/TURN libraries, runs the TURN regressions and checks target imports
and the systemd unit graph. The terminal core also starts, iterates and closes
under its service UID with deferred media and throwaway RAM data. Server builds
start target Node under the service
UID on isolated loopback, check `/ready` and bootstrap publication, and discard
all smoke-test data from a temporary RAM filesystem before packaging.

Terminal and combined appliances always use the Argon ONE Pi 4 V2 case.
`provision-applications` automatically enables the existing call-only fan
controller, adds the terminal to the I2C group, loads `i2c-dev` and restricts bus 1
access to that group. There is no optional case flag. Assembly requires this root configuration
and applies `i2c_arm=on` with the locked target `dtmerge`, verifying the bus 1
alias is enabled in the resulting slot tree. Both slots use that tree; firmware
configuration receives the same parameter. The hardware configuration is recorded
in both application and image manifests. Missing or disabled Argon configuration
in a terminal/combined root is rejected. Server-only images do not enable this
fan controller. No vendor power daemon is installed.
Physical idle/call/hangup fan transitions still require hardware qualification.

Combined releases have separate `/opt/zmalacall` and `/opt/zmalacall-server`
source trees. The server's sibling terminal-bootstrap path points to its own
private `bootstrap` directory, never the terminal's application state. All roles
use NetworkManager; the server intent/lock includes it explicitly. Ordinary SSH and legacy
application updaters are masked. Secure relay/TLS onboarding and first-owner
claim are not supplied by this development provisioning path.

### Appliance update discovery

Standalone Terminal roots package a systemd timer at local midnight. The
boot trigger catches up after a missed day. The root-owned record at
`/data/host/update-discovery/status.json` prevents duplicate checks across
reboots. The Pi's time zone determines when midnight occurs.

The service requires the approved public RAUC certificate chain in
`zmala_images/system-update-keyring.pem` at build time. The builder installs
it at `/usr/lib/zmala/system-update-keyring.pem`. Release signing keys belong
in the release workflow. The timer skips checks until the public chain is
provisioned. The checker verifies the opposite-slot bundle with RAUC 1.13.

An image release combines the OS and Terminal application. Use separate
`ZmalaTerminal-System-A.raucb` and `ZmalaTerminal-System-B.raucb` assets to
preserve distinct filesystem labels. An application-only change advances the
image release version. Bundle metadata also records the Terminal version.
Prepare the two unsigned bundle inputs from an audited regular image and an
reviewed digest of its `READY.json`:

```sh
python3 -m zmala_images.system_bundle --image /path/to/image-directory \
  --manifest-sha256 REVIEWED_READY_SHA256 --output /path/to/new-bundle-inputs
```

The release job signs each input with RAUC verity. Each input includes just
its matching boot and root filesystems. Discovery records verified metadata.
Settings integration, idle admission, trial health confirmation and hardware
rollback qualification remain prerequisites for automatic activation.

### Developer Access

Developer Access has separate service units. Preparation creates a unique host
key after persistent storage mounts; generic artifacts contain neither host keys
nor operator login credentials. The terminal shell binds only to loopback and
accepts the `zmala` operator password generated for the active Server session.
The Terminal's root helper obtains the verifier over HTTPS and pins the first
approved enrollment to the device. The operator has diagnostic sudo privileges
and the application can request a refresh or stop Developer Access. A fresh
Server approval starts the shell and tunnel after boot. Disabling access stops
both and clears the Terminal operator password. Server activation
state is retained privately, with the restricted tunnel password restored after
reboot only from a valid activation. Combined hosts distinguish the service
callers. Ordinary port 22 remains closed; generic server-image operator entry and
onboarding still need a supported path before distribution.

Generic images start with the operator account locked and generate their SSH
host keys on first boot.

The application worker executes the installed ARM64 SSH configuration in its
private network namespace, with throwaway keys and RAM storage. It checks operator
authentication, password rotation, credential revocation and connection
failure after listener shutdown. This does not exercise a real server-admin
enable/disable exchange or qualify physical network behavior. The terminal and
combined roots also select the Zmala Plymouth theme. Initramfs acceptance verifies
the retained theme, artwork and script plugin; their U-Boot command line requests
quiet splash rendering. Physical logo visibility still needs a card boot.

Pass the resulting application root through `prepare-root`, then
`build-initramfs`. `build-loader --output NEW_DIR` acquires the pinned U-Boot
source, compiles the Pi 4 ARM64 loader and host `mkimage`, and audits resolved
configuration plus compiled defaults. Its compiled fallback must have no `zm_*`
state. Toolchain freezing remains incomplete.

`assemble-image ROLE --source PREPARED_ROOT_TAR --expected-root-sha256 SHA256
--initramfs INITRAMFS_DIR --initramfs-manifest-sha256 READY_SHA256
--loader LOADER_DIR --loader-manifest-sha256 READY_SHA256
--base-cache BASE --role-cache ROLE_CACHE --output NEW_DIR` writes only new
regular files outside the checkout. Supply independently retained digests for
the root and both component READY manifests. It rejects an OS-only root or an
initramfs belonging to a different role/root. No command accepts a device path,
flashes a card or alters a running Pi.

The image version comes from [VERSION.json](../VERSION.json) independently of
the component versions. The candidate `READY.json` records that image version
and the exact application component identities.

The six GPT partitions are 32 MiB common FAT16, two 512 MiB FAT32 boot slots,
two 4 GiB ext4 system slots and 4 GiB ext4 factory data, preceded by the fixed
8 MiB boot-state gap. Each slot has its matched kernel, checked initramfs and
Pi 4 device tree. The locked target `dtmerge` applies the Pi-specific KMS overlay;
generic `fdtoverlay` cannot substitute for Raspberry Pi dormant-fragment handling.
The pinned loader copies firmware fixups into the selected slot's tree. The boot
script also adds the onboard Bluetooth RTS/CTS pins when the Pi firmware enables
them and the slot tree still contains the known TX/RX-only group. Confirm
Bluetooth initializes and a remote can pair on the affected Pi 4 revision before
qualifying the image. Initial factory state explicitly confirms A in two
CRC-protected raw environment copies;
the compiled fallback cannot fabricate it. Factory data is mode 0700 with a
mode-0600 role marker and no device identity. Data expansion is not implemented.

The default compact image is 14,001,635,328 bytes, intended for 16 GB and 32 GB
cards whose measured capacity is at least that value. The primary GPT array
starts at LBA 2 and the first usable LBA is 34 so Windows GPT recovery leaves
the array pointer valid. The first partition still starts at 8 MiB. The boot
gate also accepts and preserves the legacy first usable LBA of 2048.
New prepared roots carry
the immutable `compact-fixed-data-v1` policy. Before device identity is created,
early boot validates the Pi 4 onboard SD parent, kernel root/data extents and
UUIDs, fixed six-partition layout and factory data. It moves backup GPT metadata
to the actual card end, commits the primary header and protective-MBR length,
and synchronizes/read-checks each write. It never changes partition extents or
filesystems; space beyond the fixed data partition remains unallocated.
Interrupted metadata commits require the intact original GPT pair or a complete
new backup matching the unchanged primary partition array. Initialized media
requiring repair is refused. Once consistent, repeated boots do not write GPT.
The native tests cover sparse 16 GB/32 GB files and simulated interruption; they
do not qualify physical power loss, firmware boot or Bluetooth operation.

`--media-bytes EXACT_CAPACITY` remains available for an exact-capacity development
candidate. The result records `required_device_bytes`, `factory_gpt_relocation`
and the fixed `data_partition_bytes`; `automatic_media_expansion` remains false.
Older prepared roots without the compact policy retain their existing behavior.
Rebuild prepared roots and initramfs together; changing only image dimensions
does not add this early-boot adaptation to an old root.

Disposable copies of the existing 0.3.91 system filesystems were shrunk to 4 GiB
and passed full filesystem checks for all roles. The combined role retained
1,675,853,824 bytes free. New application/OS inputs must still be measured and
checked; this result is not a minimum-size guarantee for future updates.

The assembler bounds the uncompressed ARM64 Image to 32 MiB at `0x00080000`,
initramfs to 48 MiB at `0x02100000`, and expanded device tree to 2 MiB at
`0x05600000`. It checks FAT payload readback, ext4 marker content/ownership,
partition-copy extents, GPT/boot geometry and the final image digest. These
checks do not prove firmware, graphics/CMA or physical boot compatibility.
The development confirmed/factory path stops the loader watchdog. A trial keeps
it armed with the kernel's 60-second userspace-open limit. The standalone
Terminal checks native and UI health within that window, confirms the slot,
and reboots into normal operation. Server and combined trial health, watchdog
handover and physical qualification remain release gates.

Allow at least 32 GiB free scratch space per active builder, plus retained
outputs. On WSL, check free space on the Windows volume holding the VHD as well
as Linux `df`: the virtual capacity can exceed physical free space. Keep the VHD
on a sufficiently large volume before starting concurrent builds. A failed build
has no READY marker; preserve its log and use a new output directory after repair.

## Standalone Terminal system updates

Run **Build and sign Terminal system update** on `main` to build the ARM64
Terminal from its current main commit, or specify an exact commit on that
branch. The workflow verifies the retained OS package caches, builds the root,
application, loader and initramfs, assembles the image and packages both slots.
The separate signing job uses the release environment key and uploads
`signed-terminal-system-bundles` with both RAUC bundles and their SHA-256
checksums. The unsigned artifact includes the image `READY.json` for review.
Routine Terminal RAUC releases use the repository's Verify checks and the
build and signing audits as their release gates. Factory SD images and the
boot platform have their own physical qualification plan.

The hosted build uses the pinned package cache asset in
[`terminal-build-cache.json`](terminal-build-cache.json). **Refresh Terminal
OS security locks** checks the signed Debian Trixie security index each day.
A newer security version for a package in the Terminal build triggers APT
resolution across the base and all roles that share it. The workflow pins
the refreshed cache in a build-input draft, increments the system patch
version and stages the lock changes on a review branch. If GitHub permits
Actions to open pull requests, the workflow opens one. The run summary has
the comparison link when a maintainer needs to open it. Review and merge
after Verify passes. A change to the cache pin on main starts the system
build and protected signing job.

The same draft retains `ZmalaServer-Combined-Package-Caches.tar` for the
other refreshed role locks. Use `python3 -m zmala_images.terminal_build_cache
unpack --server-and-combined ARCHIVE OUTPUT` from the matching checkout to
verify and restore them. The base cache is in the Terminal archive.

For other package lock changes, pack the matching retained caches and upload
the archive to a draft used only for build inputs:

```sh
python3 -m zmala_images.terminal_build_cache pack BASE_CACHE TERMINAL_CACHE ZmalaTerminal-Package-Cache.tar
sha256sum ZmalaTerminal-Package-Cache.tar
```

Update the draft ID, asset ID and digest in the cache pin through a PR.
Only the reviewed public package archives, keyrings, signed repository metadata
and lock files go into this archive. Keep the draft and pinned asset available
for future builds.

The image embeds the public RAUC certificate in `system-update-keyring.pem`.
Every day at local midnight the host looks for a newer signed appliance
release, with a catch-up check after boot. Settings → Updates checks on demand
and offers immediate installation. Both paths wait for a safe maintenance
acknowledgement. Immediate installation skips the ordinary idle interval.
The updater installs the matching inactive boot and root pair, verifies both
partition hashes, and records a single trial attempt. The trial uses disposable
native-probe state and read-only persistent application state.

Prepare unsigned input pairs with `python3 -m zmala_images.system_bundle`
using the audited image and its recorded READY digest. Archive each slot
separately from its directory using GNU tar's `--sparse` option and Zstandard
compression. Include only `manifest.raucm`, `boot.vfat` and `root.ext4`.
Stage the archives on a GitHub draft release as
`ZmalaTerminal-System-Inputs-A.tar.zst` and
`ZmalaTerminal-System-Inputs-B.tar.zst`. Dispatch **Sign Terminal system updates**
from main in `sign` mode with the draft ID and both archive SHA-256 digests.
The workflow checks the matching release environment secret and returns signed
workflow artifacts for review. After Verify and the signing audit pass, publish both
`ZmalaTerminal-System-A.raucb` and `ZmalaTerminal-System-B.raucb` on the same
latest release. Keep the signing key in the main-only release environment.

## Test a Terminal package through Developer Access

Use the existing operator SSH tunnel on a standalone A/B Terminal. Enable
Developer Access for the enrolled Terminal and sign in as `zmala` with the
password shown in the Server admin dialog. Read
`host/ssh/ssh_host_ed25519_key.pub` on the initialized card to pin the fresh
card's SSH host key on your workstation. Deployment requires a running stock
Terminal and system update coordinator.

Build the ARM64 package from the Terminal checkout with
`python3 build_tools/linux/package-terminal.py --output ../tmp/ZmalaTerminal-test-linux-arm64.tar.gz`,
or use the package and SHA-256 from a Terminal Verify run. Set `digest` to the
first field of the package's `.sha256` file. From the image-builder checkout,
use an executable wrapper that forwards its command arguments and standard input
to the authenticated Pi SSH session without allocating a terminal.

```sh
python3 -m zmala_images.terminal_test --ssh /path/to/operator-ssh deploy \
    ../tmp/ZmalaTerminal-test-linux-arm64.tar.gz --sha256 "$digest"
python3 -m zmala_images.terminal_test --ssh /path/to/operator-ssh status
python3 -m zmala_images.terminal_test --ssh /path/to/operator-ssh restore
```

For an OpenSSH host alias, use `--ssh-arg=terminal-dev` in place of the wrapper.
Close Settings and let calls, setup and pending device operations finish
before deploying. The tool checks the package on both ends and uses the normal
Terminal maintenance acknowledgement before switching. A test version can
include Python, assets and TV plugins. It reuses the installed native libraries,
so a change to the native build inputs requires a system image build.

The test service runs for up to 30 minutes and uses a separate RAM copy of the
Terminal profile, including the existing enrollment and TV settings. Restoring
the stock service discards test configuration changes. The stock service also
returns after the test exits, the Developer Access shell stops, or the Pi
reboots. Test logs are available with
`sudo -n journalctl -u zmalacall-terminal-test.service` in the operator shell.
The OTA settings are unavailable during the test session. Use **restore** to
return to normal operation before trying a second package.

## Next-image acceptance contract

These are image packaging and test-delivery gates, kept outside the normative
runtime baseline in `requirements/`. A candidate is ready for the next physical
test only when all applicable gates are evidenced for its final artifact:

- Build terminal and combined profiles with mandatory Argon ONE Pi 4 V2 support,
  including I2C ownership, module loading and matching firmware/slot settings.
  Preserve the call-only fan controller; qualify actual fan transitions on the Pi.
- Use the compact 14,001,635,328-byte layout for both 16 GB and 32 GB cards,
  check the actual target capacity, and rerun first-boot GPT relocation and
  repeat-boot checks against that candidate. Record filesystem allocations and
  free space; leave excess card capacity unallocated until expansion is designed.
- Include permanent Wi-Fi supplicant activation, QR guide colour feedback and
  specific safe setup errors. Do not depend on earlier RAM repairs. Require
  Bluetooth pairing and remote operation on a cold boot. A private full-firmware
  device-tree workaround can be labelled as a development-only test adjustment,
  but cannot qualify production A/B tree compatibility; retain the original
  script and record the adjusted artifact's hash separately.
- Include the Plymouth artwork, theme and required initramfs plugin, with quiet
  splash arguments in the actual U-Boot command path. Check the visible logo on
  the Pi; configuration presence alone is insufficient.
- Keep ordinary SSH disabled and temporary Ethernet diagnostic services absent.
  Include the Server-triggered Developer Access helper and isolated units.
  Check password authentication for `zmala`, rotation on a new activation,
  revocation and listener shutdown. The Server tunnel account must reject shell,
  command and subsystem sessions and limit forwarding to its fixed loopback port.
  Confirm real Server-admin enable, login, disable, failed reconnection and reboot
  behavior on the target hardware.
- Retain source/version, package locks, component READY digests, final raw and
  compressed hashes and byte sizes. Verify both boot slots and filesystem
  payloads after any private adaptation. Deliver the artifact, checksum and
  Raspberry Pi Imager custom-image instructions for the user's manual flash;
  the agent does not write the physical card. The user must confirm storage
  selection and actual capacity before writing, then complete Imager verification.

The emulator cannot qualify the operator's real setuid elevation. The build checks
sudo policy, ownership and setuid mode; the physical controlled-tunnel check must
also run `sudo -n id -u` and obtain `0` before declaring debugging access usable.

Runtime traceability: QR capture/errors are `LLR-TERM-SETUP-027/028/029`, fan
control is `LLR-TERM-POWER-011`, boot presentation is `LLR-TERM-START-004`,
Developer Access is `LLR-TERM-NET-009` and `LLR-SRV-HOST-007`, and compact media
admission is `LLR-TERM-MAINT-058` and `LLR-SRV-HOST-031`. Their direct LLT/HLT
plans remain the source of runtime verification scope. See the
[remaining-work checklist](../sd_card_imager_todo_left.md) for physical and release
gates; an accepted development artifact is not a production image release.
