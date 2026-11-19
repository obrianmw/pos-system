// Upload stock from an Excel (.xlsx) or CSV file: download the template, pick what the numbers mean,
// see a check of every row, then save it all at once (nothing is saved while any row has a problem).
import { useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Upload, X } from "lucide-react";
import { ApiError, apiDownload, apiForm, money } from "../api";
import type { Ctx } from "./BackOffice";
import { errorText, toast } from "./ui";
import { ListControls, SortHeader, useListState } from "./listing";
import { confirmDialog } from "../Dialog";

type Row = { row: number; sku: string; barcode: string; name: string; product: number | null; new_product: boolean;
  current: string; quantity: string; after: string; change: string; cost: string; price: string; category: string; errors: string[] };
type Result = { summary: { rows: number; errors: number; new_products: number; changes: number }; rows: Row[]; mode: string;
  branch: string; can_create: boolean; applied?: { rows: number; products_created: number; items_changed: number; value_added: string; reference: string } };

const n = (v: string) => (v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 }));

export function StockUpload({ ctx, onClose, onDone }: { ctx: Ctx; onClose: () => void; onDone: () => void }) {
  const branches = ctx.me.branches.filter((b) => ["inventory.adjust", "inventory.receive"].some((p) => b.permissions.includes(p))
    || ctx.me.org_permissions.includes("inventory.adjust"));
  const [branch, setBranch] = useState(ctx.branch || String(branches[0]?.id || ""));
  const [mode, setMode] = useState<"add" | "set">("add");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const list = useListState({ sort: "row" });
  const rows = useMemo(() => result ? list.apply(result.rows, {
    text: (r) => `${r.sku} ${r.barcode} ${r.name} ${r.errors.join(" ")}`,
    filters: { show: (r, v) => (v === "errors" ? r.errors.length > 0 : v === "new" ? r.new_product : v === "changes" ? !r.errors.length && Number(r.change) !== 0 : true) },
    sorts: { row: (r) => r.row, name: (r) => r.name || r.sku, current: (r) => Number(r.current), after: (r) => Number(r.after || 0), change: (r) => Number(r.change || 0) },
  }) : [], [result, list.state]);

  async function send(apply: boolean) {
    if (!file) return;
    setBusy(true); setError("");
    const form = new FormData();
    form.append("file", file); form.append("mode", mode); form.append("apply", apply ? "1" : "0");
    try {
      const r = await apiForm<Result>("/stock/import/", form, "POST", branch);
      setResult(r);
      if (r.applied) {
        toast(`Stock updated: ${r.applied.items_changed} item(s)${r.applied.products_created ? `, ${r.applied.products_created} new product(s)` : ""}.`, "success");
        onDone();
      }
    } catch (e) {
      if (e instanceof ApiError && e.data?.rows) setResult(e.data);
      setError(e instanceof ApiError ? (e.data?.file || e.data?.detail || errorText(e)) : errorText(e));
    } finally { setBusy(false); }
  }
  async function save() {
    if (!result) return;
    const s = result.summary;
    if (!(await confirmDialog({ title: mode === "add" ? "Add this stock?" : "Replace quantities with this count?", confirmLabel: "Save stock",
      message: `${s.changes} item(s) change at ${result.branch}${s.new_products ? `, ${s.new_products} new product(s) are created` : ""}. ` +
        (mode === "add" ? "The value is booked as stock received (opening stock)." : "Differences are booked as stock adjustments.") }))) return;
    send(true);
  }
  function pick(f: File | null) { setFile(f); setResult(null); setError(""); }

  const s = result?.summary;
  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="card wide upload" role="dialog" aria-label="Upload stock from Excel">
        <div className="card-head"><h3 style={{ margin: 0 }}><FileSpreadsheet size={18} style={{ verticalAlign: -3 }} /> Upload stock from Excel</h3>
          <button className="ghost-btn" aria-label="Close" onClick={onClose}><X size={18} /></button></div>

        {result?.applied ? (
          <div className="upload-done">
            <CheckCircle2 size={34} className="ok" />
            <p><b>Saved.</b> {result.applied.items_changed} item(s) changed{result.applied.products_created ? `, ${result.applied.products_created} product(s) created` : ""}
              {Number(result.applied.value_added) > 0 && <>, stock value {money(result.applied.value_added)} added</>}. Reference {result.applied.reference}.</p>
            <button className="primary" onClick={onClose}>Done</button>
          </div>
        ) : <>
          <ol className="steps">
            <li><button className="link" onClick={() => apiDownload("/stock/import/template/", "stock-upload.xlsx").catch((e) => toast(errorText(e), "error"))}>
              <Download size={14} /> Download the template</button> and fill it in Excel (or use your own sheet with SKU or Barcode and Quantity columns).</li>
            <li>
              <div className="inline" style={{ flexWrap: "wrap", gap: 10 }}>
                {branches.length > 1 && <select aria-label="Branch" value={branch} onChange={(e) => { setBranch(e.target.value); setResult(null); }}>
                  {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}
                <div className="seg" role="radiogroup" aria-label="What the quantities mean">
                  <button role="radio" aria-checked={mode === "add"} className={mode === "add" ? "on" : ""} onClick={() => { setMode("add"); setResult(null); }}>Add to stock</button>
                  <button role="radio" aria-checked={mode === "set"} className={mode === "set" ? "on" : ""} onClick={() => { setMode("set"); setResult(null); }}>Stock count (replace)</button>
                </div>
              </div>
              <small className="muted">{mode === "add" ? "Quantities are added: goods received without a purchase order, or opening stock."
                : "Quantities are what is on the shelf now; the system's quantity is replaced and the difference recorded."}</small>
            </li>
            <li>
              <div className={`drop ${file ? "has" : ""}`} onClick={() => input.current?.click()} onDragOver={(e) => e.preventDefault()}
                   onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files[0] || null); }} role="button" tabIndex={0}
                   onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}>
                <Upload size={20} />{file ? <b>{file.name}</b> : <span>Drop the .xlsx or .csv file here, or click to choose</span>}
              </div>
              <input ref={input} type="file" hidden accept=".xlsx,.xlsm,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
                     onChange={(e) => pick(e.target.files?.[0] || null)} />
            </li>
          </ol>
          {error && <p className="error" role="alert"><AlertTriangle size={15} style={{ verticalAlign: -2 }} /> {error}</p>}
          <div className="actions">
            <button className="primary" disabled={!file || busy} onClick={() => (result && !s?.errors ? save() : send(false))}>
              {busy ? "Working…" : result && !s?.errors ? `Save ${s?.changes} change(s)` : "Check the file"}</button>
            {result && <button onClick={() => send(false)} disabled={busy}>Check again</button>}
          </div>

          {result && s && <>
            <p className={s.errors ? "warn" : "ok"} style={{ margin: "6px 0" }}>
              {s.rows} row(s) · {s.changes} change(s){s.new_products ? ` · ${s.new_products} new product(s)` : ""}
              {s.errors ? ` · ${s.errors} row(s) need fixing - nothing is saved until every row is right` : " · all rows are fine"}</p>
            <ListControls list={list} placeholder="Search rows" count={rows.length} filters={[{ key: "show", label: "Show", options:
              [["", "All rows"], ["errors", "Problems only"], ["changes", "Changes only"], ["new", "New products"]] }]} />
            <div className="upload-table">
              <table className="grid-table">
                <thead><tr><SortHeader list={list} k="row" num>Row</SortHeader><SortHeader list={list} k="name">Product</SortHeader>
                  <SortHeader list={list} k="current" num>Now</SortHeader><SortHeader list={list} k="change" num>Change</SortHeader>
                  <SortHeader list={list} k="after" num>After</SortHeader><th>Check</th></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={r.row} className={r.errors.length ? "row-bad" : ""}>
                    <td className="num">{r.row}</td>
                    <td><b>{r.name || "—"}</b> <span className="muted">{r.sku}{r.barcode && ` · ${r.barcode}`}</span>
                      {r.new_product && <span className="tag status-partial">new{r.category && ` · ${r.category}`}</span>}</td>
                    <td className="num">{n(r.current)}</td>
                    <td className={`num ${Number(r.change) < 0 ? "error" : Number(r.change) > 0 ? "ok" : ""}`}>{r.change && Number(r.change) > 0 ? "+" : ""}{n(r.change)}</td>
                    <td className="num">{n(r.after)}</td>
                    <td>{r.errors.length ? <span className="error">{r.errors.join("; ")}</span> : <span className="ok">OK</span>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </>}
        </>}
      </div>
    </div>
  );
}
