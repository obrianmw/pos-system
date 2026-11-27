// Messages & announcements: inbox, sent (with read receipts), groups, compose with audience picker.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, Archive, ArchiveRestore, Building2, Check, CheckCheck, Inbox, Megaphone, PenSquare, Reply, Send,
  Shield, Trash2, Users, UsersRound, X,
} from "lucide-react";
import { api } from "../api";
import type { Ctx } from "./BackOffice";
import { SortHeader, useListState } from "./listing";
import { errorText, initials, toast } from "./ui";
import { confirmDialog } from "../Dialog";

export type Summary = { unread: number; can_send: boolean; can_broadcast: boolean; pinned: any[]; reload: () => void };

const CHANGED = "inbox:changed";
export const inboxChanged = () => window.dispatchEvent(new Event(CHANGED));

/** Unread count + urgent/ack-needed messages, refreshed every 30 s and whenever the inbox changes. */
export function useInboxSummary(): Summary {
  const [s, setS] = useState({ unread: 0, can_send: false, can_broadcast: false, pinned: [] as any[] });
  const load = () => api("/comms/inbox/summary/", { branch: null }).then(setS).catch(() => {});
  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    window.addEventListener(CHANGED, load);
    return () => { clearInterval(id); window.removeEventListener(CHANGED, load); };
  }, []);
  return { ...s, reload: load };
}

/** Thin strip above the page for urgent or must-acknowledge messages. */
export function PinnedBanner({ summary, onOpen }: { summary: Summary; onOpen: () => void }) {
  const m = summary.pinned[0];
  if (!m) return null;
  return (
    <div className={`banner ${m.priority === "urgent" ? "" : "important"}`} role="alert">
      <AlertTriangle size={18} aria-hidden />
      <b>{m.priority === "urgent" ? "Urgent" : "Please read"}</b>
      <span className="text">{m.subject} — {m.sender_name}</span>
      {summary.pinned.length > 1 && <span className="muted">+{summary.pinned.length - 1} more</span>}
      <button onClick={onOpen}>Open</button>
    </div>
  );
}

