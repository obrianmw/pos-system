// Tabs for moving between the parts of the system a person can use: the till, the back office, the
// phone stock screen and (organization admins) the database admin site on the API's port.
import { ClipboardCheck, Database, LayoutDashboard, ShoppingCart } from "lucide-react";
import type { Me } from "./App";
import { hasBackOffice } from "./backoffice/BackOffice";
import { api } from "./api";

/** Open the database admin already signed in (one-time link from the API); the sign-in page if that fails. */
async function openAdmin(e: React.MouseEvent, fallback: string) {
  e.preventDefault();
  const w = window.open("about:blank", "_blank"); // opened inside the click so pop-up blockers allow it
  try {
    const r = await api<{ path: string; port: number }>("/admin-handoff/", { method: "POST", branch: null });
    const url = `http://${location.hostname}:${r.port}${r.path}`;
    if (w) w.location.href = url; else location.href = url;
  } catch {
    if (w) w.location.href = fallback; else location.href = fallback;
  }
}

export type SystemKey = "pos" | "office" | "count";

export function systemsFor(me: Me) {
  const any = (p: string) => me.org_permissions.includes(p) || me.branches.some((b) => b.permissions.includes(p));
  const list: { key: SystemKey | "admin"; label: string; href: string; icon: JSX.Element; external?: boolean; title: string }[] = [];
  if (me.branches.some((b) => b.permissions.includes("pos.sell")))
    list.push({ key: "pos", label: "Till", href: "#/pos", icon: <ShoppingCart size={15} />, title: "Point of sale" });
  if (hasBackOffice(me))
    list.push({ key: "office", label: "Back office", href: "#/office/dashboard", icon: <LayoutDashboard size={15} />, title: "Back office" });
  if (["inventory.count", "inventory.verify", "inventory.view"].some(any))
    list.push({ key: "count", label: "Stock", href: "#/count", icon: <ClipboardCheck size={15} />, title: "Stock counts and look-ups (phone friendly)" });
  if (me.admin_site)
    list.push({ key: "admin", label: "Database admin", external: true, icon: <Database size={15} />,
      href: `http://${location.hostname}:${me.admin_site.port}${me.admin_site.path}`,
      title: "Database admin site (organization admins, admin network only). Opens in a new tab." });
  return list;
}

export function SystemTabs({ me, current }: { me: Me; current: SystemKey }) {
  const list = systemsFor(me);
  if (list.length < 2) return null;
  return (
    <nav className="system-tabs" aria-label="Switch system">
      {list.map((s) => (
        <a key={s.key} href={s.href} title={s.title} aria-current={s.key === current ? "page" : undefined}
           className={s.key === current ? "on" : ""} {...(s.external ? { target: "_blank", rel: "noopener", onClick: (e: React.MouseEvent) => openAdmin(e, s.href) } : {})}>
          {s.icon}<span>{s.label}</span>
        </a>
      ))}
    </nav>
  );
}
