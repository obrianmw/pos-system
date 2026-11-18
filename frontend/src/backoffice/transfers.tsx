// Stock transfers between branches: draft -> sent (stock leaves sender) -> received (stock arrives).
import { useEffect, useMemo, useState } from "react";
import { api, money } from "../api";
import type { Ctx } from "./BackOffice";
import { Err, Errors, toErrors, useOptions } from "./ui";

const STATUS: Record<string, string> = { draft: "Draft", sent: "In transit", received: "Received", cancelled: "Cancelled" };

function perms(ctx: Ctx, branchId: number, perm = "inventory.transfer") {
  return ctx.me.org_permissions.includes(perm) || !!ctx.me.branches.find((b) => b.id === branchId)?.permissions.includes(perm);
}

export function Transfers({ ctx }: { ctx: Ctx }) {
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [open, setOpen] = useState<any>(null);
  const [creating, setCreating] = useState(false);
  const canCreate = ctx.me.branches.some((b) => perms(ctx, b.id));

  useEffect(() => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    api(`/transfers/?${q}`, { branch: ctx.branch }).then((d) => setRows(d.results)).catch((e) => setError(e.message));
  }, [status, tick, ctx.branch]);

  const direction = (t: any) => !ctx.branch ? null : String(t.from_branch) === ctx.branch ? "Outgoing" : "Incoming";
  // What needs doing by me: receive things in transit to my branch, send my drafts.
  const todo = (t: any) => (t.status === "sent" && perms(ctx, t.to_branch)) ? "Receive" :
    (t.status === "draft" && perms(ctx, t.from_branch)) ? "Send" : "";

  return (
    <div>
      <div className="toolbar">
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span className="spacer" />
        {canCreate && <button className="primary" onClick={() => setCreating(true)}>+ New transfer</button>}
      </div>
      {error && <p className="error">{error}</p>}
      {rows && !rows.length && <p className="muted">No transfers yet.</p>}
      {!!rows?.length && (
        <table className="grid-table clickable">
          <thead><tr><th>Transfer</th><th>Created</th><th>From</th><th>To</th><th className="num">Items</th>
            <th>Status</th><th className="num">Value</th><th /></tr></thead>
          <tbody>{rows.map((t) => (
            <tr key={t.id} tabIndex={0} onClick={() => setOpen(t)} onKeyDown={(e) => e.key === "Enter" && setOpen(t)}>
              <td>{t.number}{direction(t) && <span className="tag">{direction(t)}</span>}</td>
              <td>{new Date(t.created_at).toLocaleDateString()}</td>
              <td>{t.from_branch_name}</td><td>{t.to_branch_name}</td>
              <td className="num">{t.lines.length}</td>
              <td><span className={`tag status-${t.status === "sent" ? "partial" : t.status}`}>{STATUS[t.status]}</span></td>
              <td className="num">{t.status === "draft" ? "–" : money(t.value)}</td>
              <td>{todo(t) && <span className="tag warn">⚠ {todo(t)}</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {open && <TransferDetail ctx={ctx} t={open} onClose={() => setOpen(null)}
                               onChanged={(t) => { setOpen(t); setTick((x) => x + 1); }} />}
      {creating && <NewTransfer ctx={ctx} onClose={() => setCreating(false)}
                                onSaved={(t) => { setCreating(false); setTick((x) => x + 1); setOpen(t); }} />}
    </div>
  );
}

function TransferDetail({ ctx, t, onClose, onChanged }: { ctx: Ctx; t: any; onClose: () => void; onChanged: (t: any) => void }) {
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const isSender = perms(ctx, t.from_branch);
  const isReceiver = perms(ctx, t.to_branch);

  async function act(what: "send" | "receive" | "cancel") {
    setBusy(true); setErrors({});
    try { onChanged(await api(`/transfers/${t.id}/${what}/`, { method: "POST", branch: null })); }
    catch (e) { setErrors(toErrors(e)); } finally { setBusy(false); }
  }

  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}><div className="card wide">
      <h3>{t.number} · {t.from_branch_name} → {t.to_branch_name}</h3>
      <p className="muted">{STATUS[t.status]} · created {new Date(t.created_at).toLocaleString()} by {t.created_by_name}
        {t.received_by_name && ` · received by ${t.received_by_name}`}</p>
      {t.note && <p className="note">{t.note}</p>}
      {Object.values(errors).map((m, i) => <p key={i} className="error">{m}</p>)}
      <table className="grid-table">
        <thead><tr><th>SKU</th><th>Item</th><th className="num">Quantity</th>{t.status !== "draft" && <><th className="num">Unit cost</th><th className="num">Value</th></>}</tr></thead>
        <tbody>{t.lines.map((l: any) => (
          <tr key={l.id}><td>{l.sku}</td><td>{l.product_name}</td><td className="num">{Number(l.quantity)}</td>
            {t.status !== "draft" && <><td className="num">{money(l.unit_cost)}</td><td className="num">{money(Number(l.quantity) * Number(l.unit_cost))}</td></>}</tr>
        ))}</tbody>
        {t.status !== "draft" && <tfoot><tr><th colSpan={4}>Total value</th><th className="num">{money(t.value)}</th></tr></tfoot>}
      </table>
      <p className="muted"><small>{{
        draft: "Nothing has moved yet. Sending takes the stock out of the sending branch.",
        sent: `The goods have left ${t.from_branch_name}. ${t.to_branch_name} adds them to its stock when it receives them.`,
        received: "Done: the stock is now at the receiving branch.",
        cancelled: "Cancelled before anything was sent.",
      }[t.status as string]}</small></p>
      <div className="actions">
        {t.status === "draft" && isSender && <button className="primary" disabled={busy} onClick={() => act("send")}>Send now</button>}
        {t.status === "sent" && isReceiver && <button className="primary" disabled={busy} onClick={() => act("receive")}>Receive all items</button>}
        {t.status === "sent" && !isReceiver && <span className="muted">Waiting for {t.to_branch_name} to receive.</span>}
        {t.status === "draft" && isSender && (confirmCancel
          ? <span className="inline"><button className="danger" disabled={busy} onClick={() => act("cancel")}>Confirm cancel</button>
              <button className="link" onClick={() => setConfirmCancel(false)}>Keep draft</button></span>
          : <button onClick={() => setConfirmCancel(true)}>Cancel draft</button>)}
        <button className="link" onClick={onClose}>Close</button>
      </div>
    </div></div>
  );
}

type Line = { product: any; quantity: string };

function NewTransfer({ ctx, onClose, onSaved }: { ctx: Ctx; onClose: () => void; onSaved: (t: any) => void }) {
  const senders = ctx.me.branches.filter((b) => perms(ctx, b.id));
  const [from, setFrom] = useState(ctx.branch && senders.some((b) => String(b.id) === ctx.branch) ? ctx.branch : String(senders[0]?.id ?? ""));
  const directory = useOptions<{ id: number; name: string }>("/branches/directory/");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [find, setFind] = useState("");
  const [stock, setStock] = useState<Record<number, number>>({});
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const products = useOptions("/products/?page_size=500&is_active=true&ordering=name");

  // On-hand at the sending branch, so people see what they can actually send.
  useEffect(() => {
    if (!from) return;
    api("/stock-levels/?page_size=500", { branch: from })
      .then((d) => setStock(Object.fromEntries(d.results.map((r: any) => [r.product, Number(r.quantity)]))))
      .catch(() => setStock({}));
  }, [from]);

  const matches = useMemo(() => {
    const q = find.trim().toLowerCase();
    if (!q) return [];
    return products.items.filter((p: any) => p.track_stock && !lines.some((l) => l.product.id === p.id) &&
      (p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || p.barcode === find.trim())).slice(0, 8);
  }, [find, products.items, lines]);
  const short = lines.filter((l) => Number(l.quantity) > (stock[l.product.id] ?? 0));

  function add(p: any) { setLines([...lines, { product: p, quantity: "1" }]); setFind(""); }

  async function save(sendNow: boolean) {
    setBusy(true); setErrors({});
    try {
      let t = await api("/transfers/", { branch: null, body: {
        from_branch: Number(from), to_branch: Number(to), note,
        lines: lines.map((l) => ({ product: l.product.id, quantity: l.quantity })) } });
      if (sendNow) {
        try { t = await api(`/transfers/${t.id}/send/`, { method: "POST", branch: null }); }
        catch (e) { setErrors({ detail: `Saved as draft ${t.number}, but not sent: ${Object.values(toErrors(e)).join(" ")}` }); setBusy(false); return; }
      }
      onSaved(t);
    } catch (e) { setErrors(toErrors(e)); } finally { setBusy(false); }
  }

  const ready = from && to && lines.length && lines.every((l) => Number(l.quantity) > 0);
  return (
    <div className="modal"><div className="card wide">
      <h3>New stock transfer</h3>
      {Object.entries(errors).filter(([k]) => k !== "to_branch").map(([k, m]) => <p key={k} className="error">{m}</p>)}
      <div className="form-grid">
        <label>From (sending)
          <select value={from} onChange={(e) => { setFrom(e.target.value); if (e.target.value === to) setTo(""); }}>
            {senders.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select></label>
        <label>To (receiving)
          <select value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">Choose…</option>
            {directory.items.filter((b) => String(b.id) !== from).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select><Err e={errors} k="to_branch" /></label>
        <label style={{ gridColumn: "1 / -1" }}>Note<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional, e.g. driver name or reason" /></label>
      </div>

      <h4>Items</h4>
      <div className="picker">
        <input placeholder="Add item: search name, SKU or scan barcode" value={find} onChange={(e) => setFind(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter" && matches[0]) { e.preventDefault(); add(matches[0]); } }} />
        {!!matches.length && (
          <ul className="picker-list">{matches.map((p: any) => (
            <li key={p.id}><button type="button" onClick={() => add(p)}>{p.name} <small className="muted">{p.sku} · in stock {stock[p.id] ?? 0}</small></button></li>
          ))}</ul>
        )}
      </div>
      {lines.length ? (
        <table className="grid-table">
          <thead><tr><th>Item</th><th className="num">In stock</th><th className="num">Send</th><th /></tr></thead>
          <tbody>{lines.map((l, i) => {
            const over = Number(l.quantity) > (stock[l.product.id] ?? 0);
            return (
              <tr key={l.product.id}>
                <td>{l.product.name}</td><td className="num">{stock[l.product.id] ?? 0}</td>
                <td className="num"><input className="narrow" inputMode="decimal" aria-label={`Quantity of ${l.product.name}`} value={l.quantity}
                  onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />
                  {over && <div><small className="error">⚠ more than in stock</small></div>}</td>
                <td><button className="link" aria-label={`Remove ${l.product.name}`} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button></td>
              </tr>
            );
          })}</tbody>
        </table>
      ) : <p className="muted">No items yet.</p>}

      <div className="actions">
        <button className="primary" disabled={busy || !ready || short.length > 0} onClick={() => save(true)}>Send now</button>
        <button disabled={busy || !ready} onClick={() => save(false)}>Save as draft</button>
        <button className="link" onClick={onClose}>Cancel</button>
      </div>
      <p className="muted"><small>Send now takes the stock out of {senders.find((b) => String(b.id) === from)?.name || "the sending branch"} immediately.
        A draft moves nothing until someone sends it.</small></p>
    </div></div>
  );
}
