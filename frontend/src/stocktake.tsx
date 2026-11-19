// Stock takes. `StockCountPhone` is the phone screen at #/count (scan to count, scan to look up);
// `StockTakes` is the back-office page (start, follow, verify and post counts).
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, CheckCircle2, ClipboardCheck, Minus, Plus, ScanLine, Search, Smartphone, Trash2, Undo2, XCircle } from "lucide-react";
import { api, money } from "./api";
import type { Me } from "./App";
import { QrImage, ScannerModal } from "./Scanner";
import { useScannerInput } from "./scanning";
import { errorText, toast } from "./backoffice/ui";
import { confirmDialog, formDialog } from "./Dialog";
import { ListControls, SortHeader, useListState } from "./backoffice/listing";
import type { Ctx } from "./backoffice/BackOffice";
import { BrandMark } from "./BrandMark";
import { ThemeSwitch } from "./theme";
import { SystemTabs } from "./SystemTabs";

type Line = { id: number; product: number; product_name: string; sku: string; barcode: string; unit: string;
  counted_qty: string; counted_by_name: string; counted_at: string; expected_qty: string | null; verified_qty: string | null;
  final_qty?: string; variance: string | null };
type Count = { id: number; branch: number; branch_name: string; number: string; title: string; category_name: string;
  blind: boolean; status: "counting" | "submitted" | "posted" | "cancelled"; status_label: string; note: string;
  created_by_name: string; created_at: string; submitted_by_name: string; verified_by_name: string; verified_at: string | null;
  line_count: number; lines?: Line[]; can_count?: boolean; can_verify?: boolean; i_counted?: boolean; is_verifier?: boolean;
  summary?: { lines: number; differences: number; short: string; over: string } };
type Lookup = { id: number; name: string; sku: string; barcode: string; unit: string; category: string; reorder_level: string;
  branches: { id: number; name: string; quantity: string; price: string }[] };

const qty = (v: string | number | null | undefined) => (v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 }));
const COUNT_PERMS = ["inventory.count", "inventory.verify", "inventory.adjust"];
export const canCount = (perms: string[]) => COUNT_PERMS.some((p) => perms.includes(p));
const statusTag = (s: Count["status"]) => ({ counting: "status-partial", submitted: "warn", posted: "status-received", cancelled: "status-cancelled" }[s]);

