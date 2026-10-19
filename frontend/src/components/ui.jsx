import { useEffect, useState } from "react";

// ---------- formatting ----------
export const fmt = new Intl.NumberFormat();
export const pct = (n, d) => (d ? `${Math.round((n / d) * 100)}%` : "0%");

export function fmtDate(iso, withTime = true) {
  if (!iso) return "";
  const d = new Date(iso);
  return withTime
    ? d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function timeAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

// <input type="datetime-local"> works in local time; the API speaks UTC ISO strings.
export const toLocalInput = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
};
export const fromLocalInput = (v) => (v ? new Date(v).toISOString() : null);

// ---------- status ----------
const STATUS = {
  active: ["ok", "Active"],
  scheduled: ["idle", "Scheduled"],
  paused: ["idle", "Paused"],
  expired: ["warn", "Expired"],
  limit_reached: ["warn", "Limit reached"],
  disabled: ["bad", "Disabled"],
  archived: ["idle", "Archived"],
};
export function StatusBadge({ status }) {
  const [tone, label] = STATUS[status] || ["idle", status];
  return <span className={`badge ${tone}`}>{label}</span>;
}

export function Tags({ tags }) {
  return tags?.map((t) => (
    <span key={t.id} className="tag"><i style={{ background: t.color }} />{t.name}</span>
  ));
}

// ---------- the pulse sparkline ----------
export function Sparkline({ values = [], width = 120, height = 30 }) {
  if (!values.length) return null;
  const max = Math.max(1, ...values);
  const step = width / Math.max(1, values.length - 1);
  const pts = values.map((v, i) => [i * step, height - 3 - (v / max) * (height - 6)]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const total = values.reduce((a, b) => a + b, 0);
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={`${total} clicks in the last ${values.length} days`}>
      <path className="area" d={`${line} L${width},${height} L0,${height} Z`} />
      <path className="line" d={line} />
    </svg>
  );
}

// ---------- feedback ----------
export function Notice({ tone = "info", children }) {
  if (!children) return null;
  return <div className={`notice ${tone}`} role={tone === "error" ? "alert" : "status"}>{children}</div>;
}

export function Issues({ errors = [], warnings = [] }) {
  if (!errors.length && !warnings.length) return null;
  return (
    <ul className="issues">
      {errors.map((e, i) => <li key={`e${i}`} className="error"><span className="icon">✕</span>{e.message || e}</li>)}
      {warnings.map((w, i) => <li key={`w${i}`} className="warning"><span className="icon">!</span>{w.message || w}</li>)}
    </ul>
  );
}

export function Empty({ title, children, action }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="btn secondary small" onClick={async () => {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    }}>{done ? "Copied" : label}</button>
  );
}

export function PeriodPicker({ value, onChange }) {
  return (
    <div className="segmented" role="group" aria-label="Period">
      {[7, 30, 90].map((d) => (
        <button key={d} type="button" aria-pressed={value === d} onClick={() => onChange(d)}>{d} days</button>
      ))}
    </div>
  );
}

// Loads data, exposes {data, error, loading, reload}.
export function useLoad(fn, deps) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    set((s) => ({ ...s, loading: true }));
    fn().then((data) => live && set({ data, error: null, loading: false }))
      .catch((error) => live && set({ data: null, error, loading: false }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}
