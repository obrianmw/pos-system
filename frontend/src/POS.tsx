import { toast } from "./backoffice/ui";
import { InboxView, PinnedBanner, useInboxSummary } from "./backoffice/messages";
import { Mail, ShoppingCart, Wifi, WifiOff } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, money, OfflineError } from "./api";
import type { Me, Session } from "./App";
import CategoryBrowser, { searchProducts } from "./CategoryBrowser";
import { Catalog, enqueueSale, loadCatalog, nextOfflineNumber, PaymentMethod, Product, queuedSales, syncQueue } from "./offline";

type Override = { supervisor: string; pin: string; reason: string };
type Line = { product: Product; qty: number; price: number; discount: number; override?: Override };
type Pay = { method: PaymentMethod; amount: string; tendered?: string; phone?: string; reference?: string };
type Branch = Me["branches"][number];

const round2 = (n: number) => Math.round(n * 100) / 100;
const lineTotal = (l: Line) => round2(l.qty * l.price - l.discount);
const uuid = () => crypto.randomUUID();

export default function POS({ me, branch, session, onLogout, onClosed, onOffice }:
  { me: Me; branch: Branch; session: Session; onLogout: () => void; onClosed: () => void; onOffice?: () => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [query, setQuery] = useState("");
  const [online, setOnline] = useState(navigator.onLine);
  const [pending, setPending] = useState(0);
  const [syncErrors, setSyncErrors] = useState<string[]>([]);
  const [paying, setPaying] = useState(false);
  const [receipt, setReceipt] = useState<any | null>(null);
  const [askOverride, setAskOverride] = useState<{ idx: number; why: string } | null>(null);
  const [panel, setPanel] = useState<"" | "approvals" | "close">("");
  const searchRef = useRef<HTMLInputElement>(null);
  const inbox = useInboxSummary();
  const [inboxOpen, setInboxOpen] = useState(false);
  const can = (p: string) => branch.permissions.includes(p);

  useEffect(() => { loadCatalog(String(branch.id)).then(setCatalog).catch(() => {}); }, [branch.id]);

  // Sync loop: on reconnect and every 30 s.
  useEffect(() => {
    const tick = async () => {
      const r = await syncQueue();
      setPending(r.pending);
      if (r.errors.length) setSyncErrors(r.errors);
      try { await api("/me/"); setOnline(true); } catch (e) { setOnline(!(e instanceof OfflineError)); }
    };
    queuedSales().then((q) => setPending(q.length));
    const id = setInterval(tick, 30000);
    window.addEventListener("online", tick);
    window.addEventListener("offline", () => setOnline(false));
    tick();
    return () => { clearInterval(id); window.removeEventListener("online", tick); };
  }, []);

  const matches = useMemo(() => searchProducts(catalog, query), [catalog, query]);

  function add(p: Product) {
    setLines((ls) => {
      const i = ls.findIndex((l) => l.product.id === p.id && !l.override);
      if (i >= 0) return ls.map((l, j) => (j === i ? { ...l, qty: l.qty + 1 } : l));
      return [...ls, { product: p, qty: 1, price: Number(p.price), discount: 0 }];
    });
    setQuery("");
    searchRef.current?.focus();
  }

  // Enter in the search box: exact barcode/SKU match goes straight in (barcode scanners send Enter).
  function onSearchKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" && matches.length) add(matches[0]);
  }

  function update(idx: number, patch: Partial<Line>) {
    setLines((ls) => ls.map((l, i) => {
      if (i !== idx) return l;
      const next = { ...l, ...patch };
      // Changing price or discount invalidates an earlier approval.
      if ("price" in patch || "discount" in patch) delete next.override;
      return next;
    }));
  }

  function needsOverride(l: Line): string | null {
    if (l.override || can("pos.price_override") && can("pos.discount_override")) return null;
    if (l.price !== Number(l.product.price) && !can("pos.price_override")) return "price change";
    const gross = l.qty * l.price;
    const limit = Number(catalog?.branch.max_cashier_discount_pct || 0);
    if (l.discount && gross && (l.discount / gross) * 100 > limit && !can("pos.discount_override")) return "discount";
    return null;
  }

  const total = round2(lines.reduce((s, l) => s + lineTotal(l), 0));

  function startPay() {
    const idx = lines.findIndex((l) => needsOverride(l));
    if (idx >= 0) return setAskOverride({ idx, why: needsOverride(lines[idx])! });
    const bad = lines.find((l) => l.product.min_price && l.price < Number(l.product.min_price));
    if (bad) return toast(`${bad.product.name}: price is below the floor price ${bad.product.min_price}.`, "error");
    setPaying(true);
  }

  function saleBody(pays: Pay[]) {
    return {
      client_uuid: uuid(), till_session: session.id, client_created_at: new Date().toISOString(),
      lines: lines.map((l) => ({
        product_id: l.product.id, quantity: String(l.qty), unit_price: l.price.toFixed(2),
        discount_amount: l.discount.toFixed(2), override: l.override,
      })),
      payments: pays.map((p) => ({
        method_id: p.method.id, amount: p.amount, tendered: p.tendered || undefined,
        phone: p.phone || undefined, reference: p.reference || undefined,
      })),
    };
  }

  async function checkout(pays: Pay[]) {
    const body = saleBody(pays);
    try {
      const sale = await api("/sales/", { body });
      finishSale(sale);
      return sale;
    } catch (e) {
      if (e instanceof OfflineError) {
        if (pays.some((p) => !p.method.allowed_offline)) {
          toast("Offline: only cash / own card terminal can be taken. Choose another method.", "error");
          return null;
        }
        const tillCode = `t${session.till}`;
        const offlineSale = { ...body, number: await nextOfflineNumber(branch.code, tillCode) };
        await enqueueSale(offlineSale);
        setPending((n) => n + 1);
        finishSale({ ...offlineSale, offline: true, total: total.toFixed(2), status: "queued (offline)",
                     lines: lines.map((l) => ({ description: l.product.name, quantity: l.qty, line_total: lineTotal(l) })),
                     payments: pays.map((p) => ({ method_name: p.method.name, amount: p.amount,
                       change: p.tendered ? (Number(p.tendered) - Number(p.amount)).toFixed(2) : null })) });
        return null;
      }
      if (e instanceof ApiError && e.data?.code === "override_required") {
        setPaying(false);
        // No `kind` means the PIN/approval itself was refused: show the server's reason.
        setAskOverride({ idx: Math.max(0, lines.findIndex((l) => l.product.id === e.data.product)),
                         why: e.data.kind || e.data.detail || "approval" });
        return null;
      }
      toast((e as Error).message, "error");
      return null;
    }
  }

  function finishSale(sale: any) {
    if (sale.status === "pending_payment") return; // PayDialog keeps polling
    setReceipt(sale);
    setLines([]);
    setPaying(false);
  }

  return (
    <div className="pos">
      <PinnedBanner summary={inbox} onOpen={() => setInboxOpen(true)} />
      <header>
        <span className="logo-mark" style={{ width: 30, height: 30 }}><ShoppingCart size={16} /></span>
        <strong>{catalog?.branch.organization} · {branch.name} · {session.till_name}</strong>
        <span className={`pill ${online ? "online" : "offline"}`}>{online ? <Wifi size={13} /> : <WifiOff size={13} />}{online ? "Online" : "Offline"}</span>
        {pending > 0 && <span className="warn">{pending} sale(s) waiting to sync</span>}
        {syncErrors.length > 0 && <span className="error" title={syncErrors.join("\n")}>Sync errors: {syncErrors.length}</span>}
        <span className="spacer" />
        {can("pos.price_override") && <button onClick={() => setPanel("approvals")}>Approvals</button>}
        {onOffice && <button onClick={onOffice}>Back office</button>}
        <button className="ghost icon bell" aria-label={`Messages, ${inbox.unread} unread`} onClick={() => setInboxOpen(true)}>
          <Mail size={19} />{inbox.unread > 0 && <span className="count">{inbox.unread}</span>}
        </button>
        <button onClick={() => setPanel("close")}>Close till</button>
        <span>{me.name}</span>
        <button className="link" onClick={onLogout}>Log out</button>
      </header>

      <main>
        <section className="search">
          <input ref={searchRef} autoFocus type="search" placeholder="Scan barcode or search all products…" value={query}
                 aria-label="Scan barcode or search products" onChange={(e) => setQuery(e.target.value)} onKeyDown={onSearchKey} />
          {catalog ? <CategoryBrowser catalog={catalog} query={query} onAdd={add} /> : <p>Loading catalog…</p>}
          {catalog?.fetched_at && <small>Catalog as of {new Date(catalog.fetched_at).toLocaleTimeString()}</small>}
        </section>

        <section className="cart">
          <table>
            <thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Disc.</th><th>Total</th><th /></tr></thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i} className={needsOverride(l) ? "needs" : ""}>
                  <td>{l.product.name}{l.override && <small> ✔ {l.override.supervisor}</small>}</td>
                  <td><input type="number" min={1} value={l.qty} onChange={(e) => update(i, { qty: Math.max(1, Number(e.target.value)) })} /></td>
                  <td><input type="number" value={l.price} onChange={(e) => update(i, { price: Number(e.target.value) })} /></td>
                  <td><input type="number" min={0} value={l.discount} onChange={(e) => update(i, { discount: Number(e.target.value) })} /></td>
                  <td>{money(lineTotal(l))}</td>
                  <td><button className="link" onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="total">Total <b>{catalog?.branch.currency} {money(total)}</b></div>
          <button className="primary" disabled={!lines.length} onClick={startPay}>Pay (F2)</button>
        </section>
      </main>

      {askOverride && (
        <SupervisorDialog why={askOverride.why} line={lines[askOverride.idx]} onCancel={() => setAskOverride(null)}
          onApprove={(o) => { setLines((ls) => ls.map((l, i) => (i === askOverride.idx ? { ...l, override: o } : l))); setAskOverride(null); }} />
      )}
      {paying && catalog && <PayDialog total={total} methods={catalog.payment_methods} online={online}
                                       onCheckout={checkout} onDone={finishSale} onCancel={() => setPaying(false)} />}
      {receipt && <Receipt sale={receipt} catalog={catalog} cashier={me.name} onClose={() => setReceipt(null)} />}
      {panel === "approvals" && <Approvals onClose={() => setPanel("")} />}
      {inboxOpen && (
        <div className="modal" onClick={(e) => e.target === e.currentTarget && setInboxOpen(false)}>
          <div className="card wide"><div className="card-head"><h3>Messages</h3>
            <button className="link" onClick={() => setInboxOpen(false)}>Close</button></div>
            <InboxView compact /></div>
        </div>
      )}
      {panel === "close" && <CloseTill session={session} onClose={() => setPanel("")} onClosed={onClosed} pending={pending} />}
    </div>
  );
}

