"use strict";

const tentriArtwork = {
  classic: "tentri-banner-classic-v1.png",
  paper: "tentri-banner-paper-v1.png",
  tokyo: "tentri-banner-tokyo-v1.png",
  gruvbox: "tentri-banner-gruvbox-v1.png",
  rose: "tentri-banner-rose-v1.png",
};
let tentriArtworkChoice = "classic";
try {
  tentriArtworkChoice = localStorage.getItem("tentri-artwork") || "classic";
} catch {
  /* The original artwork also works when browser storage is unavailable. */
}
if (
  !["auto", "hidden", ...Object.keys(tentriArtwork)].includes(
    tentriArtworkChoice,
  )
)
  tentriArtworkChoice = "classic";

function updateTentriBanners() {
  const key =
    tentriArtworkChoice === "auto" ? portalTheme : tentriArtworkChoice;
  const src = "/static/" + (tentriArtwork[key] || tentriArtwork.classic);
  for (const banner of document.querySelectorAll("[data-tentri-banner]")) {
    banner.hidden = tentriArtworkChoice === "hidden";
    const img = banner.querySelector("img");
    if (img.getAttribute("src") !== src) img.src = src;
  }
}

function tentriBanner() {
  const banner = el("figure", undefined, "tentri-hero");
  banner.dataset.tentriBanner = "";
  banner.hidden = tentriArtworkChoice === "hidden";
  const key =
    tentriArtworkChoice === "auto" ? portalTheme : tentriArtworkChoice;
  const img = el("img");
  img.src = "/static/" + (tentriArtwork[key] || tentriArtwork.classic);
  img.alt = bilingual(
    "Tentri, tu centinela local",
    "Tentri, your local lookout",
  );
  img.width = 2172;
  img.height = 724;
  img.decoding = "async";
  const caption = el("figcaption");
  const gallery = el("a", bilingual("Ver ilustraciones", "View artwork"));
  gallery.href = "/static/tentri-preview.html";
  gallery.target = "_blank";
  gallery.rel = "noopener";
  caption.append(
    el("span", bilingual("Tu centinela local", "Your local lookout")),
    gallery,
  );
  banner.append(img, caption);
  return banner;
}

function tentriAppearance() {
  const p = panel(bilingual("Mascota e ilustración", "Mascot and artwork"));
  const select = field(
    "tentri_artwork",
    bilingual("Ilustración del banner", "Banner artwork"),
    "select",
    tentriArtworkChoice,
    [
      ["classic", bilingual("Original (por defecto)", "Original (default)")],
      [
        "auto",
        bilingual(
          "Seguir el tema de la interfaz",
          "Follow the interface theme",
        ),
      ],
      ...portalThemes
        .filter((theme) => theme.id !== "classic")
        .map((theme) => [theme.id, theme.name]),
      ["hidden", bilingual("Ocultar el banner", "Hide the banner")],
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
  p.append(
    el(
      "p",
      bilingual(
        "La ilustración original es la opción inicial. Puedes elegir una variante o hacer que cambie con el tema. Esta preferencia se guarda en este navegador.",
        "The original illustration is the starting choice. Pick a variant or let it change with the theme. This preference is saved in this browser.",
      ),
    ),
    select,
    tentriBanner(),
  );
  return p;
}
