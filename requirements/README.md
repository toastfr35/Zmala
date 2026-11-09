# Requirements and verification

The Doorstop YAML records are the normative runtime requirements. The
[builder specification](builder.md) covers image tooling. This guide explains
their scope and evidence; it does not add runtime obligations or record a test
execution.

## Reading the baseline

- Product records describe the intended capability. HLRs define its observable
  behavior within a stated boundary; LLRs define the implementation contract.
- `active: true` and `scope: Experimental` do not mean implemented, tested or
  qualified. Read each record's preconditions and exclusions. The experimental
  image-managed policies do not automatically apply to legacy installations.
- The `verification` field describes the acceptance work required. A reference
  to a test, an `@llr` anchor or a complete traceability report does not prove
  that every clause was exercised or that a test passed.
- [ownership.json](ownership.json) identifies the authoritative repository.
  Keep stable IDs and update paired Server/Terminal requirements together when
  they describe the same host behavior. The combined-role extensions apply to
  both components; they do not permit conversion of standalone saved state.

## Implementation and evidence boundaries

This is the scope reviewed in November 2026. Execution results belong in the
change's verification record, with its exact commit and environment.

| Requirement area | Implemented boundary and automated checks | Evidence still required |
| --- | --- | --- |
| Storage, identity and startup: HLR-SRV-HOST-008/013/017; HLR-TERM-MAINT-035/040/044 | Fixed persistent bindings, fresh RAM views, durable identity and startup gating; LLTs and Linux namespace HLTs | Physical first boot, restart and power interruption on supported hardware |
| Boot control: HLR-SRV-HOST-022; HLR-TERM-MAINT-049 | Confirmed/trial transitions, redundant environment tools and authored selector under a shell adapter | Actual U-Boot execution, Pi transport, watchdog and physical power-loss qualification |
| Combined role: HLR-SRV-HOST-028; HLR-TERM-MAINT-055 | Shared host identity and boot role with separate component state; actual UID and mount isolation in fixtures | Joint application health and coordinated maintenance; full combined-appliance qualification |
| Compact media: HLR-SRV-HOST-030; HLR-TERM-MAINT-057 | Fixed extents, GPT relocation and interrupted-write retries on regular-file fixtures | Supported real card capacities and physical interruption recovery |
| Terminal discovery: HLR-TERM-MAINT-059 | Calendar expression, persisted-date logic and release-selection fixtures | Native trust checks in an equipped environment and a running-device check; mocked metadata is not a signed bundle |
| Terminal installation and trial: HLR-TERM-MAINT-061/063 | Coordinator simulations, transfer-progress checks, service-graph inspection and a conditional native signature test | Direct acknowledgement authentication, actual installer/device/readback failure paths, executed native/UI trial health and end-to-end physical qualification |

[PROD017](product/PROD017.yml) remains the intended whole-system update capability
for Pi Terminal **and Pi Server**. The implemented discovery and coordinator
currently accept only a standalone Terminal. Server and combined host-storage
support does not establish automatic Server updates or joint maintenance.
Those capabilities and qualification remain unfinished; retain the product
requirement rather than narrowing it to the implemented subset.

The linked [coordinator LLT](../tests/terminal/LLT/test_update_coordinator.py)
substitutes admission and installation and supplies simulated health. Its
injected installer exception checks the coordinator's reaction, not partition
readback. The [system-update HLT](../tests/terminal/HLT/test_system_update.py)
inspects packaged configuration and, when tools are present, checks a native
signature example. Neither is an executed full update flow. The verification
fields in LLR-TERM-MAINT-062/064 describe the additional acceptance cases needed.

## Recording verification

Run `make requirements` after editing records, code anchors or test plans. Use
the commands in [the engineering guide](../docs/general.md) for the applicable
tests. The generated `requirements/output/` report is disposable and must not
be committed. Do not clear suspect links without reviewing the changed parent.

Record the source commit, checks executed, environment, passed/failed/skipped
results and any simulated dependencies. A skipped root, native-tool or hardware
test remains missing evidence until it executes successfully. Keep structural
inspection, simulated behavior, native integration and physical qualification
distinct. Image assembly and signing do not qualify a production SD image;
[builder acceptance](builder.md) and the
[qualification checklist](../sd_card_imager_todo_left.md) retain that boundary.
