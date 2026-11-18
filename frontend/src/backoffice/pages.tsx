import { errorText, toast } from "./ui";
import { useEffect, useState } from "react";
import { api, money } from "../api";
import type { Ctx } from "./BackOffice";
import { Thumb } from "../CategoryBrowser";
import { CategoryTree, useCategoryTree } from "./categories";

// ---- shared bits ------------------------------------------------------------------------------
const hashQuery = () => new URLSearchParams(location.hash.split("?")[1] || "");
const when = (iso?: string) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "");

function useList<T = any>(url: string | null, ctx: Ctx, deps: unknown[] = []) {
  const [rows, setRows] = useState<T[] | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!url) return;
    setError("");
    api(url, { branch: ctx.branch }).then((d) => {
      const list = Array.isArray(d) ? d : d.results;
      setRows(list); setCount(Array.isArray(d) ? d.length : d.count);
    }).catch((e) => setError(e.message));
  }, [url, ctx.branch, tick, ...deps]);
  return { rows, count, error, reload: () => setTick((t) => t + 1) };
}

function Status({ rows, error, empty }: { rows: unknown[] | null; error: string; empty: string }) {
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;
  if (!rows.length) return <p className="muted">{empty}</p>;
  return null;
}

function branchName(ctx: Ctx, id: number) {
  return ctx.me.branches.find((b) => b.id === id)?.name || `#${id}`;
}

async function act(path: string, body?: unknown, branch?: string | null) {
  try { return await api(path, { method: "POST", body, branch }); }
  catch (e: any) { toast(errorText(e), "error"); return null; }
}

