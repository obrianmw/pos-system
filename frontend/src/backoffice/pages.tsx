import { errorText, toast } from "./ui";
import { formDialog } from "../Dialog";
import { useEffect, useRef, useState } from "react";
import { FileSpreadsheet, FileText, Printer } from "lucide-react";
import { useBrandingState } from "../BrandMark";
import { Invoice, printDoc } from "../docs";
import { api, money } from "../api";
import type { Ctx } from "./BackOffice";
import { Thumb } from "../CategoryBrowser";
import { CategoryTree, useCategoryTree } from "./categories";
import { ScanButton, ScannerModal } from "../Scanner";
import { useScannerInput } from "../scanning";
import { ListControls, SortHeader, useListState } from "./listing";
import { StockUpload } from "./stockupload";

// ---- shared bits ------------------------------------------------------------------------------
const hashQuery = () => new URLSearchParams(location.hash.split("?")[1] || "");
const when = (iso?: string) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "");

function useList<T = any>(url: string | null, ctx: Ctx, deps: unknown[] = []) {
  const [rows, setRows] = useState<T[] | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!url) return;
    setError("");
    api(url, { branch: ctx.branch }).then((d) => {
      const list = Array.isArray(d) ? d : d.results;
      setRows(list); setCount(Array.isArray(d) ? d.length : d.count);
    }).catch((e) => setError(e.message));
  }, [url, ctx.branch, tick, ...deps]);
  return { rows, count, error, reload: () => setTick((t) => t + 1) };
}

function Status({ rows, error, empty }: { rows: unknown[] | null; error: string; empty: string }) {
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;
  if (!rows.length) return <p className="muted">{empty}</p>;
  return null;
}

function branchName(ctx: Ctx, id: number) {
  return ctx.me.branches.find((b) => b.id === id)?.name || `#${id}`;
}

async function act(path: string, body?: unknown, branch?: string | null) {
  try { return await api(path, { method: "POST", body, branch }); }
  catch (e: any) { toast(errorText(e), "error"); return null; }
}

