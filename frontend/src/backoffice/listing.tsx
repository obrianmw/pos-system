// Shared list controls: a search box, filter dropdowns/dates and clickable sort headers.
// Works for server lists (pass list.state to the API as ?search=&ordering=&...) and for
// lists already in memory (list.apply(rows, {...}) filters and sorts them here).
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Search, X } from "lucide-react";

export type ListState = { search: string; sort: string; filters: Record<string, string> };
export type Filter = { key: string; label: string; type?: "select" | "date"; options?: [string, string][] };

type ApplyOpts<T> = {
  text?: (row: T) => string;
  filters?: Record<string, (row: T, value: string) => boolean>;
  sorts?: Record<string, (row: T) => string | number | null | undefined>;
};

export function useListState(init: { sort?: string; filters?: Record<string, string> } = {}) {
  const [state, setState] = useState<ListState>({ search: "", sort: init.sort || "", filters: init.filters || {} });
  const [typed, setTyped] = useState("");
  // Debounce typing so server lists aren't refetched on every key.
  useEffect(() => { const t = setTimeout(() => setState((s) => (s.search === typed ? s : { ...s, search: typed })), 250); return () => clearTimeout(t); }, [typed]);
  return {
    state, typed, setTyped,
    setFilter: (key: string, value: string) => setState((s) => ({ ...s, filters: { ...s.filters, [key]: value } })),
    setSort: (sort: string) => setState((s) => ({ ...s, sort })),
    toggleSort: (key: string) => setState((s) => ({ ...s, sort: s.sort === key ? `-${key}` : key })),
    clear: () => { setTyped(""); setState((s) => ({ search: "", sort: s.sort, filters: {} })); },
    /** Query string for DRF: search, ordering and every non-empty filter. */
    query(extra: Record<string, string> = {}) {
      const qp = new URLSearchParams(extra);
      if (state.search) qp.set("search", state.search);
      if (state.sort) qp.set("ordering", state.sort);
      Object.entries(state.filters).forEach(([k, v]) => v && qp.set(k, v));
      return qp.toString();
    },
    apply<T>(rows: T[], o: ApplyOpts<T>): T[] {
      const needle = state.search.trim().toLowerCase();
      let out = rows.filter((r) => !needle || !o.text || o.text(r).toLowerCase().includes(needle));
      for (const [k, v] of Object.entries(state.filters)) {
        const fn = o.filters?.[k];
        if (v && fn) out = out.filter((r) => fn(r, v));
      }
      const key = state.sort.replace(/^-/, "");
      const get = o.sorts?.[key];
      if (get) {
        const dir = state.sort.startsWith("-") ? -1 : 1;
        out = [...out].sort((a, b) => {
          const x = get(a), y = get(b);
          if (x == null) return 1;
          if (y == null) return -1;
          return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * dir;
        });
      }
      return out;
    },
  };
}
export type List = ReturnType<typeof useListState>;

export function ListControls({ list, placeholder = "Search", filters = [], count, right }: {
  list: List; placeholder?: string; filters?: Filter[]; count?: number; right?: ReactNode;
}) {
  const active = !!list.typed || Object.values(list.state.filters).some(Boolean);
  return (
    <div className="toolbar list-controls">
      <label className="list-search"><Search size={16} aria-hidden />
        <input type="search" value={list.typed} placeholder={placeholder} aria-label={placeholder}
               onChange={(e) => list.setTyped(e.target.value)} /></label>
      {filters.map((f) => f.type === "date" ? (
        <label key={f.key}>{f.label}
          <input type="date" value={list.state.filters[f.key] || ""} onChange={(e) => list.setFilter(f.key, e.target.value)} /></label>
      ) : (
        <select key={f.key} aria-label={f.label} value={list.state.filters[f.key] || ""} onChange={(e) => list.setFilter(f.key, e.target.value)}>
          {(f.options || []).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      ))}
      {active && <button className="ghost-btn" onClick={list.clear}><X size={14} />Clear</button>}
      {count !== undefined && <span className="muted" style={{ fontSize: ".85rem" }}>{count.toLocaleString()} found</span>}
      {right && <><span className="spacer" />{right}</>}
    </div>
  );
}

export function SortHeader({ list, k, num, children }: { list: List; k: string; num?: boolean; children: ReactNode }) {
  const s = list.state.sort;
  const on = s === k || s === `-${k}`;
  const Icon = !on ? ArrowUpDown : s.startsWith("-") ? ArrowDown : ArrowUp;
  return (
    <th className={`${num ? "num " : ""}sortable${on ? " sorted" : ""}`}
        aria-sort={on ? (s.startsWith("-") ? "descending" : "ascending") : "none"}>
      <button type="button" className="sort-btn" onClick={() => list.toggleSort(k)}>
        {children}<Icon size={13} aria-hidden /></button>
    </th>
  );
}

/** From/To date inputs bound to a list's "from"/"to" filters (for toolbars that already have their own search). */
export function DateFilters({ list }: { list: List }) {
  return (<>
    <label>From <input type="date" value={list.state.filters.from || ""} onChange={(e) => list.setFilter("from", e.target.value)} /></label>
    <label>To <input type="date" value={list.state.filters.to || ""} onChange={(e) => list.setFilter("to", e.target.value)} /></label>
  </>);
}

/** Filter functions for in-memory "from"/"to" date filters on any date/ISO field. */
export function dateFilters<T>(get: (row: T) => string | null | undefined) {
  return {
    from: (r: T, v: string) => (get(r) || "").slice(0, 10) >= v,
    to: (r: T, v: string) => !!get(r) && (get(r) || "").slice(0, 10) <= v,
  };
}
