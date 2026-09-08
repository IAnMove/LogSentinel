# Portal themes

Choose a theme from the **Appearance** selector at the top, including on the login
screen, or use the preview gallery in **Appearance**. Classic remains the default.
Your selection is stored only in this browser (`logsentinel-theme`), independently
of English/Spanish. Switching preserves unsaved forms. If browser storage is
blocked, the preference lasts only for the page session.

| Theme | Direction |
| --- | --- |
| Classic | Original light portal with a green sidebar |
| Paper | Monochrome, sharp geometry and the typography of Omarchy's website |
| Tokyo Night | Indigo surfaces, electric blue, warm graph peaks |
| Gruvbox | Charcoal, amber and olive accents |
| Rosé Pine | Violet surfaces, soft rose and muted cyan |
| Omarchy (auto) | Follow the desktop palette supplied by Omarchy Theme Sync |

## Follow your Omarchy desktop

LogSentinel supports [Omarchy Theme Sync](https://github.com/omacom/omarchy-theme-sync),
the Chromium extension also used by [Omarchy Radio](https://github.com/omacom/radio.omarchy.org#wearing-the-desktops-theme)
and [Cliamp's website](https://cliamp.stream/). Checked against the upstream
integration on 8 September 2026.

1. On the **Omarchy desktop where you use Chromium**, open Chromium once, then
   follow the [extension's installation guide](https://github.com/omacom/omarchy-theme-sync#install):

   ```sh
   git clone https://github.com/omacom/omarchy-theme-sync.git
   cd omarchy-theme-sync
   ./install.sh
   ```

   Run as your normal user, without `sudo`. Keep this folder in place: the browser
   uses the extension and helper directly from it.
2. Fully quit and restart Chromium; check **Omarchy Theme Sync** in
   `chrome://extensions`. Firefox is not currently supported; other Chromium-based
   browsers may require manually loading `extension/` (see the upstream guide).
3. Open LogSentinel and select **Appearance → Follow Omarchy theme**, or choose
   **Omarchy (auto)** in the top selector, including on the login screen.
4. Change your desktop theme. The portal updates immediately when the extension
   delivers the palette, without reloading or losing unsaved forms. Appearance
   shows the theme received. A remote portal accessed over SSH follows the
   **browser computer's** theme, even if the portal server runs Ubuntu.

The bar widget and browser extension are independent. Installing the LogSentinel
plugin alone does not install this extension. LogSentinel only reads colors; no
localhost write permission or ability to change/install desktop themes is needed.
The upstream extension currently makes theme names and colors readable to the
pages where it runs; its [privacy notes](https://github.com/omacom/omarchy-theme-sync#security-and-privacy)
describe that scope.

Classic stays the default until you choose otherwise. An explicit manual choice
always wins over desktop updates. If you choose Omarchy but no complete, valid
palette arrives, the portal shows Classic and explains that it is waiting; it
keeps your choice so synchronization starts when a palette becomes available.
If the extension has been disabled, reload the page to clear its previously
injected colors. The selection is saved per browser origin, like other themes.

The bridge reads `--omarchy-*` CSS colors and `data-omarchy-theme` from `<html>`
at startup and on the official `omarchythemechange` document event. No polling,
LLM calls, server configuration, external assets, or CSP changes are involved.
Only six-digit hex colors are accepted. Background and accent originate from the
desktop; text/accent contrast is adjusted where needed, surfaces are derived,
and error/warning panels retain readable severity colors. Light/dark controls
follow the actual background brightness, even with a malformed mode hint.
Tentri uses the closest existing dark artwork or neutral Paper for light themes.

The browser checks exercise late delivery, live updates, manual overrides,
persistence, missing/invalid colors, unsaved forms, English/Spanish and contrast
under the portal's real CSP. They simulate the documented extension DOM contract;
actual native-host and installed-browser integration still needs an Omarchy desktop.

## Manual palettes

The themes cover forms, dialogs, findings, notifications, code, tables, metric
charts and help conversations. They use local system fonts, require no external
requests and honor reduced motion. The browser smoke test checks principal text,
button and severity color pairs against a 4.5:1 contrast threshold; this is not a
claim of complete accessibility certification.

Inspiration and palette references: [Omarchy's theme gallery](https://omarchy.org/themes/),
[Tokyo Night in Omarchy](https://github.com/omacom/omarchy/blob/quattro/themes/tokyo-night/colors.toml),
[Gruvbox in Omarchy](https://github.com/omacom/omarchy/blob/quattro/themes/gruvbox/colors.toml),
and [Rosé Pine](https://rosepinetheme.com/palette/ingredients/).
The five manual palettes are independently styled portal adaptations, with adjusted contrast, not
official Omarchy themes or an endorsement. The optional Omarchy widget uses the
desktop's own colors, separately from this browser preference.
