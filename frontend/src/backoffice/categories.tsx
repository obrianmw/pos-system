// Category tree (departments > subcategories) used by Products and Stock, with head-office management.
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, FolderPlus, ImagePlus, LayoutGrid, Pencil, Trash2, X } from "lucide-react";
import { api, apiForm } from "../api";
import { Thumb } from "../CategoryBrowser";
import { errorText, toast } from "./ui";
import { confirmDialog } from "../Dialog";

export type TreeRow = { id: number; name: string; parent: number | null; path: string; image_url: string | null;
  sort_order: number; products: number; total_products: number };

export function useCategoryTree() {
  const [rows, setRows] = useState<TreeRow[] | null>(null);
  const load = () => api<TreeRow[]>("/categories/tree/", { branch: null }).then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  return { rows, reload: load };
}

const order = (a: TreeRow, b: TreeRow) => a.sort_order - b.sort_order || a.name.localeCompare(b.name);

/** Categories as "Food › Meat & Poultry" options, parents first, for selects. */
export function sortedPaths(rows: TreeRow[] | null) {
  return [...(rows ?? [])].sort((a, b) => a.path.localeCompare(b.path));
}

export function CategoryTree({ rows, selected, onSelect, canManage, onChanged, allLabel = "All products" }: {
  rows: TreeRow[] | null; selected: number | null; onSelect: (id: number | null) => void;
  canManage?: boolean; onChanged?: () => void; allLabel?: string;
}) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<{ mode: "new" | "edit"; row?: TreeRow; parent: number | null } | null>(null);
  const kids = useMemo(() => {
    const m = new Map<number | null, TreeRow[]>();
    for (const r of rows ?? []) m.set(r.parent, [...(m.get(r.parent) ?? []), r]);
    for (const v of m.values()) v.sort(order);
    return m;
  }, [rows]);
  const total = (rows ?? []).filter((r) => r.parent === null).reduce((s, r) => s + r.total_products, 0);
  // Keep the branch of the selected category expanded.
  useEffect(() => {
    if (selected === null || !rows) return;
    const s = new Set(open);
    let cur = rows.find((r) => r.id === selected);
    while (cur?.parent) { s.add(cur.parent); cur = rows.find((r) => r.id === cur!.parent); }
    setOpen(s);
  }, [selected, rows]);

  function toggle(id: number) {
    const s = new Set(open);
    s.has(id) ? s.delete(id) : s.add(id);
    setOpen(s);
  }

  const node = (r: TreeRow) => {
    const children = kids.get(r.id) ?? [];
    const expanded = open.has(r.id);
    return (
      <li key={r.id}>
        <div className="cat-row">
          {children.length
            ? <button className="toggle" aria-expanded={expanded} aria-label={`${expanded ? "Collapse" : "Expand"} ${r.name}`} onClick={() => toggle(r.id)}>
                {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>
            : <span className="toggle" />}
          <button className={`name ${selected === r.id ? "on" : ""}`} aria-current={selected === r.id ? "true" : undefined}
                  onClick={() => { onSelect(r.id); if (children.length && !expanded) toggle(r.id); }}>
            <Thumb src={r.image_url} name={r.name} size={24} /><span className="label">{r.name}</span>
            <span className="count">{r.total_products}</span>
          </button>
        </div>
        {children.length > 0 && expanded && <ul>{children.map(node)}</ul>}
      </li>
    );
  };

  const sel = rows?.find((r) => r.id === selected);
  return (
    <aside className="cat-tree" aria-label="Categories">
      <div className="cat-row">
        <span className="toggle" />
        <button className={`name ${selected === null ? "on" : ""}`} onClick={() => onSelect(null)}>
          <span className="thumb thumb-fallback" style={{ width: 24, height: 24 }}><LayoutGrid size={14} /></span>
          <span className="label">{allLabel}</span><span className="count">{total}</span>
        </button>
      </div>
      {rows === null ? <div className="skeleton" style={{ height: 160, margin: 6 }} /> : <ul>{(kids.get(null) ?? []).map(node)}</ul>}
      {canManage && (
        <div className="tree-actions">
          <button className="ghost" onClick={() => setEditing({ mode: "new", parent: selected })}>
            <FolderPlus size={15} />{sel ? `Add under ${sel.name}` : "New department"}</button>
          {sel && <button className="ghost" onClick={() => setEditing({ mode: "edit", row: sel, parent: sel.parent })}><Pencil size={15} />Edit</button>}
        </div>
      )}
      {editing && <CategoryEditor rows={rows ?? []} {...editing} onClose={() => setEditing(null)}
        onSaved={(id) => { setEditing(null); onChanged?.(); if (id !== undefined) onSelect(id); }} />}
    </aside>
  );
}

