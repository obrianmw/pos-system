import { useEffect, useState } from "react";
import { ShoppingCart } from "lucide-react";
import { api, auth, login, OfflineError } from "./api";
import POS from "./POS";
import BackOffice, { hasBackOffice } from "./backoffice/BackOffice";

export type Me = {
  organization_name?: string;
  id: number; username: string; name: string;
  branches: { id: number; name: string; code: string; permissions: string[]; currency: string }[];
  org_permissions: string[];
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

  useEffect(() => {
    if (me && !branchId && me.branches.length === 1) chooseBranch(String(me.branches[0].id));
  }, [me]);

  useEffect(() => {
    if (!me || !branchId) return;
    api<Session | null>("/till-sessions/current/")
      .then((s) => { setSession(s); cache.set("pos.session", s); })
      .catch(() => {});
  }, [me, branchId]);

  function chooseBranch(id: string) { auth.branch = id; setBranchId(id); }
  function logout() {
    auth.token = null; auth.branch = null; cache.set("pos.me", null); cache.set("pos.session", null);
    setMe(null); setBranchId(null); setSession(null);
  }

  if (!me) return <Login onDone={(m) => { setMe(m); cache.set("pos.me", m); }} error={error} setError={setError} />;

  // Routing: #/office/... is the back office, anything else the till. People who can't sell go
  // straight to the back office; supervisors and admins can switch between the two.
  const sells = me.branches.some((b) => b.permissions.includes("pos.sell"));
  const office = hasBackOffice(me);
  const orgLevel = me.org_permissions.length > 0;
  if (office && (route.startsWith("#/office") || !sells || (orgLevel && !route.startsWith("#/pos")))) {
    return <BackOffice me={me} onLogout={logout} onPos={sells ? () => (location.hash = "#/pos") : undefined} />;
  }
  const branch = me.branches.find((b) => String(b.id) === branchId);
  if (!branch) {
    return (
      <div className="center card">
        <h2>Choose branch</h2>
        {me.branches.map((b) => <button key={b.id} onClick={() => chooseBranch(String(b.id))}>{b.name}</button>)}
        {!me.branches.length && <p>You have no branch assigned. Ask your administrator.</p>}
        <button className="link" onClick={logout}>Log out</button>
      </div>
    );
  }
  if (!branch.permissions.includes("pos.sell")) {
    return (
      <div className="center card">
        <h2>{branch.name}</h2>
        <p>Your role here has no till access. Back-office work is in the admin site: <a href="/admin/">/admin/</a>.</p>
        <button className="link" onClick={logout}>Log out</button>
      </div>
    );
  }
  if (!session) return <OpenTill branchId={branchId!} onOpen={(s) => { setSession(s); cache.set("pos.session", s); }} onLogout={logout} />;
  return <POS me={me} branch={branch} session={session} onLogout={logout}
              onOffice={office ? () => (location.hash = "#/office/dashboard") : undefined}
              onClosed={() => { setSession(null); cache.set("pos.session", null); }} />;
}

function Login({ onDone, error, setError }: { onDone: (m: Me) => void; error: string; setError: (s: string) => void }) {
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
      <div className="logo"><span className="logo-mark"><ShoppingCart size={18} /></span>Aden Shop</div>
      <p className="muted" style={{ margin: 0 }}>Sign in to the till or back office</p>
      <input placeholder="Username" value={u} onChange={(e) => setU(e.target.value)} autoFocus />
      <input placeholder="Password" type="password" value={p} onChange={(e) => setP(e.target.value)} />
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</button>
    </form>
  );
}

function OpenTill({ branchId, onOpen, onLogout }: { branchId: string; onOpen: (s: Session) => void; onLogout: () => void }) {
  const [tills, setTills] = useState<{ id: number; name: string; code: string }[]>([]);
  const [till, setTill] = useState("");
  const [float, setFloat] = useState("0");
  const [error, setError] = useState("");
  useEffect(() => { api("/tills/").then((d) => setTills(d.results)).catch(() => setError("Cannot load tills (offline?)")); }, [branchId]);
  async function open() {
    setError("");
    try { onOpen(await api<Session>("/till-sessions/", { body: { till: Number(till), opening_float: float } })); }
    catch (e: any) { setError(e.message); }
  }
  return (
    <div className="center card">
      <h2>Open till</h2>
      <select value={till} onChange={(e) => setTill(e.target.value)}>
        <option value="">Select till…</option>
        {tills.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
      <label>Opening float <input inputMode="decimal" value={float} onChange={(e) => setFloat(e.target.value)} /></label>
      {error && <p className="error">{error}</p>}
      <button disabled={!till} onClick={open}>Open till</button>
      <button className="link" onClick={onLogout}>Log out</button>
    </div>
  );
}
