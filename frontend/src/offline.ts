// Offline support: the branch catalog is cached in IndexedDB and sales made without a connection
// are queued there, then pushed to /api/sales/sync/. Each sale carries a client_uuid so resending is
// harmless; the server answers "duplicate" and the till just drops it from the queue.
import { del, get, set } from "idb-keyval";
import { api } from "./api";

export type Product = {
  id: number; sku: string; barcode: string; name: string; unit: string; category: string;
  category_id: number | null; category_path: string; image_url: string | null;
  price: string; min_price: string | null; tax_rate: string; tax_inclusive: boolean;
  track_stock: boolean; stock: string; reorder_level?: string;
};
export type CatalogCategory = {
  id: number; name: string; parent: number | null; path: string; image_url: string | null; sort_order: number;
};
export type PaymentMethod = {
  id: number; name: string; kind: string; provider: string; requires_reference: boolean; allowed_offline: boolean;
  /** Payment-QR settings from the method's config (qr_merchant, qr_account, qr_bank, qr_account_name, qr_template). */
  qr?: Record<string, string>;
};
export type Catalog = {
  branch: { id: number; name: string; code: string; currency: string; max_cashier_discount_pct: string;
            receipt_footer: string; organization: string };
  categories?: CatalogCategory[]; // missing in catalogs cached before categories existed
  products: Product[];
  payment_methods: PaymentMethod[];
  fetched_at?: string;
};

const catalogKey = (branch: string) => `catalog:${branch}`;
const QUEUE = "sales-queue";

export async function loadCatalog(branch: string): Promise<Catalog> {
  try {
    const fresh = await api<Catalog>("/pos/catalog/");
    fresh.fetched_at = new Date().toISOString();
    await set(catalogKey(branch), fresh);
    return fresh;
  } catch (e) {
    const cached = await get<Catalog>(catalogKey(branch));
    if (cached) return cached;
    throw e;
  }
}

export async function queuedSales(): Promise<any[]> {
  return (await get<any[]>(QUEUE)) || [];
}

export async function enqueueSale(sale: any) {
  const q = await queuedSales();
  q.push({ ...sale, offline: true });
  await set(QUEUE, q);
}

let syncing = false;
/** Push queued sales. Returns how many are still waiting (errors stay queued for a supervisor to see). */
export async function syncQueue(): Promise<{ pending: number; errors: string[] }> {
  const q = await queuedSales();
  if (!q.length || syncing) return { pending: q.length, errors: [] };
  syncing = true;
  try {
    const { results } = await api<{ results: any[] }>("/sales/sync/", { body: { sales: q } });
    const done = new Set(results.filter((r) => r.ok).map((r) => r.client_uuid));
    const left = q.filter((s) => !done.has(s.client_uuid));
    left.length ? await set(QUEUE, left) : await del(QUEUE);
    return { pending: left.length, errors: results.filter((r) => !r.ok).map((r) => r.error) };
  } catch {
    return { pending: q.length, errors: [] };
  } finally {
    syncing = false;
  }
}

/** Offline receipt numbers: TILL-local sequence, unique per till. */
export async function nextOfflineNumber(branchCode: string, tillCode: string) {
  const key = `offline-seq:${branchCode}:${tillCode}`;
  const n = ((await get<number>(key)) || 0) + 1;
  await set(key, n);
  return `${branchCode.toUpperCase()}-${tillCode.toUpperCase()}-OFF${String(n).padStart(5, "0")}`;
}