// =================================================================================================
// Phone screen
// =================================================================================================
export function StockCountPhone({ me, onLogout, onBack }: { me: Me; onLogout: () => void; onBack?: () => void }) {
  const branches = me.branches.filter((b) => canCount(b.permissions) || b.permissions.includes("inventory.view") || b.permissions.includes("pos.sell"));
  const [branch, setBranch] = useState(String(branches[0]?.id ?? ""));
  const [tab, setTab] = useState<"count" | "lookup">(branches.some((b) => canCount(b.permissions)) ? "count" : "lookup");
  const counts = canCount(branches.find((b) => String(b.id) === branch)?.permissions || []);
  return (
    <div className="phone">
      <header className="phone-head">
        {onBack ? <button className="ghost-btn" aria-label="Back" onClick={onBack}><ArrowLeft size={18} /></button> : <BrandMark size={26} />}
        <b>Stock</b>
        <SystemTabs me={me} current="count" />
        {branches.length > 1 && <select aria-label="Branch" value={branch} onChange={(e) => setBranch(e.target.value)}>
          {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}
        <span className="spacer" />
        <ThemeSwitch compact />
        <button className="link" onClick={onLogout}>Log out</button>
      </header>
      <div className="seg phone-tabs" role="tablist">
        {counts && <button role="tab" aria-selected={tab === "count"} className={tab === "count" ? "on" : ""} onClick={() => setTab("count")}><ClipboardCheck size={16} />Count</button>}
        <button role="tab" aria-selected={tab === "lookup"} className={tab === "lookup" ? "on" : ""} onClick={() => setTab("lookup")}><Search size={16} />Look up</button>
      </div>
      {!branch ? <p className="muted">You have no branch to count at.</p>
        : tab === "count" && counts ? <PhoneCount key={branch} branch={branch} /> : <PhoneLookup />}
    </div>
  );
}

function PhoneLookup() {
  const [scan, setScan] = useState(false);
  const [item, setItem] = useState<Lookup | null>(null);
  const [code, setCode] = useState("");
  async function find(c: string) {
    if (!c.trim()) return;
    try { setItem(await api<Lookup>(`/stock/lookup/?code=${encodeURIComponent(c.trim())}`, { branch: null })); setCode(""); }
    catch (e) { setItem(null); toast(errorText(e), "error"); }
  }
  useScannerInput(find, !scan);
  return (
    <div className="phone-body">
      <button className="primary big-scan" onClick={() => setScan(true)}><ScanLine size={22} />Scan to look up</button>
      <form className="inline" onSubmit={(e) => { e.preventDefault(); find(code); }}>
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Barcode or SKU" aria-label="Barcode or SKU" />
        <button type="submit">Find</button>
      </form>
      {item && <div className="card">
        <h3 style={{ margin: 0 }}>{item.name}</h3>
        <p className="muted" style={{ margin: "2px 0 10px" }}>{item.sku}{item.barcode && ` · ${item.barcode}`}{item.category && ` · ${item.category}`}</p>
        <table className="grid-table"><thead><tr><th>Branch</th><th className="num">In stock</th><th className="num">Price</th></tr></thead>
          <tbody>{item.branches.map((b) => <tr key={b.id}><td>{b.name}</td>
            <td className={`num ${Number(b.quantity) <= Number(item.reorder_level) ? "error" : ""}`}>{qty(b.quantity)} {item.unit}</td>
            <td className="num">{money(b.price)}</td></tr>)}</tbody></table>
      </div>}
      {scan && <ScannerModal title="Scan to look up" onCode={find} onClose={() => setScan(false)} />}
    </div>
  );
}

function PhoneCount({ branch }: { branch: string }) {
  const [list, setList] = useState<Count[] | null>(null);
  const [open, setOpen] = useState<Count | null>(null);
  const load = () => api(`/stock-counts/?status=counting&page_size=50`, { branch }).then((d) => setList(d.results)).catch((e) => { setList([]); toast(errorText(e), "error"); });
  useEffect(() => { load(); }, []);
  async function create() {
    const v = await formDialog({ title: "New stock take", confirmLabel: "Start counting", icon: <ClipboardCheck size={26} />,
      fields: [{ name: "title", label: "What are you counting?", placeholder: "e.g. Aisle 3, fridges", required: true }] });
    if (!v) return;
    try { const c = await api<Count>("/stock-counts/", { body: v, branch }); setOpen(c); }
    catch (e) { toast(errorText(e), "error"); }
  }
  if (open) return <PhoneSheet id={open.id} branch={branch} onBack={() => { setOpen(null); load(); }} />;
  return (
    <div className="phone-body">
      <button className="primary big-scan" onClick={create}><Plus size={20} />Start a new stock take</button>
      <h4 style={{ margin: "6px 0 0" }}>Open stock takes</h4>
      {list === null && <div className="skeleton" style={{ height: 80 }} />}
      {list && !list.length && <p className="muted">None open. Start one above, or ask your verifier for the one to join.</p>}
      {list?.map((c) => (
        <button key={c.id} className="phone-row" onClick={() => setOpen(c)}>
          <span><b>{c.title}</b><small className="muted">{c.number} · {c.line_count} items · by {c.created_by_name}</small></span>
          <ScanLine size={18} />
        </button>
      ))}
    </div>
  );
}

function PhoneSheet({ id, branch, onBack }: { id: number; branch: string; onBack: () => void }) {
  const [c, setC] = useState<Count | null>(null);
  const [scan, setScan] = useState(false);
  const [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);
  const [setMode, setSetMode] = useState(false);
  const load = () => api<Count>(`/stock-counts/${id}/`, { branch }).then(setC).catch((e) => toast(errorText(e), "error"));
  useEffect(() => { load(); }, []);
  const timer = useRef<number>();
  function show(ok: boolean, text: string) {
    setFlash({ ok, text }); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => setFlash(null), 2500);
  }
  async function record(body: Record<string, unknown>) {
    try {
      const r = await api<{ line: Line }>(`/stock-counts/${id}/scan/`, { body, branch });
      show(true, `${r.line.product_name}: ${qty(r.line.counted_qty)}`); load();
      return r.line;
    } catch (e) { show(false, errorText(e)); navigator.vibrate?.([80, 60, 80]); }
  }
  async function onCode(code: string) {
    if (!setMode) return record({ code });
    const v = await formDialog({ title: `How many on the shelf?`, message: `Code ${code}`, confirmLabel: "Save",
      fields: [{ name: "qty", label: "Quantity", type: "number", required: true }] });
    if (v) record({ code, qty: v.qty, mode: "set" });
  }
  useScannerInput((code) => { onCode(code); }, !scan && !!c?.can_count);
  async function editLine(l: Line) {
    const v = await formDialog({ title: l.product_name, confirmLabel: "Save", fields: [
      { name: "qty", label: `Counted (${l.unit || "units"})`, type: "number", value: String(Number(l.counted_qty)), required: true }] });
    if (v) record({ product: l.product, qty: v.qty, mode: "set" });
  }
  async function bump(l: Line, d: number) { record({ product: l.product, qty: String(Math.max(0, Number(l.counted_qty) + d)), mode: "set" }); }
  async function remove(l: Line) {
    if (!(await confirmDialog({ title: `Remove ${l.product_name}?`, message: "Its count is deleted from this stock take.", confirmLabel: "Remove", danger: true }))) return;
    try { setC(await api(`/stock-counts/${id}/lines/${l.id}/remove/`, { method: "POST", branch })); } catch (e) { toast(errorText(e), "error"); }
  }
  async function submit() {
    if (!(await confirmDialog({ title: "Finish counting?", message: "The stock take goes to a verifier. Nobody can add counts after this.", confirmLabel: "Submit" }))) return;
    try { await api(`/stock-counts/${id}/submit/`, { method: "POST", branch }); toast("Sent for verification.", "success"); onBack(); }
    catch (e) { toast(errorText(e), "error"); }
  }
  if (!c) return <div className="phone-body"><div className="skeleton" style={{ height: 200 }} /></div>;
  const lines = [...(c.lines || [])].sort((a, b) => b.counted_at.localeCompare(a.counted_at));
  return (
    <div className="phone-body">
      <div className="inline" style={{ justifyContent: "space-between" }}>
        <button className="ghost-btn" onClick={onBack}><ArrowLeft size={16} />All</button>
        <span className="muted">{c.number} · {lines.length} items</span>
      </div>
      <h3 style={{ margin: 0 }}>{c.title}</h3>
      {c.can_count ? <>
        <button className="primary big-scan" onClick={() => setScan(true)}><ScanLine size={22} />Scan items</button>
        <label className="check"><input type="checkbox" checked={setMode} onChange={(e) => setSetMode(e.target.checked)} />
          Type the shelf total after each scan (instead of +1 per scan)</label>
      </> : <p className="tag warn">{c.status_label}</p>}
      {flash && <p className={`flash ${flash.ok ? "ok" : "error"}`} role="status">{flash.ok ? <CheckCircle2 size={16} /> : <XCircle size={16} />}{flash.text}</p>}
      <div className="phone-lines">
        {lines.map((l) => (
          <div key={l.id} className="phone-line">
            <button className="phone-line-name" onClick={() => c.can_count && editLine(l)}>
              <b>{l.product_name}</b><small className="muted">{l.sku} · {l.counted_by_name}</small></button>
            {c.can_count && <button className="ghost-btn" aria-label={`One less ${l.product_name}`} onClick={() => bump(l, -1)}><Minus size={16} /></button>}
            <span className="phone-qty">{qty(l.counted_qty)}</span>
            {c.can_count && <button className="ghost-btn" aria-label={`One more ${l.product_name}`} onClick={() => bump(l, 1)}><Plus size={16} /></button>}
            {c.can_count && <button className="ghost-btn" aria-label={`Remove ${l.product_name}`} onClick={() => remove(l)}><Trash2 size={15} /></button>}
          </div>
        ))}
        {!lines.length && <p className="muted">Nothing counted yet. Tap “Scan items” and point the camera at a barcode or QR label.</p>}
      </div>
      {c.can_count && lines.length > 0 && <button onClick={submit}><CheckCircle2 size={16} />Finished — send for verification</button>}
      {scan && <ScannerModal title={`Counting · ${c.title}`} keepOpen onCode={onCode} onClose={() => setScan(false)}
                             footer={flash && <p className={`flash ${flash.ok ? "ok" : "error"}`}>{flash.text}</p>} />}
    </div>
  );
}

