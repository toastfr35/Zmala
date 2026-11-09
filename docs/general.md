# Zmala engineering

Read the [technical guide](../zmala_images/README.md).

## Requirements and tests

Start with the [requirements guide](../requirements/README.md) for applicability,
implemented boundaries and outstanding verification. The Doorstop records remain
normative; a generated traceability report is not a record of passed tests.

Install Python development dependencies and the pinned Doorstop tooling:

```sh
ZMALA_TMP=/path/to/zmala-workspace/tmp
mkdir -p "$ZMALA_TMP/zmala-dev-temp"
export TMPDIR="$ZMALA_TMP/zmala-dev-temp"
export PYTHONPYCACHEPREFIX="$ZMALA_TMP/zmala-pycache"
export RUFF_CACHE_DIR="$ZMALA_TMP/zmala-ruff-cache"
python3 -m venv "$ZMALA_TMP/zmala-dev"
. "$ZMALA_TMP/zmala-dev/bin/activate"
python -m pip install -r requirements-dev.txt -r build_tools/doorstop-requirements.txt
make requirements
```

`requirements/ownership.json` identifies the authoritative owner of each stable ID.
Imported parents retain their IDs. Update imported copies in a reviewed change
from their owner. Use `python build_tools/requirements.py --next-id LLR COMPONENT GROUP`
for a new ID. Keep requirement text, code references and test references in sync.

Implementation uses a standalone language comment such as
`# @llr LLR-TERM-MAINT-060` immediately before the owning declaration or
cohesive block. Separate multiple IDs with a comma and a space.

A test begins with standalone `@test`, `@requirements`, `@environment`,
`@plan` and `@pass` comments. Link LLT directly to an LLR and HLT directly to
an HLR. State inputs, procedure and expected assertions. Refer to the test from
each Doorstop item. An inventory or a plan does not record an execution.

Run `make lint check test-llt test-hlt test-adhoc` for the repository checks.
On Linux, repeat the Server and Terminal HLT suites with root privileges to
exercise their disposable mount namespaces. Report missing native tools and
hardware skips separately from passes. Keep temporary environments, caches,
logs and test outputs under the workspace's top-level `tmp/` directory; Linux
permission and mount tests require a filesystem with native Linux semantics.

`build-root` explicitly allocates scratch under the isolated builder's `/tmp`
and checks that filesystem's free space; setting `TMPDIR` does not redirect that
part of the build. Use the [builder guide](../zmala_images/README.md) for its
namespace, filesystem and capacity requirements. The network lab writes reports
relative to its checkout, so run it from a disposable checkout under workspace
`tmp/` as described in its [guide](../tests/support/network_lab/README.md).

## Change and release workflow

Use a GitHub issue, a `codex/` branch and a pull request to `main`. Keep the
requirements, code anchors, test plans and documentation synchronized. Merge
through GitHub only after Verify succeeds on the current PR commit. Documentation
updates do not require changing package locks, image versions or signing inputs.

Image and component versions are separate. The checked-in component lock supplies
manual build inputs; the hosted Terminal build identifies its selected Terminal
main commit and retains its package identity. See
[the release workflow](../zmala_images/README.md#standalone-terminal-system-updates)
for the cache pin, signing job and optional SD export. Building or signing an
artifact does not publish it or complete physical qualification.
