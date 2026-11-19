import { useEffect, useState } from "react";
import { api, auth, login, OfflineError } from "./api";
import { applyTheme, setTheme, storedTheme, Theme, ThemeSwitch } from "./theme";
import { loadBranding } from "./brand";
import { BrandMark, useBrandingState } from "./BrandMark";
import POS from "./POS";
import BackOffice, { hasBackOffice } from "./backoffice/BackOffice";
import { StockCountPhone } from "./stocktake";
import { SystemTabs } from "./SystemTabs";

export type Me = {
  organization_name?: string;
  ui_theme?: Theme;
  id: number; username: string; name: string;
  branches: { id: number; name: string; code: string; permissions: string[]; currency: string }[];
  org_permissions: string[];
  /** Set for organization admins: where the database admin site answers. */
  admin_site?: { port: number; path: string } | null;
};
export type Session = { id: number; till: number; till_name: string; opening_float: string; branch: number };

// Cached so a till that loses its connection after login keeps working.
const cache = {
  get<T>(k: string): T | null { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } },
  set(k: string, v: unknown) { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, JSON.stringify(v)); },
};

export default function App() {
  const [me, setMe] = useState<Me | null>(cache.get("pos.me"));
  const [branchId, setBranchId] = useState<string | null>(auth.branch);
  const [session, setSession] = useState<Session | null>(cache.get("pos.session"));
  const [error, setError] = useState("");
  const [route, setRoute] = useState(location.hash);

  useEffect(() => {
    const on = () => setRoute(location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  useEffect(() => {
    if (!auth.token) return;
    api<Me>("/me/").then((m) => { setMe(m); cache.set("pos.me", m); })
      .catch((e) => { if (!(e instanceof OfflineError)) logout(); });
  }, []);

  // Branding (name, logo, colours, document settings) - public part before sign-in, all of it after.
  useEffect(() => { loadBranding(!!me); }, [!!me]);
  // The theme saved on the account follows the user to this device.
  // If the account never chose one, the choice made on this device (e.g. on the login screen) is kept
  // and saved to the account.
  useEffect(() => {
    if (!me?.ui_theme) return;
    if (me.ui_theme === "system" && storedTheme() !== "system") setTheme(storedTheme());
    else applyTheme(me.ui_theme);
  }, [me?.ui_theme]);

  // One sign-in for everyone: go straight to the right branch. The last branch used on this device wins
  // if it still fits the person's roles; otherwise the first branch where they can sell, else their first.
  useEffect(() => {
    if (!me) return;
    const has = (id: string | null) => !!id && me.branches.some((b) => String(b.id) === id);
    const sells = (id: string | null) => !!me.branches.find((b) => String(b.id) === id)?.permissions.includes("pos.sell");
    const anySeller = me.branches.find((b) => b.permissions.includes("pos.sell"));
    if (has(branchId) && (sells(branchId) || !anySeller)) return;
    const last = cache.get<string>("pos.lastBranch");
    const pick = has(last) && (sells(last) || !anySeller) ? last : String((anySeller || me.branches[0])?.id ?? "");
    if (pick) chooseBranch(pick);
  }, [me]);

  useEffect(() => {
    if (!me || !branchId) return;
    api<Session | null>("/till-sessions/current/")
      .then((s) => { setSession(s); cache.set("pos.session", s); })
      .catch(() => {});
  }, [me, branchId]);

  function chooseBranch(id: string) { auth.branch = id; setBranchId(id); cache.set("pos.lastBranch", id); }
  function logout() {
    auth.token = null; auth.branch = null; cache.set("pos.me", null); cache.set("pos.session", null);
    setMe(null); setBranchId(null); setSession(null);
  }

  if (!me) return <Login onDone={(m) => { setMe(m); cache.set("pos.me", m); }} error={error} setError={setError} />;

  // Routing: #/office/... is the back office, anything else the till. People who can't sell go
  // straight to the back office; supervisors and admins can switch between the two.
  const sells = me.branches.some((b) => b.permissions.includes("pos.sell"));
  // #/count: the phone screen for stock counters/verifiers (and quick stock look-ups).
  if (route.startsWith("#/count")) {
    return <StockCountPhone me={me} onLogout={logout} onBack={() => (location.hash = sells && !hasBackOffice(me) ? "#/pos" : "#/office/dashboard")} />;
  }
  const office = hasBackOffice(me);
  const orgLevel = me.org_permissions.length > 0;
  if (office && (route.startsWith("#/office") || !sells || (orgLevel && !route.startsWith("#/pos")))) {
    return <BackOffice me={me} onLogout={logout} onPos={sells ? () => (location.hash = "#/pos") : undefined} />;
  }
  const branch = me.branches.find((b) => String(b.id) === branchId);
  if (!branch || !branch.permissions.includes("pos.sell")) {
    if (sells) return <div className="center"><p className="muted">Opening your branch…</p></div>; // picked in a moment
    // Signed in, but nothing this person can open here: no till rights and no back office.
    return (
      <div className="center card">
        <h2>Hello {me.name}</h2>
        <p>{me.branches.length ? "Your account doesn't have till or back-office access yet." : "You aren't assigned to a branch yet."} Ask your
          administrator to give you a role.</p>
        <button className="link" onClick={logout}>Log out</button>
      </div>
    );
  }
  const sellBranches = me.branches.filter((b) => b.permissions.includes("pos.sell"));
  if (!session) return <OpenTill key={branchId} me={me} branchId={branchId!} branches={sellBranches} onSwitch={chooseBranch}
                                 onOffice={office ? () => (location.hash = "#/office/dashboard") : undefined} onOpen={(s) => { setSession(s); cache.set("pos.session", s); }} onLogout={logout} />;
  return <POS me={me} branch={branch} session={session} onLogout={logout}
              onOffice={office ? () => (location.hash = "#/office/dashboard") : undefined}
              onClosed={() => { setSession(null); cache.set("pos.session", null); }} />;
}

function Login({ onDone, error, setError }: { onDone: (m: Me) => void; error: string; setError: (s: string) => void }) {
  const brand = useBrandingState();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { await login(u, p); onDone(await api<Me>("/me/")); }
    catch (err: any) { setError(err instanceof OfflineError ? "Cannot reach the server." : "Wrong username or password."); }
    finally { setBusy(false); }
  }
  return (
    <form className="card auth" onSubmit={submit}>
      <div className="logo"><BrandMark />{brand?.name || "POS System"}</div>
      <p className="muted" style={{ margin: 0 }}>{brand?.tagline ? `${brand.tagline} · ` : ""}Sign in to the till or back office</p>
      <input placeholder="Username" value={u} onChange={(e) => setU(e.target.value)} autoFocus />
      <input placeholder="Password" type="password" value={p} onChange={(e) => setP(e.target.value)} />
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</button>
      <div style={{ display: "flex", justifyContent: "center", marginTop: 4 }}><ThemeSwitch compact /></div>
    </form>
  );
}

function OpenTill({ me, branchId, branches, onSwitch, onOffice, onOpen, onLogout }: {
  me: Me; branchId: string; branches: Me["branches"]; onSwitch: (id: string) => void; onOffice?: () => void;
  onOpen: (s: Session) => void; onLogout: () => void;
}) {
  type T = { id: number; name: string; code: string; is_active: boolean; assigned_to_me: boolean;
    open_session: null | { cashier_name: string } };
  const [tills, setTills] = useState<T[] | null>(null);
  const [till, setTill] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api("/tills/?page_size=100").then((d) => {
    const list: T[] = d.results.filter((t: T) => t.is_active);
    setTills(list);
    const free = list.filter((t) => t.assigned_to_me && !t.open_session);
    if (free.length === 1) setTill(String(free[0].id));
  }).catch(() => setError("Cannot load tills (offline?)"));
  useEffect(() => { load(); }, [branchId]);
  async function open() {
    setError(""); setBusy(true);
    try { onOpen(await api<Session>("/till-sessions/", { body: { till: Number(till) } })); }
    catch (e: any) { setError(e.message); load(); } finally { setBusy(false); }
  }
  const mine = (tills || []).filter((t) => t.assigned_to_me);
  return (
    <div className="center card">
      <SystemTabs me={me} current="pos" />
      <h2>Open till</h2>
      {branches.length > 1 ? <label>Branch <select value={branchId} onChange={(e) => onSwitch(e.target.value)}>
        {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
        : <p style={{ margin: 0 }}><b>{branches[0]?.name}</b></p>}
      <p className="muted" style={{ margin: 0 }}>Tills open at zero. Ask the vault holder for your float once it's open.</p>
      {tills === null && !error && <p className="muted">Loading tills…</p>}
      {tills && !mine.length && <p className="error">You aren't assigned to any till here. Ask a branch admin to assign you.</p>}
      <div className="till-pick" role="radiogroup" aria-label="Till">
        {mine.map((t) => {
          const busyBy = t.open_session?.cashier_name;
          return (
            <button key={t.id} type="button" role="radio" aria-checked={till === String(t.id)} disabled={!!busyBy}
                    className={`till-option${till === String(t.id) ? " selected" : ""}`} onClick={() => setTill(String(t.id))}>
              <b>{t.name}</b><small>{busyBy ? `In use by ${busyBy}` : "Free"}</small>
            </button>
          );
        })}
      </div>
      {error && <p className="error">{error}</p>}
      <button disabled={!till || busy} onClick={open}>Open till at 0</button>
      <button className="link" onClick={onLogout}>Log out</button>
    </div>
  );
}
