// Branding page (organization admins): logo, name, brand colours with automatic contrast, and the
// layout of receipts, invoices and proformas - each with a live preview.
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, FileText, ImageUp, Palette, Receipt as ReceiptIcon, Save, Trash2, TriangleAlert } from "lucide-react";
import { api, apiForm } from "../api";
import { BrandingSettings, deriveBrand, getBranding, setBranding, SURFACES } from "../brand";
import { Invoice, Proforma, Receipt, SAMPLE_LINES } from "../docs";
import type { Ctx } from "./BackOffice";
import { errorText, toast } from "./ui";

const PRESETS: [string, string, string][] = [
  ["Teal", "#0f766e", "#4f46e5"], ["Ocean", "#1d4ed8", "#0891b2"], ["Forest", "#15803d", "#ca8a04"],
  ["Crimson", "#b91c1c", "#f59e0b"], ["Royal", "#6d28d9", "#db2777"], ["Sunshine", "#facc15", "#0ea5e9"],
];
const HEX = /^#[0-9a-fA-F]{6}$/;

export function Branding({ ctx }: { ctx: Ctx }) {
  const [saved, setSaved] = useState<BrandingSettings | null>(getBranding());
  const [f, setF] = useState<BrandingSettings | null>(null);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const [clearLogo, setClearLogo] = useState(false);
  const [tab, setTab] = useState<"look" | "documents">("look");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const canEdit = ctx.canOrg("org.admin");

  useEffect(() => {
    api<BrandingSettings>("/branding/settings/", { branch: null }).then((b) => { setSaved(b); setF(b); }).catch((e) => toast(errorText(e), "error"));
  }, []);
  useEffect(() => () => { if (logoPreview) URL.revokeObjectURL(logoPreview); }, [logoPreview]);

  if (!f || !saved) return <div className="skeleton" style={{ height: 320 }} />;
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });
  const logoUrl = clearLogo ? null : logoPreview || f.logo_url;
  const preview = { ...f, logo_url: logoUrl } as BrandingSettings;
  const dirty = logoFile || clearLogo || JSON.stringify(f) !== JSON.stringify(saved);

  function pickLogo(file: File | undefined) {
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) { toast("Use a PNG, JPEG or WebP image.", "error"); return; }
    if (file.size > 3 * 1024 * 1024) { toast("The logo must be under 3 MB.", "error"); return; }
    setLogoFile(file); setClearLogo(false); setLogoPreview(URL.createObjectURL(file));
  }

  async function save() {
    if (!HEX.test(f!.primary_color) || !HEX.test(f!.accent_color)) { toast("Colours must look like #0f766e.", "error"); return; }
    setBusy(true); setErrors({});
    const editable = Object.fromEntries(Object.entries(f!).filter(([k]) => !["logo_url", "name", "updated_at"].includes(k)));
    try {
      let out: BrandingSettings;
      if (logoFile || clearLogo) {
        const form = new FormData();
        Object.entries(editable).forEach(([k, v]) => form.append(k, typeof v === "boolean" ? (v ? "true" : "false") : String(v ?? "")));
        if (logoFile) form.append("logo", logoFile);
        if (clearLogo) form.append("clear_logo", "true");
        out = await apiForm<BrandingSettings>("/branding/settings/", form, "PATCH");
      } else {
        out = await api<BrandingSettings>("/branding/settings/", { method: "PATCH", body: editable, branch: null });
      }
      setSaved(out); setF(out); setLogoFile(null); setLogoPreview(null); setClearLogo(false);
      setBranding(out);
      toast("Branding saved. Everyone sees it the next time their screen loads.", "success");
    } catch (e: any) {
      if (e?.data && typeof e.data === "object") setErrors(Object.fromEntries(Object.entries(e.data).map(([k, v]) => [k, Array.isArray(v) ? v.join(" ") : String(v)])));
      toast(errorText(e), "error");
    } finally { setBusy(false); }
  }

  return (
    <div>
      <div className="toolbar">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "look"} className={tab === "look" ? "on" : ""} onClick={() => setTab("look")}><Palette size={15} />Look &amp; feel</button>
          <button role="tab" aria-selected={tab === "documents"} className={tab === "documents" ? "on" : ""} onClick={() => setTab("documents")}><FileText size={15} />Receipts &amp; documents</button>
        </div>
        <span className="spacer" />
        {dirty && <span className="muted">Unsaved changes</span>}
        {dirty && <button className="link" onClick={() => { setF(saved); setLogoFile(null); setLogoPreview(null); setClearLogo(false); }}>Discard</button>}
        {canEdit && <button className="primary" disabled={busy || !dirty} onClick={save}><Save size={16} />Save branding</button>}
      </div>
      {!canEdit && <p className="warn-box">Only organization admins can change branding. You can look but not save.</p>}
      <fieldset disabled={!canEdit}>
        {tab === "look"
          ? <LookAndFeel f={f} setF={setF} set={set} errors={errors} logoUrl={logoUrl} pickLogo={pickLogo}
                         removeLogo={() => { setLogoFile(null); setLogoPreview(null); setClearLogo(true); }} />
          : <Documents f={preview} set={set} setF={setF} errors={errors} />}
      </fieldset>
    </div>
  );
}

