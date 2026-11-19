import { toast } from "./backoffice/ui";
import { formDialog } from "./Dialog";
import { InboxView, PinnedBanner, useInboxSummary } from "./backoffice/messages";
import { FileText, Mail, Printer, QrCode, Wifi, WifiOff } from "lucide-react";
import { QrImage, ScanButton, ScannerModal } from "./Scanner";
import { SystemTabs } from "./SystemTabs";
import { connectSerialScanner, matchesCode, serialSupported, useScannerInput } from "./scanning";
import { BrandMark, useBrandingState } from "./BrandMark";
import { printDoc, Proforma, Receipt } from "./docs";
import { ThemeSwitch } from "./theme";
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
  const [proformaOpen, setProformaOpen] = useState(false);
  const [askOverride, setAskOverride] = useState<{ idx: number; why: string } | null>(null);
  const [panel, setPanel] = useState<"" | "approvals" | "close" | "scan" | "payqr">("");
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

  // Camera scan: exact barcode/SKU only (never a fuzzy name match).
  function scanned(code: string) {
    const raw = code.trim();
    const p = catalog?.products.find((x) => matchesCode(x, raw));
    if (p) { add(p); toast(`Added ${p.name}`, "success"); }
    else toast(`No product with code ${raw}.`, "error");
  }

  // Keyboard-mode USB/Bluetooth scanners work even when the search box doesn't have focus.
  useScannerInput(scanned, !panel && !paying && !receipt && !askOverride && !proformaOpen && !inboxOpen);
  // Serial (COM-port) scanner: reconnect to one allowed before; the header button picks a new one.
  const [serialOn, setSerialOn] = useState(false);
  const serialStop = useRef<null | (() => Promise<void>)>(null);
  const scannedRef = useRef(scanned); scannedRef.current = scanned;
  async function serial(pick: boolean) {
    try {
      const stop = await connectSerialScanner((c) => scannedRef.current(c), pick);
      if (stop) { serialStop.current = stop; setSerialOn(true); if (pick) toast("Serial scanner connected.", "success"); }
    } catch (e: any) { if (pick) toast(`Couldn't connect the scanner: ${e?.message || e}`, "error"); }
  }
  useEffect(() => { if (serialSupported()) serial(false); return () => { serialStop.current?.(); }; }, []);

  // Cash drop: spare cash goes to the vault holder, who counts and confirms it in the back office.
  async function cashDrop() {
    const v = await formDialog({ title: "Cash drop to the vault", confirmLabel: "Hand over",
      message: "Count the cash you're handing to the vault holder. It's recorded as waiting until they confirm it.",
      fields: [{ name: "amount", label: "Amount handed over", type: "number", required: true,
                 validate: (x) => (Number(x) > 0 ? null : "Enter an amount above zero.") },
               { name: "note", label: "Note (optional)" }] });
    if (!v) return;
    try {
      const r = await api<{ till_balance: string }>(`/till-sessions/${session.id}/drop/`, { body: v });
      toast(`Handed over ${money(v.amount)}. The vault holder must confirm it. Left in drawer: ${money(r.till_balance)}.`, "success");
    } catch (e: any) { toast(e.message, "error"); }
  }

  // Enter (or Tab) in the search box: an exact barcode/SKU match goes straight in (scanners send Enter or Tab).
  function onSearchKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" && matches.length) add(matches[0]);
    else if (e.key === "Tab" && matches.length && matchesCode(matches[0], query)) { e.preventDefault(); add(matches[0]); }
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
        <BrandMark size={30} />
        <strong>{catalog?.branch.organization} · {branch.name} · {session.till_name}</strong>
        <span className={`pill ${online ? "online" : "offline"}`}>{online ? <Wifi size={13} /> : <WifiOff size={13} />}{online ? "Online" : "Offline"}</span>
        {pending > 0 && <span className="warn">{pending} sale(s) waiting to sync</span>}
        {syncErrors.length > 0 && <span className="error" title={syncErrors.join("\n")}>Sync errors: {syncErrors.length}</span>}
        <span className="spacer" />
        {can("pos.price_override") && <button onClick={() => setPanel("approvals")}>Approvals</button>}
        <SystemTabs me={me} current="pos" />
        <ThemeSwitch compact />
        <button className="ghost icon bell" aria-label={`Messages, ${inbox.unread} unread`} onClick={() => setInboxOpen(true)}>
          <Mail size={19} />{inbox.unread > 0 && <span className="count">{inbox.unread}</span>}
        </button>
        {serialSupported() && <button onClick={() => (serialOn ? undefined : serial(true))} title="Connect a serial / COM-port barcode scanner">
          {serialOn ? "Serial scanner ✓" : "Connect scanner"}</button>}
        <button onClick={cashDrop} title="Hand spare cash to the vault holder">Cash drop</button>
        <button onClick={() => setPanel("close")}>Close till</button>
        <span>{me.name}</span>
        <button className="link" onClick={onLogout}>Log out</button>
      </header>

      <main>
        <section className="search">
          <input ref={searchRef} autoFocus type="search" placeholder="Scan barcode or search all products…" value={query}
                 aria-label="Scan barcode or search products" onChange={(e) => setQuery(e.target.value)} onKeyDown={onSearchKey} />
          <ScanButton onClick={() => setPanel("scan")} />
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
          <div className="actions" style={{ marginTop: 0 }}>
            <button className="primary" style={{ flex: 1 }} disabled={!lines.length} onClick={startPay}>Pay (F2)</button>
            <button disabled={!lines.length} onClick={() => setProformaOpen(true)} title="Print a priced quotation for this basket">
              <FileText size={16} />Proforma</button>
            <button onClick={() => setPanel("payqr")} title="Show a QR code the customer scans to pay"><QrCode size={16} />Pay by QR</button>
          </div>
        </section>
      </main>

      {askOverride && (
        <SupervisorDialog why={askOverride.why} line={lines[askOverride.idx]} onCancel={() => setAskOverride(null)}
          onApprove={(o) => { setLines((ls) => ls.map((l, i) => (i === askOverride.idx ? { ...l, override: o } : l))); setAskOverride(null); }} />
      )}
      {paying && catalog && <PayDialog total={total} methods={catalog.payment_methods} online={online}
                                       onCheckout={checkout} onDone={finishSale} onCancel={() => setPaying(false)} />}
      {receipt && <ReceiptDialog sale={receipt} catalog={catalog} cashier={me.name} onClose={() => setReceipt(null)} />}
      {proformaOpen && <ProformaDialog lines={lines} branchName={branch.name} onClose={() => setProformaOpen(false)} />}
      {panel === "approvals" && <Approvals onClose={() => setPanel("")} />}
      {inboxOpen && (
        <div className="modal" onClick={(e) => e.target === e.currentTarget && setInboxOpen(false)}>
          <div className="card wide"><div className="card-head"><h3>Messages</h3>
            <button className="link" onClick={() => setInboxOpen(false)}>Close</button></div>
            <InboxView compact /></div>
        </div>
      )}
      {panel === "scan" && <ScannerModal title="Scan to add to the sale" keepOpen onCode={scanned} onClose={() => setPanel("")} />}
      {panel === "payqr" && catalog && <PayQrDialog total={total} catalog={catalog} till={session.till_name} onClose={() => setPanel("")} />}
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
        {p?.checkout_url && <div className="payqr-one"><QrImage text={p.checkout_url} size={200} label="Scan to pay" />
          <p>Customer scans to pay, or opens: <a href={p.checkout_url} target="_blank" rel="noreferrer">{p.checkout_url}</a></p></div>}
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

