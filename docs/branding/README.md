# Zmala logo pack

A1 is the main Zmala brand. A3 is the compact phone app mark.

## Files

PNG contains 18 exports:

- A1 with the Zmala wordmark, on light and dark backgrounds, at256,512 and1024pixels wide.
- A1 without the wordmark, on light and dark backgrounds, at256,512 and1024pixels square.
- A3 without text, on light and dark backgrounds, at256,512 and1024pixels square.

Wordmark exports preserve the master aspect ratio; exact dimensions are in sizes.json.
Masters contains the six full-resolution PNG masters.
Preview.png compares all six versions. Android-mask-preview.png shows the dark app icon under square, circle and rounded-square masks.

## Recommended use

Use A1 for the website, terminal, administration and documents. Choose the light or dark version to match its surroundings.
Use A3 on a consistent dark navy background for the phone app. It keeps the purple/green mark readable on both light and dark home screens. The light app version is supplied for comparison.
App exports have no wordmark or pre-rounded outer corners and include padding for launcher masks. These are artwork exports, not an installed Android adaptive-icon resource set.

These variants retain the white Z within the mark. Light backgrounds use a dark wordmark; dark backgrounds use a near-white wordmark.
The intended palette is navy #172033, lavender #AA91F0 and mint #55BA91. Generated masters retain subtle raster shading from the approved drafts.

Generated using the built-in image tool from the approved A1 and A3 drafts. generation-prompts.json records the six edit prompts. PNG exports were resized from those masters without redesigning the artwork.

These approved assets supply the shared runtime branding. Run `node build_tools/create-product-icon.cjs` after changing an approved PNG; use `--check` to verify the derived runtime copies. A1 dark supplies terminal and server marks and in-app Android branding; A1 light supplies installer and document marks. A3 dark supplies the Android launcher foreground. The runtime SVG embeds its PNG so the existing favicon URL stays self-contained. App signing and package identity are unchanged.
