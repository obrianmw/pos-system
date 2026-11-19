// Printable QR shelf labels. Each QR holds the product's barcode (or SKU when it has none), so a
// phone camera, the POS camera button and a USB/Bluetooth scanner all read the same code.
import { qrDataUrl } from "./Scanner";
import { money } from "./api";

export type LabelProduct = { name: string; sku: string; barcode?: string; sell_price?: string; price?: string; unit?: string };

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));

export async function printLabels(products: LabelProduct[], shop = "") {
  if (!products.length) return;
  const win = window.open("", "_blank", "width=900,height=700");
  if (!win) { alert("Allow pop-ups for this site to print labels."); return; }
  win.document.write("<p style='font:14px sans-serif'>Preparing labels…</p>");
  const cards = await Promise.all(products.map(async (p) => {
    const code = p.barcode || p.sku;
    const price = p.price ?? p.sell_price;
    return `<div class="l"><img src="${await qrDataUrl(code, 260)}" alt=""><div>
      <b>${esc(p.name)}</b>${price ? `<span class="p">${esc(money(price))}</span>` : ""}
      <small>${esc(code)}${p.unit ? ` · ${esc(p.unit)}` : ""}</small>${shop ? `<small>${esc(shop)}</small>` : ""}</div></div>`;
  }));
  win.document.open();
  win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>QR labels</title><style>
    @page { size: A4; margin: 10mm; }
    body { font-family: system-ui, sans-serif; margin: 0; color: #111; }
    .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4mm; }
    .l { display: flex; gap: 3mm; align-items: center; border: 1px dashed #999; border-radius: 2mm; padding: 2.5mm; break-inside: avoid; }
    .l img { width: 24mm; height: 24mm; }
    .l div { display: flex; flex-direction: column; gap: 1mm; min-width: 0; font-size: 9pt; }
    .l b { font-size: 10pt; line-height: 1.15; }
    .p { font-size: 12pt; font-weight: 700; }
    small { color: #555; font-size: 7.5pt; overflow-wrap: anywhere; }
    .bar { padding: 10px; font-size: 14px; } @media print { .bar { display: none; } }
  </style></head><body><div class="bar">${products.length} label(s). <button onclick="print()">Print</button></div>
  <div class="grid">${cards.join("")}</div><script>setTimeout(() => print(), 300)<\/script></body></html>`);
  win.document.close();
}