const ago = (iso: string) => {
  const d = new Date(iso), s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

function Prio({ p }: { p: string }) {
  if (p === "normal") return null;
  return <span className={`prio ${p}`}>{p === "urgent" ? <AlertTriangle size={12} /> : null}{p === "urgent" ? "Urgent" : "Important"}</span>;
}

// ================================================================================================
export function Messages({ ctx }: { ctx: Ctx }) {
  const [tab, setTab] = useState<"inbox" | "sent" | "archived" | "groups">("inbox");
  const [composing, setComposing] = useState(false);
  const [canSend, setCanSend] = useState(false);
  useEffect(() => { api("/comms/inbox/summary/", { branch: null }).then((s) => setCanSend(s.can_send)).catch(() => {}); }, []);

  return (
    <div>
      <div className="toolbar">
        <div className="tabs" role="tablist">
          {([["inbox", "Inbox", <Inbox size={15} />], ["sent", "Sent", <Send size={15} />], ["archived", "Archived", <Archive size={15} />],
            ...(canSend ? [["groups", "Groups", <UsersRound size={15} />]] : [])] as [typeof tab, string, JSX.Element][]).map(([k, l, ic]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{ic}{l}</button>
          ))}
        </div>
        <span className="spacer" />
        {canSend && <button className="primary" onClick={() => setComposing(true)}><PenSquare size={16} />New message</button>}
      </div>
      {(tab === "inbox" || tab === "archived") && <InboxView archived={tab === "archived"} />}
      {tab === "sent" && <SentView />}
      {tab === "groups" && <GroupsView ctx={ctx} />}
      {composing && <Compose onClose={() => setComposing(false)} onSent={() => { setComposing(false); setTab("sent"); }} />}
    </div>
  );
}

// ---- inbox --------------------------------------------------------------------------------------
export function InboxView({ archived = false, compact = false }: { archived?: boolean; compact?: boolean }) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [filter, setFilter] = useState<"all" | "unread" | "announcement">("all");
  const [open, setOpen] = useState<any>(null);
  const [tick, setTick] = useState(0);
  const sorter = useListState({ sort: "-when" });
  const PR: Record<string, number> = { urgent: 0, important: 1, normal: 2 };
  const shown = rows && sorter.apply(rows, {
    text: (r: any) => `${r.subject} ${r.sender_name} ${r.body}`,
    sorts: { when: (r: any) => r.sent_at, priority: (r: any) => PR[r.priority] ?? 3, sender: (r: any) => r.sender_name, subject: (r: any) => r.subject } });

  useEffect(() => {
    const q = new URLSearchParams({ folder: archived ? "archived" : "inbox", page_size: "100" });
    if (filter === "unread") q.set("unread", "1");
    if (filter === "announcement") q.set("kind", "announcement");
    api(`/comms/inbox/?${q}`, { branch: null }).then((d) => setRows(d.results)).catch(() => setRows([]));
  }, [archived, filter, tick]);

  async function select(r: any) {
    setOpen(r);
    if (!r.read_at) {
      const u = await api(`/comms/inbox/${r.id}/read/`, { method: "POST", branch: null }).catch(() => null);
      if (u) { setRows((rs) => rs?.map((x) => (x.id === u.id ? u : x)) ?? null); setOpen(u); inboxChanged(); }
    }
  }
  function updated(u: any, remove = false) {
    setRows((rs) => (remove ? rs?.filter((x) => x.id !== u.id) : rs?.map((x) => (x.id === u.id ? u : x))) ?? null);
    setOpen(remove ? null : u);
    inboxChanged();
  }
  async function readAll() {
    await api("/comms/inbox/read_all/", { method: "POST", branch: null });
    setTick((t) => t + 1); inboxChanged();
  }

  return (
    <div className="mail" style={compact ? { gridTemplateColumns: "1fr" } : undefined}>
      {(!compact || !open) && (
        <div>
          <div className="toolbar" style={{ marginBottom: 8 }}>
            <div className="seg" role="group" aria-label="Show">
              {([["all", "All"], ["unread", "Unread"], ["announcement", "Announcements"]] as const).map(([k, l]) => (
                <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>
              ))}
            </div>
            {!archived && <button className="link" onClick={readAll}><CheckCheck size={15} />Mark all read</button>}
          </div>
          <div className="toolbar" style={{ marginBottom: 8 }}>
            <input type="search" placeholder="Search messages" aria-label="Search messages" value={sorter.typed}
                   onChange={(e) => sorter.setTyped(e.target.value)} style={{ flex: 1, minWidth: 140 }} />
            <select aria-label="Sort messages" value={sorter.state.sort} onChange={(e) => sorter.setSort(e.target.value)}>
              <option value="-when">Newest first</option><option value="when">Oldest first</option>
              <option value="priority">Urgent first</option><option value="sender">By sender</option><option value="subject">By subject</option>
            </select>
          </div>
          <div className="mail-list">
            {rows === null && <div className="skeleton" style={{ height: 180, margin: 12 }} />}
            {rows?.length === 0 && <p className="muted" style={{ padding: 16 }}>{archived ? "Nothing archived." : "No messages. You’re all caught up."}</p>}
            {rows && rows.length > 0 && shown?.length === 0 && <p className="muted" style={{ padding: 16 }}>No messages match.</p>}
            {shown?.map((r) => (
              <button key={r.id} className={`mail-item ${r.read_at ? "" : "unread"} ${open?.id === r.id ? "active" : ""}`} onClick={() => select(r)}>
                <span className={`m-dot ${r.read_at ? "read" : ""}`} aria-label={r.read_at ? "" : "Unread"} />
                <span className="m-subject">{r.kind === "announcement" && <Megaphone size={13} style={{ marginRight: 5, verticalAlign: -2 }} />}{r.subject}</span>
                <time dateTime={r.sent_at}>{ago(r.sent_at)}</time>
                <span className="m-meta">{r.sender_name} · {r.body.slice(0, 80)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      {open ? <MessageView r={open} onChange={updated} onBack={compact ? () => setOpen(null) : undefined} />
        : !compact && <div className="mail-view muted" style={{ display: "grid", placeItems: "center" }}><span><Inbox size={28} /><br />Choose a message to read it.</span></div>}
    </div>
  );
}

function MessageView({ r, onChange, onBack }: { r: any; onChange: (u: any, remove?: boolean) => void; onBack?: () => void }) {
  const [replying, setReplying] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setReplying(false); setText(""); }, [r.id]);

  async function ack() {
    try { onChange(await api(`/comms/inbox/${r.id}/ack/`, { method: "POST", branch: null })); toast("Thanks — marked as read and understood.", "success"); }
    catch (e) { toast(errorText(e), "error"); }
  }
  async function archive() {
    try { onChange(await api(`/comms/inbox/${r.id}/archive/`, { body: { archived: !r.archived }, branch: null }), true); }
    catch (e) { toast(errorText(e), "error"); }
  }
  async function reply() {
    setBusy(true);
    try {
      await api("/comms/compose/", { body: { parent: r.message_id, body: text }, branch: null });
      toast(`Reply sent to ${r.sender_name}.`, "success"); setReplying(false); setText("");
    } catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
  }

  return (
    <article className="mail-view" aria-live="polite">
      {onBack && <button className="link" onClick={onBack}>← Back</button>}
      <div className="inline" style={{ gap: 8, flexWrap: "wrap" }}>
        {r.kind === "announcement" && <span className="tag"><Megaphone size={12} />Announcement</span>}
        <Prio p={r.priority} />
      </div>
      <h2>{r.subject}</h2>
      <div className="inline" style={{ gap: 10 }}>
        <span className="avatar">{initials(r.sender_name)}</span>
        <div><b>{r.sender_name}</b><div className="muted" style={{ fontSize: ".82rem" }}>To: {r.audience_label} · {new Date(r.sent_at).toLocaleString()}</div></div>
      </div>
      <div className="mail-body">{r.body}</div>
      {r.requires_ack && (r.acknowledged_at
        ? <p className="ok"><Check size={15} style={{ verticalAlign: -3 }} /> You confirmed this on {new Date(r.acknowledged_at).toLocaleString()}.</p>
        : <div className="warn-box">The sender asked everyone to confirm they have read this.
            <div className="actions"><button className="primary" onClick={ack}><Check size={16} />Got it</button></div></div>)}
      <div className="actions">
        <button onClick={() => setReplying(!replying)}><Reply size={16} />Reply</button>
        <button className="ghost" onClick={archive}>{r.archived ? <><ArchiveRestore size={16} />Move to inbox</> : <><Archive size={16} />Archive</>}</button>
      </div>
      {replying && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
          <label>Reply to {r.sender_name} only
            <textarea value={text} onChange={(e) => setText(e.target.value)} autoFocus placeholder="Write your reply…" /></label>
          <div className="actions"><button className="primary" disabled={busy || !text.trim()} onClick={reply}><Send size={16} />Send reply</button>
            <button className="link" onClick={() => setReplying(false)}>Cancel</button></div>
        </div>
      )}
    </article>
  );
}

// ---- sent ---------------------------------------------------------------------------------------
function SentView() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [open, setOpen] = useState<any>(null);
  const [who, setWho] = useState<any[] | null>(null);
  useEffect(() => { api("/comms/sent/?page_size=100", { branch: null }).then((d) => setRows(d.results)).catch(() => setRows([])); }, []);
  const sorter = useListState({ sort: "-when" });
  const done = (m: any) => (m.recipient_count ? (m.requires_ack ? m.ack_count : m.read_count) / m.recipient_count : 1);
  const shown = rows && sorter.apply(rows, {
    text: (m: any) => `${m.subject} ${m.audience_label} ${m.body}`,
    filters: { kind: (m: any, v) => m.kind === v, state: (m: any, v) => (v === "open" ? done(m) < 1 : done(m) >= 1) },
    sorts: { when: (m: any) => m.created_at, read: (m: any) => done(m), subject: (m: any) => m.subject } });
  useEffect(() => { setWho(null); if (open) api(`/comms/sent/${open.id}/recipients/`, { branch: null }).then(setWho).catch(() => setWho([])); }, [open?.id]);

  return (
    <div className="mail">
      <div>
      <div className="toolbar" style={{ marginBottom: 8 }}>
        <input type="search" placeholder="Search sent" aria-label="Search sent messages" value={sorter.typed}
               onChange={(e) => sorter.setTyped(e.target.value)} style={{ flex: 1, minWidth: 140 }} />
        <select aria-label="Type" value={sorter.state.filters.kind || ""} onChange={(e) => sorter.setFilter("kind", e.target.value)}>
          <option value="">Messages & announcements</option><option value="message">Messages</option><option value="announcement">Announcements</option></select>
        <select aria-label="Reading" value={sorter.state.filters.state || ""} onChange={(e) => sorter.setFilter("state", e.target.value)}>
          <option value="">Any</option><option value="open">Not everyone has read</option><option value="done">Read by everyone</option></select>
        <select aria-label="Sort sent messages" value={sorter.state.sort} onChange={(e) => sorter.setSort(e.target.value)}>
          <option value="-when">Newest first</option><option value="when">Oldest first</option><option value="read">Least read first</option>
          <option value="subject">By subject</option></select>
      </div>
      <div className="mail-list">
        {rows === null && <div className="skeleton" style={{ height: 180, margin: 12 }} />}
        {rows?.length === 0 && <p className="muted" style={{ padding: 16 }}>You haven’t sent anything yet.</p>}
        {rows && rows.length > 0 && shown?.length === 0 && <p className="muted" style={{ padding: 16 }}>No sent messages match.</p>}
        {shown?.map((m) => {
          const pct = m.recipient_count ? Math.round(((m.requires_ack ? m.ack_count : m.read_count) / m.recipient_count) * 100) : 0;
          return (
            <button key={m.id} className={`mail-item ${open?.id === m.id ? "active" : ""}`} onClick={() => setOpen(m)}>
              <span className="m-dot read" />
              <span className="m-subject">{m.kind === "announcement" && <Megaphone size={13} style={{ marginRight: 5, verticalAlign: -2 }} />}{m.subject}</span>
              <time dateTime={m.created_at}>{ago(m.created_at)}</time>
              <span className="m-meta">To {m.audience_label} · {m.requires_ack ? `${m.ack_count}/${m.recipient_count} confirmed` : `${m.read_count}/${m.recipient_count} read`}
                <span className="progress" style={{ marginTop: 6 }}><div style={{ width: `${pct}%` }} /></span></span>
            </button>
          );
        })}
      </div>
      </div>
      {open ? (
        <article className="mail-view">
          <div className="inline" style={{ gap: 8 }}><Prio p={open.priority} />{open.kind === "announcement" && <span className="tag"><Megaphone size={12} />Announcement</span>}</div>
          <h2>{open.subject}</h2>
          <div className="muted" style={{ fontSize: ".85rem" }}>To {open.audience_label} · {new Date(open.created_at).toLocaleString()}</div>
          <div className="mail-body">{open.body}</div>
          <h4>Delivery · {open.read_count} of {open.recipient_count} read{open.requires_ack && ` · ${open.ack_count} confirmed`}</h4>
          {who === null ? <div className="skeleton" style={{ height: 80 }} /> : (
            <table className="grid-table">
              <thead><tr><th>Person</th><th>Read</th>{open.requires_ack && <th>Confirmed</th>}</tr></thead>
              <tbody>{who.map((w) => (
                <tr key={w.username}><td>{w.name}</td>
                  <td>{w.read_at ? <span className="ok"><Check size={14} style={{ verticalAlign: -2 }} /> {ago(w.read_at)}</span> : <span className="muted">Not yet</span>}</td>
                  {open.requires_ack && <td>{w.acknowledged_at ? <span className="ok"><CheckCheck size={14} style={{ verticalAlign: -2 }} /> {ago(w.acknowledged_at)}</span> : <span className="muted">—</span>}</td>}
                </tr>
              ))}</tbody>
            </table>
          )}
        </article>
      ) : <div className="mail-view muted" style={{ display: "grid", placeItems: "center" }}>Choose a sent message to see who has read it.</div>}
    </div>
  );
}

// ---- audience picker ----------------------------------------------------------------------------
type Target = { type: "users" | "departments" | "groups" | "branches" | "roles"; id: number; label: string; sub?: string };
const TYPE_ICON = { users: <Users size={13} />, departments: <Building2 size={13} />, groups: <UsersRound size={13} />,
  branches: <Building2 size={13} />, roles: <Shield size={13} /> };
const TYPE_NAME = { users: "Person", departments: "Department", groups: "Group", branches: "Whole branch", roles: "Role" };

function useDirectory() {
  const [d, setD] = useState<any>(null);
  useEffect(() => { api("/comms/directory/", { branch: null }).then(setD).catch(() => setD(false)); }, []);
  return d;
}

function AudiencePicker({ dir, value, onChange, everyone, setEveryone }: {
  dir: any; value: Target[]; onChange: (t: Target[]) => void; everyone: boolean; setEveryone: (b: boolean) => void;
}) {
  const [q, setQ] = useState("");
  const [focus, setFocus] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const all: Target[] = useMemo(() => !dir ? [] : [
    ...dir.people.map((p: any) => ({ type: "users", id: p.id, label: p.name,
      sub: [p.department, ...p.roles.map((r: any) => `${r.role} · ${r.branch}`)].filter(Boolean).join(" · ") })),
    ...dir.departments.map((x: any) => ({ type: "departments", id: x.id, label: x.name })),
    ...dir.groups.map((x: any) => ({ type: "groups", id: x.id, label: x.name, sub: `${x.size} members` })),
    ...dir.branches.map((x: any) => ({ type: "branches", id: x.id, label: x.name, sub: "everyone at this branch" })),
    ...dir.roles.map((x: any) => ({ type: "roles", id: x.id, label: `All ${x.name}s` })),
  ], [dir]);
  const chosen = new Set(value.map((v) => `${v.type}:${v.id}`));
  const term = q.trim().toLowerCase();
  const matches = term ? all.filter((t) => !chosen.has(`${t.type}:${t.id}`) &&
    (t.label.toLowerCase().includes(term) || (t.sub || "").toLowerCase().includes(term))).slice(0, 10) : [];

  function add(t: Target) { onChange([...value, t]); setQ(""); setFocus(0); inputRef.current?.focus(); }
  function key(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setFocus((f) => Math.min(f + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setFocus((f) => Math.max(f - 1, 0)); }
    else if (e.key === "Enter" && matches[focus]) { e.preventDefault(); add(matches[focus]); }
    else if (e.key === "Backspace" && !q && value.length) onChange(value.slice(0, -1));
  }

  return (
    <div>
      {dir?.can_broadcast && (
        <label className="check" style={{ marginBottom: 8 }}>
          <input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} />
          <Megaphone size={15} /> Everyone — all staff in all branches
        </label>
      )}
      {!everyone && (
        <div className="picker">
          <div className="chips" onClick={() => inputRef.current?.focus()}>
            {value.map((t) => (
              <span key={`${t.type}:${t.id}`} className="chip" title={TYPE_NAME[t.type]}>
                {TYPE_ICON[t.type]}{t.label}
                <button aria-label={`Remove ${t.label}`} onClick={() => onChange(value.filter((v) => v !== t))}><X size={13} /></button>
              </span>
            ))}
            <input ref={inputRef} value={q} onChange={(e) => { setQ(e.target.value); setFocus(0); }} onKeyDown={key}
                   placeholder={value.length ? "Add more…" : "Type a name, department, group, branch or role"}
                   aria-label="Add recipients" role="combobox" aria-expanded={matches.length > 0} />
          </div>
          {matches.length > 0 && (
            <ul className="picker-list" role="listbox">
              {matches.map((t, i) => (
                <li key={`${t.type}:${t.id}`} role="option" aria-selected={i === focus}>
                  <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => add(t)}
                          style={i === focus ? { background: "var(--card-2)" } : undefined}>
                    <span className="tag">{TYPE_ICON[t.type]}{TYPE_NAME[t.type]}</span>
                    <span>{t.label}{t.sub && <small className="muted"> · {t.sub}</small>}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {dir && !term && !value.length && (
            <div className="inline" style={{ flexWrap: "wrap", marginTop: 8, gap: 6 }}>
              <span className="muted" style={{ fontSize: ".8rem" }}>Quick picks:</span>
              {all.filter((t) => t.type !== "users").slice(0, 6).map((t) => (
                <button key={`${t.type}:${t.id}`} type="button" className="ghost" style={{ padding: "3px 8px", fontSize: ".8rem" }} onClick={() => add(t)}>
                  {TYPE_ICON[t.type]}{t.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function audienceOf(targets: Target[], everyone: boolean) {
  if (everyone) return { everyone: true };
  const a: Record<string, number[]> = {};
  for (const t of targets) (a[t.type] ||= []).push(t.id);
  return a;
}

function Compose({ onClose, onSent }: { onClose: () => void; onSent: () => void }) {
  const dir = useDirectory();
  const [targets, setTargets] = useState<Target[]>([]);
  const [everyone, setEveryone] = useState(false);
  const [kind, setKind] = useState<"message" | "announcement">("message");
  const [priority, setPriority] = useState<"normal" | "important" | "urgent">("normal");
  const [ack, setAck] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState<{ count: number; skipped: number; error?: string } | null>(null);
  const [busy, setBusy] = useState(false);

  // Live "this will reach N people" while the audience is being built.
  useEffect(() => {
    if (!everyone && !targets.length) { setPreview(null); return; }
    const t = setTimeout(() => {
      api("/comms/preview/", { body: { audience: audienceOf(targets, everyone) }, branch: null }).then(setPreview).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [targets, everyone]);

  async function send() {
    setBusy(true);
    try {
      const r = await api("/comms/compose/", { branch: null, body: {
        subject, body, kind, priority, requires_ack: ack, audience: audienceOf(targets, everyone) } });
      toast(`Sent to ${r.recipient_count} ${r.recipient_count === 1 ? "person" : "people"}${r.skipped ? ` (${r.skipped} outside your branches left out)` : ""}.`, "success");
      onSent();
    } catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
  }

  const ready = (everyone || targets.length) && subject.trim() && body.trim() && preview && preview.count > 0;
  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card wide" role="dialog" aria-label="New message">
        <div className="card-head"><h3>New {kind}</h3>
          <button className="ghost icon" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
        {dir === false && <p className="error">Your role cannot send messages.</p>}
        <div className="inline" style={{ gap: 12, flexWrap: "wrap" }}>
          <div className="seg" role="group" aria-label="Type">
            <button className={kind === "message" ? "on" : ""} onClick={() => setKind("message")}><Send size={14} />Message</button>
            <button className={kind === "announcement" ? "on" : ""} onClick={() => setKind("announcement")}><Megaphone size={14} />Announcement</button>
          </div>
          <div className="seg" role="group" aria-label="Priority">
            {(["normal", "important", "urgent"] as const).map((p) => (
              <button key={p} className={priority === p ? "on" : ""} onClick={() => setPriority(p)}>{p[0].toUpperCase() + p.slice(1)}</button>
            ))}
          </div>
          <label className="check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> Ask people to confirm they read it</label>
        </div>
        <label>To</label>
        {dir === null ? <div className="skeleton" style={{ height: 42 }} /> : dir && (
          <AudiencePicker dir={dir} value={targets} onChange={setTargets} everyone={everyone} setEveryone={setEveryone} />
        )}
        {preview && (
          <div className="audience-count" aria-live="polite">
            <Users size={16} />
            {preview.error ? <span className="error">{preview.error}</span>
              : <span>Will reach <b>{preview.count}</b> {preview.count === 1 ? "person" : "people"}
                  {preview.skipped > 0 && <span className="muted"> · {preview.skipped} outside your branches will be left out</span>}</span>}
          </div>
        )}
        <label>Subject<input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={160} placeholder="e.g. Stock count this Saturday" /></label>
        <label>Message<textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write your message…" rows={7} /></label>
        {priority === "urgent" && <p className="muted" style={{ margin: 0, fontSize: ".82rem" }}>Urgent messages show as a red banner on every screen, including the tills, until read.</p>}
        <div className="actions">
          <button className="primary" disabled={busy || !ready} onClick={send}><Send size={16} />Send{preview?.count ? ` to ${preview.count}` : ""}</button>
          <button className="link" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

// ---- groups -------------------------------------------------------------------------------------
function GroupsView({ ctx }: { ctx: Ctx }) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [editing, setEditing] = useState<any | "new" | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => { api("/comms/groups/?page_size=200", { branch: null }).then((d) => setRows(d.results)).catch(() => setRows([])); }, [tick]);
  const sorter = useListState({ sort: "name" });
  const shown = rows && sorter.apply(rows, {
    text: (g: any) => `${g.name} ${g.description} ${g.member_names.join(" ")} ${g.created_by_name}`,
    sorts: { name: (g: any) => g.name, members: (g: any) => g.member_names.length, by: (g: any) => g.created_by_name } });
  return (
    <div>
      <div className="toolbar"><span className="muted">Groups are saved lists of people you message together, e.g. “Weekend shift”.</span>
        <input type="search" placeholder="Search groups or members" aria-label="Search groups" value={sorter.typed} onChange={(e) => sorter.setTyped(e.target.value)} />
        <span className="spacer" /><button className="primary" onClick={() => setEditing("new")}><UsersRound size={16} />New group</button></div>
      {rows?.length === 0 && <p className="muted">No groups yet.</p>}
      {!!rows?.length && (
        <table className="grid-table clickable">
          <thead><tr><SortHeader list={sorter} k="name">Group</SortHeader><SortHeader list={sorter} k="members">Members</SortHeader>
            <SortHeader list={sorter} k="by">Made by</SortHeader></tr></thead>
          <tbody>{(shown || []).map((g) => (
            <tr key={g.id} tabIndex={0} onClick={() => setEditing(g)} onKeyDown={(e) => e.key === "Enter" && setEditing(g)}>
              <td><b>{g.name}</b>{g.description && <div className="muted" style={{ fontSize: ".82rem" }}>{g.description}</div>}</td>
              <td>{g.member_names.slice(0, 4).join(", ")}{g.member_names.length > 4 && ` +${g.member_names.length - 4}`}</td>
              <td>{g.created_by_name}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {editing && <GroupForm group={editing === "new" ? null : editing} me={ctx.me.id}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setTick((t) => t + 1); }} />}
    </div>
  );
}

function GroupForm({ group, onClose, onSaved }: { group: any | null; me: number; onClose: () => void; onSaved: () => void }) {
  const dir = useDirectory();
  const [name, setName] = useState(group?.name ?? "");
  const [description, setDescription] = useState(group?.description ?? "");
  const [members, setMembers] = useState<Target[]>([]);
  useEffect(() => {
    if (!dir || !group) return;
    setMembers(group.members.map((id: number) => {
      const p = dir.people.find((x: any) => x.id === id);
      return { type: "users", id, label: p ? p.name : `User #${id}` } as Target;
    }));
  }, [dir]);
  const peopleOnly = dir ? { ...dir, departments: [], groups: [], branches: [], roles: [], can_broadcast: false } : dir;

  async function save() {
    try {
      await api(group ? `/comms/groups/${group.id}/` : "/comms/groups/", { method: group ? "PATCH" : "POST", branch: null,
        body: { name, description, members: members.map((m) => m.id) } });
      toast(group ? "Group updated." : "Group created.", "success"); onSaved();
    } catch (e) { toast(errorText(e), "error"); }
  }
  async function remove() {
    if (!(await confirmDialog({ title: `Delete the group "${group.name}"?`, danger: true,
      message: "Messages already sent are not affected." }))) return;
    try { await api(`/comms/groups/${group.id}/`, { method: "DELETE", branch: null }); toast("Group deleted.", "success"); onSaved(); }
    catch (e) { toast(errorText(e), "error"); }
  }

  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card wide">
        <h3>{group ? `Edit ${group.name}` : "New group"}</h3>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Weekend shift" /></label>
        <label>Description<input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="optional" /></label>
        <label>Members</label>
        {peopleOnly ? <AudiencePicker dir={peopleOnly} value={members} onChange={setMembers} everyone={false} setEveryone={() => {}} />
          : <div className="skeleton" style={{ height: 42 }} />}
        <div className="actions">
          <button className="primary" disabled={!name.trim()} onClick={save}>{group ? "Save" : "Create group"}</button>
          {group && <button className="ghost" onClick={remove}><Trash2 size={16} />Delete</button>}
          <button className="link" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
