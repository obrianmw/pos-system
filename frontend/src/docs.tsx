// Printed documents - receipt (till printer), invoice and proforma (A4) - built from the Branding
// settings, so what the admin previews on the Branding page is exactly what prints.
import { money } from "./api";
import type { BrandingSettings } from "./brand";

export type DocLine = { name: string; sku?: string; qty: number | string; unit_price: number | string; discount?: number | string;
  tax_amount?: number | string; tax_rate?: number | string; line_total: number | string };
export type DocPayment = { name: string; amount: number | string; change?: number | string | null };

const n = (v: unknown) => Number(v || 0);
const when = (iso?: string) => (iso ? new Date(iso) : new Date()).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const day = (iso?: string) => (iso ? new Date(iso + (iso.length === 10 ? "T00:00:00" : "")) : new Date()).toLocaleDateString(undefined, { dateStyle: "long" });
const lines = (text?: string) => (text || "").split("\n").filter((l) => l.trim()).map((l, i) => <div key={i}>{l}</div>);

function Business({ s, align = "left" }: { s: BrandingSettings; align?: "left" | "center" }) {
  return (
    <div className="doc-business" style={{ textAlign: align }}>
      {s.doc_show_logo && s.logo_url && <img className="doc-logo" src={s.logo_url} alt="" />}
      <div className="doc-name">{s.doc_business_name || s.name}</div>
      {lines(s.doc_address)}
      {(s.doc_phone || s.doc_email) && <div>{[s.doc_phone, s.doc_email].filter(Boolean).join(" · ")}</div>}
      {s.doc_tax_number && <div>TPIN: {s.doc_tax_number}</div>}
    </div>
  );
}

// ---- receipt ------------------------------------------------------------------------------------
export function Receipt({ s, branch, number, date, cashier, items, total, tax, payments, offline }: {
  s: BrandingSettings; branch: string; number: string; date?: string; cashier?: string; items: DocLine[];
  total: number | string; tax?: number | string; payments: DocPayment[]; offline?: boolean;
}) {
  return (
    <div className={`print-doc doc-receipt paper-${s.receipt_paper || "80mm"}`} data-paper={s.receipt_paper || "80mm"}>
      <Business s={s} align="center" />
      {s.receipt_header && <div className="doc-center doc-small">{lines(s.receipt_header)}</div>}
      <div className="doc-rule" />
      <div className="doc-small">{branch}<br />Receipt {number} · {when(date)}{s.receipt_show_cashier && cashier && <><br />Cashier: {cashier}</>}</div>
      <div className="doc-rule" />
      <table className="doc-table"><tbody>
        {items.map((l, i) => (
          <tr key={i}><td>{n(l.qty)} × {l.name}{s.receipt_show_barcode_sku && l.sku && <div className="doc-small">{l.sku}</div>}</td>
            <td className="num">{money(l.line_total)}</td></tr>
        ))}
      </tbody></table>
      <div className="doc-rule" />
      <div className="doc-row doc-strong"><span>Total</span><span>{money(total)}</span></div>
      {s.receipt_show_vat && tax !== undefined && <div className="doc-row doc-small"><span>incl. VAT</span><span>{money(tax)}</span></div>}
      {payments.map((p, i) => (
        <div key={i} className="doc-row doc-small"><span>{p.name}</span><span>{money(p.amount)}{p.change && n(p.change) > 0 ? ` · change ${money(p.change)}` : ""}</span></div>
      ))}
      {offline && <div className="doc-center doc-small">Recorded offline - will sync automatically.</div>}
      {s.receipt_footer && <><div className="doc-rule" /><div className="doc-center doc-small">{lines(s.receipt_footer)}</div></>}
    </div>
  );
}

// ---- A4 documents (invoice & proforma share a layout) -------------------------------------------
function A4({ s, title, meta, customer, items, subtotal, discount, tax, total, payments, terms, payment, footer, accent }: {
  s: BrandingSettings; title: string; meta: [string, string][]; customer?: string[]; items: DocLine[];
  subtotal: number | string; discount?: number | string; tax: number | string; total: number | string; payments?: DocPayment[];
  terms?: string; payment?: string; footer?: string; accent?: string;
}) {
  return (
    <div className="print-doc doc-a4" data-paper="A4">
      <div className="doc-head">
        <Business s={s} />
        <div className="doc-title-block">
          <div className="doc-title" style={accent ? { color: accent } : undefined}>{title}</div>
          <table className="doc-meta"><tbody>{meta.map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}</tbody></table>
        </div>
      </div>
      {customer && customer.some(Boolean) && (
        <div className="doc-bill"><div className="doc-label">Bill to</div>{customer.filter(Boolean).map((c, i) => <div key={i}>{c}</div>)}</div>
      )}
      <table className="doc-table doc-lines">
        <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Unit price</th><th className="num">VAT</th><th className="num">Amount</th></tr></thead>
        <tbody>{items.map((l, i) => (
          <tr key={i}><td>{l.name}{l.sku && <div className="doc-small">{l.sku}</div>}</td><td className="num">{n(l.qty)}</td>
            <td className="num">{money(l.unit_price)}</td><td className="num">{l.tax_amount !== undefined ? money(l.tax_amount) : "-"}</td>
            <td className="num">{money(l.line_total)}</td></tr>
        ))}</tbody>
      </table>
      <table className="doc-totals"><tbody>
        <tr><th>Subtotal</th><td>{money(subtotal)}</td></tr>
        {n(discount) > 0 && <tr><th>Discount</th><td>−{money(discount!)}</td></tr>}
        <tr><th>VAT included</th><td>{money(tax)}</td></tr>
        <tr className="doc-grand"><th>Total ({s.currency || "MWK"})</th><td>{money(total)}</td></tr>
        {payments?.map((p, i) => <tr key={i}><th>Paid - {p.name}</th><td>{money(p.amount)}</td></tr>)}
      </tbody></table>
      {(terms || payment) && (
        <div className="doc-notes">
          {terms && <div><div className="doc-label">Terms</div>{lines(terms)}</div>}
          {payment && <div><div className="doc-label">How to pay</div>{lines(payment)}</div>}
        </div>
      )}
      {footer && <div className="doc-footer">{lines(footer)}</div>}
    </div>
  );
}

