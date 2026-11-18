import { useEffect, useState } from "react";
import {
  ArrowLeftRight, BadgeCheck, Boxes, Building2, CalendarDays, LayoutDashboard, LogOut, Mail, Menu, Package, Receipt,
  ScrollText, ShoppingCart, Truck, Users as UsersIcon, Wallet, BookOpenCheck, UserCog,
} from "lucide-react";
import type { Me } from "../App";
import Dashboard from "./Dashboard";
import { Approvals, AuditLog, Expenses, Leave, Sales, Stock, TrialBalance, Users } from "./pages";
import { Employees } from "./hr";
import { Transfers } from "./transfers";
import { Products, PurchaseOrders } from "./catalog";
import { Messages, PinnedBanner, useInboxSummary } from "./messages";
import { initials } from "./ui";
import { ErrorBoundary, ErrorCard } from "../ErrorCard";

export type Ctx = { me: Me; branch: string | null; can: (perm: string) => boolean; canOrg: (perm: string) => boolean };

type Page = { key: string; label: string; group: string; icon: JSX.Element; show: (c: Ctx) => boolean; el: (c: Ctx) => JSX.Element };
const I = { size: 17, strokeWidth: 1.9 };

// Each page shows up only for people whose role covers it (in the selected branch, or anywhere for "All").
export const PAGES: Page[] = [
  { key: "dashboard", label: "Dashboard", group: "Overview", icon: <LayoutDashboard {...I} />, show: () => true, el: (c) => <Dashboard ctx={c} /> },
  { key: "messages", label: "Messages", group: "Overview", icon: <Mail {...I} />, show: () => true, el: (c) => <Messages ctx={c} /> },
  { key: "sales", label: "Sales", group: "Shop", icon: <Receipt {...I} />, show: (c) => c.can("pos.view_all_sales") || c.can("accounting.view"), el: (c) => <Sales ctx={c} /> },
  { key: "approvals", label: "Approvals", group: "Shop", icon: <BadgeCheck {...I} />, show: (c) => c.can("pos.price_override"), el: (c) => <Approvals ctx={c} /> },
  { key: "stock", label: "Stock", group: "Shop", icon: <Boxes {...I} />, show: (c) => c.can("inventory.view"), el: (c) => <Stock ctx={c} /> },
  { key: "products", label: "Products", group: "Shop", icon: <Package {...I} />, show: (c) => c.can("catalog.manage"), el: (c) => <Products ctx={c} /> },
  { key: "purchase-orders", label: "Purchase orders", group: "Shop", icon: <Truck {...I} />,
    show: (c) => c.can("purchasing.manage") || c.can("inventory.receive"), el: (c) => <PurchaseOrders ctx={c} /> },
  { key: "transfers", label: "Transfers", group: "Shop", icon: <ArrowLeftRight {...I} />, show: (c) => c.can("inventory.transfer"), el: (c) => <Transfers ctx={c} /> },
  { key: "expenses", label: "Expenses", group: "Accounting", icon: <Wallet {...I} />, show: (c) => c.can("accounting.view"), el: (c) => <Expenses ctx={c} /> },
  { key: "trial-balance", label: "Trial balance", group: "Accounting", icon: <BookOpenCheck {...I} />, show: (c) => c.can("accounting.view"), el: (c) => <TrialBalance ctx={c} /> },
  { key: "employees", label: "Employees", group: "HR", icon: <UsersIcon {...I} />, show: (c) => c.can("hr.view"), el: (c) => <Employees ctx={c} /> },
  { key: "leave", label: "Leave", group: "HR", icon: <CalendarDays {...I} />, show: (c) => c.can("hr.view"), el: (c) => <Leave ctx={c} /> },
  { key: "users", label: "Users & roles", group: "Admin", icon: <UserCog {...I} />, show: (c) => c.can("branch.admin"), el: (c) => <Users ctx={c} /> },
  { key: "audit", label: "Audit log", group: "Admin", icon: <ScrollText {...I} />, show: (c) => c.can("audit.view"), el: (c) => <AuditLog ctx={c} /> },
];

/** Someone "has a back office" if any management page is open to them (everyone has Messages). */
export function hasBackOffice(me: Me) {
  const ctx = makeCtx(me, null);
  return PAGES.some((p) => !["dashboard", "messages"].includes(p.key) && p.show(ctx));
}

function makeCtx(me: Me, branch: string | null): Ctx {
  const scope = branch ? me.branches.filter((b) => String(b.id) === branch) : me.branches;
  return {
    me, branch,
    can: (perm) => me.org_permissions.includes(perm) || scope.some((b) => b.permissions.includes(perm)),
    canOrg: (perm) => me.org_permissions.includes(perm),
  };
}