// ---- Sales -------------------------------------------------------------------------------------
export function Sales({ ctx }: { ctx: Ctx }) {
  const list = useListState({ sort: "-created_at", filters: hashQuery().get("review") === "1" ? { needs_review: "true" } : {} });
  const [open, setOpen] = useState<any>(null);
  const { rows, count, error, reload } = useList(`/sales/?${list.query({ page_size: "100" })}`, ctx);
  return (
    <div>
      <ListControls list={list} placeholder="Receipt no., customer or cashier" count={count} filters={[
        { key: "status", label: "Status", options: [["", "Any status"], ["completed", "Completed"], ["pending_payment", "Awaiting payment"], ["voided", "Voided"], ["cancelled", "Cancelled"]] },
        { key: "kind", label: "Type", options: [["", "Sales & refunds"], ["sale", "Sales"], ["refund", "Refunds"]] },
        { key: "needs_review", label: "Review", options: [["", "All"], ["true", "Needs review"]] }, { key: "from", label: "From", type: "date" }, { key: "to", label: "To", type: "date" }]} />
      <Status rows={rows} error={error} empty="No sales match." />
      {!!rows?.length && (
        <table className="grid-table clickable">
          <thead><tr><SortHeader list={list} k="number">Receipt</SortHeader><SortHeader list={list} k="created_at">Time</SortHeader>
            {!ctx.branch && <th>Branch</th>}<th>Cashier</th><SortHeader list={list} k="kind">Type</SortHeader>
            <SortHeader list={list} k="status">Status</SortHeader><SortHeader list={list} k="total" num>Total</SortHeader></tr></thead>
          <tbody>{rows.map((s) => (
            <tr key={s.id} onClick={() => setOpen(s)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setOpen(s)}>
              <td>{s.number} {s.created_offline && <span className="tag">offline</span>} {s.needs_review && <span className="tag warn">⚠ review</span>}</td>
              <td>{when(s.completed_at || s.created_at)}</td>
              {!ctx.branch && <td>{branchName(ctx, s.branch)}</td>}
              <td>{s.cashier_name}</td><td>{s.kind}</td><td>{s.status.replace("_", " ")}</td>
              <td className="num">{s.kind === "refund" ? "−" : ""}{money(s.total)}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {count > (rows?.length || 0) && <p className="muted">Showing the first {rows?.length} of {count}. Narrow the dates or search to see others.</p>}
      {open && <SaleDetail sale={open} branchName={branchName(ctx, open.branch)} onClose={() => setOpen(null)} onChanged={() => { setOpen(null); reload(); }} />}
    </div>
  );
}

function SaleDetail({ sale, onClose, onChanged, branchName }: { sale: any; onClose: () => void; onChanged: () => void; branchName?: string }) {
  const [note, setNote] = useState("");
  const [invoice, setInvoice] = useState(false);
  const brand = useBrandingState();
  const box = useRef<HTMLDivElement>(null);
  if (invoice) {
    return (
      <div className="modal" onClick={(e) => e.target === e.currentTarget && setInvoice(false)}><div className="card wide">
        <div ref={box} className="doc-preview"><Invoice s={(brand || {}) as any} sale={sale} branch={branchName || ""} /></div>
        <div className="actions">
          <button className="primary" onClick={() => printDoc(box.current)}><Printer size={16} />Print invoice</button>
          <button onClick={() => setInvoice(false)}>Back to sale</button>
        </div>
      </div></div>
    );
  }
  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}><div className="card wide">
      <h3>{sale.kind === "refund" ? "Refund" : "Sale"} {sale.number}</h3>
      <p className="muted">{when(sale.created_at)} · {sale.cashier_name} · {sale.status.replace("_", " ")}
        {sale.created_offline && " · made offline"}</p>
      <table className="grid-table">
        <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">List</th><th className="num">Charged</th><th className="num">Disc.</th><th className="num">Total</th></tr></thead>
        <tbody>{sale.lines.map((l: any) => (
          <tr key={l.id}><td>{l.description}{l.override && <span className="tag">override</span>}</td>
            <td className="num">{Number(l.quantity)}</td><td className="num">{money(l.list_price)}</td>
            <td className="num">{money(l.unit_price)}</td><td className="num">{money(l.discount_amount)}</td>
            <td className="num">{money(l.line_total)}</td></tr>
        ))}</tbody>
      </table>
      <p>Total <b>{money(sale.total)}</b> · VAT {money(sale.tax_total)} · discounts {money(sale.discount_total)}</p>
      {sale.payments.map((p: any) => <p key={p.id}>{p.method_name}: {money(p.amount)} — {p.status}{p.provider_reference && ` · ref ${p.provider_reference}`}</p>)}
      {sale.review_reason && <pre className="note">{sale.review_reason}</pre>}
      {sale.needs_review && (
        <div className="payrow">
          <input placeholder="What did you check?" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="primary" disabled={!note} onClick={async () => (await act(`/sales/${sale.id}/mark_reviewed/`, { note }, null)) && onChanged()}>Mark reviewed</button>
        </div>
      )}
      <div className="actions">
        {sale.kind === "sale" && sale.status === "completed" &&
          <button className="primary" onClick={() => setInvoice(true)}><FileText size={16} />Invoice</button>}
        <button className="link" onClick={onClose}>Close</button>
      </div>
    </div></div>
  );
}

// ---- Approvals ---------------------------------------------------------------------------------
export function Approvals({ ctx }: { ctx: Ctx }) {
  const list = useListState({ sort: "-created_at", filters: { status: "pending" } });
  const { rows, error, reload } = useList(`/overrides/?${list.query({ page_size: "100" })}`, ctx, []);
  const status = list.state.filters.status;
  useEffect(() => { if (status !== "pending") return; const id = setInterval(reload, 5000); return () => clearInterval(id); }, [status]);
  return (
    <div>
      <ListControls list={list} placeholder="Search item or reason" filters={[
        { key: "status", label: "Status", options: [["pending", "Pending"], ["approved", "Approved"], ["used", "Used"], ["rejected", "Rejected"], ["", "All"]] },
        { key: "kind", label: "Type", options: [["", "All types"], ["price", "Price change"], ["discount", "Discount"], ["void", "Void"], ["refund", "Refund"]] }, { key: "from", label: "From", type: "date" }, { key: "to", label: "To", type: "date" }]}
        right={status === "pending" && <span className="muted">Refreshes every 5 seconds</span>} />
      <Status rows={rows} error={error} empty="Nothing here." />
      {!!rows?.length && (
        <table className="grid-table">
          <thead><tr><SortHeader list={list} k="created_at">When</SortHeader>{!ctx.branch && <th>Branch</th>}<SortHeader list={list} k="kind">Type</SortHeader>
            <th>Item</th><th className="num">From</th><th className="num">To</th><th>Asked by</th><th>Reason</th><th>How</th><th /></tr></thead>
          <tbody>{rows.map((a) => (
            <tr key={a.id}>
              <td>{when(a.created_at)}</td>{!ctx.branch && <td>{branchName(ctx, a.branch)}</td>}
              <td>{a.kind}</td><td>{a.product_name}</td>
              <td className="num">{a.original_value && money(a.original_value)}</td><td className="num">{a.new_value && money(a.new_value)}</td>
              <td>{a.requested_by_name}</td><td>{a.reason}</td><td>{a.method}</td>
              <td>{a.status === "pending" && <>
                <button onClick={async () => (await act(`/overrides/${a.id}/approve/`, undefined, null)) && reload()}>Approve</button>
                <button className="link" onClick={async () => (await act(`/overrides/${a.id}/reject/`, undefined, null)) && reload()}>Reject</button>
              </>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

// ---- Stock -------------------------------------------------------------------------------------
export function Stock({ ctx }: { ctx: Ctx }) {
  const [low, setLow] = useState(hashQuery().get("low") === "1");
  const [scanning, setScanning] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [search, setSearch] = useState("");
  useScannerInput(setSearch, !scanning);
  const [category, setCategory] = useState<number | null>(null);
  const tree = useCategoryTree();
  const cat = category !== null ? `category_tree=${category}` : "";
  const url = low ? `/stock-levels/low/${cat ? `?${cat}` : ""}`
    : `/stock-levels/?ordering=product__name&page_size=200${search ? `&search=${encodeURIComponent(search)}` : ""}${cat ? `&${cat}` : ""}`;
  const { rows, error, reload } = useList(url, ctx);
  const sorter = useListState({ sort: "product_name" });
  const base = low && search ? rows?.filter((r: any) => r.product_name.toLowerCase().includes(search.toLowerCase())) ?? null : rows;
  const shown = base && sorter.apply(base as any[], {
    filters: { level: (r: any, v) => (v === "out" ? Number(r.quantity) <= 0 : v === "low" ? Number(r.quantity) <= Number(r.reorder_level) : Number(r.quantity) > Number(r.reorder_level)) },
    sorts: { product_name: (r: any) => r.product_name, category: (r: any) => r.category_path, qty: (r: any) => Number(r.quantity),
             reorder: (r: any) => Number(r.reorder_level), cost: (r: any) => Number(r.avg_cost), value: (r: any) => Number(r.quantity) * Number(r.avg_cost),
             branch: (r: any) => branchName(ctx, r.branch) },
  });
  async function adjust(r: any) {
    const v = await formDialog({
      title: `Adjust ${r.product_name}`, confirmLabel: "Save count",
      message: `${branchName(ctx, r.branch)} · the system shows ${Number(r.quantity)} ${r.unit || "in stock"}.`,
      fields: [
        { name: "counted", label: "Counted quantity", type: "number", value: String(Number(r.quantity)), required: true,
          validate: (x) => (isFinite(Number(x)) && Number(x) >= 0 ? null : "Enter a number, 0 or more.") },
        { name: "reason", label: "Reason", placeholder: "Stock take, breakage, expiry…", required: true,
          hint: "Recorded in the audit log and the stock history." },
      ],
    });
    if (!v) return;
    if (await act("/inventory/adjust/", { product: r.product, counted_quantity: v.counted, reason: v.reason }, String(r.branch))) reload();
  }
  const canAdjust = (branch: number) => ctx.me.org_permissions.includes("inventory.adjust") ||
    !!ctx.me.branches.find((b) => b.id === branch)?.permissions.includes("inventory.adjust");
  const place = tree.rows?.find((r) => r.id === category);
  return (
    <div className="catalog-layout">
      <CategoryTree rows={tree.rows} selected={category} onSelect={setCategory} allLabel="All stock" />
      <div style={{ minWidth: 0 }}>
      <div className="toolbar">
        <input type="search" placeholder="Search product, SKU or barcode" aria-label="Search stock" value={search} onChange={(e) => setSearch(e.target.value)} />
        <ScanButton onClick={() => setScanning(true)} />
        <a href="#/count" className="muted" style={{ fontSize: ".85rem" }}>Phone mode</a>
        {scanning && <ScannerModal onCode={setSearch} onClose={() => setScanning(false)} />}
        <label><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> At or below reorder level</label>
        <select aria-label="Stock level" value={sorter.state.filters.level || ""} onChange={(e) => sorter.setFilter("level", e.target.value)}>
          <option value="">Any level</option><option value="out">Out of stock</option><option value="low">Low</option><option value="ok">Healthy</option></select>
        {shown && <span className="muted">{shown.length} items</span>}
        <span className="spacer" />
        {(ctx.can("inventory.adjust") || ctx.can("inventory.receive")) &&
          <button onClick={() => setUploading(true)}><FileSpreadsheet size={16} />Upload from Excel</button>}
        {uploading && <StockUpload ctx={ctx} onClose={() => setUploading(false)} onDone={reload} />}
        {place && <span className="muted">{place.path}</span>}
      </div>
      <Status rows={shown} error={error} empty={low ? "Nothing is low. 👍" : place ? `No stock records in ${place.path}.` : "No stock records."} />
      {!!shown?.length && (
        <table className="grid-table">
          <thead><tr><SortHeader list={sorter} k="product_name">Product</SortHeader><SortHeader list={sorter} k="category">Category</SortHeader>
            {!ctx.branch && <SortHeader list={sorter} k="branch">Branch</SortHeader>}<SortHeader list={sorter} k="qty" num>On hand</SortHeader>
            <SortHeader list={sorter} k="reorder" num>Reorder at</SortHeader><SortHeader list={sorter} k="cost" num>Avg cost</SortHeader>
            <SortHeader list={sorter} k="value" num>Value</SortHeader><th /></tr></thead>
          <tbody>{shown.map((r: any) => {
            const isLow = Number(r.quantity) <= Number(r.reorder_level);
            return (
              <tr key={r.id}>
                <td><span className="name-cell"><span className="row-thumb"><Thumb src={r.image_url} name={r.product_name} /></span>
                  <span><b>{r.product_name}</b><br /><small className="muted">{r.sku}</small></span></span></td>
                <td className="muted">{r.category_path}</td>{!ctx.branch && <td>{branchName(ctx, r.branch)}</td>}
                <td className="num">{Number(r.quantity)} {isLow && <span className="tag warn">⚠ low</span>}</td>
                <td className="num">{Number(r.reorder_level)}</td><td className="num">{money(r.avg_cost)}</td>
                <td className="num">{money(Number(r.quantity) * Number(r.avg_cost))}</td>
                <td>{canAdjust(r.branch) && <button className="link" onClick={() => adjust(r)}>Adjust</button>}</td>
              </tr>
            );
          })}</tbody>
        </table>
      )}
      </div>
    </div>
  );
}

// ---- Accounting --------------------------------------------------------------------------------
export function Expenses({ ctx }: { ctx: Ctx }) {
  const list = useListState({ sort: "-date", filters: { status: "pending" } });
  const { rows, count, error, reload } = useList(`/accounting/expenses/?${list.query({ page_size: "100" })}`, ctx);
  const [adding, setAdding] = useState(false);
  const canApprove = (branch: number) => ctx.me.org_permissions.includes("accounting.reconcile") ||
    !!ctx.me.branches.find((b) => b.id === branch)?.permissions.includes("accounting.reconcile");
  return (
    <div>
      <ListControls list={list} placeholder="Description or receipt no." count={count} filters={[
        { key: "status", label: "Status", options: [["pending", "Pending"], ["approved", "Approved"], ["rejected", "Rejected"], ["", "All"]] }, { key: "from", label: "From", type: "date" }, { key: "to", label: "To", type: "date" }]}
        right={ctx.can("accounting.post") && <button className="primary" onClick={() => setAdding(true)}>+ New expense</button>} />
      <Status rows={rows} error={error} empty="No expenses match." />
      {!!rows?.length && (
        <table className="grid-table">
          <thead><tr><SortHeader list={list} k="date">Date</SortHeader>{!ctx.branch && <th>Branch</th>}<th>Description</th><th>Receipt</th>
            <SortHeader list={list} k="amount" num>Amount</SortHeader><SortHeader list={list} k="status">Status</SortHeader><th /></tr></thead>
          <tbody>{rows.map((x: any) => (
            <tr key={x.id}>
              <td>{x.date}</td>{!ctx.branch && <td>{branchName(ctx, x.branch)}</td>}<td>{x.description}</td><td>{x.receipt_number}</td>
              <td className="num">{money(x.amount)}</td><td>{x.status}</td>
              <td>{x.status === "pending" && canApprove(x.branch) && <>
                <button onClick={async () => (await act(`/accounting/expenses/${x.id}/approve/`, undefined, null)) && reload()}>Approve</button>
                <button className="link" onClick={async () => (await act(`/accounting/expenses/${x.id}/reject/`, undefined, null)) && reload()}>Reject</button>
              </>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {adding && <NewExpense ctx={ctx} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload(); }} />}
    </div>
  );
}

function NewExpense({ ctx, onClose, onSaved }: { ctx: Ctx; onClose: () => void; onSaved: () => void }) {
  const [accounts, setAccounts] = useState<any[]>([]);
  const branches = ctx.me.branches.filter((b) => b.permissions.includes("accounting.post") || ctx.me.org_permissions.includes("accounting.post"));
  const [f, setF] = useState({ branch: ctx.branch || String(branches[0]?.id || ""), expense_account: "", paid_from: "",
    amount: "", date: new Date().toISOString().slice(0, 10), description: "", receipt_number: "" });
  useEffect(() => { api("/accounting/accounts/?page_size=200", { branch: null }).then((d) => setAccounts(d.results)).catch(() => {}); }, []);
  const set = (k: keyof typeof f) => (e: any) => setF({ ...f, [k]: e.target.value });
  async function save() {
    if (await act("/accounting/expenses/", { ...f, branch: Number(f.branch) }, f.branch)) onSaved();
  }
  return (
    <div className="modal"><div className="card">
      <h3>New expense</h3>
      <label>Branch <select value={f.branch} onChange={set("branch")}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
      <label>Expense type <select value={f.expense_account} onChange={set("expense_account")}>
        <option value="">Choose…</option>{accounts.filter((a) => a.type === "expense").map((a) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}
      </select></label>
      <label>Paid from <select value={f.paid_from} onChange={set("paid_from")}>
        <option value="">Choose…</option>{accounts.filter((a) => a.type === "asset" && /cash|bank|wallet|mobile/i.test(a.name)).map((a) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}
      </select></label>
      <label>Amount <input inputMode="decimal" value={f.amount} onChange={set("amount")} /></label>
      <label>Date <input type="date" value={f.date} onChange={set("date")} /></label>
      <label>Description <input value={f.description} onChange={set("description")} /></label>
      <label>Receipt no. <input value={f.receipt_number} onChange={set("receipt_number")} /></label>
      <p className="muted"><small>Someone other than you approves it; only then is it posted to the books.</small></p>
      <button className="primary" disabled={!f.expense_account || !f.paid_from || !f.amount || !f.description} onClick={save}>Submit for approval</button>
      <button className="link" onClick={onClose}>Cancel</button>
    </div></div>
  );
}

export function TrialBalance({ ctx }: { ctx: Ctx }) {
  const [dateTo, setDateTo] = useState("");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setError(""); setData(null);
    const q = new URLSearchParams();
    if (ctx.branch) q.set("branch", ctx.branch);
    if (dateTo) q.set("date_to", dateTo);
    api(`/reports/trial-balance/?${q}`, { branch: null }).then(setData).catch((e) => setError(
      e.status === 403 && !ctx.branch ? "Whole-organization figures need an organization role. Pick a branch above." : e.message));
  }, [ctx.branch, dateTo]);
  const balanced = data && Number(data.total_debit).toFixed(2) === Number(data.total_credit).toFixed(2);
  const list = useListState({ sort: "code" });
  const tbRows = data ? list.apply(data.rows as any[], {
    text: (r: any) => `${r.code} ${r.name}`, filters: { type: (r: any, v) => r.type === v },
    sorts: { code: (r: any) => r.code, name: (r: any) => r.name, type: (r: any) => r.type, debit: (r: any) => Number(r.debit), credit: (r: any) => Number(r.credit) },
  }) : [];
  return (
    <div>
      <div className="toolbar"><label>As at <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></label>
        {data && <span className={balanced ? "ok" : "error"}>{balanced ? "✓ Balanced" : "✕ Out of balance"}</span>}</div>
      <ListControls list={list} placeholder="Search account" filters={[{ key: "type", label: "Type", options: [["", "All types"],
        ["asset", "Assets"], ["liability", "Liabilities"], ["equity", "Equity"], ["income", "Income"], ["expense", "Expenses"]] }]} />
      {error && <p className="error">{error}</p>}
      {data && (
        <table className="grid-table">
          <thead><tr><SortHeader list={list} k="code">Code</SortHeader><SortHeader list={list} k="name">Account</SortHeader>
            <SortHeader list={list} k="type">Type</SortHeader><SortHeader list={list} k="debit" num>Debit</SortHeader><SortHeader list={list} k="credit" num>Credit</SortHeader></tr></thead>
          <tbody>{tbRows.map((r: any) => (
            <tr key={r.code}><td>{r.code}</td><td>{r.name}</td><td>{r.type}</td>
              <td className="num">{Number(r.debit) ? money(r.debit) : ""}</td><td className="num">{Number(r.credit) ? money(r.credit) : ""}</td></tr>
          ))}</tbody>
          <tfoot><tr><th colSpan={3}>Total</th><th className="num">{money(data.total_debit)}</th><th className="num">{money(data.total_credit)}</th></tr></tfoot>
        </table>
      )}
    </div>
  );
}

// ---- HR ----------------------------------------------------------------------------------------
export function Leave({ ctx }: { ctx: Ctx }) {
  const list = useListState({ sort: "-created_at", filters: { status: "pending" } });
  const { rows, error, reload } = useList(`/hr/leave/?${list.query({ page_size: "100" })}`, { ...ctx, branch: null });
  return (
    <div>
      <ListControls list={list} placeholder="Search employee or reason" filters={[
        { key: "status", label: "Status", options: [["pending", "Pending"], ["approved", "Approved"], ["rejected", "Rejected"], ["", "All"]] }, { key: "from", label: "From", type: "date" }, { key: "to", label: "To", type: "date" }]} />
      <Status rows={rows} error={error} empty="No leave requests match." />
      {!!rows?.length && (
        <table className="grid-table">
          <thead><tr><th>Employee</th><th>Type</th><SortHeader list={list} k="start_date">From</SortHeader><SortHeader list={list} k="end_date">To</SortHeader>
            <th className="num">Days</th><th>Reason</th><SortHeader list={list} k="status">Status</SortHeader><th /></tr></thead>
          <tbody>{rows.map((l: any) => (
            <tr key={l.id}><td>{l.employee_name}</td><td>{l.leave_type}</td><td>{l.start_date}</td><td>{l.end_date}</td>
              <td className="num">{l.days}</td><td>{l.reason}</td><td>{l.status}</td>
              <td>{l.status === "pending" && ctx.can("hr.approve_leave") && <>
                <button onClick={async () => (await act(`/hr/leave/${l.id}/approve/`, undefined, null)) && reload()}>Approve</button>
                <button className="link" onClick={async () => (await act(`/hr/leave/${l.id}/reject/`, undefined, null)) && reload()}>Reject</button>
              </>}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

// ---- Admin -------------------------------------------------------------------------------------
export function AuditLog({ ctx }: { ctx: Ctx }) {
  const list = useListState({ sort: "-created_at" });
  const { rows, count, error } = useList(`/audit-logs/?${list.query({ page_size: "100" })}`, ctx);
  return (
    <div>
      <ListControls list={list} placeholder="Search action, person or object" count={count} filters={[
        { key: "action", label: "Action", options: [["", "All actions"], ...["sale.created", "sale.voided", "sale.refund", "sale.reviewed",
          "override.pin_failed", "auth.login_failed", "system.error", "till.open", "till.close", "cash.drop", "cash.confirmed", "vault.assigned",
          "inventory.adjust", "stockcount.posted", "user.role_assigned", "user.role_revoked", "journal.manual"].map((a) => [a, a] as [string, string])] }, { key: "from", label: "From", type: "date" }, { key: "to", label: "To", type: "date" }]} />
      <Status rows={rows} error={error} empty="No entries match." />
      {!!rows?.length && (
        <table className="grid-table">
          <thead><tr><SortHeader list={list} k="created_at">When</SortHeader><th>Who</th>{!ctx.branch && <th>Branch</th>}
            <SortHeader list={list} k="action">Action</SortHeader><th>Details</th></tr></thead>
          <tbody>{rows.map((a: any) => (
            <tr key={a.id}><td>{when(a.created_at)}</td><td>{a.actor_name}</td>{!ctx.branch && <td>{a.branch ? branchName(ctx, a.branch) : ""}</td>}
              <td>{a.action.includes("failed") || a.action === "system.error" ? <span className="tag warn">⚠ {a.action}</span> : a.action}</td>
              <td className="details">{Object.entries(a.data || {}).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ").slice(0, 300)}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