export function Invoice({ s, sale, branch, customer }: {
  s: BrandingSettings; branch: string; customer?: string[];
  sale: { number: string; created_at?: string; completed_at?: string; subtotal: string; discount_total?: string; tax_total: string; total: string;
          lines: { description: string; quantity: string; unit_price: string; tax_amount: string; line_total: string; sku?: string }[];
          payments?: { method_name: string; amount: string; status?: string }[] };
}) {
  return (
    <A4 s={s} title={s.invoice_title || "Tax invoice"} accent="var(--doc-accent)"
        meta={[["Invoice no.", `${s.invoice_prefix || ""}${sale.number}`], ["Date", day(sale.completed_at || sale.created_at)], ["Branch", branch]]}
        customer={customer} subtotal={sale.subtotal} discount={sale.discount_total} tax={sale.tax_total} total={sale.total}
        items={sale.lines.map((l) => ({ name: l.description, sku: l.sku, qty: l.quantity, unit_price: l.unit_price, tax_amount: l.tax_amount, line_total: l.line_total }))}
        payments={(sale.payments || []).filter((p) => !p.status || p.status === "confirmed").map((p) => ({ name: p.method_name, amount: p.amount }))}
        terms={s.invoice_terms} payment={s.invoice_payment_details} footer={s.invoice_footer} />
  );
}

export function Proforma({ s, pf, branch }: {
  s: BrandingSettings; branch: string;
  pf: { number: string; created_at?: string; valid_until: string; customer_name?: string; customer_phone?: string; note?: string;
        subtotal: string; tax_total: string; total: string; lines: { name: string; sku?: string; quantity: string; unit_price: string; tax_amount: string; line_total: string }[] };
}) {
  return (
    <A4 s={s} title={s.proforma_title || "Proforma invoice"} accent="var(--doc-accent)"
        meta={[["Proforma no.", pf.number], ["Date", day(pf.created_at)], ["Valid until", day(pf.valid_until)], ["Branch", branch]]}
        customer={[pf.customer_name || "", pf.customer_phone || "", pf.note || ""]}
        subtotal={pf.subtotal} tax={pf.tax_total} total={pf.total}
        items={pf.lines.map((l) => ({ name: l.name, sku: l.sku, qty: l.quantity, unit_price: l.unit_price, tax_amount: l.tax_amount, line_total: l.line_total }))}
        terms={s.proforma_terms} payment={s.invoice_payment_details} footer={s.proforma_footer} />
  );
}

/** Print only the document inside `container` on the right paper (till roll or A4). */
export function printDoc(container: HTMLElement | null) {
  const doc = container?.querySelector<HTMLElement>(".print-doc") ?? container;
  if (!doc) return;
  const paper = doc.dataset.paper || "A4";
  const page = paper === "A4" ? "size: A4; margin: 14mm;" : `size: ${paper} auto; margin: 3mm;`;
  const style = document.createElement("style");
  style.textContent = `@page { ${page} }`;
  document.head.appendChild(style);
  doc.classList.add("printing");
  document.body.classList.add("print-mode");
  const done = () => {
    doc.classList.remove("printing");
    document.body.classList.remove("print-mode");
    style.remove();
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
  setTimeout(done, 1500); // some browsers never fire afterprint
}

// Example data used by the Branding page previews.
export const SAMPLE_LINES: DocLine[] = [
  { name: "Beef steak 1kg", sku: "BEEF-1KG", qty: 2, unit_price: 8500, tax_amount: 0, line_total: 17000 },
  { name: "Cooking oil 2L", sku: "OIL-2L", qty: 1, unit_price: 12500, tax_amount: 1770.39, line_total: 12500 },
  { name: "Bread loaf", sku: "BREAD", qty: 3, unit_price: 1700, tax_amount: 722.32, line_total: 5100 },
];
