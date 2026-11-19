// Products (category tree, pictures, create/edit, branch prices) and Purchase orders (create, receive, cancel).
import { useEffect, useMemo, useRef, useState } from "react";
import { ImagePlus, LayoutGrid, List, Plus, QrCode, X } from "lucide-react";
import { printLabels } from "../labels";
import { ScanButton, ScannerModal } from "../Scanner";
import { useScannerInput } from "../scanning";
import { api, apiForm, money } from "../api";
import { Thumb } from "../CategoryBrowser";
import { CategoryTree, sortedPaths, TreeRow, useCategoryTree } from "./categories";
import { Err, Errors, margin, QuickAdd, toErrors, useOptions } from "./ui";
import type { Ctx } from "./BackOffice";
import { DateFilters, dateFilters, SortHeader, useListState } from "./listing";

type Product = {
  id: number; sku: string; barcode: string; name: string; category: number | null; category_name: string;
  category_path: string; image_url: string | null;
  unit: string; cost_price: string; sell_price: string; tax_rate: number | null; tax_name: string;
  track_stock: boolean; reorder_level: string; min_price: string | null; is_active: boolean;
};

const VIEW_KEY = "office.products.view";

// ================================================================================================
// Products
// ================================================================================================
export function Products({ ctx }: { ctx: Ctx }) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<number | null>(null);
  const [active, setActive] = useState("true");
  const [view, setView] = useState<"grid" | "list">(() => { try { return (localStorage.getItem(VIEW_KEY) as any) || "grid"; } catch { return "grid"; } });
  const [tick, setTick] = useState(0);
  const [rows, setRows] = useState<Product[] | null>(null);
  const [count, setCount] = useState(0);
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const [scanning, setScanning] = useState(false);
  const sorter = useListState({ sort: "name" });
  const shownProducts = rows && sorter.apply(rows, {
    filters: { stocked: (p: Product, v) => (v === "yes" ? p.track_stock : !p.track_stock), photo: (p: Product, v) => (v === "yes" ? !!p.image_url : !p.image_url) },
    sorts: { name: (p: Product) => p.name, category: (p: Product) => p.category_path, cost: (p: Product) => Number(p.cost_price),
             price: (p: Product) => Number(p.sell_price), margin: (p: Product) => (Number(p.sell_price) - Number(p.cost_price)) / (Number(p.sell_price) || 1),
             tax: (p: Product) => p.tax_name, reorder: (p: Product) => Number(p.reorder_level) } });
  useScannerInput(setSearch, !scanning && !editing);
  const tree = useCategoryTree();
  const canEdit = ctx.canOrg("catalog.manage");

  useEffect(() => {
    const q = new URLSearchParams({ ordering: "name", page_size: "200" });
    if (search) q.set("search", search);
    if (category !== null) q.set("category_tree", String(category));
    if (active) q.set("is_active", active);
    setRows(null);
    api(`/products/?${q}`, { branch: null }).then((d) => { setRows(d.results); setCount(d.count); }).catch(() => setRows([]));
  }, [search, category, active, tick]);

  function pickView(v: "grid" | "list") { setView(v); try { localStorage.setItem(VIEW_KEY, v); } catch { /* private mode */ } }
  const place = tree.rows?.find((r) => r.id === category);

  return (
    <div className="catalog-layout">
      <CategoryTree rows={tree.rows} selected={category} onSelect={setCategory} canManage={canEdit}
                    onChanged={() => { tree.reload(); setTick((t) => t + 1); }} />
      <div style={{ minWidth: 0 }}>
        <div className="toolbar">
          <input type="search" placeholder="Search name, SKU or barcode" aria-label="Search products" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select aria-label="Status" value={active} onChange={(e) => setActive(e.target.value)}>
            <option value="true">Active</option><option value="false">Inactive</option><option value="">All</option>
          </select>
          <select aria-label="Stocked" value={sorter.state.filters.stocked || ""} onChange={(e) => sorter.setFilter("stocked", e.target.value)}>
            <option value="">Stocked or not</option><option value="yes">Stock tracked</option><option value="no">Not stocked</option></select>
          <select aria-label="Photo" value={sorter.state.filters.photo || ""} onChange={(e) => sorter.setFilter("photo", e.target.value)}>
            <option value="">Any photo</option><option value="yes">With photo</option><option value="no">No photo</option></select>
          {view === "grid" && <select aria-label="Sort products" value={sorter.state.sort} onChange={(e) => sorter.setSort(e.target.value)}>
            <option value="name">Name A–Z</option><option value="-name">Name Z–A</option><option value="price">Price: low first</option>
            <option value="-price">Price: high first</option><option value="-margin">Best margin</option><option value="category">Category</option></select>}
          <div className="seg" role="group" aria-label="View">
            <button className={view === "grid" ? "on" : ""} aria-pressed={view === "grid"} onClick={() => pickView("grid")}><LayoutGrid size={14} />Grid</button>
            <button className={view === "list" ? "on" : ""} aria-pressed={view === "list"} onClick={() => pickView("list")}><List size={14} />List</button>
          </div>
          <ScanButton onClick={() => setScanning(true)} />
          {scanning && <ScannerModal onCode={setSearch} onClose={() => setScanning(false)} />}
          <span className="muted">{place ? `${place.path} · ` : ""}{count} products</span>
          <span className="spacer" />
          <button disabled={!rows?.length} onClick={() => printLabels(rows || [], ctx.me.organization_name)}
                  title="Print QR shelf labels for the products listed"><QrCode size={16} />QR labels</button>
          {canEdit && <button className="primary" onClick={() => setEditing("new")}><Plus size={16} />New product</button>}
        </div>
        {!canEdit && <p className="muted">Products are managed by head office. Click a product to set its price for your branch.</p>}
        {rows === null && <div className="tile-grid">{[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton" style={{ aspectRatio: ".8" }} />)}</div>}
        {rows && !rows.length && <p className="muted">No products {place ? `in ${place.path}` : "match"}.</p>}
        {!!rows?.length && view === "grid" && (
          <div className="tile-grid">{(shownProducts || []).map((p) => (
            <button key={p.id} type="button" className={`tile ${p.is_active ? "" : "out"}`} onClick={() => setEditing(p)} aria-label={`Open ${p.name}`}>
              <span className="tile-img"><Thumb src={p.image_url} name={p.name} />
                {!p.is_active && <span className="stock-badge out">Inactive</span>}</span>
              <span className="tile-name">{p.name}</span>
              <span className="tile-foot"><b>{money(p.sell_price)}</b><small>{p.sku}</small></span>
              <small className="muted" style={{ fontSize: ".74rem" }}>{p.category_path || "No category"}</small>
            </button>
          ))}</div>
        )}
        {!!rows?.length && view === "list" && (
          <table className="grid-table clickable">
            <thead><tr><SortHeader list={sorter} k="name">Product</SortHeader><SortHeader list={sorter} k="category">Category</SortHeader>
              <SortHeader list={sorter} k="cost" num>Cost</SortHeader><SortHeader list={sorter} k="price" num>Price</SortHeader>
              <SortHeader list={sorter} k="margin" num>Margin</SortHeader><SortHeader list={sorter} k="tax">Tax</SortHeader>
              <SortHeader list={sorter} k="reorder" num>Reorder at</SortHeader><th /></tr></thead>
            <tbody>{(shownProducts || []).map((p) => (
              <tr key={p.id} tabIndex={0} onClick={() => setEditing(p)} onKeyDown={(e) => e.key === "Enter" && setEditing(p)}>
                <td><span className="name-cell"><span className="row-thumb"><Thumb src={p.image_url} name={p.name} /></span>
                  <span><b>{p.name}</b><br /><small className="muted">{p.sku}</small>{!p.track_stock && <span className="tag">not stocked</span>}</span></span></td>
                <td>{p.category_path}</td>
                <td className="num">{money(p.cost_price)}</td><td className="num">{money(p.sell_price)}</td>
                <td className="num">{margin(p.sell_price, p.cost_price)}</td><td>{p.tax_name}</td>
                <td className="num">{p.track_stock ? Number(p.reorder_level) : ""}</td>
                <td>{!p.is_active && <span className="tag">inactive</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {editing && <ProductForm ctx={ctx} product={editing === "new" ? null : editing} tree={tree.rows ?? []}
        defaultCategory={category} reloadTree={tree.reload}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setTick((t) => t + 1); tree.reload(); }} />}
    </div>
  );
}

const EMPTY = { sku: "", barcode: "", name: "", category: "", unit: "pcs", cost_price: "", sell_price: "", tax_rate: "",
  min_price: "", reorder_level: "0", track_stock: true, is_active: true };

function ProductForm({ ctx, product, tree, defaultCategory, reloadTree, onClose, onSaved }: {
  ctx: Ctx; product: Product | null; tree: TreeRow[]; defaultCategory: number | null; reloadTree: () => void;
  onClose: () => void; onSaved: () => void;
}) {
  const canEdit = ctx.canOrg("catalog.manage");
  const taxes = useOptions("/tax-rates/");
  const [f, setF] = useState(() => product ? {
    sku: product.sku, barcode: product.barcode, name: product.name, category: product.category ? String(product.category) : "",
    unit: product.unit, cost_price: product.cost_price, sell_price: product.sell_price,
    tax_rate: product.tax_rate ? String(product.tax_rate) : "", min_price: product.min_price ?? "",
    reorder_level: product.reorder_level, track_stock: product.track_stock, is_active: product.is_active,
  } : { ...EMPTY, category: defaultCategory !== null ? String(defaultCategory) : "" });
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [extraCats, setExtraCats] = useState<TreeRow[]>([]);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(product?.image_url ?? null);
  const [clearPhoto, setClearPhoto] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const cats = useMemo(() => sortedPaths([...tree, ...extraCats.filter((x) => !tree.some((t) => t.id === x.id))]), [tree, extraCats]);
  const chosen = cats.find((c) => String(c.id) === f.category);

  useEffect(() => { // default new products to the first tax rate (VAT)
    if (!product && !f.tax_rate && taxes.items[0]) setF((x) => ({ ...x, tax_rate: String(taxes.items[0].id) }));
  }, [taxes.items]);
  useEffect(() => () => { if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview); }, [preview]);

  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });

  function pickPhoto(file: File | undefined) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { setErrors({ image: "Photo is larger than 5 MB." }); return; }
    setPhoto(file); setClearPhoto(false); setPreview(URL.createObjectURL(file)); setErrors((e) => ({ ...e, image: "" }));
  }

  async function save() {
    setBusy(true); setErrors({});
    const body = {
      ...f, category: f.category ? Number(f.category) : null, tax_rate: f.tax_rate ? Number(f.tax_rate) : null,
      min_price: f.min_price === "" ? null : f.min_price, cost_price: f.cost_price || "0",
    };
    try {
      const saved = await api(product ? `/products/${product.id}/` : "/products/", { method: product ? "PATCH" : "POST", body, branch: null });
      if (photo || clearPhoto) {
        const form = new FormData();
        if (photo) form.set("image", photo); else form.set("clear_image", "true");
        try { await apiForm(`/products/${saved.id}/`, form); }
        catch (e) { setErrors({ image: Object.values(toErrors(e)).join(" ") }); setBusy(false); return; }
      }
      onSaved();
    } catch (e) { setErrors(toErrors(e)); } finally { setBusy(false); }
  }

  const ro = !canEdit;
  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}><div className="card wide">
      <div className="card-head"><h3>{product ? product.name : "New product"}</h3>
        <button className="ghost icon" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
      {errors.detail && <p className="error">{errors.detail}</p>}
      <div className="photo-picker">
        <span className="preview"><Thumb src={clearPhoto ? null : preview} name={f.name || "?"} /></span>
        {!ro && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <button type="button" onClick={() => fileInput.current?.click()}><ImagePlus size={16} />{preview && !clearPhoto ? "Change photo" : "Add photo"}</button>
            {preview && !clearPhoto && <button type="button" className="ghost" onClick={() => { setClearPhoto(true); setPhoto(null); }}><X size={15} />Remove photo</button>}
            <span className="drop-hint">A clear photo on a plain background helps cashiers. JPEG, PNG or WebP, up to 5 MB — it is resized automatically.</span>
            <Err e={errors} k="image" />
          </div>
        )}
        <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => pickPhoto(e.target.files?.[0])} />
      </div>
      <fieldset disabled={ro} className="form-grid">
        <label>Name<input value={f.name} onChange={set("name")} autoFocus={!product} /><Err e={errors} k="name" /></label>
        <label>SKU<input value={f.sku} onChange={set("sku")} placeholder="e.g. SUG-2KG" /><Err e={errors} k="sku" /></label>
        <label>Barcode<input value={f.barcode} onChange={set("barcode")} placeholder="Scan or type" /><Err e={errors} k="barcode" /></label>
        <label>Category
          <select value={f.category} onChange={set("category")}>
            <option value="">No category</option>
            {cats.map((c) => <option key={c.id} value={c.id}>{c.path}</option>)}
          </select>
          {!ro && <QuickAdd label={chosen ? `under ${chosen.name}` : "department"}
            fields={[{ key: "name", placeholder: chosen ? `New subcategory of ${chosen.name}` : "New department name", required: true }]}
            create={async ({ name }) => {
              const c = await api("/categories/", { body: { name: name.trim(), parent: chosen ? chosen.id : null }, branch: null });
              setExtraCats((x) => [...x, { ...c, products: 0, total_products: 0 }]);
              reloadTree(); setF((x) => ({ ...x, category: String(c.id) }));
            }} />}
          <Err e={errors} k="category" /></label>
        <label>Unit<input value={f.unit} onChange={set("unit")} placeholder="pcs, kg, bunch…" /></label>
        <label>Tax
          <select value={f.tax_rate} onChange={set("tax_rate")}>
            <option value="">None</option>
            {taxes.items.map((t: any) => <option key={t.id} value={t.id}>{t.name}{t.inclusive ? " (in price)" : " (added)"}</option>)}
          </select><Err e={errors} k="tax_rate" /></label>
        <label>Cost price<input inputMode="decimal" value={f.cost_price} onChange={set("cost_price")} /><Err e={errors} k="cost_price" /></label>
        <label>Selling price<input inputMode="decimal" value={f.sell_price} onChange={set("sell_price")} />
          <small className="muted">Margin {margin(f.sell_price, f.cost_price)}</small><Err e={errors} k="sell_price" /></label>
        <label>Floor price<input inputMode="decimal" value={f.min_price} onChange={set("min_price")} placeholder="optional" />
          <small className="muted">No one can sell below this, even with approval.</small><Err e={errors} k="min_price" /></label>
        <label>Reorder level<input inputMode="decimal" value={f.reorder_level} onChange={set("reorder_level")} disabled={!f.track_stock} />
          <Err e={errors} k="reorder_level" /></label>
        <label className="check"><input type="checkbox" checked={f.track_stock} onChange={set("track_stock")} /> Track stock (untick for services, airtime)</label>
        <label className="check"><input type="checkbox" checked={f.is_active} onChange={set("is_active")} /> Active (sold at tills)</label>
      </fieldset>
      {product && <BranchPrices product={product} />}
      <div className="actions">
        {canEdit && <button className="primary" disabled={busy || !f.name || !f.sku || !f.sell_price} onClick={save}>
          {busy ? "Saving…" : product ? "Save changes" : "Create product"}</button>}
        <button className="link" onClick={onClose}>{canEdit ? "Cancel" : "Close"}</button>
      </div>
    </div></div>
  );
}

