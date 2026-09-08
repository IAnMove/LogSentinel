"use strict";
// Runs before the stylesheet: the saved palette is applied without a light flash.
const portalThemes = [
  {
    id: "classic",
    name: "Classic",
    es: "El original. Claro, tranquilo y familiar.",
    en: "The original. Light, quiet and familiar.",
  },
  {
    id: "paper",
    name: "Paper",
    es: "Tinta, papel y precisión. Inspirado en la web de Omarchy.",
    en: "Ink, paper and precision. Inspired by the Omarchy website.",
  },
  {
    id: "tokyo",
    name: "Tokyo Night",
    es: "Azul eléctrico e índigo para largas noches de terminal.",
    en: "Electric blue and indigo for long terminal nights.",
  },
  {
    id: "gruvbox",
    name: "Gruvbox",
    es: "Carbón, ámbar y verde oliva. Un escritorio cálido.",
    en: "Charcoal, amber and olive. A warmer desktop.",
  },
  {
    id: "rose",
    name: "Rosé Pine",
    es: "Violeta profundo y rosa suave, con contraste sereno.",
    en: "Deep violet and soft rose, with quiet contrast.",
  },
];
let portalTheme = "classic";
try {
  portalTheme = localStorage.getItem("logsentinel-theme") || "classic";
} catch {
  /* Session-only preference. */
}
if (
  portalTheme !== "omarchy" &&
  !portalThemes.some((theme) => theme.id === portalTheme)
)
  portalTheme = "classic";
