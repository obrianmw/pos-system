// Till product browser: department tabs -> subcategory chips -> picture tiles.
// Typing in the search box searches every category; an exact barcode/SKU match is added on Enter.
import { useMemo, useState } from "react";
import { matchesCode } from "./scanning";
import { ChevronRight, LayoutGrid } from "lucide-react";
import { money } from "./api";
import type { Catalog, CatalogCategory, Product } from "./offline";

/** Picture for a product/category; falls back to an initials tile when there is no photo or it fails to load. */
export function Thumb({ src, name, size }: { src: string | null | undefined; name: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  const style = size ? { width: size, height: size } : undefined;
  if (!src || broken) {
    const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");
    return <span className="thumb thumb-fallback" style={style} aria-hidden>{initials || "?"}</span>;
  }
  return <img className="thumb" style={style} src={src} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} />;
}

function stockState(p: Product): "out" | "low" | "" {
  if (!p.track_stock) return "";
  const n = Number(p.stock);
  if (n <= 0) return "out";
  if (n <= Number(p.reorder_level ?? 5)) return "low";
  return "";
}

export function ProductTile({ p, onAdd }: { p: Product; onAdd: (p: Product) => void }) {
  const st = stockState(p);
  return (
    <button type="button" className={`tile ${st}`} onClick={() => onAdd(p)}
            aria-label={`${p.name}, ${money(p.price)}${st === "out" ? ", out of stock" : st === "low" ? ", low stock" : ""}`}>
      <span className="tile-img"><Thumb src={p.image_url} name={p.name} />
        {st && <span className={`stock-badge ${st}`}>{st === "out" ? "Out of stock" : `Low · ${Number(p.stock)}`}</span>}
      </span>
      <span className="tile-name">{p.name}</span>
      <span className="tile-foot"><b>{money(p.price)}</b>{p.track_stock && !st && <small>{Number(p.stock)} in stock</small>}</span>
    </button>
  );
}

function descendants(cats: CatalogCategory[], id: number): Set<number> {
  const out = new Set<number>([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const c of cats) if (c.parent !== null && out.has(c.parent) && !out.has(c.id)) { out.add(c.id); grew = true; }
  }
  return out;
}

const byOrder = (a: CatalogCategory, b: CatalogCategory) => a.sort_order - b.sort_order || a.name.localeCompare(b.name);

export function searchProducts(catalog: Catalog | null, query: string): Product[] {
  if (!catalog || !query.trim()) return [];
  const raw = query.trim(), q = raw.toLowerCase();
  const exact = catalog.products.filter((p) => matchesCode(p, raw));
  const rest = catalog.products.filter((p) => !exact.includes(p) &&
    (p.name.toLowerCase().includes(q) || p.category_path?.toLowerCase().includes(q)));
  return [...exact, ...rest].slice(0, 30);
}

export default function CategoryBrowser({ catalog, query, onAdd }: {
  catalog: Catalog; query: string; onAdd: (p: Product) => void;
}) {
  const cats = catalog.categories ?? [];
  const [dept, setDept] = useState<number | null>(null);
  const [sub, setSub] = useState<number | null>(null);
  const tops = useMemo(() => cats.filter((c) => c.parent === null).sort(byOrder), [cats]);
  const subs = useMemo(() => (dept === null ? [] : cats.filter((c) => c.parent === dept).sort(byOrder)), [cats, dept]);
  const node = sub ?? dept;
  const inNode = useMemo(() => {
    if (node === null) return catalog.products;
    const ids = descendants(cats, node);
    return catalog.products.filter((p) => p.category_id !== null && ids.has(p.category_id));
  }, [catalog.products, cats, node]);
  const found = useMemo(() => searchProducts(catalog, query), [catalog, query]);
  const searching = query.trim().length > 0;
  const shown = searching ? found : inNode;
  const name = (id: number | null) => cats.find((c) => c.id === id)?.name ?? "";

  return (
    <div className="browser">
      {!searching && tops.length > 0 && (
        <>
          <div className="dept-tabs" role="tablist" aria-label="Departments">
            <button role="tab" aria-selected={dept === null} className={dept === null ? "on" : ""}
                    onClick={() => { setDept(null); setSub(null); }}>
              <span className="dept-icon"><LayoutGrid size={20} /></span>All
            </button>
            {tops.map((c) => (
              <button key={c.id} role="tab" aria-selected={dept === c.id} className={dept === c.id ? "on" : ""}
                      onClick={() => { setDept(c.id); setSub(null); }}>
                <Thumb src={c.image_url} name={c.name} size={36} />{c.name}
              </button>
            ))}
          </div>
          {subs.length > 0 && (
            <div className="sub-chips" role="group" aria-label={`${name(dept)} subcategories`}>
              <button className={sub === null ? "on" : ""} aria-pressed={sub === null} onClick={() => setSub(null)}>All {name(dept)}</button>
              {subs.map((c) => (
                <button key={c.id} className={sub === c.id ? "on" : ""} aria-pressed={sub === c.id} onClick={() => setSub(c.id)}>
                  <Thumb src={c.image_url} name={c.name} size={22} />{c.name}
                </button>
              ))}
            </div>
          )}
        </>
      )}
      <nav className="crumbs" aria-label="Where you are">
        {searching ? <span>Search results for “{query.trim()}” · {found.length}</span> : (
          <>
            <button className="link" onClick={() => { setDept(null); setSub(null); }}>All</button>
            {dept !== null && <><ChevronRight size={14} /><button className="link" onClick={() => setSub(null)}>{name(dept)}</button></>}
            {sub !== null && <><ChevronRight size={14} /><span>{name(sub)}</span></>}
            <span className="muted"> · {inNode.length} items</span>
          </>
        )}
      </nav>
      {shown.length ? (
        <div className="tile-grid">{shown.map((p) => <ProductTile key={p.id} p={p} onAdd={onAdd} />)}</div>
      ) : <p className="muted">{searching ? "No product matches. Check the spelling or scan the barcode." : "No products in this category yet."}</p>}
    </div>
  );
}
