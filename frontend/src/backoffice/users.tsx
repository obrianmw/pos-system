// Users & roles: create people, edit their details, switch accounts on/off, reset passwords and
// supervisor PINs, and manage which roles they hold at which branches. The server decides what each
// admin may change (branch admins: only staff who work solely at their branches).
import { useEffect, useMemo, useState } from "react";
import { ArrowRightLeft, KeyRound, Lock, Plus, ShieldCheck, Trash2, UserPlus, X } from "lucide-react";
import { api } from "../api";
import type { Ctx } from "./BackOffice";
import { DateFilters, dateFilters, SortHeader, useListState } from "./listing";
import { Err, Errors, initials, toErrors, toast, errorText } from "./ui";
import { confirmDialog, formDialog } from "../Dialog";

type Membership = { id: number; role: number; role_name: string; branch: number | null; is_active: boolean };
type User = {
  id: number; username: string; first_name: string; last_name: string; email: string; phone: string;
  is_active: boolean; last_login: string | null; has_supervisor_pin: boolean; can_edit: boolean; memberships: Membership[];
};
type Role = { id: number; name: string; scope: "org" | "branch"; permissions: string[]; is_active: boolean };

const fullName = (u: User) => `${u.first_name} ${u.last_name}`.trim() || u.username;
const ago = (iso: string | null) => {
  if (!iso) return "Never";
  const d = (Date.now() - new Date(iso).getTime()) / 86400000;
  return d < 1 ? "Today" : d < 2 ? "Yesterday" : d < 30 ? `${Math.floor(d)} days ago` : new Date(iso).toLocaleDateString();
};
const passwordFields = [
  { name: "p1", label: "New password", type: "password" as const, required: true,
    hint: "At least 8 characters; not too common or too like the username." },
  { name: "p2", label: "Repeat it", type: "password" as const, required: true,
    validate: (v: string, all: Record<string, string>) => (v === all.p1 ? null : "The two passwords differ.") },
];

