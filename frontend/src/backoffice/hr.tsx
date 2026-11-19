// Employees: list, create/edit, link a system login, terminate (which disables the login).
import { useEffect, useState } from "react";
import { api, money } from "../api";
import type { Ctx } from "./BackOffice";
import { DateFilters, dateFilters, SortHeader, useListState } from "./listing";
import { Err, Errors, QuickAdd, toErrors, useOptions } from "./ui";

const TYPES: Record<string, string> = { permanent: "Permanent", contract: "Contract", casual: "Casual", intern: "Intern" };
const STATUS: Record<string, string> = { active: "Active", suspended: "Suspended", terminated: "Terminated" };

export function Employees({ ctx }: { ctx: Ctx }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("active");
  const [dept, setDept] = useState("");
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [editing, setEditing] = useState<any | "new" | null>(null);
  const depts = useOptions("/hr/departments/?page_size=200");
  const sorter = useListState({ sort: "name" });
  const shown = rows && sorter.apply(rows, { sorts: {
    number: (e: any) => e.employee_number, name: (e: any) => `${e.first_name} ${e.last_name}`, job: (e: any) => e.job_title,
    branch: (e: any) => e.branch_name || "", dept: (e: any) => e.department_name || "", type: (e: any) => e.employment_type, status: (e: any) => e.status } });
  const canAdd = ctx.canOrg("hr.manage") || ctx.me.branches.some((b) => b.permissions.includes("hr.manage"));

  useEffect(() => {
    const q = new URLSearchParams({ ordering: "first_name", page_size: "200" });
    if (ctx.branch) q.set("branch", ctx.branch);
    if (search) q.set("search", search);
    if (status) q.set("status", status);
    if (dept) q.set("department", dept);
    api(`/hr/employees/?${q}`, { branch: null }).then((d) => setRows(d.results)).catch((e) => setError(e.message));
  }, [ctx.branch, search, status, dept, tick]);

  return (
    <div>
      <div className="toolbar">
        <input placeholder="Search name, number or phone" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select aria-label="Department" value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="">All departments</option>
          {depts.items.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        {rows && <span className="muted">{rows.length} people</span>}
        <span className="spacer" />
        {canAdd && <button className="primary" onClick={() => setEditing("new")}>+ New employee</button>}
      </div>
      {error && <p className="error">{error}</p>}
      {rows && !rows.length && <p className="muted">No employees match.</p>}
      {!!rows?.length && (
        <table className="grid-table clickable">
          <thead><tr><SortHeader list={sorter} k="number">No.</SortHeader><SortHeader list={sorter} k="name">Name</SortHeader>
            <SortHeader list={sorter} k="job">Job</SortHeader><SortHeader list={sorter} k="branch">Branch</SortHeader>
            <SortHeader list={sorter} k="dept">Department</SortHeader><SortHeader list={sorter} k="type">Type</SortHeader><th>Login</th>
            <SortHeader list={sorter} k="status">Status</SortHeader></tr></thead>
          <tbody>{(shown || []).map((e) => (
            <tr key={e.id} tabIndex={0} onClick={() => setEditing(e)} onKeyDown={(k) => k.key === "Enter" && setEditing(e)}>
              <td>{e.employee_number}</td><td>{e.first_name} {e.last_name}</td><td>{e.job_title}</td>
              <td>{e.branch_name || "Head office"}</td><td>{e.department_name}</td><td>{TYPES[e.employment_type]}</td>
              <td>{e.username ? <>{e.username}{e.login_active === false && <span className="tag">disabled</span>}</> : <span className="muted">–</span>}</td>
              <td>{e.status === "active" ? STATUS[e.status] : <span className="tag warn">{STATUS[e.status]}</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {editing && <EmployeeForm ctx={ctx} emp={editing === "new" ? null : editing} depts={depts}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setTick((t) => t + 1); }} />}
    </div>
  );
}

const today = () => new Date().toISOString().slice(0, 10);

function EmployeeForm({ ctx, emp, depts, onClose, onSaved }: {
  ctx: Ctx; emp: any | null; depts: { items: any[]; reload: () => void }; onClose: () => void; onSaved: () => void;
}) {
  const orgHR = ctx.canOrg("hr.manage");
  const hrBranches = ctx.me.branches.filter((b) => orgHR || b.permissions.includes("hr.manage"));
  const canEdit = emp ? !!emp.can_manage : hrBranches.length > 0;
  const showPay = !emp || emp.can_manage;
  const [f, setF] = useState(() => ({
    first_name: emp?.first_name ?? "", last_name: emp?.last_name ?? "", phone: emp?.phone ?? "", email: emp?.email ?? "",
    national_id: emp?.national_id ?? "", employee_number: emp?.employee_number ?? "",
    branch: emp ? (emp.branch ? String(emp.branch) : "") : (ctx.branch || (orgHR ? "" : String(hrBranches[0]?.id ?? ""))),
    department: emp?.department ? String(emp.department) : "", job_title: emp?.job_title ?? "",
    employment_type: emp?.employment_type ?? "permanent", status: emp?.status ?? "active",
    hire_date: emp?.hire_date ?? today(), end_date: emp?.end_date ?? "",
    basic_salary: emp?.basic_salary ?? "", annual_leave_days: String(emp?.annual_leave_days ?? 18),
    bank_name: emp?.bank_name ?? "", bank_account: emp?.bank_account ?? "", next_of_kin: emp?.next_of_kin ?? "",
    user: emp?.user ? String(emp.user) : "",
  }));
  const [logins, setLogins] = useState<any[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  useEffect(() => {
    if (canEdit) api("/hr/employees/linkable_users/", { branch: null }).then(setLogins).catch(() => setLogins([]));
  }, []);

  const terminating = f.status === "terminated" && emp?.status !== "terminated";

  async function save() {
    setBusy(true); setErrors({});
    const body: Record<string, unknown> = {
      ...f, branch: f.branch ? Number(f.branch) : null, department: f.department ? Number(f.department) : null,
      user: f.user ? Number(f.user) : null, end_date: f.end_date || null,
      basic_salary: f.basic_salary === "" ? "0" : f.basic_salary, annual_leave_days: Number(f.annual_leave_days || 0),
    };
    if (!showPay) for (const k of ["national_id", "basic_salary", "bank_name", "bank_account", "next_of_kin"]) delete body[k];
    try {
      await api(emp ? `/hr/employees/${emp.id}/` : "/hr/employees/", { method: emp ? "PATCH" : "POST", body, branch: null });
      onSaved();
    } catch (e) { setErrors(toErrors(e)); } finally { setBusy(false); }
  }

  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}><div className="card wide">
      <h3>{emp ? `${emp.first_name} ${emp.last_name} · ${emp.employee_number}` : "New employee"}</h3>
      {errors.detail && <p className="error">{errors.detail}</p>}
      <fieldset disabled={!canEdit}>
        <h4>Person</h4>
        <div className="form-grid">
          <label>First name<input value={f.first_name} onChange={set("first_name")} autoFocus={!emp} /><Err e={errors} k="first_name" /></label>
          <label>Last name<input value={f.last_name} onChange={set("last_name")} /><Err e={errors} k="last_name" /></label>
          <label>Phone<input value={f.phone} onChange={set("phone")} inputMode="tel" /></label>
          <label>Email<input value={f.email} onChange={set("email")} type="email" /><Err e={errors} k="email" /></label>
          {showPay && <label>National ID<input value={f.national_id} onChange={set("national_id")} /></label>}
          {showPay && <label>Next of kin<input value={f.next_of_kin} onChange={set("next_of_kin")} placeholder="Name and phone" /></label>}
        </div>

        <h4>Job</h4>
        <div className="form-grid">
          <label>Employee number<input value={f.employee_number} onChange={set("employee_number")} placeholder={emp ? "" : "Leave empty to number automatically"} />
            <Err e={errors} k="employee_number" /></label>
          <label>Branch
            <select value={f.branch} onChange={set("branch")}>
              {orgHR && <option value="">Head office</option>}
              {hrBranches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              {emp?.branch && !hrBranches.some((b) => b.id === emp.branch) && <option value={emp.branch}>{emp.branch_name}</option>}
            </select><Err e={errors} k="branch" /></label>
          <label>Department
            <select value={f.department} onChange={set("department")}>
              <option value="">None</option>
              {depts.items.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
            {canEdit && <QuickAdd label="department" fields={[{ key: "name", placeholder: "Department name", required: true }]}
              create={async ({ name }) => {
                const d = await api("/hr/departments/", { body: { name: name.trim() }, branch: null });
                depts.reload(); setF((x) => ({ ...x, department: String(d.id) }));
              }} />}
          </label>
          <label>Job title<input value={f.job_title} onChange={set("job_title")} placeholder="e.g. Cashier, Storekeeper" /></label>
          <label>Employment type
            <select value={f.employment_type} onChange={set("employment_type")}>
              {Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
          <label>Hire date<input type="date" value={f.hire_date} onChange={set("hire_date")} /><Err e={errors} k="hire_date" /></label>
          <label>Status
            <select value={f.status} onChange={set("status")}>
              {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
          <label>Last working day<input type="date" value={f.end_date} onChange={set("end_date")} />
            <Err e={errors} k="end_date" /></label>
        </div>
        {terminating && <p className="warn-box">⚠ Terminating also <b>disables {emp?.username ? `the login "${emp.username}"` : "any linked login"}</b> straight away,
          including a session already open at a till. Re-enabling it later needs an administrator.</p>}

        {showPay && <>
          <h4>Pay & bank</h4>
          <div className="form-grid">
            <label>Basic salary (monthly)<input inputMode="decimal" value={f.basic_salary} onChange={set("basic_salary")} />
              {f.basic_salary && <small className="muted">{money(f.basic_salary)}</small>}<Err e={errors} k="basic_salary" /></label>
            <label>Annual leave days<input inputMode="numeric" value={f.annual_leave_days} onChange={set("annual_leave_days")} /></label>
            <label>Bank<input value={f.bank_name} onChange={set("bank_name")} /></label>
            <label>Account number<input value={f.bank_account} onChange={set("bank_account")} /></label>
          </div>
        </>}
        {!showPay && <p className="muted"><small>Pay, bank and ID details are visible to HR only.</small></p>}

        <h4>System login</h4>
        <label>Linked login
          <select value={f.user} onChange={set("user")}>
            <option value="">No login (doesn’t use the system)</option>
            {emp?.user && <option value={emp.user}>{emp.username}{emp.login_active === false ? " (disabled)" : ""}</option>}
            {logins.map((u) => <option key={u.id} value={u.id}>{u.username} — {u.first_name} {u.last_name}</option>)}
          </select><Err e={errors} k="user" />
          <small className="muted">Linking lets them clock in and request leave. Create logins and roles under Users & roles.</small></label>
      </fieldset>
      <div className="actions">
        {canEdit && <button className={terminating ? "danger" : "primary"} disabled={busy || !f.first_name || !f.last_name || !f.hire_date} onClick={save}>
          {emp ? (terminating ? "Terminate employee" : "Save changes") : "Add employee"}</button>}
        <button className="link" onClick={onClose}>{canEdit ? "Cancel" : "Close"}</button>
      </div>
    </div></div>
  );
}
