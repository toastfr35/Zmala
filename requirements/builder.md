# Image build specification

The build specification applies to tooling and complements the installed
runtime requirements in Doorstop.

- Pin each application archive by component, version, source commit and
  SHA-256. Verify both the archive digest and embedded package identity.
- Retain the exact dependency inputs used to provision the selected server,
  terminal or combined role. Build and provision in an isolated offline root.
- Record the retained inputs, image digest, image geometry and qualification
  status alongside every image candidate.
- Require physical boot, enrollment, persisted identity and state, recovery,
  and power interruption evidence for the supported hardware matrix before
  publishing production images.

The [image builder guide](../zmala_images/README.md) describes the commands.
The [image tooling tests](../tests/adhoc/) exercise the build interfaces.