/** Quick payment QR: one code per QR-ready method (mobile money merchant / bank account), with the
 *  amount and a short reference the cashier then types as the payment's reference. */
function PayQrDialog({ total, catalog, till, onClose }: { total: number; catalog: Catalog; till: string; onClose: () => void }) {
  const [amount, setAmount] = useState(total ? total.toFixed(2) : "");
  const [ref] = useState(() => `${catalog.branch.code}-${till.replace(/\s+/g, "")}-${new Date().toTimeString().slice(0, 8).replace(/:/g, "")}`.toUpperCase());
  const ready = catalog.payment_methods.filter((m) => m.qr && (m.qr.merchant || m.qr.account || m.qr.template));
  const [pick, setPick] = useState(ready[0]?.id ?? 0);
  const m = ready.find((x) => x.id === pick);
  const amt = Number(amount || 0).toFixed(2);
  const qr = m?.qr || {};
  const text = !m ? "" : qr.template
    ? qr.template.replace(/\{amount\}/g, amt).replace(/\{ref\}/g, ref).replace(/\{merchant\}/g, qr.merchant || "")
    : [`Pay ${catalog.branch.organization} - ${catalog.branch.name}`,
       qr.merchant ? `${m.name} merchant/till no: ${qr.merchant}` : m.name,
       qr.account ? `Account: ${qr.account}${qr.bank ? ` (${qr.bank})` : ""}${qr.account_name ? `, ${qr.account_name}` : ""}` : "",
       `Amount: ${catalog.branch.currency} ${amt}`, `Reference: ${ref}`].filter(Boolean).join("\n");
  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card payqr" role="dialog" aria-label="Pay by QR">
        <div className="card-head"><h3><QrCode size={18} style={{ verticalAlign: -3 }} /> Pay by QR</h3>
          <button className="link" onClick={onClose}>Close</button></div>
        {!ready.length ? <p className="muted">No payment method has QR details yet. An admin adds them to a payment method's settings
          (<code>qr_merchant</code>, or <code>qr_bank</code> + <code>qr_account</code>).</p> : <>
          <div className="inline" style={{ flexWrap: "wrap" }}>
            {ready.map((x) => <button key={x.id} className={x.id === pick ? "primary" : ""} onClick={() => setPick(x.id)}>{x.name}</button>)}
          </div>
          <label>Amount ({catalog.branch.currency}) <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
          {m && Number(amount) > 0 ? <div className="payqr-one">
            <QrImage text={text} size={240} label={`Scan to pay ${money(amt)} with ${m.name}`} />
            <div><p style={{ margin: 0 }}><b>{money(amt)}</b> via {m.name}</p>
              {qr.merchant && <p style={{ margin: 0 }}>Merchant / till no: <b>{qr.merchant}</b></p>}
              {qr.account && <p style={{ margin: 0 }}>{qr.bank} {qr.account}</p>}
              <p style={{ margin: 0 }}>Reference: <b>{ref}</b></p>
              <p className="muted" style={{ fontSize: ".85rem" }}>When the customer's payment comes through, take payment with {m.name} and enter the transaction ID as the reference.</p></div>
          </div> : <p className="muted">Enter an amount to show the code.</p>}
        </>}
      </div>
    </div>
  );
}

