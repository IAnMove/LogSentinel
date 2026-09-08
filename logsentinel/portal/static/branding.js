"use strict";

function tentriTheme() {
  return portalThemes.some((theme) => theme.id === portalPalette)
    ? portalPalette
    : "classic";
}
// Artwork now follows the interface. Preserve an earlier opt-out, but migrate
// the old default and fixed-palette choices to automatic theme matching.
let tentriArtworkChoice = "auto";
try {
  if (localStorage.getItem("tentri-artwork") === "hidden")
    tentriArtworkChoice = "hidden";
} catch {
  /* Session-only preference. */
}

// Fixed UI symbols, not model identities or monitoring status indicators.
const tentriCartridges = {
  summary:
    '<path d="M3 12s3-6 9-6 9 6 9 6-3 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="3"/>',
  machine:
    '<rect x="3" y="4" width="18" height="13" rx="1"/><path d="M12 17v4M8 21h8"/>',
  metrics: '<path d="M2 13h5l3-8 4 14 3-6h5"/>',
  health: '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z M8 12l3 3 5-6"/>',
  capacity: '<path d="M5 20v-6M12 20V9M19 20V3"/>',
  appearance:
    '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18M6 6l12 12M6 18 18 6"/>',
  desktop:
    '<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M3 9h18M8 9v11"/>',
  source: '<path d="M4 4h6v6H4zM14 14h6v6h-6zM7 10v7h7M14 7h6M17 4v6"/>',
  problems: '<path d="m12 3 10 18H2Z M12 9v5M12 17v1"/>',
  events: '<path d="M8 5h13M8 12h13M8 19h13M3 5h1M3 12h1M3 19h1"/>',
  destination: '<path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5ZM10 21h4M12 2v2"/>',
  rule: '<path d="M3 4h18l-7 9v6l-4 2v-8Z"/>',
  settings:
    '<rect x="6" y="6" width="12" height="12" rx="1"/><path d="M10 10h4v4h-4zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  chat: '<path d="M3 4h18v13H9l-6 4ZM7 9h10M7 13h6"/>',
  activity: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/>',
  backup: '<path d="M4 3h13l3 3v15H4ZM8 3v6h8V3M8 21v-7h8v7"/>',
  setup: '<path d="m4 17 10-10 3 3L7 20ZM14 2v2M21 7h-2M4 4l2 2M8 2v2"/>',
  about: '<circle cx="12" cy="12" r="9"/><path d="M12 10v7M12 6v1"/>',
};

function updateTentriBanners() {
  const theme = tentriTheme();
  for (const img of document.querySelectorAll('[data-tentri-part="case"]')) {
    const src = `/static/tentri-case-${theme}-v2.png`;
    if (img.getAttribute("src") !== src) img.src = src;
  }
  for (const mascot of document.querySelectorAll("[data-tentri-companion]")) {
    mascot.hidden =
      mascot.id === "section-mascot" && tentriArtworkChoice === "hidden";
    const img = mascot.querySelector('[data-tentri-part="body"]');
    const src = `/static/tentri-body-${theme}-v2.png`;
    if (img.getAttribute("src") !== src) img.src = src;
  }
}

function tentriCartridge(section) {
  const cartridge = el("span", undefined, "tentri-cartridge");
  cartridge.dataset.cartridge = section;
  cartridge.setAttribute("aria-hidden", "true");
  const housing = el("img");
  housing.dataset.tentriPart = "case";
  housing.src = `/static/tentri-case-${tentriTheme()}-v2.png`;
  housing.alt = "";
  housing.width = 384;
  housing.height = 384;
  housing.decoding = "async";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.innerHTML = tentriCartridges[section] || tentriCartridges.summary;
  cartridge.append(housing, svg);
  return cartridge;
}

function tentriNavButton(section, label) {
  const item = button("", () => navigate(section));
  item.append(tentriCartridge(section), el("span", t(label)));
  return item;
}

