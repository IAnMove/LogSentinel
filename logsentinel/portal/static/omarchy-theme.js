"use strict";

// Four seeds from Omarchy Radio (ground, ink, accent, line). Classic and Paper
// stay as hand-tuned portal skins; these 24 follow the radio list value for value.
const RADIO_SKINS = [
  { name: "green", bg: "#0a0b0a", fg: "#e7e6e0", ac: "#5ef2a0", bd: "#23261f" },
  { name: "daylight", bg: "#f7f6f2", fg: "#23231f", ac: "#2f9e63", bd: "#dedbd2" },
  { name: "catppuccin", bg: "#1e1e2e", fg: "#cdd6f4", ac: "#89b4fa", bd: "#45475a" },
  {
    name: "catppuccin latte",
    bg: "#eff1f5",
    fg: "#4c4f69",
    ac: "#1e66f5",
    bd: "#ccd0da",
  },
  { name: "ethereal", bg: "#060b1e", fg: "#ffcead", ac: "#7d82d9", bd: "#252e56" },
  { name: "everforest", bg: "#2d353b", fg: "#d3c6aa", ac: "#7fbbb3", bd: "#3d484d" },
  {
    name: "flexoki light",
    bg: "#fffcf0",
    fg: "#100f0f",
    ac: "#205ea6",
    bd: "#cecdc3",
  },
  { name: "gruvbox", bg: "#282828", fg: "#d4be98", ac: "#7daea3", bd: "#504945" },
  { name: "hackerman", bg: "#0b0c16", fg: "#ddf7ff", ac: "#82fb9c", bd: "#1f253a" },
  { name: "kanagawa", bg: "#1f1f28", fg: "#dcd7ba", ac: "#dcd7ba", bd: "#363646" },
  {
    name: "last horizon",
    bg: "#0c0b0c",
    fg: "#e2dddc",
    ac: "#b59790",
    bd: "#584e51",
  },
  { name: "lumon", bg: "#16242d", fg: "#f2fcff", ac: "#8bc9eb", bd: "#243d56" },
  { name: "lupine", bg: "#fafafa", fg: "#000000", ac: "#3264eb", bd: "#d0d0d0" },
  { name: "matte black", bg: "#121212", fg: "#bebebe", ac: "#e68e0d", bd: "#2a2a2a" },
  { name: "miasma", bg: "#222222", fg: "#c2c2b0", ac: "#78824b", bd: "#383838" },
  { name: "nord", bg: "#2e3440", fg: "#d8dee9", ac: "#81a1c1", bd: "#434c5e" },
  { name: "osaka jade", bg: "#111c18", fg: "#f7e8b2", ac: "#509475", bd: "#32473b" },
  { name: "retro 82", bg: "#05182e", fg: "#f6dcac", ac: "#faa968", bd: "#134e5a" },
  { name: "ristretto", bg: "#2c2525", fg: "#e6d9db", ac: "#f38d70", bd: "#403e41" },
  { name: "rose pine", bg: "#faf4ed", fg: "#575279", ac: "#56949f", bd: "#dfdad9" },
  { name: "solitude", bg: "#101315", fg: "#a5aeb4", ac: "#798186", bd: "#343d41" },
  { name: "tokyo night", bg: "#1a1b26", fg: "#c0caf5", ac: "#7aa2f7", bd: "#292e42" },
  { name: "vantablack", bg: "#000000", fg: "#ffffff", ac: "#8d8d8d", bd: "#1a1a1a" },
  { name: "white", bg: "#ffffff", fg: "#000000", ac: "#6e6e6e", bd: "#c0c0c0" },
];

const RADIO_BLURBS = {
  green: ["Verde de terminal sobre casi negro.", "Terminal green on near-black."],
  daylight: ["Claro, como trabajar de día.", "Bright, like working in daylight."],
  catppuccin: ["Lavanda y azul sobre mocha.", "Lavender and blue on mocha."],
  "catppuccin latte": ["El mismo café, en taza clara.", "The same coffee, in a light cup."],
  ethereal: ["Naranja cálido sobre azul profundo.", "Warm orange on deep blue."],
  everforest: ["Bosque húmedo, musgo y piedra.", "Damp forest, moss and stone."],
  "flexoki light": ["Papel cálido y azul de tinta.", "Warm paper and ink blue."],
  gruvbox: ["Carbón y verde agua de terminal.", "Charcoal and terminal aqua."],
  hackerman: ["Verde fósforo sobre azul noche.", "Phosphor green on night blue."],
  kanagawa: ["Tinta de ola y arena.", "Wave ink and sand."],
  "last horizon": ["Óxido suave sobre negro.", "Soft rust on black."],
  lumon: ["Cian de oficina sobre petróleo.", "Office cyan on oil-dark."],
  lupine: ["Blanco puro y azul eléctrico.", "Pure white and electric blue."],
  "matte black": ["Negro mate y ámbar.", "Matte black and amber."],
  miasma: ["Oliva apagado sobre gris.", "Muted olive on grey."],
  nord: ["Hielo polar, azul frío.", "Polar ice, cold blue."],
  "osaka jade": ["Jade y oro sobre bosque.", "Jade and gold on forest."],
  "retro 82": ["Ámbar de CRT sobre azul.", "CRT amber on blue."],
  ristretto: ["Café tostado y coral.", "Roast coffee and coral."],
  "rose pine": ["Papel rosa y pino cian.", "Rose paper and pine cyan."],
  solitude: ["Gris de acero, casi silencio.", "Steel grey, almost quiet."],
  "tokyo night": ["Índigo y azul eléctrico.", "Indigo and electric blue."],
  vantablack: ["Negro absoluto y blanco.", "Absolute black and white."],
  white: ["Blanco, negro y gris.", "White, black and grey."],
};

