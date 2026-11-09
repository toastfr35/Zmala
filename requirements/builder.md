# Image build specification

The build specification applies to tooling and complements the installed
runtime requirements in Doorstop.

- Pin each application archive by component, version, source commit and
  SHA-256. Verify both the archive digest and embedded package identity.
- Retain the exact dependency inputs used to provision the selected server,
  terminal or combined role. Build and provision in an isolated offline root.
- For an image containing a compatible Terminal, provision the pinned Pi 4
  hub tooling and root-owned USB power helper. Grant the Terminal service
  only the fixed on/off commands and install maintenance-aware shutdown
  restoration. The Terminal retains Always on as its default. A standalone
  Server image shall not provision the Terminal USB power policy.
- Record the retained inputs, image digest, image geometry and qualification
  status alongside every image candidate.
- The hosted Terminal release workflow shall build both slots from reviewed
  package caches and an identified Terminal main commit. Only the separate
  release signing job shall receive the private signing key.
- An optional SD export from the hosted build shall use the same assembled
  Terminal image as the OTA inputs. Verify the partition table and check the
  decompressed digest against the audited image before uploading the archive.
- Preserve firmware-selected onboard Bluetooth UART flow control on Pi 4 when
  the selected slot device tree has the known TX/RX-only pin group.
- Place the primary GPT array at LBA 2 and declare LBA 34 as the first usable
  sector so Windows keeps the primary GPT bootable. Keep the first partition
  and raw boot state at their fixed offsets.
- Require physical boot, enrollment, persisted identity and state, recovery,
  and power interruption evidence for the supported hardware matrix before
  publishing production images.

The [image builder guide](../zmala_images/README.md) describes the commands.
The [image tooling tests](../tests/adhoc/) exercise the build interfaces.
