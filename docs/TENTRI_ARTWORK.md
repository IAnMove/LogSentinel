# LogSentinel and Tentri

**LogSentinel** is the application. **Tentri** is its mascot: a mechanical octopus supervising several sources with an interchangeable brain cartridge. The portal, sign-in screen and browser title use LogSentinel.

The approved concept sheets, `static/tentri-v1.png` and `static/tentri-v2.png`, are preserved byte for byte. The small monochrome silhouette in their bottom-left corner supplies the app mark; the second sheet supplies the horizontal illustrations. The earlier full-color icon is also retained.

All artwork is served locally. Visit `/static/tentri-preview.html` to compare and download every version. No model call is involved in switching artwork or sections.

## Presentation

- The sidebar and sign-in use the monochrome mark in the current theme's foreground color. The PNG is a white-on-black luminance mask, not a transparent PNG. It also serves as the browser and touch icon.
- A compact mascot sits beside the section title. Its body and physical cartridge are separate RGBA PNG files, with actual transparency around the silhouette and between the arms. The component has no painted background or CSS rectangle matching the page color.
- The cartridge retains the original illustrated case, bevels, screws, glass screen and gold contacts. Its symbol is a separate SVG overlay. The same cartridge component also appears to the left of every navigation label. The top socket displays the symbol for the current section: a waveform for metrics, lines for event history, a bell for notifications, a chip for model settings, and distinct symbols for the other sections. These are navigation cues; they do not indicate the active LLM or system health. They have no animation and remain decorative to assistive technology because the adjacent heading already names the section.
- Illustrations automatically follow the interface palette. Earlier fixed-palette choices migrate to this behavior; an earlier explicit choice to hide artwork is preserved.
- Appearance offers a browser-local preference to hide the header mascot and a collapsed full illustration assembled from the transparent parts. Section icons remain available in navigation. The overview starts with monitoring information and statistics, without a large banner.

## Assets

Files live in `logsentinel/portal/static/`:

- `tentri-body-{classic,paper,tokyo,gruvbox,rose}-v2.png`: five body cutouts at 1162 × 724, without the original floating cartridge. These retain the original RGB pixels; only the crop and alpha channel change.
- `tentri-case-{classic,paper,tokyo,gruvbox,rose}-v2.png`: five standalone cartridge cases at 384 × 384. The glass display is blank so the section symbol can be rendered independently.

- `tentri-icon-mono-v1.png`: active monochrome icon, derived from the small silhouette in the second original concept sheet.
- `tentri-icon-v1.png`: earlier full-color icon on opaque teal; retained in the gallery.
- `tentri-banner-classic-v1.png`: original cream and teal horizontal illustration.
- `tentri-banner-paper-v1.png`: paper and ink with halftone shading.
- `tentri-banner-tokyo-v1.png`: Tokyo Night pixel art.
- `tentri-banner-gruvbox-v1.png`: charcoal, olive and parchment terminal art.
- `tentri-banner-rose-v1.png`: Rosé Pine pixel art.

## Direction and provenance

Inspired by the typography, terminal culture and theme system of [Omarchy](https://omarchy.org/) and [its themes](https://omarchy.org/themes/), using the palettes already present in this portal. These are original Tentri illustrations, not official Omarchy branding.

Raster assets were generated and edited with the built-in `imagegen` tool. Exact prompts and references are recorded in [tentri-artwork-prompts.json](tentri-artwork-prompts.json). The first full-color icon attempt painted a checkerboard instead of alpha; its final version deliberately uses opaque teal. The monochrome mark deliberately uses white on black for CSS luminance masking. Original generated files are retained at the tool's output location. The new case prompts and reference paths are recorded in [tentri-transparent-prompts.json](tentri-transparent-prompts.json). The original body-cutout generation returned a painted checkerboard and was rejected. The user then explicitly authorized local image editing. Body masks were prepared locally with background flood fill for the light themes and IS-Net segmentation with mask corrections for dark contours; the RGB artwork was preserved. Case exports were isolated using their alpha channel or outer case contour and resized to 384 pixels. Every final body and case was checked for real RGBA transparency. Local image tools and segmentation models were used only to prepare these static files; the portal has no new runtime dependency or model call. Section symbols and the shared cartridge component are in `branding.js`.

Preserved SHA-256 values:

```text
637af34ee8ef0891f0a44dcb1d447a26283d1d5267555f4c765593aeb65e900e  tentri-v1.png
f33d0b127c494eaebfae1c3363aad17c4b80f1af668f72d64994f28ad63da9df  tentri-v2.png
```
