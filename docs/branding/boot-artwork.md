# Terminal boot artwork

The Terminal package asset `zmala_terminal/common/assets/boot-family.png` retains
the family word cloud and uses the approved A1 mark at its centre.
Its source belongs to the ZmalaTerminal repository. Zmala's offline application
provisioning installs the packaged artwork and Plymouth theme into Terminal and
combined roots; the initramfs build checks the retained theme, artwork and plugin.

It was edited with the built-in image-generation tool. The edit prompt was:

> Replace only the old central speech-bubble logo with the approved A1 symbol:
> purple upper-left bubble, mint lower-right bubble and strong white Z, without
> the wordmark. Keep the same placement and approximate scale, the dark rounded
> panel, all surrounding multilingual family words, their positions and subdued
> colours, the dark background and landscape composition. Add no words or
> other changes.

The legacy Terminal installer also installs the artwork. Legacy application-only
updates do not rebuild boot files, whereas a whole-system Terminal bundle replaces
the matched boot/root pair and can include updated artwork.

The boot-version helper reads the legacy updater's confirmed release metadata
and sends `Zmala vX.Y.Z` to Plymouth when that metadata is available. Missing
metadata or an unavailable splash does not block startup; do not assume that
every image-managed boot displays a version overlay. Visible artwork and text
must be checked on the actual candidate. Version text does not alter the PNG.
