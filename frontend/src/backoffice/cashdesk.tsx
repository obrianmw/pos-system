// Cash: tills (who may open each one) and the branch vault (holder, floats, pickups, bank/finance/restock).
import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownToLine, ArrowUpFromLine, Banknote, Building2, KeyRound, Landmark, Lock, Monitor, Plus, ShoppingBag,
  UserCheck, Users as UsersIcon, Vault as VaultIcon,
} from "lucide-react";
import { api, money } from "../api";
import type { Ctx } from "./BackOffice";
import { errorText, initials, toast } from "./ui";
import { confirmDialog, formDialog } from "../Dialog";
import { ListControls, SortHeader, useListState } from "./listing";

// =================================================================================================
// Tills
// =================================================================================================
type Till = { id: number; branch: number; name: string; code: string; is_active: boolean; users: number[];
  user_names: { id: number; name: string }[]; open_session: null | { cashier_name: string; opened_at: string } };

export function Tills({ ctx }: { ctx: Ctx }) {
  const [rows, setRows] = useState<Till[] | null>(null);
  const [tick, setTick] = useState(0);
  const [editing, setEditing] = useState<Till | null>(null);
  const admin = (branch: number) => ctx.canOrg("org.admin") || !!ctx.me.branches.find((b) => b.id === branch)?.permissions.includes("branch.admin");
  const branchName = (id: number) => ctx.me.branches.find((b) => b.id === id)?.name || "";
  const list = useListState({ sort: "name" });

  useEffect(() => {
    api("/tills/?page_size=200", { branch: ctx.branch }).then((d) => setRows(d.results)).catch((e) => { setRows([]); toast(errorText(e), "error"); });
  }, [ctx.branch, tick]);

  const shown = useMemo(() => list.apply(rows || [], {
    text: (t) => `${t.name} ${t.code} ${t.user_names.map((u) => u.name).join(" ")}`,
    filters: { status: (t, v) => (v === "open" ? !!t.open_session : v === "free" ? !t.open_session && t.is_active : v === "off" ? !t.is_active : true) },
    sorts: { name: (t) => t.name, branch: (t) => branchName(t.branch), users: (t) => t.users.length, status: (t) => (t.open_session ? 0 : t.is_active ? 1 : 2) },
  }), [rows, list.state]);

  async function addTill() {
    const branches = ctx.me.branches.filter((b) => admin(b.id));
    const branch = ctx.branch ? Number(ctx.branch) : branches[0]?.id;
    if (!branch) return;
    const v = await formDialog({ title: "New till", icon: <Monitor size={26} />, confirmLabel: "Create till",
      message: `At ${branchName(branch)}${!ctx.branch && branches.length > 1 ? " (pick another branch at the top to add it there)" : ""}.`,
      fields: [{ name: "name", label: "Name", placeholder: "e.g. Till 4", required: true },
               { name: "code", label: "Short code", placeholder: "e.g. t4", required: true,
                 validate: (x) => (/^[a-z0-9-]+$/.test(x) ? null : "Lower-case letters, digits and dashes only.") }] });
    if (!v) return;
    try { await api("/tills/", { body: { ...v, branch }, branch: String(branch) }); toast("Till created. Now choose who may open it.", "success"); setTick((t) => t + 1); }
    catch (e) { toast(errorText(e), "error"); }
  }

  return (
    <div>
      <ListControls list={list} placeholder="Search tills or people" filters={[
        { key: "status", label: "Status", options: [["", "All"], ["open", "Open now"], ["free", "Free"], ["off", "Switched off"]] }]}
        right={ctx.me.branches.some((b) => admin(b.id)) && <button className="primary" onClick={addTill}><Plus size={16} />New till</button>} />
      {rows === null && <div className="skeleton" style={{ height: 160 }} />}
      {rows && !shown.length && <p className="muted">No tills match.</p>}
      {!!shown.length && (
        <table className="grid-table clickable">
          <thead><tr>
            <SortHeader list={list} k="name">Till</SortHeader>{!ctx.branch && <SortHeader list={list} k="branch">Branch</SortHeader>}
            <SortHeader list={list} k="users">Who may open it</SortHeader><SortHeader list={list} k="status">Status</SortHeader></tr></thead>
          <tbody>{shown.map((t) => (
            <tr key={t.id} tabIndex={0} onClick={() => admin(t.branch) && setEditing(t)} onKeyDown={(e) => e.key === "Enter" && admin(t.branch) && setEditing(t)}>
              <td><b>{t.name}</b> <span className="muted">{t.code}</span></td>
              {!ctx.branch && <td>{branchName(t.branch)}</td>}
              <td>{t.user_names.length ? t.user_names.map((u) => <span key={u.id} className="tag">{u.name}</span>) : <span className="tag warn">Nobody assigned</span>}</td>
              <td>{!t.is_active ? <span className="tag">Switched off</span> : t.open_session
                ? <span className="tag status-partial">Open · {t.open_session.cashier_name}</span> : <span className="tag status-received">Free</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <p className="muted" style={{ fontSize: ".85rem" }}>Only the people listed can open a till, one at a time. Tills open at zero; the vault holder hands over the float.</p>
      {editing && <TillEditor till={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setTick((t) => t + 1); }} />}
    </div>
  );
}

function TillEditor({ till, onClose, onSaved }: { till: Till; onClose: () => void; onSaved: () => void }) {
  const [staff, setStaff] = useState<{ id: number; name: string; roles: string }[]>([]);
  const [chosen, setChosen] = useState<Set<number>>(new Set(till.users));
  const [active, setActive] = useState(till.is_active);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api(`/users/?branch=${till.branch}&is_active=true&page_size=200`, { branch: null })
      .then((d) => setStaff(d.results.map((u: any) => ({ id: u.id, name: `${u.first_name} ${u.last_name}`.trim() || u.username,
        roles: u.memberships.filter((m: any) => m.branch === till.branch).map((m: any) => m.role_name).join(", ") }))))
      .catch(() => {});
  }, []);
  function toggle(id: number) { const s = new Set(chosen); s.has(id) ? s.delete(id) : s.add(id); setChosen(s); }
  async function save() {
    if (!active && till.open_session && !(await confirmDialog({ title: "Switch off an open till?", message:
      `${till.open_session.cashier_name} has it open. They can finish and close it, but nobody can open it again.` }))) return;
    setBusy(true);
    try { await api(`/tills/${till.id}/`, { method: "PATCH", body: { users: [...chosen], is_active: active }, branch: null }); toast("Till saved.", "success"); onSaved(); }
    catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
  }
  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card" role="dialog" aria-label={`Edit ${till.name}`}>
        <h3>{till.name}</h3>
        <p className="muted" style={{ margin: 0 }}>Choose who may open this till. Only one of them can have it open at a time.</p>
        <div className="checklist">
          {staff.length === 0 && <p className="muted">Loading staff…</p>}
          {staff.map((u) => (
            <label key={u.id} className="check"><input type="checkbox" checked={chosen.has(u.id)} onChange={() => toggle(u.id)} />
              <span className="avatar" style={{ width: 26, height: 26, fontSize: ".65rem" }}>{initials(u.name)}</span>
              <span>{u.name}<small className="muted"> · {u.roles || "no role here"}</small></span></label>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Till in use (untick to switch it off)</label>
        <div className="actions">
          <button className="primary" disabled={busy} onClick={save}>Save</button>
          <button className="ghost-btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

// =================================================================================================
// Vault
// =================================================================================================
type VaultData = { id: number; branch: number; branch_name: string; name: string; balance: string;
  custodian: null | { id: number; name: string; until: string; since: string }; i_hold_it: boolean;
  can_operate: boolean; can_assign: boolean;
  open_tills: { session: number; till: string; cashier: string; opened_at: string; balance: string }[];
  in_transit: string; pending: Transfer[] };
type Transfer = { id: number; kind: string; kind_label: string; amount: string; till_name: string; created_by_name: string;
  created_at: string; status: string; status_label: string; received_amount: string | null; difference: string | null;
  confirmed_by_name: string; confirm_note: string; direction: string; counterparty: string; reference: string; vault_balance_after: string };

const KIND_LABEL: Record<string, string> = { float: "Float to till", pickup: "Pickup from till", close: "Till closing", drop: "Cash drop from till",
  to_finance: "To finance", from_finance: "From finance", to_bank: "Bank deposit", from_bank: "Bank withdrawal", restock: "Restocking payment" };

export function VaultPage({ ctx }: { ctx: Ctx }) {
  const [vaults, setVaults] = useState<VaultData[] | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => { api<VaultData[]>("/cash/vaults/", { branch: ctx.branch }).then(setVaults).catch((e) => { setVaults([]); toast(errorText(e), "error"); }); }, [ctx.branch, tick]);
  const refresh = () => setTick((t) => t + 1);
  if (vaults === null) return <div className="skeleton" style={{ height: 220 }} />;
  if (!vaults.length) return <p className="muted">You don't have access to any vault. The vault is visible to branch admins, accountants and whoever holds it today.</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {vaults.map((v) => <VaultCard key={v.id} v={v} onChanged={refresh} />)}
      <TransferHistory ctx={ctx} tick={tick} />
    </div>
  );
}

function VaultCard({ v, onChanged }: { v: VaultData; onChanged: () => void }) {
  async function run(kind: string, extra: { till_session?: number; till?: string; max?: string } = {}) {
    const into = ["pickup", "from_finance", "from_bank"].includes(kind);
    const needsRef = ["to_bank", "from_bank", "restock"].includes(kind);
    const needsWho = ["to_finance", "from_finance", "restock"].includes(kind);
    const limit = extra.max ?? (into ? undefined : v.balance);
    const val = await formDialog({
      title: `${KIND_LABEL[kind]}${extra.till ? ` · ${extra.till}` : ""}`, confirmLabel: into ? "Receive" : "Hand over",
      icon: into ? <ArrowDownToLine size={26} /> : <ArrowUpFromLine size={26} />,
      message: limit ? `Available: ${money(limit)}` : undefined,
      fields: [
        { name: "amount", label: "Amount", type: "number", required: true,
          validate: (x) => (!(Number(x) > 0) ? "Enter an amount above zero." : limit && Number(x) > Number(limit) ? `No more than ${money(limit)}.` : null) },
        ...(needsWho ? [{ name: "counterparty", label: kind === "restock" ? "Supplier" : "Person in finance", required: true }] : []),
        ...(needsRef ? [{ name: "reference", label: kind === "restock" ? "Supplier invoice / receipt no." : "Bank slip no.", required: true }] : []),
        { name: "note", label: "Note (optional)" },
      ],
    });
    if (!val) return;
    try {
      await api(`/cash/vaults/${v.id}/move/`, { branch: null, body: { kind, ...val, till_session: extra.till_session } });
      toast(`${KIND_LABEL[kind]}: ${money(val.amount)} recorded.`, "success"); onChanged();
    } catch (e) { toast(errorText(e), "error"); }
  }

  async function assign() {
    const people = await api<{ id: number; name: string }[]>(`/cash/vaults/${v.id}/candidates/`, { branch: null });
    const val = await formDialog({ title: `Who holds the ${v.branch_name} vault?`, icon: <KeyRound size={26} />, confirmLabel: "Hand over the vault",
      message: "They become this branch's authorizer (approve price changes, voids and refunds) until the time below.",
      fields: [
        { name: "who", label: `Type a name: ${people.map((p) => p.name).join(", ")}`, required: true,
          validate: (x) => (people.some((p) => p.name.toLowerCase() === x.toLowerCase()) ? null : "Choose one of the names listed.") },
        { name: "until", label: "Until (leave empty for end of today)", placeholder: "YYYY-MM-DD HH:MM" },
      ] });
    if (!val) return;
    const who = people.find((p) => p.name.toLowerCase() === val.who.toLowerCase())!;
    try {
      await api(`/cash/vaults/${v.id}/assign/`, { branch: null, body: { custodian: who.id, until: val.until ? val.until.replace(" ", "T") : undefined } });
      toast(`${who.name} now holds the vault.`, "success"); onChanged();
    } catch (e) { toast(errorText(e), "error"); }
  }
  async function release() {
    if (!(await confirmDialog({ title: "Release the vault?", message: "Nobody will be able to move vault cash or authorize until someone is assigned again.", confirmLabel: "Release" }))) return;
    try { await api(`/cash/vaults/${v.id}/release/`, { method: "POST", branch: null }); toast("Vault released.", "success"); onChanged(); }
    catch (e) { toast(errorText(e), "error"); }
  }

  async function confirmHandover(t: Transfer) {
    const val = await formDialog({ title: `Confirm ${t.kind_label.toLowerCase()} · ${t.till_name}`, icon: <ArrowDownToLine size={26} />,
      confirmLabel: "Confirm & put in vault",
      message: `${t.created_by_name} handed over ${money(t.amount)}. Count it and enter what you actually received.`,
      fields: [
        { name: "received", label: "Amount received", type: "number", value: String(Number(t.amount)), required: true,
          validate: (x) => (Number(x) >= 0 && x.trim() !== "" ? null : "Enter the amount you counted.") },
        { name: "note", label: "Note (required if the count differs)",
          validate: (x, all) => (Number(all.received) !== Number(t.amount) && !x.trim() ? "Say why the count differs." : null) },
      ] });
    if (!val) return;
    try {
      await api(`/cash/vaults/${v.id}/confirm/`, { branch: null, body: { transfer: t.id, received_amount: val.received, note: val.note } });
      const diff = Number(val.received) - Number(t.amount);
      toast(diff ? `Confirmed. ${money(Math.abs(diff))} ${diff < 0 ? "short" : "over"} was booked.` : `Confirmed: ${money(val.received)} is in the vault.`, diff ? "info" : "success");
      onChanged();
    } catch (e) { toast(errorText(e), "error"); }
  }

  const can = v.can_operate;
  return (
    <section className="card vault-card">
      <div className="card-head">
        <div className="inline" style={{ gap: 12 }}>
          <span className="kpi-icon" style={{ width: 42, height: 42 }}><VaultIcon size={22} /></span>
          <div><h2 style={{ margin: 0 }}>{v.branch_name} · {v.name}</h2>
            <span className="muted" style={{ fontSize: ".85rem" }}>
              {v.custodian ? <>Held by <b>{v.custodian.name}</b>{v.i_hold_it && " (you)"} until {new Date(v.custodian.until).toLocaleString()}</>
                : <span className="warn">Nobody holds the vault. Cash can't be moved and nobody is authorizing.</span>}</span></div>
        </div>
        <div style={{ textAlign: "right" }}><span className="muted" style={{ fontSize: ".8rem" }}>Vault balance</span>
          <div style={{ fontSize: "1.8rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{money(v.balance)}</div></div>
      </div>
      <div className="actions">
        {v.can_assign && <button onClick={assign}><UserCheck size={16} />{v.custodian ? "Hand to someone else" : "Assign holder"}</button>}
        {v.custodian && (v.i_hold_it || v.can_assign) && <button className="ghost-btn" onClick={release}>Release</button>}
        <span className="spacer" />
        {can && <>
          <button onClick={() => run("to_finance")}><UsersIcon size={16} />To finance</button>
          <button onClick={() => run("to_bank")}><Landmark size={16} />Bank deposit</button>
          <button onClick={() => run("restock")}><ShoppingBag size={16} />Restocking</button>
          <button onClick={() => run("from_bank")}><Building2 size={16} />Bank withdrawal</button>
          <button onClick={() => run("from_finance")}><Banknote size={16} />From finance</button>
        </>}
      </div>
      {!can && <p className="muted" style={{ margin: 0, fontSize: ".85rem" }}><Lock size={13} style={{ verticalAlign: -2 }} /> Only the vault holder moves cash.</p>}
      {v.pending.length > 0 && <div className="pending-box">
        <h4 style={{ marginTop: 0 }}>Waiting for the vault holder to confirm · {money(v.in_transit)} in transit</h4>
        <p className="muted" style={{ margin: "0 0 8px", fontSize: ".85rem" }}>Cash handed over from tills isn't in the vault until it's counted and confirmed.</p>
        <table className="grid-table">
          <thead><tr><th>Handed over</th><th>Till</th><th>By</th><th className="num">Declared</th><th /></tr></thead>
          <tbody>{v.pending.map((t) => (
            <tr key={t.id}><td>{t.kind_label} · {new Date(t.created_at).toLocaleTimeString()}</td><td>{t.till_name}</td><td>{t.created_by_name}</td>
              <td className="num">{money(t.amount)}</td>
              <td style={{ textAlign: "right" }}>{can ? <button className="primary" onClick={() => confirmHandover(t)}>Count & confirm</button>
                : <span className="tag warn">Waiting</span>}</td></tr>
          ))}</tbody>
        </table>
      </div>}
      <h4>Open tills</h4>
      {v.open_tills.length ? (
        <table className="grid-table">
          <thead><tr><th>Till</th><th>Cashier</th><th>Opened</th><th className="num">In drawer</th><th /></tr></thead>
          <tbody>{v.open_tills.map((t) => (
            <tr key={t.session}><td>{t.till}</td><td>{t.cashier}</td><td>{new Date(t.opened_at).toLocaleTimeString()}</td>
              <td className="num">{money(t.balance)}</td>
              <td style={{ textAlign: "right" }}>{can && <>
                <button onClick={() => run("float", { till_session: t.session, till: t.till })}>Give float</button>{" "}
                <button className="ghost-btn" disabled={Number(t.balance) <= 0}
                        onClick={() => run("pickup", { till_session: t.session, till: t.till, max: t.balance })}>Pick up cash</button></>}</td></tr>
          ))}</tbody>
        </table>
      ) : <p className="muted">No tills are open.</p>}
    </section>
  );
}

function TransferHistory({ ctx, tick }: { ctx: Ctx; tick: number }) {
  const list = useListState({ sort: "-created_at" });
  const [rows, setRows] = useState<any[] | null>(null);
  const [count, setCount] = useState(0);
  const f = list.state.filters;
  useEffect(() => {
    const qp = new URLSearchParams({ page_size: "200", ordering: list.state.sort });
    if (list.state.search) qp.set("search", list.state.search);
    if (f.kind) qp.set("kind", f.kind);
    if (f.status) qp.set("status", f.status);
    if (f.from) qp.set("from", f.from);
    if (f.to) qp.set("to", f.to);
    api(`/cash/transfers/?${qp}`, { branch: ctx.branch }).then((d) => { setRows(d.results); setCount(d.count); }).catch(() => setRows([]));
  }, [list.state, ctx.branch, tick]);
  return (
    <section>
      <h3 style={{ margin: "8px 0" }}>Cash movements</h3>
      <ListControls list={list} placeholder="Search reference, person, till" count={count} filters={[
        { key: "kind", label: "Type", options: [["", "All types"], ...Object.entries(KIND_LABEL)] as [string, string][] },
        { key: "status", label: "Status", options: [["", "Any status"], ["pending", "Waiting for confirmation"], ["settled", "Settled"]] },
        { key: "from", label: "From", type: "date" }, { key: "to", label: "To", type: "date" }]} />
      {rows === null ? <div className="skeleton" style={{ height: 120 }} /> : !rows.length ? <p className="muted">No movements match.</p> : (
        <table className="grid-table">
          <thead><tr><SortHeader list={list} k="created_at">When</SortHeader><SortHeader list={list} k="kind">Type</SortHeader>
            <th>Till / who</th><th>Reference</th><th>By</th><SortHeader list={list} k="amount" num>Amount</SortHeader><th className="num">Vault after</th></tr></thead>
          <tbody>{rows.map((t) => (
            <tr key={t.id}><td>{new Date(t.created_at).toLocaleString()}</td>
              <td>{t.kind_label}{t.status === "pending" && <span className="tag warn">Waiting for confirmation</span>}
                {t.confirmed_by_name && <small className="muted" title={t.confirm_note}><br />Confirmed by {t.confirmed_by_name}
                  {Number(t.difference) !== 0 && t.difference !== null && <b className="error"> · {Number(t.difference) > 0 ? "+" : ""}{money(t.difference)}</b>}</small>}</td>
              <td>{t.till_name || t.counterparty}</td><td>{t.reference}</td><td>{t.created_by_name}</td>
              <td className={`num ${t.direction === "in" ? "ok" : ""}`}>{t.direction === "in" ? "+" : "−"}{money(t.amount)}</td>
              <td className="num">{t.status === "pending" ? "—" : money(t.vault_balance_after)}</td></tr>
          ))}</tbody>
        </table>
      )}
    </section>
  );
}