let portalPalette = "classic";
let omarchyPalette = null;
function themeText(es, en) {
  return document.documentElement.lang === "es" ? es : en;
}
function refreshPortalTheme() {
  omarchyPalette = readOmarchyTheme();
  const following = portalTheme === "omarchy";
  portalPalette = following
    ? omarchyPalette?.artwork || "classic"
    : portalTheme;
  const root = document.documentElement;
  root.dataset.theme = portalPalette;
  root.dataset.themeSource = following
    ? omarchyPalette
      ? "omarchy"
      : "fallback"
    : "manual";
  if (following && omarchyPalette) {
    for (const [key, value] of Object.entries(omarchyPalette.tokens))
      root.style.setProperty(`--desktop-${key}`, value);
  }
  if (typeof updateTentriBanners === "function") updateTentriBanners();
  updatePortalThemeControls();
}
function applyPortalTheme(id) {
  if (id !== "omarchy" && !portalThemes.some((theme) => theme.id === id))
    return;
  portalTheme = id;
  try {
    localStorage.setItem("logsentinel-theme", id);
  } catch {
    /* Session-only preference. */
  }
  refreshPortalTheme();
}
function updatePortalThemeControls(scope = document) {
  const picker = scope.querySelector("#theme");
  if (picker) picker.value = portalTheme;
  scope.querySelectorAll(".theme-card").forEach((card) => {
    card.setAttribute(
      "aria-pressed",
      String(card.dataset.palette === portalTheme),
    );
    card.querySelector(".theme-selected").textContent =
      card.dataset.palette === portalTheme
        ? themeText("Seleccionado", "Selected")
        : "";
  });
  const follow = scope.querySelector("#follow-omarchy");
  if (follow)
    follow.setAttribute("aria-pressed", String(portalTheme === "omarchy"));
  const status = scope.querySelector("#omarchy-theme-status");
  if (status) {
    status.textContent = omarchyPalette
      ? (portalTheme === "omarchy"
          ? themeText("Siguiendo el escritorio: ", "Following desktop: ")
          : themeText("Tema disponible: ", "Desktop theme available: ")) +
        omarchyPalette.name
      : portalTheme === "omarchy"
        ? themeText(
            "Esperando una paleta válida de Omarchy Theme Sync. Se muestra Classic mientras tanto.",
            "Waiting for a valid palette from Omarchy Theme Sync. Showing Classic in the meantime.",
          )
        : themeText(
            "No se ha recibido un tema de Omarchy en este navegador.",
            "No Omarchy theme has been received in this browser.",
          );
  }
}
// Palette delivery is asynchronous; the initial read also covers extensions
// that publish before our scripts load. The event carries no trusted payload.
document.addEventListener("omarchythemechange", refreshPortalTheme);
refreshPortalTheme();
document.addEventListener("DOMContentLoaded", () => {
  const picker = document.querySelector("#theme");
  for (const theme of portalThemes) {
    const option = document.createElement("option");
    option.value = theme.id;
    option.textContent = theme.name;
    picker.append(option);
  }
  const automatic = document.createElement("option");
  automatic.value = "omarchy";
  automatic.textContent = "Omarchy (auto)";
  picker.append(automatic);
  refreshPortalTheme();
  picker.addEventListener("change", (event) =>
    applyPortalTheme(event.target.value),
  );
});
function omarchyAppearance() {
  const section = panel("Omarchy Theme Sync");
  const status = el("p");
  status.id = "omarchy-theme-status";
  status.setAttribute("role", "status");
  const follow = button(
    bilingual("Seguir tema de Omarchy", "Follow Omarchy theme"),
    () => applyPortalTheme("omarchy"),
  );
  follow.id = "follow-omarchy";
  const help = el("details");
  help.append(
    el(
      "summary",
      bilingual("Cómo activar la sincronización", "How to enable theme sync"),
    ),
    el(
      "p",
      bilingual(
        "Instala Omarchy Theme Sync en el equipo Omarchy donde abres Chromium y reinicia completamente el navegador. Esta opción sigue los cambios del escritorio sin recargar el portal, también al entrar por un túnel SSH.",
        "Install Omarchy Theme Sync on the Omarchy desktop where you run Chromium, then fully restart the browser. This option follows desktop changes without reloading the portal, including over an SSH tunnel.",
      ),
    ),
  );
  const guide = el(
    "a",
    bilingual(
      "Instalación oficial de Omarchy Theme Sync",
      "Official Omarchy Theme Sync installation",
    ),
  );
  guide.href = "https://github.com/omacom/omarchy-theme-sync#install";
  guide.target = "_blank";
  guide.rel = "noopener noreferrer";
  help.append(
    guide,
    el(
      "p",
      bilingual(
        "La extensión es independiente del widget de la barra. Actualmente admite Chromium; Firefox aún no está soportado. El portal solo lee la paleta: no necesita permiso para cambiar el escritorio. Puedes volver a cualquier tema manual cuando quieras.",
        "The extension is separate from the bar widget. Chromium is supported; Firefox is not supported yet. The portal only reads the palette and needs no permission to change your desktop. You can return to any manual theme at any time.",
      ),
    ),
  );
  section.append(status, follow, help);
  updatePortalThemeControls(section);
  return section;
}
function appearanceView(root) {
  const intro = panel(t("Apariencia"));
  intro.classList.add("appearance-intro");
  intro.append(
    el(
      "p",
      bilingual(
        "Tu observatorio, a tu manera. Elige entre cinco paletas o sigue el tema de tu escritorio Omarchy. El tema se recuerda en este navegador y puedes cambiarlo sin perder lo que estás editando.",
        "Your observatory, your way. Choose from five palettes or follow your Omarchy desktop theme. This browser remembers your theme; switching keeps your unsaved edits.",
      ),
    ),
  );
  intro.append(
    el(
      "div",
      bilingual(
        "5 PALETAS + OMARCHY · LOCAL",
        "5 PALETTES + OMARCHY · LOCAL",
      ),
      "eyebrow",
    ),
  );
  const grid = el("div", undefined, "theme-gallery");
  for (const theme of portalThemes) {
    const card = button("", () => applyPortalTheme(theme.id), "theme-card");
    card.dataset.palette = theme.id;
    card.setAttribute("aria-label", theme.name);
    card.setAttribute("aria-pressed", String(portalTheme === theme.id));
    const sample = el("span", undefined, "theme-preview");
    sample.setAttribute("aria-hidden", "true");
    sample.innerHTML =
      '<span class="preview-rail"><b>◈</b><i></i><i></i><i></i></span><span class="preview-body"><span class="preview-heading">LOGSENTINEL <b>●</b></span><span class="preview-metrics"><i>24<span>HOSTS</span></i><i>03<span>FINDINGS</span></i></span><span class="preview-chart"></span><span class="preview-lines"><i></i><i></i><i></i></span></span>';
    card.append(
      sample,
      el("span", theme.name, "theme-name"),
      el("span", bilingual(theme.es, theme.en), "theme-description"),
      el(
        "span",
        portalTheme === theme.id ? bilingual("Seleccionado", "Selected") : "",
        "theme-selected",
      ),
    );
    grid.append(card);
  }
  root.append(
    intro,
    omarchyAppearance(),
    tentriAppearance(),
    grid,
    el(
      "p",
      bilingual(
        "Classic es el tema por defecto. Las cinco paletas manuales no requieren Omarchy. La sincronización adapta los colores del escritorio manteniendo legibles textos y alertas; Tentri usa la variante existente más cercana. Todos los recursos se sirven desde este portal.",
        "Classic is the default. The five manual palettes need no Omarchy installation. Sync adapts desktop colors to keep text and alerts readable; Tentri uses the closest existing artwork. All assets are served by this portal.",
      ),
      "subtle",
    ),
  );
}