const pageFromHash = () => location.hash.replace(/^#\/office\/?/, "").split("?")[0] || "dashboard";

export default function BackOffice({ me, onLogout, onPos }: { me: Me; onLogout: () => void; onPos?: () => void }) {
  const [page, setPage] = useState(pageFromHash());
  const [branch, setBranch] = useState<string | null>(() => { try { return localStorage.getItem("office.branch"); } catch { return null; } });
  const [navOpen, setNavOpen] = useState(false);
  const inbox = useInboxSummary();
  const ctx = makeCtx(me, branch);
  const visible = PAGES.filter((p) => p.show(ctx));
  const allowed = visible.find((p) => p.key === page);
  // Unknown page -> 404 card; a page that exists but isn't open to this role/branch -> 403 card.
  const missing = allowed ? null : PAGES.some((p) => p.key === page) ? 403 : 404;
  const current = allowed || visible[0];

  useEffect(() => {
    const on = () => setPage(pageFromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => { document.title = `${missing ? (missing === 404 ? "Page not found" : "Access denied") : current.label} · ${me.organization_name || "POS System"}`; }, [current.key, missing]);

  function go(key: string) { location.hash = `#/office/${key}`; setNavOpen(false); }
  function pickBranch(v: string) {
    const b = v || null;
    setBranch(b);
    try { b ? localStorage.setItem("office.branch", b) : localStorage.removeItem("office.branch"); } catch { /* private mode */ }
  }

  const groups = [...new Set(visible.map((p) => p.group))];
  return (
    <div className={`office ${navOpen ? "nav-open" : ""}`}>
      <aside onClick={(e) => e.target === e.currentTarget && setNavOpen(false)}>
        <div className="brand">
          <span className="logo-mark"><ShoppingCart size={18} /></span>
          <span><b>{me.organization_name || "POS System"}</b><small>Back office</small></span>
        </div>
        {groups.map((g) => (
          <nav key={g} aria-label={g}>
            <div className="nav-group">{g}</div>
            {visible.filter((p) => p.group === g).map((p) => (
              <a key={p.key} href={`#/office/${p.key}`} className={p === current ? "active" : ""} aria-current={p === current ? "page" : undefined}
                 onClick={(e) => { e.preventDefault(); go(p.key); }}>
                {p.icon}{p.label}
                {p.key === "messages" && inbox.unread > 0 && <span className="badge" aria-label={`${inbox.unread} unread`}>{inbox.unread}</span>}
              </a>
            ))}
          </nav>
        ))}
      </aside>
      <div className="office-main">
        <PinnedBanner summary={inbox} onOpen={() => go("messages")} />
        <header>
          <button className="menu ghost icon" aria-label="Menu" onClick={() => setNavOpen(!navOpen)}><Menu size={20} /></button>
          <h1>{missing ? (missing === 404 ? "Page not found" : "Access denied") : current.label}</h1>
          <span className="spacer" />
          {me.branches.length > 1 ? (
            <label className="inline" style={{ flexDirection: "row" }}>
              <Building2 size={16} className="muted" aria-hidden />
              <select aria-label="Branch" value={branch || ""} onChange={(e) => pickBranch(e.target.value)}>
                <option value="">All branches</option>
                {me.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </label>
          ) : <span className="muted">{me.branches[0]?.name}</span>}
          {onPos && <button onClick={onPos}><ShoppingCart size={16} />Open POS</button>}
          <button className="ghost icon bell" aria-label={`Messages, ${inbox.unread} unread`} onClick={() => go("messages")}>
            <Mail size={19} />{inbox.unread > 0 && <span className="count">{inbox.unread > 99 ? "99+" : inbox.unread}</span>}
          </button>
          <span className="user-chip"><span className="avatar">{initials(me.name)}</span><span>{me.name}</span></span>
          <button className="ghost icon" aria-label="Log out" title="Log out" onClick={onLogout}><LogOut size={18} /></button>
        </header>
        <div className="content" key={`${page}:${branch}`}>
          {missing === 404 ? <ErrorCard inline code={404} title="Page not found" home="#/office/dashboard"
                               message="This back-office page does not exist or has moved." />
            : missing === 403 ? <ErrorCard inline code={403} title="Access denied" home="#/office/dashboard"
                                  message={branch ? "Your role can't open this page for the selected branch. Try All branches." : "Your role can't open this page."} />
            : <ErrorBoundary>{current.el({ ...ctx })}</ErrorBoundary>}
        </div>
      </div>
    </div>
  );
}