function updateTentriSection(section, title) {
  const mascot = document.querySelector("#section-mascot");
  if (!mascot) return;
  const key = section === "problem_detail" ? "problems" : section;
  mascot.className = "tentri-companion";
  mascot.dataset.tentriCompanion = "";
  mascot.dataset.cartridge = key;
  mascot.setAttribute("aria-hidden", "true");
  mascot.title = bilingual(
    `Tentri · Cartucho de ${title.toLowerCase()}`,
    `Tentri · ${title} cartridge`,
  );
  if (!mascot.firstChild) {
    const body = el("img", undefined, "tentri-body");
    body.dataset.tentriPart = "body";
    body.alt = "";
    body.src = `/static/tentri-body-${tentriTheme()}-v2.png`;
    body.decoding = "async";
    const cartridge = tentriCartridge(key);
    mascot.append(body, cartridge);
  }
  // Only the symbol changes. The illustrated physical housing stays in place.
  // These SVG fragments are constants, never log or user content.
  mascot.querySelector(".tentri-cartridge").dataset.cartridge = key;
  mascot.querySelector("svg").innerHTML =
    tentriCartridges[key] || tentriCartridges.summary;
  updateTentriBanners();
}

function tentriBanner() {
  const banner = el("figure", undefined, "tentri-hero");
  const illustration = el("div", undefined, "tentri-artwork-preview");
  illustration.setAttribute("role", "img");
  illustration.setAttribute(
    "aria-label",
    bilingual(
      "Tentri, la mascota de LogSentinel",
      "Tentri, the LogSentinel mascot",
    ),
  );
  const wordmark = el("span", "TENTRI", "tentri-wordmark");
  const companion = el(
    "div",
    undefined,
    "tentri-companion tentri-companion-preview",
  );
  companion.dataset.tentriCompanion = "";
  companion.setAttribute("aria-hidden", "true");
  const body = el("img", undefined, "tentri-body");
  body.dataset.tentriPart = "body";
  body.alt = "";
  body.loading = "lazy";
  body.decoding = "async";
  body.src = `/static/tentri-body-${tentriTheme()}-v2.png`;
  companion.append(body, tentriCartridge("appearance"));
  illustration.append(wordmark, companion);
  const caption = el("figcaption");
  const gallery = el(
    "a",
    bilingual("Ver todas las ilustraciones", "View all artwork"),
  );
  gallery.href = "/static/tentri-preview.html";
  gallery.target = "_blank";
  gallery.rel = "noopener";
  caption.append(el("span", "LogSentinel · Tentri"), gallery);
  banner.append(illustration, caption);
  return banner;
}

function tentriAppearance() {
  const p = panel(bilingual("Tentri, tu centinela", "Tentri, your lookout"));
  const select = field(
    "tentri_artwork",
    bilingual("Mascota en el portal", "Portal mascot"),
    "select",
    tentriArtworkChoice,
    [
      [
        "auto",
        bilingual("Visible · seguir el tema", "Visible · follow the theme"),
      ],
      ["hidden", bilingual("Oculta", "Hidden")],
    ],
  );
  select.querySelector("select").onchange = (event) => {
    tentriArtworkChoice = event.target.value;
    try {
      localStorage.setItem("tentri-artwork", tentriArtworkChoice);
    } catch {
      /* The choice still works for this browser session. */
    }
    updateTentriBanners();
  };
  const details = el("details", undefined, "tentri-artwork-details");
  details.append(
    el(
      "summary",
      bilingual("Ver ilustración completa", "View full illustration"),
    ),
    tentriBanner(),
  );
  p.append(
    el(
      "p",
      bilingual(
        "LogSentinel es la aplicación; Tentri es tu mascota. Su ilustración sigue el tema y su cartucho identifica la sección que visitas, también en el menú. El modelo de análisis se elige en Modelo y análisis. Esta preferencia visual se guarda en este navegador.",
        "LogSentinel is the application; Tentri is your mascot. Its artwork follows the theme and its cartridge identifies the section you visit, including in the menu. Choose the analysis model in Model and analysis. This visual preference is saved in this browser.",
      ),
    ),
    select,
    details,
  );
  return p;
}
