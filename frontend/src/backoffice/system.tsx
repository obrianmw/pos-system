// System dashboard for admins: health, live operations, parameters and events - whole organization, or the
// branch picked at the top. Org admins also see server health, security and organization settings.
import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Database, HardDrive, RefreshCw, Server, ShieldCheck, XCircle } from "lucide-react";
import { api, money } from "../api";
import type { Ctx } from "./BackOffice";
import { errorText, toast } from "./ui";
import { ListControls, SortHeader, useListState } from "./listing";

type Overview = any;
const bytes = (n?: number | null) => n == null ? "—" : n > 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1e3)} KB`;
const dur = (s: number) => { const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; };
const LABEL: Record<string, string> = {
  "auth.login_failed": "Wrong password", "override.pin_failed": "Wrong supervisor PIN", "system.error": "Server error",
  "sale.voided": "Sale voided", "sale.refund": "Refund", "journal.manual": "Manual journal", "journal.reversed": "Journal reversed",
  "inventory.adjust": "Stock adjusted", "stockcount.posted": "Stock take posted", "till.updated": "Till changed",
  "branding.updated": "Branding changed", "vault.assigned": "Vault handed over", "vault.released": "Vault released",
  "user.created": "User created", "user.updated": "User edited", "user.deactivated": "User deactivated",
  "user.password_reset": "Password reset", "user.role_assigned": "Role given", "user.role_revoked": "Role removed", "user.pin_changed": "PIN changed",
};
const label = (a: string) => LABEL[a] || a;
const brief = (data: Record<string, unknown> = {}) => Object.entries(data).slice(0, 4).map(([k, v]) => {
  const t = Array.isArray(v) ? (v.length > 3 ? `${v.length} items` : v.join(", ")) : v && typeof v === "object" ? "…" : String(v);
  return `${k.replace(/_/g, " ")}: ${t.length > 48 ? t.slice(0, 46) + "…" : t}`;
}).join(" · ");
const SEVERE = new Set(["auth.login_failed", "override.pin_failed", "system.error", "user.deactivated", "journal.reversed"]);

function Check({ ok, title, children, icon }: { ok: boolean | null; title: string; children: React.ReactNode; icon: JSX.Element }) {
  return (
    <div className={`card health ${ok === false ? "bad" : ok ? "good" : ""}`}>
      <div className="health-head">{icon}<b>{title}</b><span className="spacer" />
        {ok === false ? <XCircle size={18} className="error" aria-label="Problem" /> : ok ? <CheckCircle2 size={18} className="ok" aria-label="OK" /> : <span className="muted">n/a</span>}</div>
      <div className="health-body">{children}</div>
    </div>
  );
}

export function SystemDashboard({ ctx }: { ctx: Ctx }) {
  const [d, setD] = useState<Overview | null>(null);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setBusy(true);
    api<Overview>(`/system/overview/${ctx.branch ? `?branch=${ctx.branch}` : ""}`, { branch: null })
      .then(setD).catch((e) => toast(errorText(e), "error")).finally(() => setBusy(false));
  }, [ctx.branch, tick]);
  useEffect(() => { const id = setInterval(() => setTick((t) => t + 1), 60_000); return () => clearInterval(id); }, []);
  if (!d) return <div className="skeleton" style={{ height: 300 }} />;
  const h = d.health, o = d.operations, p = d.parameters;
  const alerts: string[] = [
    ...(h.database.ok ? [] : ["The database is not answering."]),
    ...(h.database.pending_migrations ? [`${h.database.pending_migrations} database update(s) not applied - run migrate.`] : []),
    ...(h.broker && h.broker.ok === false ? [h.broker.detail] : []),
    ...(h.disk && !h.disk.ok ? [`Low disk space: ${bytes(h.disk.free_bytes)} free.`] : []),
    ...(h.security?.problems || []),
    ...(o.pending_handovers.count ? [`${o.pending_handovers.count} till handover(s) (${money(o.pending_handovers.total)}) waiting for the vault holder.`] : []),
    ...(o.stock_takes_to_verify ? [`${o.stock_takes_to_verify} stock take(s) waiting for verification.`] : []),
    ...(o.failed_sign_ins_24h >= 5 ? [`${o.failed_sign_ins_24h} wrong-password sign-ins in 24 h.`] : []),
    ...(o.server_errors_24h ? [`${o.server_errors_24h} server error(s) in 24 h.`] : []),
    ...p.branches.filter((b: any) => !b.vault_holder && b.active).map((b: any) => `${b.name}: nobody holds the vault.`),
    ...p.branches.filter((b: any) => b.tills_unassigned).map((b: any) => `${b.name}: ${b.tills_unassigned} till(s) with nobody assigned.`),
  ];
  return (
    <div className="system">
      <div className="toolbar">
        <span className="muted">{d.scope.branch ? d.scope.branch_name : d.scope.full ? "All branches" : "All my branches"} · checked {new Date(h.checked_at).toLocaleTimeString()} · refreshes every minute</span>
        <span className="spacer" />
        <button onClick={() => setTick((t) => t + 1)} disabled={busy}><RefreshCw size={15} className={busy ? "spin" : ""} />Refresh</button>
      </div>
      <section className={`card attention ${alerts.length ? "has" : ""}`}>
        <h3 style={{ margin: 0 }}>{alerts.length ? <><AlertTriangle size={18} /> Needs attention ({alerts.length})</> : <><CheckCircle2 size={18} /> All clear</>}</h3>
        {alerts.length > 0 && <ul>{alerts.map((a, i) => <li key={i}>{a}</li>)}</ul>}
      </section>

      <h3>Today</h3>
      <div className="kpi-grid">
        {[["Sales today", `${o.sales_today.count} · ${money(o.sales_today.total)}`], ["Open tills", o.open_tills],
          ["Vault cash", money(o.vault_total)], ["Cash in transit", money(o.pending_handovers.total)],
          ["Awaiting payment", o.awaiting_payment], ["Low stock items", o.low_stock],
          ["Stock takes: counting / to verify", `${o.stock_takes_counting} / ${o.stock_takes_to_verify}`],
          ["Staff signed in today", o.users_signed_in_today], ["Wrong passwords (24 h)", o.failed_sign_ins_24h],
          ["Wrong supervisor PINs (24 h)", o.failed_pins_24h], ["Server errors (24 h)", o.server_errors_24h]]
          .map(([k, v]) => <div key={k as string} className="card kpi"><span className="muted">{k}</span><b>{v}</b></div>)}
      </div>

      <h3>Health</h3>
      <div className="health-grid">
        <Check ok={h.database.ok} title="Database" icon={<Database size={18} />}>
          {h.database.engine} · {h.database.latency_ms} ms · {bytes(h.database.size_bytes)}
          <br />{h.database.pending_migrations ? `${h.database.pending_migrations} update(s) pending` : "Up to date"}</Check>
        {h.broker && <Check ok={h.broker.ok} title="Background jobs" icon={<Activity size={18} />}>{h.broker.detail}</Check>}
        {h.disk && <Check ok={h.disk.ok} title="Disk" icon={<HardDrive size={18} />}>{bytes(h.disk.free_bytes)} free of {bytes(h.disk.total_bytes)}</Check>}
        {h.server && <Check ok={true} title="Server" icon={<Server size={18} />}>
          Up {dur(h.server.uptime_seconds)} · Python {h.server.python} · Django {h.server.django}
          <br />{h.server.debug ? "Development mode" : "Production mode"} · {h.server.time_zone} · Phones {h.server.phones_on ? "on" : "off"}</Check>}
        {h.security && <Check ok={!h.security.problems.length} title="Security" icon={<ShieldCheck size={18} />}>
          Admin site from: <code>{h.security.admin_networks}</code><br />Host names: <code>{h.security.allowed_hosts.join(", ")}</code></Check>}
      </div>

      <h3>Activity, last 14 days</h3>
      <div className="card"><StackedColumns data={d.events.per_day} cats={d.events.categories} /></div>

      <h3>Notable events</h3>
      <Events rows={d.events.notable} />

      <h3>Settings</h3>
      <Params p={p} />
    </div>
  );
}

function StackedColumns({ data, cats }: { data: any[]; cats: string[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const used = cats.filter((c) => data.some((d) => d[c]));
  const totals = data.map((d) => used.reduce((s, c) => s + d[c], 0));
  const max = Math.max(1, ...totals);
  const W = 640, H = 200, pad = 26, bw = (W - pad) / data.length;
  if (!used.length) return <p className="muted">No activity recorded yet.</p>;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H + 22}`} className="stacked" role="img"
           aria-label={`Events per day: ${data.map((d, i) => `${d.day} ${totals[i]}`).join(", ")}`}>
        {[0, 0.5, 1].map((f) => <g key={f}><line x1={pad} x2={W} y1={H - f * (H - 10)} y2={H - f * (H - 10)} className="gridline" />
          <text x={pad - 4} y={H - f * (H - 10) + 4} textAnchor="end" className="axis">{Math.round(max * f)}</text></g>)}
        {data.map((d, i) => {
          let y = H;
          return (
            <g key={d.day} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={pad + i * bw} y={0} width={bw} height={H} fill="transparent" />
              {used.map((c, j) => {
                const h = (d[c] / max) * (H - 10);
                y -= h;
                return h > 0 && <rect key={c} x={pad + i * bw + bw * 0.18} y={y} width={bw * 0.64} height={Math.max(0, h - 1)} rx={2}
                                      style={{ fill: `var(--series-${j + 1})`, opacity: hover === null || hover === i ? 1 : 0.45 }} />;
              })}
              {(i % 2 === data.length % 2 || data.length < 10) && <text x={pad + i * bw + bw / 2} y={H + 15} textAnchor="middle" className="axis">
                {new Date(d.day + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}</text>}
            </g>
          );
        })}
      </svg>
      <div className="legend">
        {used.map((c, j) => <span key={c}><i style={{ background: `var(--series-${j + 1})` }} />{c}
          {hover !== null && <b> {data[hover][c]}</b>}</span>)}
        {hover !== null && <span className="muted">{new Date(data[hover].day + "T00:00").toLocaleDateString()} · {totals[hover]} events</span>}
      </div>
    </div>
  );
}

