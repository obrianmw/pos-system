// Brand colours -> readable UI colours for light and dark themes.
// The shop picks any primary/accent; we nudge lightness (keeping the hue) until text and buttons meet
// WCAG contrast against each theme's surfaces. Chart/data colours are deliberately NOT touched.
import { api } from "./api";

type RGB = [number, number, number];

export function hexToRgb(hex: string): RGB {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB;
}
export function rgbToHex([r, g, b]: RGB) {
  return "#" + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
}
function rgbToHsl([r, g, b]: RGB): RGB {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h / 6, s, l];
}
function hslToRgb([h, s, l]: RGB): RGB {
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t: number) => {
    t = (t + 1) % 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
}
export function luminance(hex: string) {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a: string, b: string) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
export function mix(a: string, b: string, amountOfB: number) {
  const [x, y] = [hexToRgb(a), hexToRgb(b)];
  return rgbToHex(x.map((v, i) => v + (y[i] - v) * amountOfB) as RGB);
}
function setLightness(hex: string, l: number) {
  const [h, s] = rgbToHsl(hexToRgb(hex));
  return rgbToHex(hslToRgb([h, s, Math.max(0, Math.min(1, l))]));
}
/** Move lightness in `direction` until the colour reaches `target` contrast against `surface`. */
function reach(hex: string, surface: string, target: number, direction: -1 | 1) {
  let [, , l] = rgbToHsl(hexToRgb(hex));
  let out = hex;
  for (let i = 0; i < 60 && contrast(out, surface) < target; i++) {
    l += 0.015 * direction;
    out = setLightness(hex, l);
  }
  return out;
}
const bestText = (bg: string, dark: string, light = "#ffffff") => (contrast(bg, light) >= contrast(bg, dark) ? light : dark);

export const SURFACES = { light: { card: "#ffffff", bg: "#f4f6f8", ink: "#111827" }, dark: { card: "#131920", bg: "#0b0f14", ink: "#0b0f14" } };

export type ContrastRow = { mode: "light" | "dark"; label: string; color: string; against: string; ratio: number; need: number };

/** A filled control (button) can keep the brand colour itself as long as SOME text colour reads well on
 *  it. Only when neither white nor near-black reaches 4.5:1 do we nudge its lightness. */
function fillFor(brand: string, ink: string): { fill: string; text: string } {
  let fill = brand;
  let text = bestText(fill, ink);
  if (contrast(fill, text) < 4.5) {
    const dir: -1 | 1 = text === "#ffffff" ? -1 : 1; // white text -> darker fill, dark text -> lighter fill
    fill = reach(brand, text, 4.5, dir);
    text = bestText(fill, ink);
  }
  return { fill, text };
}

const shift = (hex: string, by: number) => setLightness(hex, rgbToHsl(hexToRgb(hex))[2] + by);

export function deriveBrand(primary: string, accent: string) {
  const L = SURFACES.light, D = SURFACES.dark;
  // Ink: text, links, borders, focus rings - must read on the page surface.
  const lp = reach(primary, L.card, 4.5, -1), dp = reach(primary, D.card, 4.5, 1);
  const la = reach(accent, L.card, 3, -1), da = reach(accent, D.card, 3, 1);
  // Fill: button backgrounds - the brand colour itself whenever a text colour reads on it.
  const lf = fillFor(primary, "#111827"), df = fillFor(primary, D.ink);
  const light = {
    "--primary": lp, "--primary-hover": shift(lp, -0.07), "--primary-soft": mix(lp, "#ffffff", 0.86), "--accent": la,
    "--primary-fill": lf.fill, "--primary-fill-hover": shift(lf.fill, lf.text === "#ffffff" ? -0.07 : -0.05), "--primary-text": lf.text,
    "--doc-accent": lp,
  };
  const dark = {
    "--primary": dp, "--primary-hover": shift(dp, 0.07), "--primary-soft": mix(dp, D.card, 0.8), "--accent": da,
    "--primary-fill": df.fill, "--primary-fill-hover": shift(df.fill, df.text === "#ffffff" ? -0.06 : 0.06), "--primary-text": df.text,
    "--doc-accent": lp, // documents are printed on white paper in every theme
  };
  const report: ContrastRow[] = [
    { mode: "light", label: "Links & highlights", color: lp, against: L.card, ratio: contrast(lp, L.card), need: 4.5 },
    { mode: "light", label: "Button text on button", color: lf.text, against: lf.fill, ratio: contrast(lf.text, lf.fill), need: 4.5 },
    { mode: "light", label: "Accent on page", color: la, against: L.card, ratio: contrast(la, L.card), need: 3 },
    { mode: "dark", label: "Links & highlights", color: dp, against: D.card, ratio: contrast(dp, D.card), need: 4.5 },
    { mode: "dark", label: "Button text on button", color: df.text, against: df.fill, ratio: contrast(df.text, df.fill), need: 4.5 },
    { mode: "dark", label: "Accent on page", color: da, against: D.card, ratio: contrast(da, D.card), need: 3 },
  ];
  const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
  return { light, dark, report, fills: { light: lf.fill, dark: df.fill },
           adjusted: { light: !same(lp, primary), dark: !same(dp, primary), fillLight: !same(lf.fill, primary), fillDark: !same(df.fill, primary) } };
}

/** Put the derived colours into a <style> after styles.css so they override the defaults in every theme. */
export function applyBrand(primary: string, accent: string) {
  const { light, dark } = deriveBrand(primary, accent);
  const decl = (v: Record<string, string>) => Object.entries(v).map(([k, x]) => `${k}:${x};`).join("");
  let el = document.getElementById("brand-vars") as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement("style");
    el.id = "brand-vars";
    document.head.appendChild(el);
  }
  el.textContent = `:root{${decl(light)}}:root[data-theme="dark"]{${decl(dark)}}` +
    `@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){${decl(dark)}}}`;
}

// ---- branding store (public bits for the login page, full settings after sign-in) ------------
export type DemoAccounts = {
  password: string; pin: string;
  accounts: { username: string; role: string; branch: string; has_pin: boolean }[];
};
export type PublicBranding = {
  name: string; tagline: string; logo_url: string | null; primary_color: string; accent_color: string;
  demo?: DemoAccounts | null; // only on the public demo: the sign-in page lists the shared accounts
};
export type BrandingSettings = PublicBranding & Record<string, any>;

let current: BrandingSettings | null = null;
let listeners: ((b: BrandingSettings | null) => void)[] = [];
const CACHE = "pos.branding";

function publish(b: BrandingSettings) {
  current = b;
  try { localStorage.setItem(CACHE, JSON.stringify(b)); } catch { /* private mode */ }
  applyBrand(b.primary_color, b.accent_color);
  if (b.name) document.title = document.title.replace(/POS System|Aden Shop/, b.name);
  listeners.forEach((l) => l(b));
}

export function getBranding() { return current; }
export function onBranding(l: (b: BrandingSettings | null) => void) {
  listeners.push(l);
  return () => { listeners = listeners.filter((x) => x !== l); };
}

/** Called at startup: cached copy first (works offline), then refresh from the server. */
export async function loadBranding(signedIn: boolean) {
  if (!current) {
    try { const cached = localStorage.getItem(CACHE); if (cached) publish(JSON.parse(cached)); } catch { /* ignore */ }
  }
  try {
    const b = signedIn ? await api<BrandingSettings>("/branding/settings/", { branch: null })
      : await api<BrandingSettings>("/branding/", { branch: null });
    publish({ ...(current || {}), ...b });
  } catch { /* offline: keep cached */ }
}

export function setBranding(b: BrandingSettings) { publish(b); }