function SupervisorDialog({ why, line, onApprove, onCancel }:
  { why: string; line?: Line; onApprove: (o: Override) => void; onCancel: () => void }) {
  const [supervisor, setSupervisor] = useState("");
  const [pin, setPin] = useState("");
  const [reason, setReason] = useState("");
  return (
    <div className="modal"><div className="card">
      <h3>Supervisor approval: {why}</h3>
      {line && <p>{line.product.name}: list {money(line.product.price)} → {money(line.price)}, discount {money(line.discount)}</p>}
      <input placeholder="Supervisor username" value={supervisor} onChange={(e) => setSupervisor(e.target.value)} autoFocus />
      <input placeholder="PIN" type="password" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value)} />
      <input placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      <p><small>The PIN is checked by the server at checkout (or when offline sales sync).</small></p>
      <button disabled={!supervisor || !pin || !reason} onClick={() => onApprove({ supervisor, pin, reason })}>Approve</button>
      <button className="link" onClick={onCancel}>Cancel</button>
    </div></div>
  );
}

function PayDialog({ total, methods, online, onCheckout, onDone, onCancel }: {
  total: number; methods: PaymentMethod[]; online: boolean;
  onCheckout: (p: Pay[]) => Promise<any>; onDone: (s: any) => void; onCancel: () => void;
}) {
  const usable = methods.filter((m) => online || m.allowed_offline);
  const cash = usable.find((m) => m.kind === "cash") || usable[0];
  const [pays, setPays] = useState<Pay[]>(cash ? [{ method: cash, amount: total.toFixed(2), tendered: total.toFixed(2) }] : []);
  const [pendingSale, setPendingSale] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const paid = round2(pays.reduce((s, p) => s + Number(p.amount || 0), 0));

  // While a wallet payment is pending, ask the server (which asks the provider) every 4 s.
  useEffect(() => {
    if (!pendingSale) return;
    const id = setInterval(async () => {
      const p = pendingSale.payments.find((x: any) => x.status === "pending");
      if (!p) return;
      try {
        const s = await api(`/sales/${pendingSale.id}/payments/${p.id}/refresh/`, { method: "POST" });
        setPendingSale(s);
        if (s.status === "completed") onDone(s);
      } catch { /* keep polling */ }
    }, 4000);
    return () => clearInterval(id);
  }, [pendingSale]);

  async function submit() {
    setBusy(true);
    const s = await onCheckout(pays);
    setBusy(false);
    if (s?.status === "pending_payment") setPendingSale(s);
  }

  async function cancelPending() {
    await api(`/sales/${pendingSale.id}/cancel/`, { body: { reason: "Payment not completed" } });
    onCancel();
  }

  if (pendingSale) {
    const p = pendingSale.payments.find((x: any) => x.status !== "confirmed");
    return (
      <div className="modal"><div className="card">
        <h3>Waiting for payment…</h3>
        {p && <p>{p.method_name}: {money(p.amount)} — {p.status}. {p.message}</p>}
        {p?.checkout_url && <p>Customer pays at: <a href={p.checkout_url} target="_blank">{p.checkout_url}</a></p>}
        {p?.status === "failed" && <p className="error">Payment failed. Cancel and take another method.</p>}
        <button className="link" onClick={cancelPending}>Cancel sale</button>
      </div></div>
    );
  }

  return (
    <div className="modal"><div className="card wide">
      <h3>Payment — total {money(total)}</h3>
      {!online && <p className="warn">Offline: only methods allowed offline are shown.</p>}
      {pays.map((p, i) => (
        <div className="payrow" key={i}>
          <select value={p.method.id} onChange={(e) => setPays(pays.map((x, j) => j === i ? { ...x, method: usable.find((m) => m.id === Number(e.target.value))! } : x))}>
            {usable.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <input placeholder="Amount" value={p.amount} onChange={(e) => setPays(pays.map((x, j) => j === i ? { ...x, amount: e.target.value } : x))} />
          {p.method.kind === "cash" && <input placeholder="Tendered" value={p.tendered || ""} onChange={(e) => setPays(pays.map((x, j) => j === i ? { ...x, tendered: e.target.value } : x))} />}
          {p.method.kind === "mobile_money" && <input placeholder="Customer phone" value={p.phone || ""} onChange={(e) => setPays(pays.map((x, j) => j === i ? { ...x, phone: e.target.value } : x))} />}
          {p.method.requires_reference && <input placeholder="Txn / slip ref" value={p.reference || ""} onChange={(e) => setPays(pays.map((x, j) => j === i ? { ...x, reference: e.target.value } : x))} />}
          {pays.length > 1 && <button className="link" onClick={() => setPays(pays.filter((_, j) => j !== i))}>✕</button>}
        </div>
      ))}
      <button className="link" onClick={() => setPays([...pays, { method: usable[0], amount: Math.max(0, round2(total - paid)).toFixed(2) }])}>+ Split payment</button>
      <p>Paid {money(paid)} {paid !== total && <span className="error">(must equal {money(total)})</span>}
        {pays[0]?.tendered && pays[0].method.kind === "cash" && <> · Change <b>{money(Number(pays[0].tendered) - Number(pays[0].amount))}</b></>}</p>
      <button className="primary" disabled={busy || paid !== total} onClick={submit}>Complete sale</button>
      <button className="link" onClick={onCancel}>Back</button>
    </div></div>
  );
}

function Receipt({ sale, catalog, cashier, onClose }: { sale: any; catalog: Catalog | null; cashier: string; onClose: () => void }) {
  return (
    <div className="modal"><div className="card receipt">
      <h3>{catalog?.branch.organization}</h3>
      <p>{catalog?.branch.name}<br />Receipt {sale.number} · {new Date().toLocaleString()}<br />Cashier: {cashier}</p>
      <table><tbody>
        {sale.lines.map((l: any, i: number) => <tr key={i}><td>{Number(l.quantity)} × {l.description}</td><td>{money(l.line_total)}</td></tr>)}
      </tbody></table>
      <p><b>Total {money(sale.total)}</b>{sale.tax_total && <><br />incl. VAT {money(sale.tax_total)}</>}</p>
      {sale.payments.map((p: any, i: number) => <p key={i}>{p.method_name} {money(p.amount)}{p.change && Number(p.change) > 0 && <> · change {money(p.change)}</>}</p>)}
      {sale.offline && <p className="warn">Recorded offline — will sync automatically.</p>}
      <p><small>{catalog?.branch.receipt_footer}</small></p>
      <button onClick={() => window.print()}>Print</button>
      <button className="primary" onClick={onClose} autoFocus>New sale</button>
    </div></div>
  );
}

function Approvals({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const load = () => api("/overrides/?status=pending").then((d) => setItems(d.results)).catch(() => {});
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);
  async function decide(id: number, ok: boolean) {
    try { await api(`/overrides/${id}/${ok ? "approve" : "reject"}/`, { method: "POST" }); } catch (e: any) { toast(e.message, "error"); }
    load();
  }
  return (
    <div className="modal"><div className="card wide">
      <h3>Pending approvals</h3>
      {!items.length && <p>Nothing waiting.</p>}
      {items.map((a) => (
        <div key={a.id} className="payrow">
          <span>#{a.id} {a.kind} · {a.product_name} {a.original_value} → {a.new_value} · {a.requested_by_name}: {a.reason}</span>
          <button onClick={() => decide(a.id, true)}>Approve</button>
          <button className="link" onClick={() => decide(a.id, false)}>Reject</button>
        </div>
      ))}
      <button className="link" onClick={onClose}>Close</button>
    </div></div>
  );
}

function CloseTill({ session, onClose, onClosed, pending }: { session: Session; onClose: () => void; onClosed: () => void; pending: number }) {
  const [summary, setSummary] = useState<any>(null);
  const [counted, setCounted] = useState("");
  const [result, setResult] = useState<any>(null);
  useEffect(() => { api(`/till-sessions/${session.id}/summary/`).then(setSummary).catch(() => {}); }, []);
  async function close() {
    try { setResult(await api(`/till-sessions/${session.id}/close/`, { body: { counted_cash: counted } })); }
    catch (e: any) { toast(e.message, "error"); }
  }
  return (
    <div className="modal"><div className="card wide">
      <h3>Close till — {session.till_name}</h3>
      {pending > 0 && <p className="error">{pending} offline sale(s) not yet synced. Reconnect before closing.</p>}
      {summary && <>
        {summary.by_method.map((r: any, i: number) => <p key={i}>{r.sale__kind} · {r.method__name}: {money(r.total)} ({r.count})</p>)}
      </>}
      {!result ? <>
        <label>Cash counted in drawer <input inputMode="decimal" value={counted} onChange={(e) => setCounted(e.target.value)} autoFocus /></label>
        <button className="primary" disabled={!counted || pending > 0} onClick={close}>Close till</button>
        <button className="link" onClick={onClose}>Back</button>
      </> : <>
        <p>Expected {money(result.expected_cash)} · Counted {money(result.counted_cash)} ·{" "}
          <b className={Number(result.variance) === 0 ? "ok" : "error"}>Variance {money(result.variance)}</b></p>
        <button className="primary" onClick={onClosed}>Done</button>
      </>}
    </div></div>
  );
}