// ---- Sales -------------------------------------------------------------------------------------
export function Sales({ ctx }: { ctx: Ctx }) {
  const [review, setReview] = useState(hashQuery().get("review") === "1");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<any>(null);
  const url = `/sales/?ordering=-created_at${review ? "&needs_review=true" : ""}${search ? `&search=${encodeURIComponent(search)}` : ""}`;
  const { rows, count, error, reload } = useList(url, ctx);
  return (
    <div>
      <div className="toolbar">
        <input placeholder="Receipt no. or customer" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label><input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} /> Needs review only</label>
        <span className="muted">{count} sales</span>
      </div>
      <Status rows={rows} error={error} empty={review ? "No sales waiting for review." : "No sales yet."} />
      {!!rows?.length && (
        <table className="grid-table clickable">
          <thead><tr><th>Receipt</th><th>Time</th>{!ctx.branch && <th>Branch</th>}<th>Cashier</th><th>Type</th><th>Status</th><th className="num">Total</th></tr></thead>
          <tbody>{rows.map((s) => (
            <tr key={s.id} onClick={() => setOpen(s)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setOpen(s)}>
              <td>{s.number} {s.created_offline && <span className="tag">offline</span>} {s.needs_review && <span className="tag warn">⚠ review</span>}</td>
              <td>{when(s.completed_at || s.created_at)}</td>
              {!ctx.branch && <td>{branchName(ctx, s.branch)}</td>}
              <td>{s.cashier_name}</td><td>{s.kind}</td><td>{s.status.replace("_", " ")}</td>
              <td className="num">{s.kind === "refund" ? "−" : ""}{money(s.total)}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {open && <SaleDetail sale={open} onClose={() => setOpen(null)} onChanged={() => { setOpen(null); reload(); }} />}
    </div>
  );
}

function SaleDetail({ sale, onClose, onChanged }: { sale: any; onClose: () => void; onChanged: () => void }) {
  const [note, setNote] = useState("");
  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}><div className="card wide">
      <h3>{sale.kind === "refund" ? "Refund" : "Sale"} {sale.number}</h3>
      <p className="muted">{when(sale.created_at)} · {sale.cashier_name} · {sale.status.replace("_", " ")}
        {sale.created_offline && " · made offline"}</p>
      <table className="grid-table">
        <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">List</th><th className="num">Charged</th><th className="num">Disc.</th><th className="num">Total</th></tr></thead>
        <tbody>{sale.lines.map((l: any) => (
          <tr key={l.id}><td>{l.description}{l.override && <span className="tag">override</span>}</td>
            <td className="num">{Number(l.quantity)}</td><td className="num">{money(l.list_price)}</td>
            <td className="num">{money(l.unit_price)}</td><td className="num">{money(l.discount_amount)}</td>
            <td className="num">{money(l.line_total)}</td></tr>
        ))}</tbody>
      </table>
      <p>Total <b>{money(sale.total)}</b> · VAT {money(sale.tax_total)} · discounts {money(sale.discount_total)}</p>
      {sale.payments.map((p: any) => <p key={p.id}>{p.method_name}: {money(p.amount)} — {p.status}{p.provider_reference && ` · ref ${p.provider_reference}`}</p>)}
      {sale.review_reason && <pre className="note">{sale.review_reason}</pre>}
      {sale.needs_review && (
        <div className="payrow">
          <input placeholder="What did you check?" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="primary" disabled={!note} onClick={async () => (await act(`/sales/${sale.id}/mark_reviewed/`, { note }, null)) && onChanged()}>Mark reviewed</button>
        </div>
      )}
      <button className="link" onClick={onClose}>Close</button>
    </div></div>
  );
}

// ---- Approvals ---------------------------------------------------------------------------------
export function Approvals({ ctx }: { ctx: Ctx }) {
  const [status, setStatus] = useState("pending");
  const { rows, error, reload } = useList(`/overrides/?status=${status}&ordering=-created_at`, ctx, []);
  useEffect(() => { if (status !== "pending") return; const id = setInterval(reload, 5000); return () => clearInterval(id); }, [status]);
  return (
    <div>
      <div className="toolbar">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {["pending", "used", "approved", "rejected"].map((s) => <option key={s}>{s}</option>)}
        </select>
        {status === "pending" && <span className="muted">Refreshes every 5 seconds</span>}
      </div>
      <Status rows={rows} error={error} empty="Nothing here." />
      {!!rows?.length && (
        <table className="grid-table">
          <thead><tr><th>When</th>{!ctx.branch && <th>Branch</th>}<th>Type</th><th>Item</th><th className="num">From</th><th className="num">To</th><th>Asked by</th><th>Reason</th><th>How</th><th /></tr></thead>
          <tbody>{rows.map((a) => (
            <tr key={a.id}>
              <td>{when(a.created_at)}</td>{!ctx.branch && <td>{branchName(ctx, a.branch)}</td>}
              <td>{a.kind}</td><td>{a.product_name}</td>
              <td className="num">{a.original_value && money(a.original_value)}</td><td className="num">{a.new_value && money(a.new_value)}</td>
              <td>{a.requested_by_name}</td><td>{a.reason}</td><td>{a.method}</td>
              <td>{a.status === "pending" && <>
                <button onClick={async () => (await act(`/overrides/${a.id}/approve/`, undefined, null)) && reload()}>Approve</button>
                <button className="link" onClick={async () => (await act(`/overrides/${a.id}/reject/`, undefined, null)) && reload()}>Reject</button>
              </>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

// ---- Stock -------------------------------------------------------------------------------------
export function Stock({ ctx }: { ctx: Ctx }) {
  const [low, setLow] = useState(hashQuery().get("low") === "1");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<number | null>(null);
  const tree = useCategoryTree();
  const cat = category !== null ? `category_tree=${category}` : "";
  const url = low ? `/stock-levels/low/${cat ? `?${cat}` : ""}`
    : `/stock-levels/?ordering=product__name&page_size=200${search ? `&search=${encodeURIComponent(search)}` : ""}${cat ? `&${cat}` : ""}`;
  const { rows, error, reload } = useList(url, ctx);
  const shown = low && search ? rows?.filter((r: any) => r.product_name.toLowerCase().includes(search.toLowerCase())) ?? null : rows;
  async function adjust(r: any) {
    const counted = prompt(`Counted quantity of ${r.product_name} at ${branchName(ctx, r.branch)}:`, String(Number(r.quantity)));
    if (counted == null) return;
    const reason = prompt("Reason (stock take, breakage, expiry…):");
    if (!reason) return;
    if (await act("/inventory/adjust/", { product: r.product, counted_quantity: counted, reason }, String(r.branch))) reload();
  }
  const canAdjust = (branch: number) => ctx.me.org_permissions.includes("inventory.adjust") ||
    !!ctx.me.branches.find((b) => b.id === branch)?.permissions.includes("inventory.adjust");
  const place = tree.rows?.find((r) => r.id === category);
  return (
    <div className="catalog-layout">
      <CategoryTree rows={tree.rows} selected={category} onSelect={setCategory} allLabel="All stock" />
      <div style={{ minWidth: 0 }}>
      <div className="toolbar">
        <input type="search" placeholder="Search product" aria-label="Search stock" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> At or below reorder level</label>
        {place && <span className="muted">{place.path}</span>}
      </div>
      <Status rows={shown} error={error} empty={low ? "Nothing is low. 👍" : place ? `No stock records in ${place.path}.` : "No stock records."} />
      {!!shown?.length && (
        <table className="grid-table">
          <thead><tr><th>Product</th><th>Category</th>{!ctx.branch && <th>Branch</th>}<th className="num">On hand</th><th className="num">Reorder at</th><th className="num">Avg cost</th><th className="num">Value</th><th /></tr></thead>
          <tbody>{shown.map((r: any) => {
            const isLow = Number(r.quantity) <= Number(r.reorder_level);
            return (
              <tr key={r.id}>
                <td><span className="name-cell"><span className="row-thumb"><Thumb src={r.image_url} name={r.product_name} /></span>
                  <span><b>{r.product_name}</b><br /><small className="muted">{r.sku}</small></span></span></td>
                <td className="muted">{r.category_path}</td>{!ctx.branch && <td>{branchName(ctx, r.branch)}</td>}
                <td className="num">{Number(r.quantity)} {isLow && <span className="tag warn">⚠ low</span>}</td>
                <td className="num">{Number(r.reorder_level)}</td><td className="num">{money(r.avg_cost)}</td>
                <td className="num">{money(Number(r.quantity) * Number(r.avg_cost))}</td>
                <td>{canAdjust(r.branch) && <button className="link" onClick={() => adjust(r)}>Adjust</button>}</td>
              </tr>
            );
          })}</tbody>
        </table>
      )}
      </div>
    </div>
  );
}

// ---- Accounting --------------------------------------------------------------------------------
export function Expenses({ ctx }: { ctx: Ctx }) {
  const [status, setStatus] = useState("pending");
  const { rows, error, reload } = useList(`/accounting/expenses/?ordering=-date${status ? `&status=${status}` : ""}`, ctx);
  const [adding, setAdding] = useState(false);
  const canApprove = (branch: number) => ctx.me.org_permissions.includes("accounting.reconcile") ||
    !!ctx.me.branches.find((b) => b.id === branch)?.permissions.includes("accounting.reconcile");
  return (
    <div>
      <div className="toolbar">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="">All</option>
        </select>
        {ctx.can("accounting.post") && <button className="primary" onClick={() => setAdding(true)}>+ New expense</button>}
      </div>
      <Status rows={rows} error={error} empty="No expenses." />
      {!!rows?.length && (
        <table className="grid-table">
          <thead><tr><th>Date</th>{!ctx.branch && <th>Branch</th>}<th>Description</th><th>Receipt</th><th className="num">Amount</th><th>Status</th><th /></tr></thead>
          <tbody>{rows.map((x: any) => (
            <tr key={x.id}>
              <td>{x.date}</td>{!ctx.branch && <td>{branchName(ctx, x.branch)}</td>}<td>{x.description}</td><td>{x.receipt_number}</td>
              <td className="num">{money(x.amount)}</td><td>{x.status}</td>
              <td>{x.status === "pending" && canApprove(x.branch) && <>
                <button onClick={async () => (await act(`/accounting/expenses/${x.id}/approve/`, undefined, null)) && reload()}>Approve</button>
                <button className="link" onClick={async () => (await act(`/accounting/expenses/${x.id}/reject/`, undefined, null)) && reload()}>Reject</button>
              </>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {adding && <NewExpense ctx={ctx} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload(); }} />}
    </div>
  );
}

function NewExpense({ ctx, onClose, onSaved }: { ctx: Ctx; onClose: () => void; onSaved: () => void }) {
  const [accounts, setAccounts] = useState<any[]>([]);
  const branches = ctx.me.branches.filter((b) => b.permissions.includes("accounting.post") || ctx.me.org_permissions.includes("accounting.post"));
  const [f, setF] = useState({ branch: ctx.branch || String(branches[0]?.id || ""), expense_account: "", paid_from: "",
    amount: "", date: new Date().toISOString().slice(0, 10), description: "", receipt_number: "" });
  useEffect(() => { api("/accounting/accounts/?page_size=200", { branch: null }).then((d) => setAccounts(d.results)).catch(() => {}); }, []);
  const set = (k: keyof typeof f) => (e: any) => setF({ ...f, [k]: e.target.value });
  async function save() {
    if (await act("/accounting/expenses/", { ...f, branch: Number(f.branch) }, f.branch)) onSaved();
  }
  return (
    <div className="modal"><div className="card">
      <h3>New expense</h3>
      <label>Branch <select value={f.branch} onChange={set("branch")}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
      <label>Expense type <select value={f.expense_account} onChange={set("expense_account")}>
        <option value="">Choose…</option>{accounts.filter((a) => a.type === "expense").map((a) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}
      </select></label>
      <label>Paid from <select value={f.paid_from} onChange={set("paid_from")}>
        <option value="">Choose…</option>{accounts.filter((a) => a.type === "asset" && /cash|bank|wallet|mobile/i.test(a.name)).map((a) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}
      </select></label>
      <label>Amount <input inputMode="decimal" value={f.amount} onChange={set("amount")} /></label>
      <label>Date <input type="date" value={f.date} onChange={set("date")} /></label>
      <label>Description <input value={f.description} onChange={set("description")} /></label>
      <label>Receipt no. <input value={f.receipt_number} onChange={set("receipt_number")} /></label>
      <p className="muted"><small>Someone other than you approves it; only then is it posted to the books.</small></p>
      <button className="primary" disabled={!f.expense_account || !f.paid_from || !f.amount || !f.description} onClick={save}>Submit for approval</button>
      <button className="link" onClick={onClose}>Cancel</button>
    </div></div>
  );
}

export function TrialBalance({ ctx }: { ctx: Ctx }) {
  const [dateTo, setDateTo] = useState("");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setError(""); setData(null);
    const q = new URLSearchParams();
    if (ctx.branch) q.set("branch", ctx.branch);
    if (dateTo) q.set("date_to", dateTo);
    api(`/reports/trial-balance/?${q}`, { branch: null }).then(setData).catch((e) => setError(
      e.status === 403 && !ctx.branch ? "Whole-organization figures need an organization role. Pick a branch above." : e.message));
  }, [ctx.branch, dateTo]);
  const balanced = data && Number(data.total_debit).toFixed(2) === Number(data.total_credit).toFixed(2);
  return (
    <div>
      <div className="toolbar"><label>As at <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></label>
        {data && <span className={balanced ? "ok" : "error"}>{balanced ? "✓ Balanced" : "✕ Out of balance"}</span>}</div>
      {error && <p className="error">{error}</p>}
      {data && (
        <table className="grid-table">
          <thead><tr><th>Code</th><th>Account</th><th>Type</th><th className="num">Debit</th><th className="num">Credit</th></tr></thead>
          <tbody>{data.rows.map((r: any) => (
            <tr key={r.code}><td>{r.code}</td><td>{r.name}</td><td>{r.type}</td>
              <td className="num">{Number(r.debit) ? money(r.debit) : ""}</td><td className="num">{Number(r.credit) ? money(r.credit) : ""}</td></tr>
          ))}</tbody>
          <tfoot><tr><th colSpan={3}>Total</th><th className="num">{money(data.total_debit)}</th><th className="num">{money(data.total_credit)}</th></tr></tfoot>
        </table>
      )}
    </div>
  );
}

// ---- HR ----------------------------------------------------------------------------------------
export function Leave({ ctx }: { ctx: Ctx }) {
  const [status, setStatus] = useState("pending");
  const { rows, error, reload } = useList(`/hr/leave/?ordering=-created_at${status ? `&status=${status}` : ""}`, { ...ctx, branch: null });
  return (
    <div>
      <div className="toolbar"><select value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="">All</option>
      </select></div>
      <Status rows={rows} error={error} empty="No leave requests." />
      {!!rows?.length && (
        <table className="grid-table">
          <thead><tr><th>Employee</th><th>Type</th><th>From</th><th>To</th><th className="num">Days</th><th>Reason</th><th>Status</th><th /></tr></thead>
          <tbody>{rows.map((l: any) => (
            <tr key={l.id}><td>{l.employee_name}</td><td>{l.leave_type}</td><td>{l.start_date}</td><td>{l.end_date}</td>
              <td className="num">{l.days}</td><td>{l.reason}</td><td>{l.status}</td>
              <td>{l.status === "pending" && ctx.can("hr.approve_leave") && <>
                <button onClick={async () => (await act(`/hr/leave/${l.id}/approve/`, undefined, null)) && reload()}>Approve</button>
                <button className="link" onClick={async () => (await act(`/hr/leave/${l.id}/reject/`, undefined, null)) && reload()}>Reject</button>
              </>}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

// ---- Admin -------------------------------------------------------------------------------------
export function Users({ ctx }: { ctx: Ctx }) {
  const [search, setSearch] = useState("");
  const { rows, error, reload } = useList(`/users/?ordering=username${search ? `&search=${encodeURIComponent(search)}` : ""}`, { ...ctx, branch: null });
  const [roles, setRoles] = useState<any[]>([]);
  const [assign, setAssign] = useState<any>(null);
  useEffect(() => { api("/roles/", { branch: null }).then((d) => setRoles(d.results || d)).catch(() => {}); }, []);
  const roleName = (id: number) => roles.find((r) => r.id === id)?.name || `role ${id}`;
  const shown = rows?.filter((u: any) => !ctx.branch || u.memberships.some((m: any) => !m.branch || String(m.branch) === ctx.branch)) ?? null;
  return (
    <div>
      <div className="toolbar"><input placeholder="Search users" value={search} onChange={(e) => setSearch(e.target.value)} />
        <a href="/admin/accounts/user/add/" target="_blank" rel="noreferrer">+ Add user in admin</a></div>
      <Status rows={shown} error={error} empty="No users." />
      {!!shown?.length && (
        <table className="grid-table">
          <thead><tr><th>Username</th><th>Name</th><th>Roles</th><th>Active</th><th /></tr></thead>
          <tbody>{shown.map((u: any) => (
            <tr key={u.id}><td>{u.username}</td><td>{u.first_name} {u.last_name}</td>
              <td>{u.memberships.filter((m: any) => m.is_active).map((m: any) => (
                <span key={m.id} className="tag">{m.role_name || roleName(m.role)} @ {m.branch ? branchName(ctx, m.branch) : "all branches"}
                  <button className="link" title="Remove role" onClick={async () => confirm(`Remove ${m.role_name} from ${u.username}?`) &&
                    (await act(`/users/${u.id}/revoke_role/`, { membership_id: m.id }, null)) !== null && reload()}>✕</button></span>
              ))}</td>
              <td>{u.is_active ? "Yes" : "No"}</td>
              <td><button className="link" onClick={() => setAssign(u)}>Add role</button></td></tr>
          ))}</tbody>
        </table>
      )}
      {assign && <AssignRole ctx={ctx} user={assign} roles={roles} onClose={() => setAssign(null)} onSaved={() => { setAssign(null); reload(); }} />}
    </div>
  );
}

function AssignRole({ ctx, user, roles, onClose, onSaved }: { ctx: Ctx; user: any; roles: any[]; onClose: () => void; onSaved: () => void }) {
  const [role, setRole] = useState("");
  const [branch, setBranch] = useState(ctx.branch || "");
  const r = roles.find((x) => String(x.id) === role);
  const adminBranches = ctx.me.branches.filter((b) => ctx.canOrg("org.admin") || b.permissions.includes("branch.admin"));
  return (
    <div className="modal"><div className="card">
      <h3>Add role for {user.username}</h3>
      <label>Role <select value={role} onChange={(e) => setRole(e.target.value)}>
        <option value="">Choose…</option>
        {roles.filter((x) => x.is_active && (x.scope === "branch" || ctx.canOrg("org.admin"))).map((x) =>
          <option key={x.id} value={x.id}>{x.name} ({x.scope === "org" ? "all branches" : "one branch"})</option>)}
      </select></label>
      {r?.scope === "branch" && <label>Branch <select value={branch} onChange={(e) => setBranch(e.target.value)}>
        <option value="">Choose…</option>{adminBranches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
      </select></label>}
      {r && <p className="muted"><small>Can: {r.permissions.join(", ")}</small></p>}
      <button className="primary" disabled={!r || (r.scope === "branch" && !branch)} onClick={async () =>
        (await act(`/users/${user.id}/assign_role/`, { role: Number(role), branch: r.scope === "branch" ? Number(branch) : null }, null)) && onSaved()}>Assign</button>
      <button className="link" onClick={onClose}>Cancel</button>
    </div></div>
  );
}

export function AuditLog({ ctx }: { ctx: Ctx }) {
  const [action, setAction] = useState("");
  const { rows, error } = useList(`/audit-logs/?ordering=-created_at${action ? `&action=${encodeURIComponent(action)}` : ""}`, ctx);
  return (
    <div>
      <div className="toolbar"><select value={action} onChange={(e) => setAction(e.target.value)}>
        <option value="">All actions</option>
        {["sale.created", "sale.voided", "sale.refund", "sale.reviewed", "override.pin_failed", "override.approved", "till.open", "till.close",
          "inventory.adjust", "user.role_assigned", "user.role_revoked", "journal.manual", "cash.movement"].map((a) => <option key={a}>{a}</option>)}
      </select></div>
      <Status rows={rows} error={error} empty="No entries." />
      {!!rows?.length && (
        <table className="grid-table">
          <thead><tr><th>When</th><th>Who</th>{!ctx.branch && <th>Branch</th>}<th>Action</th><th>Details</th></tr></thead>
          <tbody>{rows.map((a: any) => (
            <tr key={a.id}><td>{when(a.created_at)}</td><td>{a.actor_name}</td>{!ctx.branch && <td>{a.branch ? branchName(ctx, a.branch) : ""}</td>}
              <td>{a.action.includes("failed") ? <span className="tag warn">⚠ {a.action}</span> : a.action}</td>
              <td className="details">{Object.entries(a.data || {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
