# LogSentinel and Tentri

**LogSentinel** is the application. **Tentri** is its mascot: a mechanical octopus supervising several sources with an interchangeable brain cartridge. The portal, sign-in screen and browser title use LogSentinel.

The approved concept sheets, `static/tentri-v1.png` and `static/tentri-v2.png`, are preserved byte for byte. The small monochrome silhouette in their bottom-left corner supplies the app mark; the second sheet supplies the horizontal illustrations. The earlier full-color icon is also retained.

All artwork is served locally. Visit `/static/tentri-preview.html` to compare and download every version. No model call is involved in switching artwork or sections.

## Presentation

- The sidebar and sign-in use the monochrome mark in the current theme's foreground color. The PNG is a white-on-black luminance mask, not a transparent PNG. It also serves as the browser and touch icon.
- A compact mascot sits beside the section title. It uses the mascot half of the existing theme banner, displayed through CSS without changing the source image.
- The top socket displays a small SVG cartridge symbol for the current section: a waveform for metrics, lines for event history, a bell for notifications, a chip for model settings, and distinct symbols for the other sections. These are navigation cues; they do not indicate the active LLM or system health. They have no animation and remain decorative to assistive technology because the adjacent heading already names the section.
- Illustrations automatically follow the interface palette. Earlier fixed-palette choices migrate to this behavior; an earlier explicit choice to hide artwork is preserved.
- Appearance offers a browser-local show/hide preference and a collapsed full illustration. The overview starts with monitoring information and statistics, without a large banner.

## Assets

Files live in `logsentinel/portal/static/`:

- `tentri-icon-mono-v1.png`: active monochrome icon, derived from the small silhouette in the second original concept sheet.
- `tentri-icon-v1.png`: earlier full-color icon on opaque teal; retained in the gallery.
- `tentri-banner-classic-v1.png`: original cream and teal horizontal illustration.
- `tentri-banner-paper-v1.png`: paper and ink with halftone shading.
- `tentri-banner-tokyo-v1.png`: Tokyo Night pixel art.
- `tentri-banner-gruvbox-v1.png`: charcoal, olive and parchment terminal art.
- `tentri-banner-rose-v1.png`: Rosé Pine pixel art.

## Direction and provenance

Inspired by the typography, terminal culture and theme system of [Omarchy](https://omarchy.org/) and [its themes](https://omarchy.org/themes/), using the palettes already present in this portal. These are original Tentri illustrations, not official Omarchy branding.

Raster assets were generated and edited with the built-in `imagegen` tool. Exact prompts and references are recorded in [tentri-artwork-prompts.json](tentri-artwork-prompts.json). The first full-color icon attempt painted a checkerboard instead of alpha; its final version deliberately uses opaque teal. The monochrome mark deliberately uses white on black for CSS luminance masking. Original generated files are retained at the tool's output location. Section cartridge symbols are code-native SVG in `branding.js`.

Preserved SHA-256 values:

```text
637af34ee8ef0891f0a44dcb1d447a26283d1d5267555f4c765593aeb65e900e  tentri-v1.png
f33d0b127c494eaebfae1c3363aad17c4b80f1af668f72d64994f28ad63da9df  tentri-v2.png
```