function ReceiptDialog({ sale, catalog, cashier, onClose }: { sale: any; catalog: Catalog | null; cashier: string; onClose: () => void }) {
  const brand = useBrandingState();
  const box = useRef<HTMLDivElement>(null);
  const settings = { name: catalog?.branch.organization || "", receipt_footer: catalog?.branch.receipt_footer, ...(brand || {}) } as any;
  return (
    <div className="modal"><div className="card">
      <div ref={box} className="doc-preview" style={{ maxHeight: "60vh" }}>
        <Receipt s={settings} branch={catalog?.branch.name || ""} number={sale.number} date={sale.completed_at || sale.created_at}
          cashier={cashier} total={sale.total} tax={sale.tax_total} offline={sale.offline}
          items={sale.lines.map((l: any) => ({ name: l.description, qty: l.quantity, unit_price: l.unit_price ?? 0, line_total: l.line_total,
            sku: catalog?.products.find((p) => p.name === l.description)?.sku }))}
          payments={sale.payments.map((p: any) => ({ name: p.method_name, amount: p.amount, change: p.change }))} />
      </div>
      <div className="actions">
        <button onClick={() => printDoc(box.current)}><Printer size={16} />Print</button>
        <button className="primary" onClick={onClose} autoFocus>New sale</button>
      </div>
    </div></div>
  );
}

function ProformaDialog({ lines, branchName, onClose }: { lines: Line[]; branchName: string; onClose: () => void }) {
  const brand = useBrandingState();
  const box = useRef<HTMLDivElement>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [pf, setPf] = useState<any>(null);
  const discounted = lines.some((l) => l.discount > 0);

  async function create() {
    setBusy(true);
    try {
      setPf(await api("/proformas/", { body: {
        customer_name: name, customer_phone: phone, note,
        lines: lines.map((l) => ({ product_id: l.product.id, quantity: String(l.qty),
          ...(l.price !== Number(l.product.price) ? { unit_price: l.price.toFixed(2) } : {}) })) } }));
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  }

  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}><div className="card wide">
      {!pf ? <>
        <h3>Proforma for this basket</h3>
        <p className="muted" style={{ margin: 0 }}>A priced quotation for the customer. Nothing is sold and stock is not reserved.</p>
        {discounted && <p className="warn-box">Line discounts are not carried onto proformas; change the price instead (needs a supervisor).</p>}
        <div className="form-grid">
          <label>Customer name<input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></label>
          <label>Phone<input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" /></label>
          <label style={{ gridColumn: "1 / -1" }}>Note<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional, e.g. for school order" /></label>
        </div>
        <div className="actions">
          <button className="primary" disabled={busy} onClick={create}><FileText size={16} />Create proforma</button>
          <button className="link" onClick={onClose}>Cancel</button>
        </div>
      </> : <>
        <div ref={box} className="doc-preview"><Proforma s={(brand || {}) as any} pf={pf} branch={branchName} /></div>
        <div className="actions">
          <button className="primary" onClick={() => printDoc(box.current)}><Printer size={16} />Print {pf.number}</button>
          <button onClick={onClose}>Done</button>
        </div>
      </>}
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
        <p className="muted" style={{ margin: 0 }}>Count all the cash in the drawer. It's handed to the vault holder, who counts and confirms it; the till closes at zero.</p>
        <label>Cash counted in drawer <input inputMode="decimal" value={counted} onChange={(e) => setCounted(e.target.value)} autoFocus /></label>
        <button className="primary" disabled={!counted || pending > 0} onClick={close}>Close till</button>
        <button className="link" onClick={onClose}>Back</button>
      </> : <>
        <p>Expected {money(result.expected_cash)} · Counted {money(result.counted_cash)} ·{" "}
          <b className={Number(result.variance) === 0 ? "ok" : "error"}>Variance {money(result.variance)}</b></p>
        <p className="ok">{money(result.counted_cash)} handed over. It settles in the vault once the vault holder confirms it. Till balance: {money(0)}.</p>
        <button className="primary" onClick={onClosed}>Done</button>
      </>}
    </div></div>
  );
}