// =================================================================================================
// Back office
// =================================================================================================
export function StockTakes({ ctx }: { ctx: Ctx }) {
  const list = useListState({ sort: "-created_at" });
  const [rows, setRows] = useState<Count[] | null>(null);
  const [total, setTotal] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    api(`/stock-counts/?${list.query({ page_size: "200" })}`, { branch: ctx.branch })
      .then((d) => { setRows(d.results); setTotal(d.count); }).catch((e) => { setRows([]); toast(errorText(e), "error"); });
  }, [list.state, ctx.branch, tick]);
  const phoneUrl = `${location.origin}${location.pathname}#/count`;
  const local = /^(localhost|127\.|\[::1\])/.test(location.hostname);

  async function create() {
    const branchId = ctx.branch || String(ctx.me.branches.find((b) => canCount(b.permissions))?.id || "");
    if (!branchId) return;
    const v = await formDialog({ title: "New stock take", icon: <ClipboardCheck size={26} />, confirmLabel: "Start",
      message: "Counters join it on their phones. Blind counts hide the system quantity from counters.",
      fields: [{ name: "title", label: "Title", placeholder: "e.g. Month-end full count", required: true },
               { name: "note", label: "Note (optional)" }] });
    if (!v) return;
    try { const c = await api<Count>("/stock-counts/", { body: { ...v, blind: true }, branch: branchId }); setOpenId(c.id); setTick((t) => t + 1); }
    catch (e) { toast(errorText(e), "error"); }
  }

  if (openId) return <CountDetail id={openId} onBack={() => { setOpenId(null); setTick((t) => t + 1); }} />;
  return (
    <div>
      <div className="phone-invite card">
        <QrImage text={phoneUrl} size={104} label="Open stock counting on a phone" />
        <div><b><Smartphone size={16} style={{ verticalAlign: -3 }} /> Count on a phone</b>
          <p className="muted" style={{ margin: "4px 0" }}>Scan this with a phone on the shop Wi-Fi, sign in, and scan items to count or look up stock.</p>
          <code>{phoneUrl}</code>
          {local && <p className="warn" style={{ margin: "4px 0 0", fontSize: ".85rem" }}>This page is open on localhost, which phones can't reach. Open it from the server's network (https) address so the code points there.</p>}
        </div>
      </div>
      <ListControls list={list} placeholder="Search number, title or note" count={total} filters={[
        { key: "status", label: "Status", options: [["", "All statuses"], ["counting", "Counting"], ["submitted", "Waiting for verification"], ["posted", "Posted"], ["cancelled", "Cancelled"]] },
        { key: "from", label: "From", type: "date" }, { key: "to", label: "To", type: "date" }]}
        right={<button className="primary" onClick={create}><Plus size={16} />New stock take</button>} />
      {rows === null ? <div className="skeleton" style={{ height: 160 }} /> : !rows.length ? <p className="muted">No stock takes match.</p> : (
        <table className="grid-table clickable">
          <thead><tr><SortHeader list={list} k="number">No.</SortHeader><SortHeader list={list} k="title">Title</SortHeader>
            {!ctx.branch && <th>Branch</th>}<th className="num">Items</th><SortHeader list={list} k="status">Status</SortHeader>
            <th>Started by</th><SortHeader list={list} k="created_at">Started</SortHeader></tr></thead>
          <tbody>{rows.map((c) => (
            <tr key={c.id} tabIndex={0} onClick={() => setOpenId(c.id)} onKeyDown={(e) => e.key === "Enter" && setOpenId(c.id)}>
              <td>{c.number}</td><td><b>{c.title}</b>{c.category_name && <span className="muted"> · {c.category_name}</span>}</td>
              {!ctx.branch && <td>{c.branch_name}</td>}<td className="num">{c.line_count}</td>
              <td><span className={`tag ${statusTag(c.status)}`}>{c.status_label}</span></td>
              <td>{c.created_by_name}</td><td>{new Date(c.created_at).toLocaleString()}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

function CountDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const [c, setC] = useState<Count | null>(null);
  const list = useListState({ sort: "product_name", filters: { show: "" } });
  const load = () => api<Count>(`/stock-counts/${id}/`, { branch: null }).then(setC).catch((e) => toast(errorText(e), "error"));
  useEffect(() => { load(); }, []);
  const lines = useMemo(() => list.apply(c?.lines || [], {
    text: (l) => `${l.product_name} ${l.sku} ${l.barcode} ${l.counted_by_name}`,
    filters: { show: (l, v) => (v === "diff" ? Number(l.variance) !== 0 : v === "short" ? Number(l.variance) < 0 : v === "over" ? Number(l.variance) > 0 : v === "recounted" ? l.verified_qty != null : true) },
    sorts: { product_name: (l) => l.product_name, counted: (l) => Number(l.counted_qty), expected: (l) => Number(l.expected_qty),
             variance: (l) => Number(l.variance), counted_by: (l) => l.counted_by_name },
  }), [c, list.state]);

  async function act(path: string, ask?: { title: string; message: string; confirmLabel: string; danger?: boolean }, done?: string) {
    if (ask && !(await confirmDialog(ask))) return;
    try { setC(await api(`/stock-counts/${id}/${path}/`, { method: "POST", branch: null })); if (done) toast(done, "success"); }
    catch (e) { toast(errorText(e), "error"); }
  }
  async function recount(l: Line) {
    const v = await formDialog({ title: `Recount ${l.product_name}`, confirmLabel: "Save recount",
      message: `Counted ${qty(l.counted_qty)} by ${l.counted_by_name}; system had ${qty(l.expected_qty)}.`,
      fields: [{ name: "qty", label: "Your count", type: "number", value: l.verified_qty ?? String(Number(l.counted_qty)), required: true }] });
    if (!v) return;
    try { setC(await api(`/stock-counts/${id}/recount/`, { body: { line: l.id, qty: v.qty }, branch: null })); } catch (e) { toast(errorText(e), "error"); }
  }
  if (!c) return <div className="skeleton" style={{ height: 240 }} />;
  const hidden = c.lines?.[0]?.variance === null;
  return (
    <div>
      <div className="toolbar">
        <button className="ghost-btn" onClick={onBack}><ArrowLeft size={16} />All stock takes</button>
        <h2 style={{ margin: 0 }}>{c.number} · {c.title}</h2>
        <span className={`tag ${statusTag(c.status)}`}>{c.status_label}</span>
        <span className="spacer" />
        {c.can_verify && <>
          <button onClick={() => act("reopen", undefined, "Sent back to the counters.")}><Undo2 size={16} />Send back for recount</button>
          <button className="primary" onClick={() => act("approve", { title: "Approve and post?", confirmLabel: "Approve & post",
            message: `${c.summary?.differences ?? 0} item(s) differ from the system. Their stock will be adjusted and the value booked to shrinkage. This can't be undone.` }, "Stock take posted.")}>
            <CheckCircle2 size={16} />Approve & post</button>
        </>}
        {(c.status === "counting" || c.status === "submitted") && (c.is_verifier || c.i_counted) &&
          <button className="ghost-btn" onClick={() => act("cancel", { title: "Cancel this stock take?", message: "Counts are kept for the record but nothing is posted.", confirmLabel: "Cancel stock take", danger: true })}>Cancel</button>}
      </div>
      <p className="muted" style={{ marginTop: 0 }}>{c.branch_name} · started by {c.created_by_name} {new Date(c.created_at).toLocaleString()}
        {c.submitted_by_name && ` · submitted by ${c.submitted_by_name}`}{c.verified_by_name && ` · verified by ${c.verified_by_name}`}</p>
      {c.status === "submitted" && c.is_verifier && !c.can_verify && <p className="warn">You counted part of this stock take, so someone else has to verify it.</p>}
      {c.summary && <div className="kpis" style={{ marginBottom: 14 }}>
        <div className="card kpi"><span className="muted">Items counted</span><b>{c.summary.lines}</b></div>
        <div className="card kpi"><span className="muted">Differences</span><b>{c.summary.differences}</b></div>
        <div className="card kpi"><span className="muted">Short</span><b className="error">{qty(c.summary.short)}</b></div>
        <div className="card kpi"><span className="muted">Over</span><b className="ok">{qty(c.summary.over)}</b></div>
      </div>}
      <ListControls list={list} placeholder="Search item, SKU or counter" count={lines.length} filters={hidden ? [] : [
        { key: "show", label: "Show", options: [["", "All items"], ["diff", "Differences only"], ["short", "Short"], ["over", "Over"], ["recounted", "Recounted"]] }]} />
      <table className="grid-table">
        <thead><tr><SortHeader list={list} k="product_name">Item</SortHeader><SortHeader list={list} k="counted_by">Counted by</SortHeader>
          <SortHeader list={list} k="counted" num>Counted</SortHeader>
          {!hidden && <><SortHeader list={list} k="expected" num>System</SortHeader><th className="num">Recount</th><SortHeader list={list} k="variance" num>Difference</SortHeader></>}
          {c.can_verify && <th />}</tr></thead>
        <tbody>{lines.map((l) => (
          <tr key={l.id}><td><b>{l.product_name}</b> <span className="muted">{l.sku}</span></td><td>{l.counted_by_name}</td>
            <td className="num">{qty(l.counted_qty)}</td>
            {!hidden && <><td className="num">{qty(l.expected_qty)}</td><td className="num">{qty(l.verified_qty)}</td>
              <td className={`num ${Number(l.variance) < 0 ? "error" : Number(l.variance) > 0 ? "ok" : ""}`}>{Number(l.variance) > 0 ? "+" : ""}{qty(l.variance)}</td></>}
            {c.can_verify && <td style={{ textAlign: "right" }}><button className="ghost-btn" onClick={() => recount(l)}>Recount</button></td>}</tr>
        ))}</tbody>
      </table>
      {hidden && <p className="muted">This is a blind count: system quantities and differences are shown to verifiers only.</p>}
    </div>
  );
}
