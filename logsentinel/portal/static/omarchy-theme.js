"use strict";

// Omarchy Theme Sync's shared DOM is the read-only contract. No extension API,
// local files, theme-setting permissions or server requests are needed here.
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

  const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const mix = (a, b, weight) =>
    "#" +
    rgb(a)
      .map((v, i) =>
        Math.round(v * (1 - weight) + rgb(b)[i] * weight)
          .toString(16)
          .padStart(2, "0"),
      )
      .join("");
  const luminance = (hex) =>
    rgb(hex).reduce((total, v, i) => {
      v /= 255;
      return (
        total +
        (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4) *
          [0.2126, 0.7152, 0.0722][i]
      );
    }, 0);
  const contrast = (a, b) => {
    const values = [luminance(a), luminance(b)].sort((x, y) => x - y);
    return (values[1] + 0.05) / (values[0] + 0.05);
  };
  // Determine legibility from the actual background, including custom themes
  // whose advertised mode is missing or inconsistent with their colors.
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
  const danger = readable(color("red") || "#d34455", [...surfaces, errorBg]);
  const tokens = {
    bg: background,
    surface,
    "surface-alt": surfaceAlt,
    ink: text,
    muted,
    border: mix(background, ink, 0.24),
    "control-border": readable(mix(background, ink, 0.5), surfaces, 3),
    accent: highlight,
    "button-ink": readable(ink, [highlight]),
    soft: surfaceAlt,
    "soft-border": mix(background, ink, 0.3),
    focus: highlight,
    danger,
    "error-bg": errorBg,
    "error-ink": readable(color("red") || "#d34455", [errorBg]),
    "error-border": danger,
    "warn-bg": warnBg,
    "warn-ink": readable(color("yellow") || "#b98925", [warnBg]),
    rail: background,
    "rail-ink": text,
    "rail-muted": muted,
    "rail-active": surfaceAlt,
    "rail-accent": highlight,
    "rail-border": mix(background, ink, 0.24),
    "chart-max": readable(color("yellow") || "#b98925", surfaces, 3),
    "chart-avg": readable(color("blue") || accent, surfaces, 3),
  };
  // Reuse the closest existing transparent artwork; never request an asset
  // using an external theme name. Light themes use the neutral Paper artwork.
  const artwork = light
    ? "paper"
    : [
        ["tokyo", "#7aa2f7"],
        ["gruvbox", "#d8a657"],
        ["rose", "#ebbcba"],
      ].sort((a, b) => {
        const distance = (hex) =>
          rgb(hex).reduce((sum, v, i) => sum + (v - rgb(accent)[i]) ** 2, 0);
        return distance(a[1]) - distance(b[1]);
      })[0][0];
  return {
    name: name.slice(0, 120),
    mode: light ? "light" : "dark",
    tokens,
    artwork,
  };
}