// ---- look & feel --------------------------------------------------------------------------------
function ColorField({ label, value, onChange, error }: { label: string; value: string; onChange: (v: string) => void; error?: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <label>{label}
      <span className="inline">
        <input type="color" className="swatch-input" value={HEX.test(value) ? value : "#000000"} onChange={(e) => onChange(e.target.value)} aria-label={`${label} picker`} />
        <input value={text} maxLength={7} onChange={(e) => { setText(e.target.value); if (HEX.test(e.target.value)) onChange(e.target.value.toLowerCase()); }}
               aria-label={`${label} hex code`} style={{ fontFamily: "ui-monospace, Consolas, monospace", maxWidth: 120 }} />
      </span>
      {(error || (!HEX.test(text) && text)) && <small className="error">{error || "Use a colour like #0f766e"}</small>}
    </label>
  );
}

function LookAndFeel({ f, setF, set, errors, logoUrl, pickLogo, removeLogo }: {
  f: BrandingSettings; setF: (b: BrandingSettings) => void; set: (k: string) => (e: any) => void; errors: Record<string, string>;
  logoUrl: string | null; pickLogo: (file: File | undefined) => void; removeLogo: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const derived = useMemo(() => deriveBrand(f.primary_color, f.accent_color), [f.primary_color, f.accent_color]);
  return (
    <div className="brand-grid">
      <section className="card">
        <h4 style={{ marginTop: 0 }}>Identity</h4>
        <div className="form-grid">
          <label>Shop name in the app<input value={f.display_name || ""} onChange={set("display_name")} placeholder={f.name} maxLength={80} /></label>
          <label>Tagline<input value={f.tagline || ""} onChange={set("tagline")} placeholder="e.g. Groceries, fresh food and more" maxLength={120} /></label>
        </div>
        <h4>Logo</h4>
        <div className="logo-drop" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); pickLogo(e.dataTransfer.files[0]); }}>
          {logoUrl ? <img src={logoUrl} alt="Logo preview" /> : <span className="muted">No logo yet - the cart mark is used.</span>}
          <div className="actions" style={{ marginTop: 0 }}>
            <button type="button" onClick={() => fileRef.current?.click()}><ImageUp size={16} />{logoUrl ? "Replace" : "Upload logo"}</button>
            {logoUrl && <button type="button" className="ghost" onClick={removeLogo}><Trash2 size={16} />Remove</button>}
          </div>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => pickLogo(e.target.files?.[0])} />
          <small className="muted">PNG with a transparent background works best on both themes. Shrunk to 512 px.</small>
          {errors.logo && <small className="error">{errors.logo}</small>}
        </div>
        <h4>Brand colours</h4>
        <div className="form-grid">
          <ColorField label="Main colour" value={f.primary_color} error={errors.primary_color} onChange={(v) => setF({ ...f, primary_color: v })} />
          <ColorField label="Accent colour" value={f.accent_color} error={errors.accent_color} onChange={(v) => setF({ ...f, accent_color: v })} />
        </div>
        <div className="presets" aria-label="Colour presets">
          {PRESETS.map(([name, p, a]) => (
            <button key={name} type="button" className={f.primary_color === p && f.accent_color === a ? "on" : ""}
                    onClick={() => setF({ ...f, primary_color: p, accent_color: a })} title={name}>
              <span className="dot" style={{ background: p }} /><span className="dot" style={{ background: a }} />{name}
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <h4 style={{ marginTop: 0 }}>Preview</h4>
        <p className="muted" style={{ margin: 0, fontSize: ".85rem" }}>
          Your colours are adjusted automatically so text and buttons stay readable in each theme. Chart colours never change, so their meaning stays the same.
        </p>
        <div className="theme-previews">
          <MiniApp mode="light" name={f.display_name || f.name} logo={logoUrl} vars={derived.light} />
          <MiniApp mode="dark" name={f.display_name || f.name} logo={logoUrl} vars={derived.dark} />
        </div>
        <h4>Contrast check</h4>
        <table className="grid-table contrast-table">
          <thead><tr><th>Theme</th><th>Where</th><th>Colour</th><th className="num">Contrast</th><th>Result</th></tr></thead>
          <tbody>{derived.report.map((r, i) => (
            <tr key={i}><td>{r.mode === "light" ? "Light" : "Dark"}</td><td>{r.label}</td>
              <td><span className="chip-color" style={{ background: r.against, color: r.color, outline: "1px solid var(--line)" }}>A</span>
                <code>{r.color}</code> on <code>{r.against}</code></td>
              <td className="num">{r.ratio.toFixed(1)} : 1</td>
              <td>{r.ratio >= r.need ? <span className="ok"><Check size={14} style={{ verticalAlign: -2 }} /> Readable</span>
                : <span className="warn"><TriangleAlert size={14} style={{ verticalAlign: -2 }} /> Low</span>}</td></tr>
          ))}</tbody>
        </table>
        {(derived.adjusted.light || derived.adjusted.dark) && (
          <p className="muted" style={{ fontSize: ".82rem" }}>
            Buttons {derived.adjusted.fillLight || derived.adjusted.fillDark ? "use a slightly adjusted shade" : "keep your exact colour"} with
            whichever text reads best on them.
            {derived.adjusted.light && " Links and highlights are a little darker in light mode."}
            {derived.adjusted.dark && " They are a little lighter in dark mode."} The hue stays the same; printed documents use the light-mode shade.
          </p>
        )}
      </section>
    </div>
  );
}

/** A tiny screen drawn with the derived colours, so admins see both themes at once. */
function MiniApp({ mode, name, logo, vars }: { mode: "light" | "dark"; name: string; logo: string | null; vars: Record<string, string> }) {
  const surf = mode === "light"
    ? { "--card": SURFACES.light.card, "--bg": SURFACES.light.bg, "--text": "#111827", "--muted": "#6b7280", "--line": "#e5e7eb" }
    : { "--card": SURFACES.dark.card, "--bg": SURFACES.dark.bg, "--text": "#e6e9ee", "--muted": "#94a0b0", "--line": "#243040" };
  return (
    <div className="mini-app" style={{ ...surf, ...vars } as React.CSSProperties} aria-label={`${mode} theme preview`}>
      <div className="mini-top">
        {logo ? <img src={logo} alt="" /> : <span className="mini-mark" />}
        <b>{name}</b><span className="mini-mode">{mode === "light" ? "Light" : "Dark"}</span>
      </div>
      <div className="mini-body">
        <div className="mini-nav"><span className="active">Dashboard</span><span>Sales</span><span>Stock</span></div>
        <div className="mini-main">
          <div>Sales today <a href="#" onClick={(e) => e.preventDefault()}>View report</a></div>
          <div className="mini-badge">3 approvals waiting</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span className="mini-btn">Pay now</span><span className="mini-btn ghost">Cancel</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- documents ----------------------------------------------------------------------------------
function Documents({ f, set, setF, errors }: { f: BrandingSettings; set: (k: string) => (e: any) => void; setF: (b: BrandingSettings) => void; errors: Record<string, string> }) {
  const [doc, setDoc] = useState<"receipt" | "invoice" | "proforma">("receipt");
  const E = ({ k }: { k: string }) => (errors[k] ? <small className="error">{errors[k]}</small> : null);
  const today = new Date().toISOString();
  const validUntil = new Date(Date.now() + Number(f.proforma_validity_days || 14) * 86400000).toISOString().slice(0, 10);
  const totals = { subtotal: "34600", tax_total: "2492.71", total: "34600" };
  const saleLines = SAMPLE_LINES.map((l) => ({ description: l.name, sku: l.sku, quantity: String(l.qty), unit_price: String(l.unit_price), tax_amount: String(l.tax_amount), line_total: String(l.line_total) }));
  return (
    <div className="brand-grid">
      <section className="card">
        <h4 style={{ marginTop: 0 }}>On every document</h4>
        <div className="form-grid">
          <label>Business name<input value={f.doc_business_name || ""} onChange={set("doc_business_name")} placeholder={f.name} /></label>
          <label>TPIN / VAT number<input value={f.doc_tax_number || ""} onChange={set("doc_tax_number")} /></label>
          <label>Phone<input value={f.doc_phone || ""} onChange={set("doc_phone")} /></label>
          <label>Email<input value={f.doc_email || ""} onChange={set("doc_email")} /></label>
          <label style={{ gridColumn: "1 / -1" }}>Address<textarea rows={2} value={f.doc_address || ""} onChange={set("doc_address")} /></label>
          <label className="check"><input type="checkbox" checked={!!f.doc_show_logo} onChange={set("doc_show_logo")} /> Print the logo</label>
        </div>
        <div className="tabs" role="tablist" style={{ marginTop: 14 }}>
          {([["receipt", "Receipt"], ["invoice", "Invoice"], ["proforma", "Proforma"]] as const).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={doc === k} className={doc === k ? "on" : ""} onClick={() => setDoc(k)}>
              {k === "receipt" ? <ReceiptIcon size={15} /> : <FileText size={15} />}{l}</button>
          ))}
        </div>
        {doc === "receipt" && (
          <div className="form-grid">
            <label>Paper width
              <select value={f.receipt_paper} onChange={set("receipt_paper")}><option value="80mm">80 mm (standard)</option><option value="58mm">58 mm (small)</option></select></label>
            <span />
            <label style={{ gridColumn: "1 / -1" }}>Header (under the shop details)<textarea rows={2} value={f.receipt_header || ""} onChange={set("receipt_header")} placeholder="e.g. Open 7am - 8pm every day" /></label>
            <label style={{ gridColumn: "1 / -1" }}>Footer<textarea rows={2} value={f.receipt_footer || ""} onChange={set("receipt_footer")} placeholder="e.g. Goods sold are not returnable after 7 days" /></label>
            <label className="check"><input type="checkbox" checked={!!f.receipt_show_vat} onChange={set("receipt_show_vat")} /> Show VAT included</label>
            <label className="check"><input type="checkbox" checked={!!f.receipt_show_cashier} onChange={set("receipt_show_cashier")} /> Show cashier name</label>
            <label className="check"><input type="checkbox" checked={!!f.receipt_show_barcode_sku} onChange={set("receipt_show_barcode_sku")} /> Show product codes</label>
          </div>
        )}
        {doc === "invoice" && (
          <div className="form-grid">
            <label>Title<input value={f.invoice_title || ""} onChange={set("invoice_title")} maxLength={40} /><E k="invoice_title" /></label>
            <label>Number prefix<input value={f.invoice_prefix || ""} onChange={set("invoice_prefix")} maxLength={10} /><E k="invoice_prefix" />
              <small className="muted">Invoice number = prefix + receipt number</small></label>
            <label style={{ gridColumn: "1 / -1" }}>Terms<textarea rows={2} value={f.invoice_terms || ""} onChange={set("invoice_terms")} /></label>
            <label style={{ gridColumn: "1 / -1" }}>How to pay (bank / mobile money)<textarea rows={3} value={f.invoice_payment_details || ""} onChange={set("invoice_payment_details")} placeholder={"e.g. National Bank, Acc 100200300\nAirtel Money 0999 000 000"} /></label>
            <label style={{ gridColumn: "1 / -1" }}>Footer<textarea rows={2} value={f.invoice_footer || ""} onChange={set("invoice_footer")} /></label>
          </div>
        )}
        {doc === "proforma" && (
          <div className="form-grid">
            <label>Title<input value={f.proforma_title || ""} onChange={set("proforma_title")} maxLength={40} /></label>
            <label>Number prefix<input value={f.proforma_prefix || ""} onChange={set("proforma_prefix")} maxLength={10} /><E k="proforma_prefix" /></label>
            <label>Valid for (days)<input type="number" min={1} max={365} value={f.proforma_validity_days ?? 14}
              onChange={(e) => setF({ ...f, proforma_validity_days: Number(e.target.value) })} /><E k="proforma_validity_days" /></label>
            <span />
            <label style={{ gridColumn: "1 / -1" }}>Terms<textarea rows={2} value={f.proforma_terms || ""} onChange={set("proforma_terms")} /></label>
            <label style={{ gridColumn: "1 / -1" }}>Footer<textarea rows={2} value={f.proforma_footer || ""} onChange={set("proforma_footer")} /></label>
            <small className="muted" style={{ gridColumn: "1 / -1" }}>Proformas also print the “How to pay” details from the Invoice tab.</small>
          </div>
        )}
      </section>
      <section className="card">
        <h4 style={{ marginTop: 0 }}>Preview <span className="muted" style={{ fontWeight: 400 }}>· sample data</span></h4>
        <div className="doc-preview">
          {doc === "receipt" && <Receipt s={f} branch="Lilongwe City Centre" number="LL-0000123" date={today} cashier="Lilongwe Cashier"
            items={SAMPLE_LINES} total={34600} tax={2492.71} payments={[{ name: "Cash", amount: 34600, change: 400 }]} />}
          {doc === "invoice" && <div style={{ zoom: 0.62 }}><Invoice s={f} branch="Lilongwe City Centre" customer={["Kondwani Phiri", "0999 000 111"]}
            sale={{ number: "LL-0000123", created_at: today, ...totals, discount_total: "0", lines: saleLines, payments: [{ method_name: "Cash", amount: "34600" }] }} /></div>}
          {doc === "proforma" && <div style={{ zoom: 0.62 }}><Proforma s={f} branch="Lilongwe City Centre"
            pf={{ number: `${f.proforma_prefix || ""}000123`, created_at: today, valid_until: validUntil, customer_name: "Mzuzu Primary School",
                  customer_phone: "0888 000 222", note: "Term 1 supplies", ...totals,
                  lines: SAMPLE_LINES.map((l) => ({ name: l.name, sku: l.sku, quantity: String(l.qty), unit_price: String(l.unit_price), tax_amount: String(l.tax_amount), line_total: String(l.line_total) })) }} /></div>}
        </div>
      </section>
    </div>
  );
}