export function Users({ ctx }: { ctx: Ctx }) {
  const [rows, setRows] = useState<User[] | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [status, setStatus] = useState("true");
  const [tick, setTick] = useState(0);
  const [open, setOpen] = useState<User | null>(null);
  const [creating, setCreating] = useState(false);
  const branchName = (id: number | null) => (id === null ? "All branches" : ctx.me.branches.find((b) => b.id === id)?.name || `Branch #${id}`);

  useEffect(() => { api("/roles/", { branch: null }).then((d) => setRoles((d.results || d).filter((r: Role) => r.is_active))).catch(() => {}); }, []);
  useEffect(() => {
    const q = new URLSearchParams({ page_size: "200" });
    if (search) q.set("search", search);
    if (roleFilter) q.set("role", roleFilter);
    if (status) q.set("is_active", status);
    if (ctx.branch) q.set("branch", ctx.branch);
    api(`/users/?${q}`, { branch: null }).then((d) => setRows(d.results)).catch((e) => { setRows([]); toast(errorText(e), "error"); });
  }, [search, roleFilter, status, ctx.branch, tick]);

  const sorter = useListState({ sort: "name" });
  const DAY = 864e5;
  const since = (u: User) => (u.last_login ? Date.now() - new Date(u.last_login).getTime() : Infinity);
  const shown = rows && sorter.apply(rows, {
    filters: { seen: (u: User, v) => (v === "never" ? !u.last_login : v === "week" ? since(u) < 7 * DAY : !!u.last_login && since(u) > 30 * DAY) },
    sorts: { name: (u: User) => fullName(u), roles: (u: User) => u.memberships.map((m) => m.role_name).join(", "), phone: (u: User) => u.phone || "",
             seen: (u: User) => u.last_login || "", status: (u: User) => (u.is_active ? 0 : 1) } });
  const refresh = (u?: User) => { setTick((t) => t + 1); if (u) setOpen(u); };
  return (
    <div>
      <div className="toolbar">
        <input placeholder="Search name, username, phone, email" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Role" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
          <option value="">All roles</option>
          {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="true">Active</option><option value="false">Deactivated</option><option value="">All</option>
        </select>
        <select aria-label="Last sign-in" value={sorter.state.filters.seen || ""} onChange={(e) => sorter.setFilter("seen", e.target.value)}>
          <option value="">Any sign-in</option><option value="week">Signed in this week</option><option value="month">Not for 30+ days</option><option value="never">Never signed in</option>
        </select>
        <span className="muted">{shown?.length ?? 0} people</span>
        <span className="spacer" />
        <button className="primary" onClick={() => setCreating(true)}><UserPlus size={16} />New user</button>
      </div>
      {rows === null && <div className="skeleton" style={{ height: 200 }} />}
      {rows?.length === 0 && <p className="muted">No one matches.</p>}
      {!!rows?.length && (
        <table className="grid-table clickable">
          <thead><tr><SortHeader list={sorter} k="name">Person</SortHeader><SortHeader list={sorter} k="roles">Roles</SortHeader>
            <SortHeader list={sorter} k="phone">Phone</SortHeader><SortHeader list={sorter} k="seen">Last sign-in</SortHeader>
            <SortHeader list={sorter} k="status">Status</SortHeader></tr></thead>
          <tbody>{(shown || []).map((u) => (
            <tr key={u.id} tabIndex={0} onClick={() => setOpen(u)} onKeyDown={(e) => e.key === "Enter" && setOpen(u)}>
              <td><span className="inline" style={{ gap: 10 }}><span className="avatar">{initials(fullName(u))}</span>
                <span><b>{fullName(u)}</b><div className="muted" style={{ fontSize: ".8rem" }}>{u.username}</div></span></span></td>
              <td>{u.memberships.length ? u.memberships.map((m) => (
                <span key={m.id} className="tag">{m.role_name} · {branchName(m.branch)}</span>)) : <span className="muted">No role</span>}</td>
              <td>{u.phone}</td><td>{ago(u.last_login)}</td>
              <td>{u.is_active ? "Active" : <span className="tag warn">Deactivated</span>}
                {!u.can_edit && <Lock size={13} className="muted" style={{ marginLeft: 6, verticalAlign: -2 }} aria-label="Read-only for you" />}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {open && <UserEditor ctx={ctx} user={open} roles={roles} branchName={branchName}
        onClose={() => setOpen(null)} onChanged={refresh} />}
      {creating && <NewUser ctx={ctx} roles={roles} onClose={() => setCreating(false)}
        onSaved={(u) => { setCreating(false); refresh(u); }} />}
    </div>
  );
}

/** Branches this admin can give roles at, and which roles they may hand out. */
function useGrantable(ctx: Ctx, roles: Role[]) {
  const orgAdmin = ctx.canOrg("org.admin");
  const branches = ctx.me.branches.filter((b) => orgAdmin || b.permissions.includes("branch.admin"));
  const grantable = roles.filter((r) => orgAdmin || (r.scope === "branch" && !r.permissions.includes("*") && !r.permissions.includes("org.admin")));
  return { orgAdmin, branches, grantable };
}

function UserEditor({ ctx, user, roles, branchName, onClose, onChanged }: {
  ctx: Ctx; user: User; roles: Role[]; branchName: (id: number | null) => string;
  onClose: () => void; onChanged: (u?: User) => void;
}) {
  const [u, setU] = useState(user);
  const [f, setF] = useState({ first_name: user.first_name, last_name: user.last_name, username: user.username,
                               email: user.email, phone: user.phone });
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const { branches, grantable } = useGrantable(ctx, roles);
  const [newRole, setNewRole] = useState("");
  const [newBranch, setNewBranch] = useState(String(branches[0]?.id ?? ""));
  const self = user.id === ctx.me.id;
  const ro = !u.can_edit;
  const dirty = (Object.keys(f) as (keyof typeof f)[]).some((k) => f[k] !== (u as any)[k]);
  const roleObj = grantable.find((r) => String(r.id) === newRole);

  async function patch(body: Record<string, unknown>, ok: string) {
    setBusy(true); setErrors({});
    try { const r = await api<User>(`/users/${u.id}/`, { method: "PATCH", body, branch: null }); setU(r); onChanged(r); toast(ok, "success"); return true; }
    catch (e) { setErrors(toErrors(e)); toast(errorText(e), "error"); return false; }
    finally { setBusy(false); }
  }
  const reload = async () => { const r = await api<User>(`/users/${u.id}/`, { branch: null }); setU(r); onChanged(r); };

  async function toggleActive() {
    const on = !u.is_active;
    if (!(await confirmDialog({
      title: on ? `Reactivate ${fullName(u)}?` : `Deactivate ${fullName(u)}?`, danger: !on, confirmLabel: on ? "Reactivate" : "Deactivate",
      message: on ? "They will be able to sign in again with their password." :
        "They are signed out everywhere at once and can't sign in. Their sales and history are kept." }))) return;
    await patch({ is_active: on }, on ? "Account reactivated." : "Account deactivated.");
  }
  async function resetPassword() {
    const v = await formDialog({ title: `New password for ${fullName(u)}`, icon: <KeyRound size={26} />, confirmLabel: "Set password",
      message: "Give it to them privately. They can sign in with it straight away.", fields: passwordFields });
    if (v) await patch({ password: v.p1 }, "Password changed.");
  }
  async function setPin() {
    const v = await formDialog({ title: u.has_supervisor_pin ? "Change supervisor PIN" : "Set a supervisor PIN", icon: <ShieldCheck size={26} />,
      message: "Supervisors type this at a till to approve price changes, voids and refunds.", confirmLabel: "Save PIN",
      fields: [{ name: "pin", label: "PIN (4–8 digits)", type: "password", required: true,
                 validate: (x) => (/^\d{4,8}$/.test(x) ? null : "Use 4 to 8 digits.") }] });
    if (v) await patch({ supervisor_pin: v.pin }, "Supervisor PIN saved.");
  }
  async function clearPin() {
    if (await confirmDialog({ title: "Remove the supervisor PIN?", danger: true, confirmLabel: "Remove",
      message: "They won't be able to approve overrides at a till until a new PIN is set." }))
      await patch({ supervisor_pin: "" }, "Supervisor PIN removed.");
  }
  async function addRole() {
    try {
      await api(`/users/${u.id}/assign_role/`, { branch: null,
        body: { role: Number(newRole), branch: roleObj?.scope === "org" ? null : Number(newBranch) } });
      toast("Role added.", "success"); setNewRole(""); await reload();
    } catch (e) { toast(errorText(e), "error"); }
  }
  async function removeRole(m: Membership) {
    if (!(await confirmDialog({ title: `Remove ${m.role_name}?`, danger: true, confirmLabel: "Remove",
      message: `${fullName(u)} loses this role at ${branchName(m.branch)} straight away.` }))) return;
    try { await api(`/users/${u.id}/revoke_role/`, { body: { membership_id: m.id }, branch: null }); toast("Role removed.", "success"); await reload(); }
    catch (e) { toast(errorText(e), "error"); }
  }
  async function moveRole(m: Membership, to: string) {
    if (!to || Number(to) === m.branch) return;
    if (!(await confirmDialog({ title: `Move to ${branchName(Number(to))}?`, icon: <ArrowRightLeft size={26} />, confirmLabel: "Move",
      message: `${fullName(u)} will be ${m.role_name} at ${branchName(Number(to))} instead of ${branchName(m.branch)}.` }))) return;
    try {
      await api(`/users/${u.id}/assign_role/`, { body: { role: m.role, branch: Number(to) }, branch: null });
      await api(`/users/${u.id}/revoke_role/`, { body: { membership_id: m.id }, branch: null });
      toast("Moved.", "success"); await reload();
    } catch (e) { toast(errorText(e), "error"); await reload(); }
  }

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card wide" role="dialog" aria-label={`Edit ${fullName(u)}`}>
        <div className="card-head">
          <span className="inline" style={{ gap: 12 }}><span className="avatar" style={{ width: 44, height: 44, fontSize: "1rem" }}>{initials(fullName(u))}</span>
            <span><h3>{fullName(u)}</h3><span className="muted" style={{ fontSize: ".85rem" }}>{u.username} · last sign-in {ago(u.last_login).toLowerCase()}
              {!u.is_active && <span className="tag warn" style={{ marginLeft: 8 }}>Deactivated</span>}</span></span></span>
          <button className="ghost icon" aria-label="Close" onClick={onClose}><X size={18} /></button>
        </div>
        {ro && <div className="warn-box"><Lock size={14} style={{ verticalAlign: -2 }} /> Read-only for you: this person has organization-wide
          access or also works at a branch you don't administer. An organization admin can change this account.</div>}

        <h4>Details</h4>
        <fieldset disabled={ro || busy} className="form-grid">
          <label>First name<input value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} /><Err e={errors} k="first_name" /></label>
          <label>Last name<input value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} /><Err e={errors} k="last_name" /></label>
          <label>Username<input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" /><Err e={errors} k="username" /></label>
          <label>Phone<input value={f.phone} inputMode="tel" onChange={(e) => setF({ ...f, phone: e.target.value })} /><Err e={errors} k="phone" /></label>
          <label style={{ gridColumn: "1 / -1" }}>Email<input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /><Err e={errors} k="email" /></label>
        </fieldset>
        {!ro && <div className="actions"><button className="primary" disabled={!dirty || busy || !f.username.trim()}
          onClick={() => patch(f, "Details saved.")}>Save details</button>{dirty && <span className="muted">Unsaved changes</span>}</div>}

        <h4>Sign-in & security</h4>
        <div className="actions">
          <button disabled={ro || busy} onClick={resetPassword}><KeyRound size={16} />Reset password</button>
          <button disabled={ro || busy} onClick={setPin}><ShieldCheck size={16} />{u.has_supervisor_pin ? "Change supervisor PIN" : "Set supervisor PIN"}</button>
          {u.has_supervisor_pin && <button className="link" disabled={ro || busy} onClick={clearPin}>Remove PIN</button>}
          <span className="spacer" />
          <button className={u.is_active ? "ghost-btn" : "primary"} disabled={ro || busy || (self && u.is_active)} onClick={toggleActive}
                  title={self ? "You can't deactivate your own account" : undefined}>
            {u.is_active ? "Deactivate account" : "Reactivate account"}</button>
        </div>

        <h4>Roles & branches</h4>
        {u.memberships.length ? (
          <table className="grid-table">
            <thead><tr><th>Role</th><th>Where</th><th /></tr></thead>
            <tbody>{u.memberships.map((m) => (
              <tr key={m.id}>
                <td>{m.role_name}</td>
                <td>{m.branch === null ? "All branches" : ro ? branchName(m.branch) : (
                  <select aria-label={`Move ${m.role_name} to another branch`} value={m.branch} onChange={(e) => moveRole(m, e.target.value)}>
                    {[...branches.filter((b) => b.id !== m.branch), { id: m.branch, name: branchName(m.branch) }]
                      .sort((a, b) => a.name.localeCompare(b.name)).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>)}</td>
                <td style={{ textAlign: "right" }}>{!ro && <button className="link" onClick={() => removeRole(m)}><Trash2 size={14} />Remove</button>}</td>
              </tr>
            ))}</tbody>
          </table>
        ) : <p className="muted">No roles yet. Without a role they can sign in but can't use the till or back office.</p>}
        {!ro && (
          <div className="payrow" style={{ marginTop: 10 }}>
            <select aria-label="Role to add" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
              <option value="">Add a role…</option>
              {grantable.map((r) => <option key={r.id} value={r.id}>{r.name}{r.scope === "org" ? " (all branches)" : ""}</option>)}
            </select>
            {roleObj?.scope !== "org" && (
              <select aria-label="Branch" value={newBranch} onChange={(e) => setNewBranch(e.target.value)}>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>)}
            <button disabled={!newRole} onClick={addRole}><Plus size={16} />Add</button>
          </div>
        )}
        {roleObj && <p className="muted" style={{ fontSize: ".82rem", margin: "6px 0 0" }}>
          {roleObj.name} can: {roleObj.permissions.includes("*") ? "everything" : roleObj.permissions.join(", ")}</p>}
      </div>
    </div>
  );
}

function NewUser({ ctx, roles, onClose, onSaved }: { ctx: Ctx; roles: Role[]; onClose: () => void; onSaved: (u: User) => void }) {
  const { orgAdmin, branches, grantable } = useGrantable(ctx, roles);
  const cashier = grantable.find((r) => r.name === "Cashier");
  const [f, setF] = useState({ first_name: "", last_name: "", username: "", email: "", phone: "", password: "", password2: "",
    role: cashier ? String(cashier.id) : "", branch: ctx.branch && branches.some((b) => String(b.id) === ctx.branch) ? ctx.branch : String(branches[0]?.id ?? "") });
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const role = useMemo(() => grantable.find((r) => String(r.id) === f.role), [f.role, grantable]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  // Suggest a username from the name until the admin types one.
  const [userTouched, setUserTouched] = useState(false);
  useEffect(() => {
    if (!userTouched) setF((x) => ({ ...x, username: `${x.first_name}.${x.last_name}`.toLowerCase().replace(/[^a-z0-9.]/g, "").replace(/^\.|\.$/g, "") }));
  }, [f.first_name, f.last_name]);

  async function save() {
    if (f.password !== f.password2) { setErrors({ password2: "The two passwords differ." }); return; }
    setBusy(true); setErrors({});
    try {
      const body: Record<string, unknown> = { first_name: f.first_name, last_name: f.last_name, username: f.username, email: f.email,
        phone: f.phone, password: f.password, role: f.role ? Number(f.role) : undefined,
        branch: role && role.scope === "branch" ? Number(f.branch) : undefined };
      const u = await api<User>("/users/", { body, branch: null });
      toast(`${u.first_name || u.username} can now sign in.`, "success"); onSaved(u);
    } catch (e) { setErrors(toErrors(e)); } finally { setBusy(false); }
  }

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card wide" role="dialog" aria-label="New user">
        <div className="card-head"><h3>New user</h3><button className="ghost icon" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
        {errors.detail && <p className="error">{errors.detail}</p>}
        <div className="form-grid">
          <label>First name<input value={f.first_name} onChange={set("first_name")} autoFocus /><Err e={errors} k="first_name" /></label>
          <label>Last name<input value={f.last_name} onChange={set("last_name")} /><Err e={errors} k="last_name" /></label>
          <label>Username<input value={f.username} autoComplete="off" onChange={(e) => { setUserTouched(true); set("username")(e); }} /><Err e={errors} k="username" /></label>
          <label>Phone<input value={f.phone} inputMode="tel" onChange={set("phone")} /></label>
          <label style={{ gridColumn: "1 / -1" }}>Email (optional)<input type="email" value={f.email} onChange={set("email")} /><Err e={errors} k="email" /></label>
          <label>Starting password<input type="password" value={f.password} autoComplete="new-password" onChange={set("password")} /><Err e={errors} k="password" /></label>
          <label>Repeat password<input type="password" value={f.password2} autoComplete="new-password" onChange={set("password2")} /><Err e={errors} k="password2" /></label>
          <label>Role
            <select value={f.role} onChange={set("role")}>
              {orgAdmin && <option value="">No role yet</option>}
              {grantable.map((r) => <option key={r.id} value={r.id}>{r.name}{r.scope === "org" ? " (all branches)" : ""}</option>)}
            </select><Err e={errors} k="role" /></label>
          {(!role || role.scope === "branch") && (
            <label>Branch
              <select value={f.branch} onChange={set("branch")} disabled={!role}>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select></label>)}
        </div>
        {role && <p className="muted" style={{ fontSize: ".82rem", margin: 0 }}>{role.name} can: {role.permissions.includes("*") ? "everything" : role.permissions.join(", ")}</p>}
        <div className="actions">
          <button className="primary" disabled={busy || !f.username.trim() || !f.password || (!orgAdmin && !f.role)} onClick={save}><UserPlus size={16} />Create user</button>
          <button className="link" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
