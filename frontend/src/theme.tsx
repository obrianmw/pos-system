// Light / Dark / System theme. Saved on this device and, when signed in, on the user's account so it
// follows them to any till or PC.
import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { api, auth } from "./api";

export type Theme = "system" | "light" | "dark";
const KEY = "pos.theme";
let listeners: ((t: Theme) => void)[] = [];

export function storedTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch { return "system"; }
}

export function applyTheme(t: Theme) {
  const root = document.documentElement;
  if (t === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", t);
  try { localStorage.setItem(KEY, t); } catch { /* private mode */ }
  listeners.forEach((l) => l(t));
}

/** Change the theme now; remember it on the account if signed in (best effort - works offline too). */
export function setTheme(t: Theme) {
  applyTheme(t);
  if (auth.token) api("/me/preferences/", { method: "PATCH", body: { ui_theme: t }, branch: null }).catch(() => {});
}

export function useTheme(): Theme {
  const [t, setT] = useState<Theme>(storedTheme());
  useEffect(() => { listeners.push(setT); return () => { listeners = listeners.filter((l) => l !== setT); }; }, []);
  return t;
}

const OPTIONS: { value: Theme; label: string; icon: JSX.Element }[] = [
  { value: "light", label: "Light", icon: <Sun size={15} /> },
  { value: "system", label: "System", icon: <Monitor size={15} /> },
  { value: "dark", label: "Dark", icon: <Moon size={15} /> },
];

export function ThemeSwitch({ compact = false }: { compact?: boolean }) {
  const t = useTheme();
  return (
    <div className="seg theme-switch" role="radiogroup" aria-label="Theme">
      {OPTIONS.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={t === o.value} className={t === o.value ? "on" : ""}
                title={`${o.label} theme`} aria-label={`${o.label} theme`} onClick={() => setTheme(o.value)}>
          {o.icon}{!compact && <span>{o.label}</span>}
        </button>
      ))}
    </div>
  );
}

// Apply the saved choice before React draws anything, so there is no flash of the wrong theme.
applyTheme(storedTheme());
