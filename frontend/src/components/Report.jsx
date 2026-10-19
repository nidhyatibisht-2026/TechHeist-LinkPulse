import { Link } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt, pct } from "./ui.jsx";

export function Kpis({ totals, extra = [] }) {
  const items = [
    ["Clicks", totals.clicks, "Human redirects"],
    ["Unique visitors", totals.unique_visitors, "Counted per day, without storing IPs"],
    ["QR scans", totals.qr_scans, "Clicks that came from a QR code"],
    ["Bots filtered", totals.filtered_bots, "Preview fetchers, crawlers and scripts"],
    ["Blocked visits", totals.blocked_attempts, "Disabled, expired or full links and wrong passwords"],
    ...extra,
  ];
  return (
    <div className="kpis">
      {items.map(([label, value, title]) => (
        <div className="kpi" key={label} title={title}>
          <div className="value">{typeof value === "number" ? fmt.format(value) : value}</div>
          <div className="label">{label}</div>
        </div>
      ))}
    </div>
  );
}

export function ClicksChart({ series }) {
  const data = series.map((d) => ({ ...d, label: new Date(d.date + "T00:00:00Z").toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" }) }));
  return (
    <div style={{ width: "100%", height: 260 }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 12 }} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 6, color: "var(--text)" }} />
          <Area type="monotone" dataKey="clicks" name="Clicks" stroke="var(--pulse)" strokeWidth={2} fill="var(--pulse-soft)" />
          <Line type="monotone" dataKey="unique" name="Unique visitors" stroke="var(--muted)" strokeDasharray="4 3" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BarList({ items, valueKey = "clicks", empty = "No data yet" }) {
  if (!items?.length) return <p className="muted small">{empty}</p>;
  const max = Math.max(...items.map((i) => i[valueKey]));
  const total = items.reduce((a, i) => a + i[valueKey], 0);
  return (
    <ul className="barlist">
      {items.map((i) => (
        <li key={i.name}>
          <span className="truncate" style={{ textTransform: i.name.length <= 8 ? "capitalize" : "none" }}>{i.name}</span>
          <span className="muted nowrap">{fmt.format(i[valueKey])} <span className="small">({pct(i[valueKey], total)})</span></span>
          <span className="bar"><span style={{ width: `${(i[valueKey] / max) * 100}%` }} /></span>
        </li>
      ))}
    </ul>
  );
}

const SEVERITY = { high: "bad", medium: "warn", low: "idle" };
const SEVERITY_LABEL = { high: "Act now", medium: "Watch", low: "Info" };

export function Alerts({ alerts }) {
  if (!alerts?.length) return <p className="panel-body muted small">No alerts. Every link looks healthy.</p>;
  return alerts.map((a, i) => (
    <div className="alert-row" key={i}>
      <span className={`badge ${SEVERITY[a.severity]}`}>{SEVERITY_LABEL[a.severity]}</span>
      <span><Link to={`/links/${a.link_id}`} className="code">/{a.code}</Link> <span className="muted">{a.message}</span></span>
    </div>
  ));
}

export default function Report({ report, showCampaigns = true, showTopLinks = true, showAlerts = true }) {
  const b = report.breakdowns;
  return (
    <div className="stack">
      <Kpis totals={report.totals} />

      <section className="panel">
        <div className="panel-head">
          <h2>Clicks per day</h2>
          <span className="muted small">UTC days. Bots excluded.</span>
        </div>
        <div className="panel-body"><ClicksChart series={report.series} /></div>
      </section>

      {showAlerts && (
        <section className="panel">
          <div className="panel-head"><h2>Link alerts</h2><span className="muted small">{report.alerts.length} open</span></div>
          <Alerts alerts={report.alerts} />
        </section>
      )}

      {(showTopLinks || showCampaigns) && (
        <div className="grid-2">
          {showTopLinks && (
            <section className="panel">
              <div className="panel-head"><h2>Top links</h2></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Link</th><th className="num">Clicks</th><th className="num">Unique</th></tr></thead>
                  <tbody>
                    {report.top_links.length === 0 && <tr><td colSpan={3} className="muted">No clicks in this period.</td></tr>}
                    {report.top_links.map((l) => (
                      <tr key={l.id}>
                        <td><Link to={`/links/${l.id}`} className="code">/{l.code}</Link><div className="muted small truncate" style={{ maxWidth: 260 }}>{l.title}</div></td>
                        <td className="num">{fmt.format(l.clicks)}</td>
                        <td className="num">{fmt.format(l.unique)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {showCampaigns && (
            <section className="panel">
              <div className="panel-head"><h2>Campaign performance</h2></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Campaign</th><th className="num">Links</th><th className="num">Clicks</th><th className="num">Unique</th></tr></thead>
                  <tbody>
                    {report.campaigns.map((c) => (
                      <tr key={c.id ?? "none"}>
                        <td>{c.id ? <Link to={`/campaigns/${c.id}`}>{c.name}</Link> : <span className="muted">{c.name}</span>}</td>
                        <td className="num">{c.links}</td>
                        <td className="num">{fmt.format(c.clicks)}</td>
                        <td className="num">{fmt.format(c.unique)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}

      <div className="grid-3">
        <section className="panel"><div className="panel-head"><h3>Traffic sources</h3></div><div className="panel-body"><BarList items={b.referrers} /></div></section>
        <section className="panel"><div className="panel-head"><h3>Countries</h3></div><div className="panel-body"><BarList items={b.countries} /></div></section>
        <section className="panel"><div className="panel-head"><h3>Devices</h3></div><div className="panel-body"><BarList items={b.devices} /></div></section>
        <section className="panel"><div className="panel-head"><h3>Browsers</h3></div><div className="panel-body"><BarList items={b.browsers} /></div></section>
        <section className="panel"><div className="panel-head"><h3>Operating systems</h3></div><div className="panel-body"><BarList items={b.os} /></div></section>
        <section className="panel">
          <div className="panel-head"><h3>Why bots were filtered</h3></div>
          <div className="panel-body"><BarList items={report.bot_reasons} valueKey="count" empty="No automated traffic detected." /></div>
        </section>
      </div>
    </div>
  );
}