const TENTRI_ARTWORK = ["classic", "paper", "tokyo", "gruvbox", "rose"];
const THEME_ALIASES = { tokyo: "tokyo-night", rose: "rose-pine" };

function radioSkinId(name) {
  return name.replaceAll(" ", "-");
}

function radioSkinTitle(name) {
  if (name === "rose pine") return "Rosé Pine";
  return name.replace(/\b([a-z])/g, (letter) => letter.toUpperCase());
}

function rgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}

function mix(a, b, weight) {
  return (
    "#" +
    rgb(a)
      .map((v, i) =>
        Math.round(v * (1 - weight) + rgb(b)[i] * weight)
          .toString(16)
          .padStart(2, "0"),
      )
      .join("")
  );
}

function luminance(hex) {
  return rgb(hex).reduce((total, v, i) => {
    v /= 255;
    return (
      total +
      (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4) *
        [0.2126, 0.7152, 0.0722][i]
    );
  }, 0);
}

function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((x, y) => x - y);
  return (values[1] + 0.05) / (values[0] + 0.05);
}

function tentriArtworkFor(accent, light) {
  if (light) return "paper";
  return [
    ["tokyo", "#7aa2f7"],
    ["gruvbox", "#d8a657"],
    ["rose", "#ebbcba"],
  ].sort((a, b) => {
    const distance = (hex) =>
      rgb(hex).reduce((sum, v, i) => sum + (v - rgb(accent)[i]) ** 2, 0);
    return distance(a[1]) - distance(b[1]);
  })[0][0];
}

function derivePortalTokens({
  background,
  foreground,
  accent,
  selection,
  red,
  yellow,
  blue,
}) {
  const light = luminance(background) > 0.179;
  const ground = light ? "#ffffff" : "#000000";
  const ink = light ? "#000000" : "#ffffff";
  const surface = mix(background, ground, 0.08);
  const surfaceAlt = mix(background, ground, 0.16);
  const surfaces = [background, surface, surfaceAlt];
  const readable = (candidate, grounds = surfaces, minimum = 4.5) => {
    const target = ["#000000", "#ffffff"].sort(
      (a, b) =>
        Math.min(...grounds.map((g) => contrast(b, g))) -
        Math.min(...grounds.map((g) => contrast(a, g))),
    )[0];
    for (let step = 0; step <= 20; step++) {
      const adjusted = mix(candidate, target, step / 20);
      if (grounds.every((g) => contrast(adjusted, g) >= minimum))
        return adjusted;
    }
    return target;
  };
  const text = readable(foreground);
  const highlight = readable(accent);
  const muted = readable(mix(text, background, 0.25));
  const errorBg = light ? "#f6dddd" : "#402b3a";
  const warnBg = light ? "#f3e7bd" : "#3d342a";
  const line = selection && /^#[0-9a-f]{6}$/i.test(selection) ? selection : null;
  const danger = readable(red || "#d34455", [...surfaces, errorBg]);
  const tokens = {
    bg: background,
    surface,
    "surface-alt": surfaceAlt,
    ink: text,
    muted,
    border: line || mix(background, ink, 0.24),
    "control-border": readable(mix(background, ink, 0.5), surfaces, 3),
    accent: highlight,
    "button-ink": readable(ink, [highlight]),
    soft: surfaceAlt,
    "soft-border": mix(background, ink, 0.3),
    focus: highlight,
    danger,
    "error-bg": errorBg,
    "error-ink": readable(red || "#d34455", [errorBg]),
    "error-border": danger,
    "warn-bg": warnBg,
    "warn-ink": readable(yellow || "#b98925", [warnBg]),
    rail: background,
    "rail-ink": text,
    "rail-muted": muted,
    "rail-active": line ? mix(line, background, 0.35) : surfaceAlt,
    "rail-accent": highlight,
    "rail-border": line || mix(background, ink, 0.24),
    "chart-max": readable(yellow || "#b98925", surfaces, 3),
    "chart-avg": readable(blue || accent, surfaces, 3),
  };
  return {
    tokens,
    artwork: tentriArtworkFor(accent, light),
    mode: light ? "light" : "dark",
  };
}

function deriveRadioSkin(skin) {
  return derivePortalTokens({
    background: skin.bg,
    foreground: skin.fg,
    accent: skin.ac,
    selection: skin.bd,
  });
}

function applyDesktopTokens(root, tokens) {
  for (const [key, value] of Object.entries(tokens))
    root.style.setProperty(`--desktop-${key}`, value);
}

function clearDesktopTokens(root) {
  const style = root.style;
  for (let i = style.length - 1; i >= 0; i--) {
    const key = style.item(i);
    if (key.startsWith("--desktop-")) style.removeProperty(key);
  }
  style.removeProperty("color-scheme");
}

function applyTokenPreview(node, tokens, mode) {
  for (const [key, value] of Object.entries(tokens))
    node.style.setProperty(`--${key}`, value);
  if (mode) node.style.colorScheme = mode;
}

function readOmarchyTheme() {
  const root = document.documentElement;
  const name = root.dataset.omarchyTheme?.trim();
  if (!name) return null;
  const style = getComputedStyle(root);
  const color = (key) => {
    const value = style.getPropertyValue(`--omarchy-${key}`).trim();
    return /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : null;
  };
  const background = color("background");
  const foreground = color("bright-foreground") || color("foreground");
  const accent = color("accent");
  if (!background || !foreground || !accent) return null;
  const derived = derivePortalTokens({
    background,
    foreground,
    accent,
    selection: color("selection"),
    red: color("red"),
    yellow: color("yellow"),
    blue: color("blue"),
  });
  return {
    name: name.slice(0, 120),
    mode: derived.mode,
    tokens: derived.tokens,
    artwork: derived.artwork,
  };
}
