// One dialog for every question the app asks: same card as the error pages (icon badge, title,
// message, centred buttons). Replaces the browser's own confirm()/prompt() boxes.
//
//   if (await confirmDialog({ title: "Delete group?", message: "...", danger: true })) { ... }
//   const v = await formDialog({ title: "Adjust stock", fields: [{ name: "qty", label: "Counted", ... }] });
//   if (v) use(v.qty)
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, HelpCircle, Info, PackageCheck, Trash2 } from "lucide-react";

type Tone = "info" | "warning" | "danger" | "success";
export type Field = {
  name: string; label: string; type?: "text" | "number" | "password" | "textarea";
  value?: string; placeholder?: string; required?: boolean; hint?: string;
  validate?: (v: string, all: Record<string, string>) => string | null;
};
type Request = {
  id: number; title: string; message?: string; tone: Tone; icon?: JSX.Element; fields?: Field[];
  confirmLabel: string; cancelLabel: string; resolve: (v: Record<string, string> | null) => void;
};

let push: ((r: Request) => void) | null = null;
let nextId = 1;

function open(opts: Omit<Request, "id" | "resolve" | "tone" | "confirmLabel" | "cancelLabel"> &
  Partial<Pick<Request, "tone" | "confirmLabel" | "cancelLabel">>) {
  return new Promise<Record<string, string> | null>((resolve) => {
    const req: Request = { id: nextId++, tone: "info", confirmLabel: "OK", cancelLabel: "Cancel", ...opts, resolve };
    if (push) push(req);
    else resolve(window.confirm(`${opts.title}\n\n${opts.message || ""}`) ? {} : null); // host not mounted yet
  });
}

/** Yes/no question. Resolves true when confirmed. */
export async function confirmDialog(o: { title: string; message?: string; confirmLabel?: string; danger?: boolean; icon?: JSX.Element }) {
  const r = await open({ title: o.title, message: o.message, confirmLabel: o.confirmLabel || (o.danger ? "Delete" : "OK"),
                         tone: o.danger ? "danger" : "warning", icon: o.icon });
  return r !== null;
}

/** Ask for one or more values. Resolves the values, or null if cancelled. */
export function formDialog(o: { title: string; message?: string; fields: Field[]; confirmLabel?: string; tone?: Tone; icon?: JSX.Element }) {
  return open({ ...o, confirmLabel: o.confirmLabel || "Save", tone: o.tone || "info" });
}

const ICONS: Record<Tone, JSX.Element> = {
  info: <Info size={26} />, warning: <HelpCircle size={26} />, danger: <Trash2 size={26} />, success: <PackageCheck size={26} />,
};

/** Mounted once (main.tsx). Shows queued dialogs one at a time. */
export function DialogHost() {
  const [queue, setQueue] = useState<Request[]>([]);
  useEffect(() => { push = (r) => setQueue((q) => [...q, r]); return () => { push = null; }; }, []);
  const current = queue[0];
  if (!current) return null;
  const close = (v: Record<string, string> | null) => { current.resolve(v); setQueue((q) => q.slice(1)); };
  return <DialogCard key={current.id} req={current} onClose={close} />;
}

function DialogCard({ req, onClose }: { req: Request; onClose: (v: Record<string, string> | null) => void }) {
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries((req.fields || []).map((f) => [f.name, f.value ?? ""])));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const firstRef = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    (req.fields?.length ? firstRef.current : okRef.current)?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(null); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    const errs: Record<string, string> = {};
    for (const f of req.fields || []) {
      const v = (values[f.name] ?? "").trim();
      if (f.required && !v) errs[f.name] = "Required.";
      else if (f.validate) { const m = f.validate(v, values); if (m) errs[f.name] = m; }
    }
    setErrors(errs);
    if (!Object.keys(errs).length) onClose(Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v.trim()])));
  }

  return (
    <div className="modal dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose(null)}>
      <form className="dialog-card" role="alertdialog" aria-modal="true" aria-labelledby={`dlg-${req.id}`} onSubmit={submit}>
        <div className={`dialog-icon ${req.tone}`} aria-hidden>{req.icon || (req.tone === "danger" ? <AlertTriangle size={26} /> : ICONS[req.tone])}</div>
        <h2 id={`dlg-${req.id}`}>{req.title}</h2>
        {req.message && <p>{req.message}</p>}
        {!!req.fields?.length && (
          <div className="dialog-fields">
            {req.fields.map((f, i) => (
              <label key={f.name}>{f.label}
                {f.type === "textarea"
                  ? <textarea ref={i === 0 ? firstRef : undefined} rows={3} value={values[f.name]} placeholder={f.placeholder}
                              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
                  : <input ref={i === 0 ? firstRef : undefined} type={f.type === "number" ? "text" : f.type || "text"}
                           inputMode={f.type === "number" ? "decimal" : undefined} value={values[f.name]} placeholder={f.placeholder}
                           onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />}
                {errors[f.name] ? <small className="error">{errors[f.name]}</small> : f.hint && <small className="muted">{f.hint}</small>}
              </label>
            ))}
          </div>
        )}
        <div className="dialog-actions">
          <button type="button" className="ghost-btn" onClick={() => onClose(null)}>{req.cancelLabel}</button>
          <button ref={okRef} type="submit" className={req.tone === "danger" ? "danger" : "primary"}>{req.confirmLabel}</button>
        </div>
      </form>
    </div>
  );
}
