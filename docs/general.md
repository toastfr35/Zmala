# Zmala engineering

Read the [technical guide](../zmala_images/README.md).

## Requirements and tests

Install Python development dependencies and the pinned Doorstop tooling:

```sh
python3 -m venv .venv
. .venv/bin/activate
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
