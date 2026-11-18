// Small, dependency-free charts for the dashboard. All single-series, so one hue (--series-1),
// no legend box (the card title names the series). Every bar is its own hover/focus target,
// and each chart has a table view so no value depends on hovering.
import { useState } from "react";
import { money } from "../api";

type Point = { label: string; value: number; sub?: string };

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v)!;
}

const short = (v: number) =>
  v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}K` : String(v);

/** Vertical columns over time. Bars <= 24px, 4px rounded top, square at the baseline. */
export function ColumnChart({ data, height = 220, title }: { data: Point[]; height?: number; title: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const W = Math.max(320, data.length * 40), H = height, padL = 44, padB = 26, padT = 10;
  const max = niceMax(Math.max(...data.map((d) => d.value), 0));
  const band = (W - padL) / data.length;
  const bw = Math.min(24, band - 2);
  const y = (v: number) => padT + (H - padT - padB) * (1 - v / max);
  const ticks = [0, max / 2, max];
  const every = Math.ceil(data.length / 8);

  if (table) return (
    <div>
      <ViewToggle table={table} setTable={setTable} />
      <DataTable title={title} rows={data.map((d) => [d.label, money(d.value), d.sub || ""])} head={["Date", "Amount", ""]} />
    </div>
  );
  return (
    <div className="chart">
      <ViewToggle table={table} setTable={setTable} />
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} style={{ width: "100%", height: "auto" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W} y1={y(t)} y2={y(t)} className="grid" />
            <text x={padL - 6} y={y(t) + 4} className="axis" textAnchor="end">{short(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + i * band + (band - bw) / 2;
          const top = y(d.value), h = Math.max(0, H - padB - top);
          const r = Math.min(4, h);
          return (
            <g key={i} tabIndex={0} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}
               onFocus={() => setHover(i)} onBlur={() => setHover(null)} aria-label={`${d.label}: ${money(d.value)}`}>
              <rect x={padL + i * band} y={padT} width={band} height={H - padT - padB} fill="transparent" />
              {h > 0 && <path className={`bar ${hover === i ? "hot" : ""}`}
                d={`M${x},${H - padB} V${top + r} q0,-${r} ${r},-${r} H${x + bw - r} q${r},0 ${r},${r} V${H - padB} Z`} />}
              {i % every === 0 && <text x={x + bw / 2} y={H - 8} className="axis" textAnchor="middle">{d.label}</text>}
            </g>
          );
        })}
        <line x1={padL} x2={W} y1={H - padB} y2={H - padB} className="baseline" />
        {hover !== null && (() => {
          const d = data[hover];
          const cx = Math.min(Math.max(padL + hover * band + band / 2, padL + 70), W - 70);
          return (
            <g pointerEvents="none">
              <rect x={cx - 68} y={2} width={136} height={d.sub ? 42 : 28} rx={6} className="tip" />
              <text x={cx} y={19} textAnchor="middle" className="tip-text">{d.label}: {money(d.value)}</text>
              {d.sub && <text x={cx} y={36} textAnchor="middle" className="tip-sub">{d.sub}</text>}
            </g>
          );
        })()}
      </svg>
    </div>
  );
}

/** Horizontal bars for ranking categories (branches, payment methods). Value printed at the bar end. */
export function BarList({ data, title, empty = "No data yet today." }: { data: Point[]; title: string; empty?: string }) {
  const [table, setTable] = useState(false);
  const max = Math.max(...data.map((d) => d.value), 0) || 1;
  if (!data.length) return <p className="muted">{empty}</p>;
  return (
    <div>
      <ViewToggle table={table} setTable={setTable} />
      {table ? <DataTable title={title} rows={data.map((d) => [d.label, money(d.value), d.sub || ""])} head={["", "Amount", ""]} /> : (
        <ul className="barlist" aria-label={title}>
          {data.map((d) => (
            <li key={d.label} tabIndex={0} title={`${d.label}: ${money(d.value)}${d.sub ? ` · ${d.sub}` : ""}`}>
              <span className="bl-label">{d.label}</span>
              <span className="bl-track">
                {d.value > 0 && <span className="bl-bar" style={{ width: `${(d.value / max) * 100}%` }} />}
                <span className="bl-value">{money(d.value)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ViewToggle({ table, setTable }: { table: boolean; setTable: (b: boolean) => void }) {
  return <button className="link viewtoggle" onClick={() => setTable(!table)}>{table ? "Chart" : "Table"}</button>;
}

function DataTable({ title, head, rows }: { title: string; head: string[]; rows: string[][] }) {
  return (
    <table className="grid-table"><caption className="sr-only">{title}</caption>
      <thead><tr>{head.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
    </table>
  );
}

// =================================================================================================
// Newer interactive charts. One axis each; hover/focus tooltips; table views; color never alone.
// =================================================================================================
type TrendPoint = { label: string; date: string; value: number; prev: number; sub?: string };

/** Line + soft area for this period, dashed grey line for the previous period, crosshair tooltip. */
export function AreaTrend({ data, title, height = 240 }: { data: TrendPoint[]; title: string; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const W = 720, H = height, padL = 48, padR = 12, padT = 12, padB = 28;
  const max = niceMax(Math.max(...data.map((d) => Math.max(d.value, d.prev)), 0));
  const x = (i: number) => padL + (data.length <= 1 ? 0 : (i * (W - padL - padR)) / (data.length - 1));
  const y = (v: number) => padT + (H - padT - padB) * (1 - v / max);
  const path = (k: "value" | "prev") => data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[k]).toFixed(1)}`).join(" ");
  const area = `${path("value")} L${x(data.length - 1)},${H - padB} L${x(0)},${H - padB} Z`;
  const every = Math.ceil(data.length / 7);

  function move(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((px - padL) / (W - padL - padR)) * (data.length - 1));
    setHover(Math.max(0, Math.min(data.length - 1, i)));
  }
  function key(e: React.KeyboardEvent) {
    if (e.key === "ArrowRight") setHover((h) => Math.min(data.length - 1, (h ?? -1) + 1));
    if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? data.length) - 1));
  }
  if (table) return (
    <div><ViewToggle table={table} setTable={setTable} />
      <DataTable title={title} head={["Date", "This period", "Previous period"]}
        rows={data.map((d) => [d.label, money(d.value), money(d.prev)])} /></div>
  );
  const h = hover !== null ? data[hover] : null;
  const change = h && h.prev ? ((h.value - h.prev) / h.prev) * 100 : null;
  return (
    <div className="chart">
      <div className="card-head" style={{ marginBottom: 6 }}>
        <div className="legend"><span><i style={{ background: "var(--series-1)" }} />This period</span><span><i className="dash" />Previous period</span></div>
        <ViewToggle table={table} setTable={setTable} />
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. Use the left and right arrow keys to read each day.`} tabIndex={0}
           style={{ width: "100%", height: "auto" }} onPointerMove={move} onPointerLeave={() => setHover(null)} onKeyDown={key}
           onFocus={() => setHover((v) => v ?? data.length - 1)} onBlur={() => setHover(null)}>
        <defs>
          <linearGradient id="areaFade" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--series-1)" stopOpacity=".22" /><stop offset="100%" stopColor="var(--series-1)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, max / 2, max].map((t) => (
          <g key={t}><line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} className="grid" />
            <text x={padL - 8} y={y(t) + 4} className="axis" textAnchor="end">{short(t)}</text></g>
        ))}
        <path d={area} fill="url(#areaFade)" />
        <path d={path("prev")} className="line ref" />
        <path d={path("value")} className="line" />
        {data.map((d, i) => i % every === 0 && (
          <text key={i} x={x(i)} y={H - 8} className="axis" textAnchor="middle">{d.label}</text>))}
        <line x1={padL} x2={W - padR} y1={H - padB} y2={H - padB} className="baseline" />
        {hover !== null && (<g pointerEvents="none">
          <line x1={x(hover)} x2={x(hover)} y1={padT} y2={H - padB} className="crosshair" />
          <circle cx={x(hover)} cy={y(data[hover].prev)} r={4} className="dot ref" />
          <circle cx={x(hover)} cy={y(data[hover].value)} r={5} className="dot" />
        </g>)}
        <circle cx={x(data.length - 1)} cy={y(data[data.length - 1]?.value ?? 0)} r={4} className="dot" />
      </svg>
      {h && (
        <div className="tooltip" style={{ left: `${Math.min(84, Math.max(16, (x(hover!) / W) * 100))}%`, top: 44, transform: "translateX(-50%)" }}>
          <div className="t-title">{new Date(h.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</div>
          <div className="t-row"><span><i style={{ background: "var(--series-1)" }} />This period</span><b>{money(h.value)}</b></div>
          <div className="t-row"><span><i style={{ background: "var(--ref-line)" }} />Previous</span><b>{money(h.prev)}</b></div>
          {change !== null && <div className="t-row"><span>Change</span><b>{change >= 0 ? "+" : ""}{change.toFixed(0)}%</b></div>}
          {h.sub && <div className="t-row"><span>{h.sub}</span></div>}
        </div>
      )}
    </div>
  );
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HEAT_STEPS = ["var(--card-2)", "var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)", "var(--seq-7)"];

/** Weekday x hour heatmap: one blue ramp, light = quiet, dark = busy. */
export function Heatmap({ cells, metric = "count", title }: {
  cells: { weekday: number; hour: number; count: number; total: string | number }[]; metric?: "count" | "total"; title: string;
}) {
  const [table, setTable] = useState(false);
  if (!cells.length) return <p className="muted">No sales in this period yet.</p>;
  const hours = [...new Set(cells.map((c) => c.hour))].sort((a, b) => a - b);
  const cols = Array.from({ length: hours[hours.length - 1] - hours[0] + 1 }, (_, i) => hours[0] + i);
  const val = (c?: { count: number; total: string | number }) => (c ? Number(metric === "count" ? c.count : c.total) : 0);
  const map = new Map(cells.map((c) => [`${c.weekday}:${c.hour}`, c]));
  const max = Math.max(1, ...cells.map((c) => val(c)));
  const color = (v: number) => (v <= 0 ? HEAT_STEPS[0] : HEAT_STEPS[Math.min(7, 1 + Math.floor((v / max) * 6.999))]);
  const fmt = (v: number) => (metric === "count" ? `${v} sale${v === 1 ? "" : "s"}` : money(v));
  const busiest = cells.reduce((b, c) => (val(c) > val(b) ? c : b), cells[0]);

  if (table) return (
    <div><ViewToggle table={table} setTable={setTable} />
      <DataTable title={title} head={["Day", "Hour", metric === "count" ? "Sales" : "Amount"]}
        rows={cells.filter((c) => val(c) > 0).sort((a, b) => val(b) - val(a)).map((c) => [DAYS[c.weekday], `${c.hour}:00`, fmt(val(c))])} /></div>
  );
  return (
    <div>
      <div className="card-head" style={{ marginBottom: 8 }}>
        <span className="card-sub" style={{ margin: 0 }}>Busiest: <b>{DAYS[busiest.weekday]} {busiest.hour}:00 to {busiest.hour + 1}:00</b></span>
        <ViewToggle table={table} setTable={setTable} />
      </div>
      <div className="heat" role="grid" aria-label={title} style={{ gridTemplateColumns: `34px repeat(${cols.length}, minmax(0, 1fr))` }}>
        <span />
        {cols.map((hr) => <span key={hr} className="clabel">{hr % 2 === 0 ? hr : ""}</span>)}
        {DAYS.map((d, wd) => (
          <div key={d} style={{ display: "contents" }} role="row">
            <span className="rlabel">{d}</span>
            {cols.map((hr) => {
              const v = val(map.get(`${wd}:${hr}`));
              const label = `${d} ${hr}:00 to ${hr + 1}:00: ${fmt(v)}`;
              return <span key={hr} className="cell" role="gridcell" title={label} aria-label={label} style={{ background: color(v) }} />;
            })}
          </div>
        ))}
      </div>
      <div className="heat-scale" style={{ marginTop: 10 }}>
        <span>Quiet</span>{HEAT_STEPS.slice(1).map((s) => <span key={s} className="sw" style={{ background: s }} />)}<span>Busy</span>
      </div>
    </div>
  );
}

/** One whole split into parts (payment mix). Legend lists name, amount, share; colors in fixed slot order. */
export function SegmentedBar({ data, title }: { data: { label: string; value: number }[]; title: string }) {
  const [table, setTable] = useState(false);
  const total = data.reduce((s, d) => s + d.value, 0);
  if (!total) return <p className="muted">No payments yet today.</p>;
  const slot = (i: number) => `var(--series-${(i % 8) + 1})`;
  const share = (v: number) => `${((v / total) * 100).toFixed(v / total < 0.1 ? 1 : 0)}%`;
  if (table) return (
    <div><ViewToggle table={table} setTable={setTable} />
      <DataTable title={title} head={["Method", "Amount", "Share"]} rows={data.map((d) => [d.label, money(d.value), share(d.value)])} /></div>
  );
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}><ViewToggle table={table} setTable={setTable} /></div>
      <div className="segbar" role="img" aria-label={`${title}: ${data.map((d) => `${d.label} ${share(d.value)}`).join(", ")}`}>
        {data.map((d, i) => d.value > 0 && (
          <div key={d.label} tabIndex={0} title={`${d.label}: ${money(d.value)} (${share(d.value)})`}
               style={{ width: `${(d.value / total) * 100}%`, background: slot(i) }} />
        ))}
      </div>
      <ul className="barlist" style={{ marginTop: 14, gap: 8 }}>
        {data.map((d, i) => (
          <li key={d.label} style={{ gridTemplateColumns: "1fr auto auto" }}>
            <span className="bl-label"><i style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: slot(i), marginRight: 8 }} />{d.label}</span>
            <span className="bl-value">{money(d.value)}</span>
            <span className="muted" style={{ minWidth: 44, textAlign: "right" }}>{share(d.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Tiny trend line for KPI tiles; decorative (the tile states the number), so hidden from screen readers. */
export function Sparkline({ values, width = 90, height = 28 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1), min = Math.min(...values, 0);
  const py = (v: number) => height - 2 - ((v - min) / (max - min || 1)) * (height - 4);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * width},${py(v)}`);
  return (
    <svg className="spark" width={width} height={height} aria-hidden="true">
      <polyline points={pts.join(" ")} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={width} cy={py(values[values.length - 1])} r={2.5} fill="var(--series-1)" />
    </svg>
  );
}
