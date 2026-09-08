# Tentri artwork

Tentri is the portal's visual identity: a mechanical octopus supervising several sources with an interchangeable model cartridge. The Python package, service, API and desktop plugin identifiers remain compatible with existing LogSentinel installations.

The two approved concept sheets, `static/tentri-v1.png` and `static/tentri-v2.png`, are preserved byte for byte. The first supplies the app-icon identity, and the second supplies the horizontal banner's identity.

All artwork is served locally. Visit `/static/tentri-preview.html` to compare and download the originals and the new variants. No model call is involved in switching artwork.

## Assets

Files live in `logsentinel/portal/static/`:

- `tentri-icon-v1.png`: isolated original mascot on an opaque dark teal square, used in the sidebar, sign-in screen and browser icon.
- `tentri-banner-classic-v1.png`: horizontal adaptation of the second concept sheet. This is the default banner, independently of the interface theme.
- `tentri-banner-paper-v1.png`: paper and ink with halftone shading.
- `tentri-banner-tokyo-v1.png`: Tokyo Night pixel art.
- `tentri-banner-gruvbox-v1.png`: warm charcoal, olive and parchment terminal art.
- `tentri-banner-rose-v1.png`: Rosé Pine pixel art.

The Appearance page lets each browser keep the original, choose a particular variant, follow the interface palette, or hide the banner. Hiding artwork does not change monitoring behavior.

## Direction and provenance

Inspired by the typography, terminal culture and theme system of [Omarchy](https://omarchy.org/) and [its themes](https://omarchy.org/themes/), using the palettes already present in this portal. These are original Tentri illustrations, not official Omarchy branding.

Generated and edited with the built-in `imagegen` tool. The exact prompts and references are recorded in [tentri-artwork-prompts.json](tentri-artwork-prompts.json). The first icon attempt painted a checkerboard instead of producing alpha; the final icon deliberately uses an opaque teal background. Original generated files are retained at the tool's output location.

Preserved SHA-256 values:

```text
637af34ee8ef0891f0a44dcb1d447a26283d1d5267555f4c765593aeb65e900e  tentri-v1.png
f33d0b127c494eaebfae1c3363aad17c4b80f1af668f72d64994f28ad63da9df  tentri-v2.png
```