function BranchPrices({ product }: { product: Product }) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [edit, setEdit] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState<Record<number, string>>({});
  useEffect(() => { api(`/products/${product.id}/branch_prices/`, { branch: null }).then(setRows).catch(() => setRows([])); }, [product.id]);
  async function save(branch: number, price: string) {
    try {
      setRows(await api(`/products/${product.id}/branch_prices/`, { body: { branch, price }, branch: null }));
      setMsg({ ...msg, [branch]: "Saved" }); setEdit({ ...edit, [branch]: undefined as any });
    } catch (e) { setMsg({ ...msg, [branch]: Object.values(toErrors(e)).join(" ") }); }
  }
  if (!rows?.length) return null;
  return (
    <section>
      <h4>Branch prices</h4>
      <p className="muted"><small>Leave empty to sell at the base price ({money(product.sell_price)}).</small></p>
      <table className="grid-table">
        <thead><tr><th>Branch</th><th className="num">Price at till</th><th /></tr></thead>
        <tbody>{rows.map((r) => {
          const val = edit[r.branch] ?? (r.price ?? "");
          return (
            <tr key={r.branch}>
              <td>{r.name}</td>
              <td className="num">{r.can_edit
                ? <input className="narrow" inputMode="decimal" placeholder={money(r.base_price)} value={val}
                         onChange={(e) => setEdit({ ...edit, [r.branch]: e.target.value })} />
                : money(r.price ?? r.base_price)}</td>
              <td>{r.can_edit && <button disabled={val === (r.price ?? "")} onClick={() => save(r.branch, val)}>Save</button>}
                {msg[r.branch] && <small className={msg[r.branch] === "Saved" ? "ok" : "error"}> {msg[r.branch]}</small>}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </section>
  );
}

// ================================================================================================
// Purchase orders
// ================================================================================================
const STATUS_LABEL: Record<string, string> = { draft: "Draft", ordered: "Ordered", partial: "Partly received",
  received: "Received", cancelled: "Cancelled" };

export function PurchaseOrders({ ctx }: { ctx: Ctx }) {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [open, setOpen] = useState<any>(null);
  const [creating, setCreating] = useState(false);
  const branchName = (id: number) => ctx.me.branches.find((b) => b.id === id)?.name || `#${id}`;
  const sorter = useListState({ sort: "-created_at" });
  const shownPOs = rows && sorter.apply(rows, {
    filters: dateFilters((o: any) => o.created_at),
    sorts: { number: (o: any) => o.number, created_at: (o: any) => o.created_at, supplier: (o: any) => o.supplier_name, expected: (o: any) => o.expected_date || "",
             status: (o: any) => o.status, total: (o: any) => Number(o.total), branch: (o: any) => branchName(o.branch) } });

  useEffect(() => {
    const q = new URLSearchParams({ ordering: "-created_at", page_size: "200" });
    if (status) q.set("status", status);
    if (search) q.set("search", search);
    api(`/purchase-orders/?${q}`, { branch: ctx.branch }).then((d) => setRows(d.results)).catch((e) => setError(e.message));
  }, [status, search, tick, ctx.branch]);

  return (
    <div>
      <div className="toolbar">
        <input placeholder="PO number or supplier" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <DateFilters list={sorter} />
        <span className="spacer" />
        {ctx.can("purchasing.manage") && <button className="primary" onClick={() => setCreating(true)}>+ New purchase order</button>}
      </div>
      {error && <p className="error">{error}</p>}
      {rows && !rows.length && <p className="muted">No purchase orders yet.</p>}
      {!!rows?.length && (
        <table className="grid-table clickable">
          <thead><tr><SortHeader list={sorter} k="number">PO</SortHeader><SortHeader list={sorter} k="created_at">Created</SortHeader>
            {!ctx.branch && <SortHeader list={sorter} k="branch">Branch</SortHeader>}<SortHeader list={sorter} k="supplier">Supplier</SortHeader>
            <SortHeader list={sorter} k="expected">Expected</SortHeader><SortHeader list={sorter} k="status">Status</SortHeader>
            <SortHeader list={sorter} k="total" num>Total</SortHeader></tr></thead>
          <tbody>{(shownPOs || []).map((o) => (
            <tr key={o.id} tabIndex={0} onClick={() => setOpen(o)} onKeyDown={(e) => e.key === "Enter" && setOpen(o)}>
              <td>{o.number}</td><td>{new Date(o.created_at).toLocaleDateString()}</td>
              {!ctx.branch && <td>{branchName(o.branch)}</td>}
              <td>{o.supplier_name}</td><td>{o.expected_date || ""}</td>
              <td><span className={`tag status-${o.status}`}>{STATUS_LABEL[o.status]}</span></td>
              <td className="num">{money(o.total)}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {open && <PODetail ctx={ctx} order={open} onClose={() => setOpen(null)}
                         onChanged={(o) => { setOpen(o); setTick((t) => t + 1); }} />}
      {creating && <NewPO ctx={ctx} onClose={() => setCreating(false)}
                          onSaved={(o) => { setCreating(false); setTick((t) => t + 1); setOpen(o); }} />}
    </div>
  );
}

function PODetail({ ctx, order, onClose, onChanged }: { ctx: Ctx; order: any; onClose: () => void; onChanged: (o: any) => void }) {
  const at = ctx.me.branches.find((b) => b.id === order.branch);
  const has = (p: string) => ctx.me.org_permissions.includes(p) || !!at?.permissions.includes(p);
  const outstanding = (l: any) => Math.max(0, Number(l.quantity) - Number(l.received_quantity));
  const receivable = ["ordered", "partial"].includes(order.status) && has("inventory.receive");
  const fresh = () => Object.fromEntries(order.lines.map((l: any) => [l.id, String(outstanding(l))]));
  const [qty, setQty] = useState<Record<number, string>>(fresh);
  useEffect(() => setQty(fresh()), [order]); // after a delivery, default to what is still outstanding
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const toReceive = () => Object.fromEntries(order.lines.filter((l: any) => outstanding(l) > 0).map((l: any) => [l.id, qty[l.id] || "0"]));
  const receiveValue = order.lines.reduce((s: number, l: any) =>
    s + (outstanding(l) > 0 ? Number(qty[l.id] || 0) * Number(l.unit_cost) : 0), 0);

  async function receive() {
    setBusy(true); setErrors({});
    try { onChanged(await api(`/purchase-orders/${order.id}/receive/`, { body: { lines: toReceive() }, branch: String(order.branch) })); }
    catch (e) { setErrors(toErrors(e)); } finally { setBusy(false); }
  }
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  async function cancel() {
    try { onChanged(await api(`/purchase-orders/${order.id}/cancel/`, { body: { reason }, branch: String(order.branch) })); }
    catch (e) { setErrors(toErrors(e)); }
  }

  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}><div className="card wide">
      <h3>{order.number} · {order.supplier_name}</h3>
      <p className="muted">{at?.name} · {STATUS_LABEL[order.status]} · created {new Date(order.created_at).toLocaleString()}
        {order.created_by_name && ` by ${order.created_by_name}`}{order.expected_date && ` · expected ${order.expected_date}`}</p>
      {order.note && <p className="note">{order.note}</p>}
      {Object.values(errors).map((m, i) => <p key={i} className="error">{m}</p>)}
      <table className="grid-table">
        <thead><tr><th>Item</th><th className="num">Ordered</th><th className="num">Received</th><th className="num">Unit cost</th>
          <th className="num">Line total</th>{receivable && <th className="num">Receive now</th>}</tr></thead>
        <tbody>{order.lines.map((l: any) => (
          <tr key={l.id}>
            <td>{l.product_name}</td><td className="num">{Number(l.quantity)}</td>
            <td className="num">{Number(l.received_quantity)}{outstanding(l) === 0 && " ✓"}</td>
            <td className="num">{money(l.unit_cost)}</td><td className="num">{money(Number(l.quantity) * Number(l.unit_cost))}</td>
            {receivable && <td className="num">{outstanding(l) > 0
              ? <input className="narrow" inputMode="decimal" aria-label={`Receive ${l.product_name}`} value={qty[l.id] ?? ""}
                       onChange={(e) => setQty({ ...qty, [l.id]: e.target.value })} />
              : "–"}</td>}
          </tr>
        ))}</tbody>
        <tfoot><tr><th colSpan={4}>Order total</th><th className="num">{money(order.total)}</th>{receivable && <th />}</tr></tfoot>
      </table>
      <div className="actions">
        {receivable && <button className="primary" disabled={busy || receiveValue <= 0} onClick={receive}>
          Receive goods ({money(receiveValue)})</button>}
        {order.status === "ordered" && has("purchasing.manage") && (cancelling ? (
          <span className="inline">
            <input placeholder="Reason for cancelling" aria-label="Reason for cancelling" value={reason} autoFocus
                   onChange={(e) => setReason(e.target.value)} />
            <button className="danger" disabled={!reason.trim()} onClick={cancel}>Confirm cancel</button>
            <button className="link" onClick={() => setCancelling(false)}>Keep order</button>
          </span>
        ) : <button onClick={() => setCancelling(true)}>Cancel order</button>)}
        <button className="link" onClick={onClose}>Close</button>
      </div>
      {receivable && <p className="muted"><small>Receiving adds the goods to stock at this cost and records what you owe the supplier.</small></p>}
    </div></div>
  );
}

type Line = { product: any; quantity: string; unit_cost: string };

function NewPO({ ctx, onClose, onSaved }: { ctx: Ctx; onClose: () => void; onSaved: (o: any) => void }) {
  const branches = ctx.me.branches.filter((b) => ctx.me.org_permissions.includes("purchasing.manage") || b.permissions.includes("purchasing.manage"));
  const [branch, setBranch] = useState(ctx.branch && branches.some((b) => String(b.id) === ctx.branch) ? ctx.branch : String(branches[0]?.id ?? ""));
  const suppliers = useOptions("/suppliers/?page_size=500");
  const products = useOptions("/products/?page_size=500&is_active=true&ordering=name");
  const [supplier, setSupplier] = useState("");
  const [expected, setExpected] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [find, setFind] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  const matches = useMemo(() => {
    const q = find.trim().toLowerCase();
    if (!q) return [];
    return products.items.filter((p: any) => p.track_stock && !lines.some((l) => l.product.id === p.id) &&
      (p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || p.barcode === find.trim())).slice(0, 8);
  }, [find, products.items, lines]);
  const total = lines.reduce((s, l) => s + Number(l.quantity || 0) * Number(l.unit_cost || 0), 0);

  function add(p: any) { setLines([...lines, { product: p, quantity: "1", unit_cost: p.cost_price }]); setFind(""); }
  function upd(i: number, k: "quantity" | "unit_cost", v: string) { setLines(lines.map((l, j) => (j === i ? { ...l, [k]: v } : l))); }

  async function save() {
    setBusy(true); setErrors({});
    try {
      const o = await api("/purchase-orders/", { branch, body: {
        branch: Number(branch), supplier: Number(supplier), expected_date: expected || null, note,
        lines: lines.map((l) => ({ product: l.product.id, quantity: l.quantity, unit_cost: l.unit_cost })) } });
      onSaved(o);
    } catch (e) { setErrors(toErrors(e)); } finally { setBusy(false); }
  }

  return (
    <div className="modal"><div className="card wide">
      <h3>New purchase order</h3>
      {Object.entries(errors).filter(([k]) => !["supplier"].includes(k)).map(([k, m]) => <p key={k} className="error">{m}</p>)}
      <div className="form-grid">
        <label>Deliver to branch
          <select value={branch} onChange={(e) => setBranch(e.target.value)}>
            {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select></label>
        <label>Supplier
          <span className="inline">
            <select value={supplier} onChange={(e) => setSupplier(e.target.value)}>
              <option value="">Choose…</option>
              {suppliers.items.filter((s: any) => s.is_active).map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </span>
          <QuickAdd label="supplier" fields={[{ key: "name", placeholder: "Supplier name", required: true },
                                              { key: "phone", placeholder: "Phone (optional)" }]}
            create={async ({ name, phone }) => {
              const sp = await api("/suppliers/", { body: { name: name.trim(), phone: phone || "" }, branch: null });
              suppliers.reload(); setSupplier(String(sp.id));
            }} />
          <Err e={errors} k="supplier" /></label>
        <label>Expected delivery<input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} /></label>
        <label>Note<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional" /></label>
      </div>

      <h4>Items</h4>
      <div className="picker">
        <input placeholder="Add item: search name, SKU or scan barcode" value={find} onChange={(e) => setFind(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter" && matches[0]) { e.preventDefault(); add(matches[0]); } }} />
        {!!matches.length && (
          <ul className="picker-list">{matches.map((p: any) => (
            <li key={p.id}><button type="button" onClick={() => add(p)}>{p.name} <small className="muted">{p.sku} · cost {money(p.cost_price)}</small></button></li>
          ))}</ul>
        )}
      </div>
      {lines.length ? (
        <table className="grid-table">
          <thead><tr><th>Item</th><th className="num">Quantity</th><th className="num">Unit cost</th><th className="num">Line total</th><th /></tr></thead>
          <tbody>{lines.map((l, i) => (
            <tr key={l.product.id}>
              <td>{l.product.name}</td>
              <td className="num"><input className="narrow" inputMode="decimal" aria-label={`Quantity of ${l.product.name}`} value={l.quantity} onChange={(e) => upd(i, "quantity", e.target.value)} /></td>
              <td className="num"><input className="narrow" inputMode="decimal" aria-label={`Unit cost of ${l.product.name}`} value={l.unit_cost} onChange={(e) => upd(i, "unit_cost", e.target.value)} /></td>
              <td className="num">{money(Number(l.quantity || 0) * Number(l.unit_cost || 0))}</td>
              <td><button className="link" aria-label={`Remove ${l.product.name}`} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button></td>
            </tr>
          ))}</tbody>
          <tfoot><tr><th colSpan={3}>Total</th><th className="num">{money(total)}</th><th /></tr></tfoot>
        </table>
      ) : <p className="muted">No items yet.</p>}

      <div className="actions">
        <button className="primary" disabled={busy || !supplier || !branch || !lines.length ||
          lines.some((l) => !(Number(l.quantity) > 0) || l.unit_cost === "")} onClick={save}>Place order</button>
        <button className="link" onClick={onClose}>Cancel</button>
      </div>
    </div></div>
  );
}
