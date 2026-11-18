// Small pieces shared by the back-office forms.
import { useEffect, useState } from "react";
import { api, ApiError } from "../api";

export type Errors = Record<string, string>;

// DRF returns {"field": ["msg"]} or {"detail": "msg"}; flatten to one message per field.
export function toErrors(e: unknown): Errors {
  if (e instanceof ApiError && e.data && typeof e.data === "object") {
    return Object.fromEntries(Object.entries(e.data).map(([k, v]) => [k, Array.isArray(v) ? v.join(" ") : String(v)]));
  }
  return { detail: (e as Error).message };
}
export const Err = ({ e, k }: { e: Errors; k: string }) => (e[k] ? <small className="error">{e[k]}</small> : null);
export const margin = (sell: string | number, cost: string | number) =>
  Number(sell) > 0 && cost !== "" ? `${(((Number(sell) - Number(cost)) / Number(sell)) * 100).toFixed(1)}%` : "–";

export function useOptions<T = any>(url: string) {
  const [items, setItems] = useState<T[]>([]);
  const [tick, setTick] = useState(0);
  useEffect(() => { api(url, { branch: null }).then((d) => setItems(d.results ?? d)).catch(() => {}); }, [url, tick]);
  return { items, reload: () => setTick((t) => t + 1) };
}

/** Inline "+ New" for a select: expands into fields right under it instead of a browser prompt. */
export function QuickAdd({ label, fields, create }: {
  label: string; fields: { key: string; placeholder: string; required?: boolean }[];
  create: (values: Record<string, string>) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [v, setV] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  if (!open) return <button type="button" className="link" onClick={() => setOpen(true)}>+ New</button>;
  async function save() {
    setBusy(true); setErr("");
    try { await create(v); setOpen(false); setV({}); }
    catch (e) { setErr(Object.values(toErrors(e)).join(" ")); } finally { setBusy(false); }
  }
  return (
    <div className="quickadd" role="group" aria-label={`New ${label}`}>
      {fields.map((f) => (
        <input key={f.key} placeholder={f.placeholder} aria-label={f.placeholder} value={v[f.key] || ""} autoFocus={f === fields[0]}
               onChange={(e) => setV({ ...v, [f.key]: e.target.value })}
               onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(); } if (e.key === "Escape") setOpen(false); }} />
      ))}
      <button type="button" disabled={busy || fields.some((f) => f.required && !v[f.key]?.trim())} onClick={save}>Add {label}</button>
      <button type="button" className="link" onClick={() => setOpen(false)}>Cancel</button>
      {err && <small className="error">{err}</small>}
    </div>
  );
}


// ---- toasts: small notices in the corner instead of browser alert() pop-ups -------------------
type Toast = { id: number; text: string; kind: "info" | "error" | "success" };
let listeners: ((t: Toast[]) => void)[] = [];
let toasts: Toast[] = [];
let nextId = 1;

export function toast(text: string, kind: Toast["kind"] = "info") {
  const t = { id: nextId++, text, kind };
  toasts = [...toasts, t].slice(-4);
  listeners.forEach((l) => l(toasts));
  setTimeout(() => dismiss(t.id), kind === "error" ? 7000 : 4000);
}

function dismiss(id: number) {
  toasts = toasts.filter((t) => t.id !== id);
  listeners.forEach((l) => l(toasts));
}

export function Toaster() {
  const [list, setList] = useState<Toast[]>(toasts);
  useEffect(() => { listeners.push(setList); return () => { listeners = listeners.filter((l) => l !== setList); }; }, []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          <span>{t.text}</span>
          <button aria-label="Dismiss" onClick={() => dismiss(t.id)}>✕</button>
        </div>
      ))}
    </div>
  );
}

/** Turn any API error into one readable line. */
export function errorText(e: unknown) {
  return Object.values(toErrors(e)).join(" ");
}

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
}
