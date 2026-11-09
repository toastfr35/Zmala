# Zmala

This repository contains the Zmala SD-card image builder and host platform.

- [Image build and Terminal update guide](zmala_images/README.md)
- [Shared host runtime](zmala_system/README.md)
- [Update protections and recovery limits](safe_upgrade_system.md)
- [Image qualification checklist](sd_card_imager_todo_left.md)
- [Development and requirements](docs/general.md)
- [Reviewed component package pins](components.lock.json)
- [Downloads](https://github.com/toastfr35/Zmala/releases)

The builder supports a native, single-root Server development image and
Terminal/combined development images using the shared A/B storage layout.
Automatic signed whole-system updates are
implemented for standalone Terminals. Server and combined update coordination,
onboarding and production image qualification remain unfinished. A successful
build or signed artifact is not evidence of physical qualification; see the
[requirements guide](requirements/README.md) for the verification boundaries.

The [original system-update plan](update_upgrade.md) preserves dated experiments
and future architecture. Use the current guides above for commands and status.

## Related repositories

- [ZmalaServer](https://github.com/toastfr35/ZmalaServer)
- [ZmalaTerminal](https://github.com/toastfr35/ZmalaTerminal)
- [ZmalaApp](https://github.com/toastfr35/ZmalaApp)
- [Original ZmalaCall repository and historical downloads](https://github.com/toastfr35/ZmalaCall)
