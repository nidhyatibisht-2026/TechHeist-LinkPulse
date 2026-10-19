import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { CopyButton, Empty, Notice, Sparkline, StatusBadge, Tags, fmt, useLoad } from "../components/ui.jsx";

const STATUSES = [
  ["", "All statuses"], ["active", "Active"], ["scheduled", "Scheduled"], ["paused", "Paused"],
  ["expired", "Expired"], ["limit_reached", "Limit reached"], ["disabled", "Disabled"], ["archived", "Archived"],
];

export default function Links() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") || "");
  const status = params.get("status") || "";
  const campaign = params.get("campaign_id") || "";
  const page = Number(params.get("page") || 1);

  const campaigns = useLoad(() => api("/api/campaigns"), []);
  const qs = new URLSearchParams({ page, page_size: 20, ...(status && { status }), ...(campaign && { campaign_id: campaign }), ...(params.get("q") && { q: params.get("q") }) });
  const { data, error, loading } = useLoad(() => api(`/api/links?${qs}`), [qs.toString()]);

  const update = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in patch)) next.delete("page");
    setParams(next);
  };

  // Debounce the search box.
  useEffect(() => {
    const t = setTimeout(() => { if ((params.get("q") || "") !== q) update({ q }); }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Links</h1>
          <p className="muted">{data ? `${data.total} links` : "\u00a0"}{user.role === "admin" && " across all users"}</p>
        </div>
        <div className="row">
          <Link className="btn secondary" to="/import">Import CSV</Link>
          <Link className="btn" to="/links/new">Create link</Link>
        </div>
      </div>

      <div className="row" style={{ marginBottom: 16 }}>
        <input type="search" placeholder="Search by alias, title or destination" value={q} onChange={(e) => setQ(e.target.value)}
          style={{ maxWidth: 340 }} aria-label="Search links" />
        <select value={status} onChange={(e) => update({ status: e.target.value })} style={{ maxWidth: 180 }} aria-label="Status">
          {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={campaign} onChange={(e) => update({ campaign_id: e.target.value })} style={{ maxWidth: 220 }} aria-label="Campaign">
          <option value="">All campaigns</option>
          {campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      <Notice tone="error">{error?.message}</Notice>
      <section className="panel">
        {data && data.items.length === 0 ? (
          <Empty title={status || params.get("q") ? "No links match these filters" : "No links yet"}
            action={!status && !params.get("q") && <Link className="btn" to="/links/new">Create link</Link>}>
            {status || params.get("q") ? "Try a different search or clear the filters." : "Short links you create appear here."}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Short link</th><th>Destination</th><th>Status</th><th>Last 14 days</th><th className="num">Clicks</th><th></th></tr>
              </thead>
              <tbody>
                {loading && !data && <tr><td colSpan={6} className="muted">Loading links…</td></tr>}
                {data?.items.map((l) => (
                  <tr key={l.id} className="clickable" onClick={() => nav(`/links/${l.id}`)}>
                    <td>
                      <Link to={`/links/${l.id}`} className="code" onClick={(e) => e.stopPropagation()}>/{l.code}</Link>
                      <div className="small muted truncate" style={{ maxWidth: 240 }}>{l.title}</div>
                      <div>{l.campaign && <span className="tag">{l.campaign.name}</span>}<Tags tags={l.tags} /></div>
                    </td>
                    <td><div className="dest truncate">{l.destination}</div>
                      {user.role === "admin" && <div className="small muted">{l.owner_email}</div>}</td>
                    <td><StatusBadge status={l.effective_status} />
                      {l.click_cap && <div className="small muted">{l.click_count}/{l.click_cap} used</div>}</td>
                    <td><Sparkline values={l.spark} /></td>
                    <td className="num">{fmt.format(l.spark.reduce((a, b) => a + b, 0))}<div className="small muted">{fmt.format(l.click_count)} all time</div></td>
                    <td onClick={(e) => e.stopPropagation()}><CopyButton text={l.short_url} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {pages > 1 && (
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn secondary small" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>Previous</button>
          <span className="small muted">Page {page} of {pages}</span>
          <button className="btn secondary small" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>Next</button>
        </div>
      )}
    </>
  );
}