function CategoryEditor({ rows, mode, row, parent, onClose, onSaved }: {
  rows: TreeRow[]; mode: "new" | "edit"; row?: TreeRow; parent: number | null;
  onClose: () => void; onSaved: (selectId?: number | null) => void;
}) {
  const [name, setName] = useState(row?.name ?? "");
  const [parentId, setParentId] = useState<string>(parent === null || parent === undefined ? "" : String(parent));
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(row?.image_url ?? null);
  const [clear, setClear] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const blocked = new Set<number>();
  if (row) { // a category cannot move under itself or its own subcategories
    blocked.add(row.id);
    let grew = true;
    while (grew) { grew = false; for (const r of rows) if (r.parent !== null && blocked.has(r.parent) && !blocked.has(r.id)) { blocked.add(r.id); grew = true; } }
  }
  useEffect(() => () => { if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview); }, [preview]);

  function pick(f: File | undefined) {
    if (!f) return;
    setFile(f); setClear(false); setPreview(URL.createObjectURL(f));
  }

  async function save() {
    setBusy(true);
    try {
      const form = new FormData();
      form.set("name", name.trim());
      form.set("parent", parentId);
      if (file) form.set("image", file);
      if (clear) form.set("clear_image", "true");
      const saved = mode === "new" ? await apiForm("/categories/", form, "POST") : await apiForm(`/categories/${row!.id}/`, form, "PATCH");
      toast(mode === "new" ? `Added “${saved.path}”.` : "Category saved.", "success");
      onSaved(saved.id);
    } catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
  }
  async function remove() {
    if (!row || !(await confirmDialog({ title: `Delete "${row.name}"?`, danger: true,
      message: "This only works when the category has no products and no subcategories." }))) return;
    try { await api(`/categories/${row.id}/`, { method: "DELETE", branch: null }); toast("Category deleted.", "success"); onSaved(null); }
    catch (e) { toast(errorText(e), "error"); }
  }

  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card" role="dialog" aria-label={mode === "new" ? "New category" : `Edit ${row?.name}`}>
        <div className="card-head"><h3>{mode === "new" ? "New category" : `Edit ${row?.name}`}</h3>
          <button className="ghost icon" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Meat & Poultry" /></label>
        <label>Sits under
          <select value={parentId} onChange={(e) => setParentId(e.target.value)}>
            <option value="">Nothing — it is a department</option>
            {sortedPaths(rows).filter((r) => !blocked.has(r.id)).map((r) => <option key={r.id} value={r.id}>{r.path}</option>)}
          </select></label>
        <label>Picture</label>
        <div className="photo-picker">
          <span className="preview"><Thumb src={clear ? null : preview} name={name || "?"} /></span>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <button type="button" onClick={() => input.current?.click()}><ImagePlus size={16} />Choose picture</button>
            {(preview && !clear) && <button type="button" className="ghost" onClick={() => { setClear(true); setFile(null); }}><X size={15} />Remove picture</button>}
            <span className="drop-hint">JPEG, PNG or WebP, up to 5 MB.</span>
          </div>
          <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => pick(e.target.files?.[0])} />
        </div>
        <div className="actions">
          <button className="primary" disabled={busy || !name.trim()} onClick={save}>{mode === "new" ? "Add category" : "Save"}</button>
          {mode === "edit" && <button className="ghost" onClick={remove}><Trash2 size={15} />Delete</button>}
          <button className="link" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
