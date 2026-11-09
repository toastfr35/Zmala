# Zmala engineering

Read the [technical guide](../zmala_images/README.md).

## Requirements and tests

Start with the [requirements guide](../requirements/README.md) for applicability,
implemented boundaries and outstanding verification. The Doorstop records remain
normative; a generated traceability report is not a record of passed tests.

Install Python development dependencies and the pinned Doorstop tooling:

```sh
ZMALA_TMP=/path/to/zmala-workspace/tmp
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
`# @llr LLR-TERM-REMOTE-016` immediately before the owning declaration or
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
