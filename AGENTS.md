# Zmala repository instructions

Use a GitHub issue and a `codex/` feature branch for every change. Open a pull
request to `main`. Wait for Verify and resolve failures before merging through
GitHub. Keep release inputs confined to the release workflow.

This repository owns the SD-card image builder and host platform. Keep code, normative Doorstop items,
standalone `@llr` comments, LLT/HLT plans and documentation synchronized.
Keep runtime requirements in `requirements/`. Keep IDs stable and reserve
numbers across HLR and LLR within each theme. Consult `requirements/ownership.json`
before editing a shared requirement. Coordinate imported copies with the owner.

Run `make requirements` after changes to requirements, code anchors, or test
plans. Do not commit `requirements/output/` or clear suspect links without
review. Product tests go in the top-level `tests/` tree. Keep packaging,
installer and tooling tests in `tests/adhoc/`. Record hardware skips explicitly.

Image builds remain development candidates pending physical qualification. Keep inputs pinned and publish qualified images only.
