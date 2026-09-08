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
if (!portalThemes.some((theme) => theme.id === portalTheme))
  portalTheme = "classic";
document.documentElement.dataset.theme = portalTheme;
function applyPortalTheme(id) {
  if (!portalThemes.some((theme) => theme.id === id)) return;
  portalTheme = id;
  document.documentElement.dataset.theme = id;
  try {
    localStorage.setItem("logsentinel-theme", id);
  } catch {
    /* Session-only preference. */
  }
  const picker = document.querySelector("#theme");
  if (picker) picker.value = id;
  if (typeof updateTentriBanners === "function") updateTentriBanners();
  document.querySelectorAll(".theme-card").forEach((card) => {
    card.setAttribute("aria-pressed", String(card.dataset.palette === id));
    card.querySelector(".theme-selected").textContent =
      card.dataset.palette === id
        ? document.documentElement.lang === "es"
          ? "Seleccionado"
          : "Selected"
        : "";
  });
}
document.addEventListener("DOMContentLoaded", () => {
  const picker = document.querySelector("#theme");
  for (const theme of portalThemes) {
    const option = document.createElement("option");
    option.value = theme.id;
    option.textContent = theme.name;
    picker.append(option);
  }
  picker.value = portalTheme;
  picker.addEventListener("change", (event) =>
    applyPortalTheme(event.target.value),
  );
});
function appearanceView(root) {
  const intro = panel(t("Apariencia"));
  intro.classList.add("appearance-intro");
  intro.append(
    el(
      "p",
      bilingual(
        "Tu observatorio, a tu manera. Cinco paletas completas para logs, métricas y conversaciones. El tema se recuerda en este navegador y puedes cambiarlo sin perder lo que estás editando.",
        "Your observatory, your way. Five complete palettes for logs, metrics and conversations. This browser remembers your theme; switching keeps your unsaved edits.",
      ),
    ),
  );
  intro.append(
    el(
      "div",
      bilingual(
        "5 TEMAS · LOCAL · SIN DESCARGAS",
        "5 THEMES · LOCAL · OFFLINE",
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
      '<span class="preview-rail"><b>◈</b><i></i><i></i><i></i></span><span class="preview-body"><span class="preview-heading">TENTRI <b>●</b></span><span class="preview-metrics"><i>24<span>HOSTS</span></i><i>03<span>FINDINGS</span></i></span><span class="preview-chart"></span><span class="preview-lines"><i></i><i></i><i></i></span></span>';
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
    tentriAppearance(),
    grid,
    el(
      "p",
      bilingual(
        "Classic es el tema por defecto. Las otras paletas son adaptaciones para Tentri; no requieren Omarchy y todos los recursos se sirven desde este portal. El widget de Omarchy hereda por separado el tema del escritorio.",
        "Classic is the default. The other palettes are Tentri adaptations; they need no Omarchy installation and all assets are served by this portal. The Omarchy widget separately inherits your desktop theme.",
      ),
      "subtle",
    ),
  );
}
