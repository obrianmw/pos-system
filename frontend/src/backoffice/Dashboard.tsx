import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Banknote, Landmark, Receipt, RotateCcw, ShoppingBasket } from "lucide-react";
import { api, money, whole } from "../api";
import type { Ctx } from "./BackOffice";
import { AreaTrend, BarList, Heatmap, SegmentedBar, Sparkline } from "./charts";

type Alerts = Partial<Record<"needs_review" | "open_tills" | "low_stock" | "pending_overrides" | "pending_expenses" | "pending_leave", number>>;

// Status is never color alone: each alert carries an icon and words, and links to the page that clears it.
const ALERTS: { key: keyof Alerts; label: string; page: string; level: "critical" | "warning" | "info" }[] = [
  { key: "pending_overrides", label: "price/void approvals waiting", page: "approvals", level: "warning" },
  { key: "needs_review", label: "offline sales need review", page: "sales?review=1", level: "critical" },
  { key: "low_stock", label: "items at or below reorder level", page: "stock?low=1", level: "warning" },
  { key: "pending_expenses", label: "expenses awaiting approval", page: "expenses", level: "warning" },
  { key: "pending_leave", label: "leave requests to decide", page: "leave", level: "warning" },
  { key: "open_tills", label: "tills open now", page: "sales", level: "info" },
];
const ICON = { critical: "⛔", warning: "⚠", info: "ℹ" };
const day = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });

function Delta({ now, before, label }: { now: number; before: number; label: string }) {
  if (!before) return <small>{label}: no figures to compare</small>;
  const pct = ((now - before) / before) * 100;
  const up = pct >= 0;
  return (
    <small><span className={`delta ${up ? "up" : "down"}`}>{up ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{Math.abs(pct).toFixed(0)}%</span>
      {" "}{label} ({money(before)})</small>
  );
}

export default function Dashboard({ ctx }: { ctx: Ctx }) {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [heatMetric, setHeatMetric] = useState<"count" | "total">("count");

  useEffect(() => {
    setError("");
    const q = `?days=${days}${ctx.branch ? `&branch=${ctx.branch}` : ""}`;
    api(`/reports/dashboard/${q}`, { branch: null }).then(setData).catch((e) => setError(e.message));
  }, [days, ctx.branch]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return (
    <div className="dash">
      <div className="kpis">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 112 }} />)}</div>
      <div className="skeleton" style={{ height: 300 }} />
    </div>
  );
  const s = data.sales;
  const alerts = ALERTS.filter((a) => data.alerts[a.key] !== undefined);
  const series = s ? s.trend.map((t: any) => Number(t.total)) : [];
  const counts = s ? s.trend.map((t: any) => t.count) : [];

  return (
    <div className="dash">
      {s && (
        <section className="kpis" aria-label="Today">
          <div className="kpi hero">
            <span className="kpi-head"><span className="kpi-icon"><Banknote size={16} /></span>Sales today ({ctx.me.branches[0]?.currency || "MWK"})</span>
            <b>{whole(s.today.total)}</b>
            <Delta now={Number(s.today.total)} before={Number(s.yesterday_total)} label="vs yesterday" />
            <Sparkline values={series} width={120} height={36} />
          </div>
          <div className="kpi"><span className="kpi-head"><span className="kpi-icon"><Receipt size={16} /></span>Transactions</span>
            <b>{s.today.count}</b><Sparkline values={counts} /></div>
          <div className="kpi"><span className="kpi-head"><span className="kpi-icon"><ShoppingBasket size={16} /></span>Average basket</span>
            <b>{whole(s.today.avg_basket)}</b></div>
          <div className="kpi"><span className="kpi-head"><span className="kpi-icon"><RotateCcw size={16} /></span>Refunds</span>
            <b>{whole(s.today.refunds_total)}</b><small>{s.today.refunds_count} today</small></div>
          <div className="kpi"><span className="kpi-head"><span className="kpi-icon"><Landmark size={16} /></span>VAT collected</span>
            <b>{whole(s.today.tax)}</b></div>
        </section>
      )}

      {alerts.length > 0 && (
        <section className="alerts" aria-label="Things that need attention">
          {alerts.map((a) => {
            const n = data.alerts[a.key] as number;
            const level = n === 0 ? "good" : a.level;
            return (
              <a key={a.key} href={`#/office/${a.page}`} className={`alert ${level}`}>
                <span aria-hidden>{n === 0 ? "✓" : ICON[a.level]}</span><b>{n}</b> {a.label}
              </a>
            );
          })}
        </section>
      )}

      {s && (
        <section className="cards">
          <div className="card span2">
            <div className="card-head">
              <div><h2>Sales trend</h2>
                <div className="card-sub" style={{ marginTop: 2 }}>{money(s.period_total)} in the last {days} days ·{" "}
                  <Delta now={Number(s.period_total)} before={Number(s.prev_period_total)} label="vs the previous period" /></div></div>
              <div className="seg" role="group" aria-label="Period">
                {[7, 14, 30].map((d) => <button key={d} className={d === days ? "on" : ""} aria-pressed={d === days} onClick={() => setDays(d)}>{d} days</button>)}
              </div>
            </div>
            <AreaTrend title="Daily sales, this period vs previous period" data={s.trend.map((t: any) => ({
              label: day(t.date), date: t.date, value: Number(t.total), prev: Number(t.prev_total),
              sub: `${t.count} sale${t.count === 1 ? "" : "s"}${Number(t.refunds) ? ` · refunds ${money(t.refunds)}` : ""}`,
            }))} />
          </div>

          <div className="card">
            <div className="card-head"><h2>Busiest times · last {days} days</h2>
              <div className="seg" role="group" aria-label="Measure">
                <button className={heatMetric === "count" ? "on" : ""} onClick={() => setHeatMetric("count")}>Sales</button>
                <button className={heatMetric === "total" ? "on" : ""} onClick={() => setHeatMetric("total")}>Amount</button>
              </div></div>
            <Heatmap title="Sales by weekday and hour" cells={s.heatmap} metric={heatMetric} />
          </div>

          <div className="card">
            <h2>Payment mix today</h2>
            <SegmentedBar title="Payment mix today" data={s.by_method.map((m: any) => ({ label: m.name, value: Number(m.total) }))} />
          </div>

          {!ctx.branch && s.by_branch.length > 1 && (
            <div className="card">
              <h2>Sales by branch today</h2>
              <BarList title="Sales by branch today" data={s.by_branch.map((b: any) => ({ label: b.name, value: Number(b.total), sub: `${b.count} sales` }))} />
            </div>
          )}

          <div className="card">
            <h2>Top products · last {days} days</h2>
            {s.top_products.length ? (
              <table className="grid-table">
                <thead><tr><th>Product</th><th className="num">Qty</th><th className="num">Sales</th></tr></thead>
                <tbody>{s.top_products.map((p: any) => (
                  <tr key={p.name}><td>{p.name}</td><td className="num">{Number(p.qty)}</td><td className="num">{money(p.total)}</td></tr>
                ))}</tbody>
              </table>
            ) : <p className="muted">No sales in this period.</p>}
          </div>
        </section>
      )}
      {!s && <p className="muted">Your role has no sales figures; the items above are what needs your attention.</p>}
    </div>
  );
}