function Events({ rows }: { rows: any[] }) {
  const list = useListState({ sort: "-at" });
  const cats = [...new Set(rows.map((r) => r.category))];
  const shown = useMemo(() => list.apply(rows, {
    text: (r) => `${label(r.action)} ${r.action} ${r.actor} ${r.branch} ${JSON.stringify(r.data)}`,
    filters: { category: (r, v) => r.category === v, severity: (r, v) => (v === "high" ? SEVERE.has(r.action) : true) },
    sorts: { at: (r) => r.at, action: (r) => label(r.action), actor: (r) => r.actor, branch: (r) => r.branch },
  }), [rows, list.state]);
  return (
    <div>
      <ListControls list={list} placeholder="Search events" count={shown.length} filters={[
        { key: "category", label: "Type", options: [["", "All types"], ...cats.map((c) => [c, c] as [string, string])] },
        { key: "severity", label: "Severity", options: [["", "All"], ["high", "Security & errors"]] }]}
        right={<a href="#/office/audit">Full audit log →</a>} />
      {!shown.length ? <p className="muted">No notable events.</p> : (
        <table className="grid-table">
          <thead><tr><SortHeader list={list} k="at">When</SortHeader><SortHeader list={list} k="action">Event</SortHeader>
            <SortHeader list={list} k="actor">Who</SortHeader><SortHeader list={list} k="branch">Branch</SortHeader><th>Details</th></tr></thead>
          <tbody>{shown.map((r) => (
            <tr key={r.id}><td>{new Date(r.at).toLocaleString()}</td>
              <td>{SEVERE.has(r.action) && <AlertTriangle size={14} className="error" style={{ verticalAlign: -2, marginRight: 4 }} />}{label(r.action)}</td>
              <td>{r.actor || r.data?.username || "—"}</td><td>{r.branch || "—"}</td>
              <td className="muted" style={{ fontSize: ".82rem", maxWidth: 360, overflowWrap: "anywhere" }}>
                {brief(r.data)}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

function Params({ p }: { p: any }) {
  const list = useListState({ sort: "name" });
  const rows = useMemo(() => list.apply(p.branches, {
    text: (b: any) => `${b.name} ${b.code} ${b.vault_holder || ""}`,
    sorts: { name: (b: any) => b.name, tills: (b: any) => b.tills, disc: (b: any) => Number(b.max_cashier_discount_pct) },
  }), [p, list.state]);
  const org = p.organization;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {org && <div className="card params">
        <div><span className="muted">Organization</span><b>{org.name}</b></div>
        <div><span className="muted">Currency</span><b>{org.currency}</b></div>
        <div><span className="muted">Time zone</span><b>{org.time_zone}</b></div>
        <div><span className="muted">Sign-in lasts</span><b>{org.sign_in_hours} h</b></div>
        <div><span className="muted">Active users / roles</span><b>{org.users} / {org.roles}</b></div>
        <div><span className="muted">Tax rates</span><b>{org.tax_rates.map((t: any) => `${t.name}${t.inclusive ? " (incl.)" : ""}`).join(", ") || "—"}</b></div>
        <div style={{ gridColumn: "1 / -1" }}><span className="muted">Payment methods</span>
          <b style={{ fontWeight: 400 }}>{org.payment_methods.map((m: any) => <span key={m.name} className="tag">{m.name}{m.offline ? " · offline" : ""}{m.qr ? " · QR" : ""}</span>)}</b></div>
      </div>}
      <ListControls list={list} placeholder="Search branches" />
      <table className="grid-table">
        <thead><tr><SortHeader list={list} k="name">Branch</SortHeader><SortHeader list={list} k="tills" num>Tills</SortHeader>
          <th>Vault holder</th><SortHeader list={list} k="disc" num>Cashier discount limit</SortHeader><th>Negative stock</th></tr></thead>
        <tbody>{rows.map((b: any) => (
          <tr key={b.id}><td><b>{b.name}</b> <span className="muted">{b.code}</span>{!b.active && <span className="tag">inactive</span>}</td>
            <td className="num">{b.tills}{b.tills_unassigned ? <span className="tag warn">{b.tills_unassigned} unassigned</span> : null}</td>
            <td>{b.vault_holder || <span className="tag warn">Nobody</span>}</td>
            <td className="num">{Number(b.max_cashier_discount_pct)}%</td><td>{b.allow_negative_stock ? "Allowed" : "Blocked"}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}
