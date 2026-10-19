import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, blobUrl, download } from "../api.js";
import { useAuth } from "../auth.jsx";
import Report from "../components/Report.jsx";
import { CopyButton, Notice, PeriodPicker, StatusBadge, Tags, fmtDate, fromLocalInput, timeAgo, toLocalInput, useLoad } from "../components/ui.jsx";
import { TargetEditor } from "./NewLink.jsx";

const TABS = [["analytics", "Analytics"], ["settings", "Settings"], ["share", "QR code"], ["simulator", "Rule simulator"], ["visits", "Recent visits"]];
const OUTCOME = { redirect: "Redirected", blocked: "Blocked", expired: "Expired", limit: "Limit reached",
                  password_failed: "Wrong password", preview: "Preview card" };

function Analytics({ id }) {
  const [days, setDays] = useState(30);
  const { data, error } = useLoad(() => api(`/api/links/${id}/analytics?days=${days}`), [id, days]);
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}><PeriodPicker value={days} onChange={setDays} /></div>
      <Notice tone="error">{error?.message}</Notice>
      {data ? <Report report={data} showCampaigns={false} showTopLinks={false} /> : <p className="muted">Loading analytics…</p>}
    </div>
  );
}

function Settings({ link, onSaved }) {
  const [f, setF] = useState(() => ({
    title: link.title, destination: link.destination, campaign_id: link.campaign?.id ?? "",
    tag_ids: link.tags.map((t) => t.id), starts_at: toLocalInput(link.starts_at), expires_at: toLocalInput(link.expires_at),
    expired_url: link.expired_url || "", click_cap: link.click_cap ?? "", password: "", remove_password: false,
    targets: link.targets,
  }));
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const campaigns = useLoad(() => api("/api/campaigns"), []);
  const tags = useLoad(() => api("/api/tags"), []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const body = {
        title: f.title, destination: f.destination, campaign_id: f.campaign_id ? Number(f.campaign_id) : null,
        tag_ids: f.tag_ids, starts_at: fromLocalInput(f.starts_at), expires_at: fromLocalInput(f.expires_at),
        expired_url: f.expired_url || null, click_cap: f.click_cap ? Number(f.click_cap) : null,
        targets: f.targets.filter((t) => t.destination).map((t, i) => ({ ...t, priority: i })),
        remove_password: f.remove_password,
        ...(f.password && { password: f.password }),
      };
      onSaved(await api(`/api/links/${link.id}`, { method: "PATCH", body }));
      setMsg(["success", "Changes saved. They apply to the next visit."]);
      setF((x) => ({ ...x, password: "" }));
    } catch (err) {
      setMsg(["error", err.message]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel panel-body stack" onSubmit={save} style={{ maxWidth: 860 }}>
      {msg && <Notice tone={msg[0]}>{msg[1]}</Notice>}
      <div className="form-grid">
        <label className="field full">Destination URL<input value={f.destination} onChange={set("destination")} required /></label>
        <label className="field">Title<input value={f.title} onChange={set("title")} /></label>
        <label className="field">Campaign
          <select value={f.campaign_id} onChange={set("campaign_id")}>
            <option value="">No campaign</option>
            {campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <div className="field full"><span style={{ fontWeight: 500, fontSize: "0.9rem" }}>Tags</span>
          <div className="row">{tags.data?.map((t) => (
            <label key={t.id} className="check"><input type="checkbox" checked={f.tag_ids.includes(t.id)}
              onChange={(e) => setF({ ...f, tag_ids: e.target.checked ? [...f.tag_ids, t.id] : f.tag_ids.filter((x) => x !== t.id) })} />{t.name}</label>
          ))}</div>
        </div>
        <label className="field">Goes live at<input type="datetime-local" value={f.starts_at} onChange={set("starts_at")} /></label>
        <label className="field">Expires at<input type="datetime-local" value={f.expires_at} onChange={set("expires_at")} /></label>
        <label className="field full">After expiry, send visitors to<input value={f.expired_url} onChange={set("expired_url")} placeholder="Show the expired page" /></label>
        <label className="field">Click limit <span className="hint">{link.click_count} used so far</span>
          <input type="number" min={1} value={f.click_cap} onChange={set("click_cap")} placeholder="No limit" /></label>
        <label className="field">{link.has_password ? "New password" : "Password"}
          <input type="password" minLength={4} value={f.password} onChange={set("password")} placeholder={link.has_password ? "Keep current password" : "No password"} autoComplete="new-password" />
          {link.has_password && <span className="check hint"><input type="checkbox" checked={f.remove_password} onChange={(e) => setF({ ...f, remove_password: e.target.checked })} />Remove password protection</span>}
        </label>
        <div className="full"><h3 style={{ marginBottom: 10 }}>Device and location routing</h3>
          <TargetEditor targets={f.targets} onChange={(targets) => setF({ ...f, targets })} /></div>
      </div>
      <div><button className="btn" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button></div>
    </form>
  );
}

function Share({ link }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url;
    blobUrl(`/api/links/${link.id}/qr?fmt=png`).then((u) => { url = u; setSrc(u); }).catch(() => {});
    return () => url && URL.revokeObjectURL(url);
  }, [link.id]);
  return (
    <div className="panel panel-body qr-box">
      {src ? <img src={src} alt={`QR code for ${link.short_url}`} /> : <div style={{ width: 168, height: 168 }} />}
      <div className="stack" style={{ gap: 10, maxWidth: 420 }}>
        <p>The QR code points at your short link, so you can change the destination later without reprinting it.</p>
        <p className="small muted">Scans are reported separately as "QR scans", and every rule applies to them.</p>
        <div className="row">
          <button className="btn secondary small" onClick={() => download(`/api/links/${link.id}/qr?fmt=png&download=true`, `linkpulse-${link.code}.png`)}>Download PNG</button>
          <button className="btn secondary small" onClick={() => download(`/api/links/${link.id}/qr?fmt=svg&download=true`, `linkpulse-${link.code}.svg`)}>Download SVG (for print)</button>
        </div>
      </div>
    </div>
  );
}

function Simulator({ link }) {
  const [input, setInput] = useState({ device: "mobile", os: "ios", country: "IN", password_ok: false, at: "" });
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const set = (k) => (e) => setInput({ ...input, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function run(e) {
    e?.preventDefault();
    setError("");
    try {
      setResult(await api(`/api/links/${link.id}/simulate`, { method: "POST", body: {
        device: input.device, os: input.os, country: input.country || null, password_ok: input.password_ok, at: fromLocalInput(input.at) } }));
    } catch (err) { setError(err.message); }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, [link.id]);

  const byRule = Object.fromEntries((result?.trace || []).map((s) => [s.rule, s]));
  return (
    <div className="grid-2">
      <form className="panel panel-body stack" onSubmit={run}>
        <p className="muted small">Pretend to be a visitor. This runs the same rule engine real visits use, and nothing is counted or logged.</p>
        <div className="form-grid">
          <label className="field">Device<select value={input.device} onChange={set("device")}>{["mobile", "tablet", "desktop"].map((v) => <option key={v}>{v}</option>)}</select></label>
          <label className="field">Operating system<select value={input.os} onChange={set("os")}>{["ios", "android", "windows", "macos", "linux", "other"].map((v) => <option key={v}>{v}</option>)}</select></label>
          <label className="field">Country code<input value={input.country} maxLength={2} onChange={(e) => setInput({ ...input, country: e.target.value.toUpperCase() })} /></label>
          <label className="field">Visit time <span className="hint">Empty means now</span><input type="datetime-local" value={input.at} onChange={set("at")} /></label>
          {link.has_password && <label className="check full"><input type="checkbox" checked={input.password_ok} onChange={set("password_ok")} />Visitor enters the correct password</label>}
        </div>
        <div><button className="btn">Run simulation</button></div>
        <Notice tone="error">{error}</Notice>
      </form>
      <section className="panel panel-body">
        {result && (
          <>
            <ol className="pipeline">
              {result.rule_order.map((r, i) => {
                const step = byRule[r.rule];
                const cls = !step ? "skip" : step.passed ? "pass" : "fail";
                return (
                  <li key={r.rule} className={cls}>
                    <span className="dot">{step ? (step.passed ? "✓" : "✕") : i + 1}</span>
                    <div><div className="title">{r.label}</div><div className="detail">{step ? step.detail : "Not reached"}</div></div>
                  </li>
                );
              })}
            </ol>
            <div className="outcome">
              {result.action === "redirect"
                ? <>Visitor is redirected to <span className="dest" style={{ wordBreak: "break-all" }}>{result.url}</span></>
                : result.url ? <>Visitor is sent to the fallback <span className="dest">{result.url}</span></>
                : <>Visitor sees: <strong>{result.reason}</strong></>}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function Visits({ id }) {
  const { data, error } = useLoad(() => api(`/api/links/${id}/events?limit=100`), [id]);
  return (
    <section className="panel">
      <div className="panel-head"><h2>Recent visits</h2><span className="small muted">Including filtered bots, so you can see why they were excluded</span></div>
      <Notice tone="error">{error?.message}</Notice>
      <div className="table-wrap">
        <table>
          <thead><tr><th>When</th><th>Result</th><th>Visitor</th><th>From</th><th>Country</th><th>Source</th></tr></thead>
          <tbody>
            {data?.length === 0 && <tr><td colSpan={6} className="muted">No visits yet.</td></tr>}
            {data?.map((e, i) => (
              <tr key={i}>
                <td className="nowrap" title={fmtDate(e.ts)}>{timeAgo(e.ts)}</td>
                <td>{OUTCOME[e.outcome] || e.outcome}</td>
                <td>{e.is_bot ? <span className="badge idle" title="Excluded from click counts">Bot: {e.bot_reason}</span>
                  : <span className="small">{e.device}, {e.os}, {e.browser}</span>}</td>
                <td className="small">{e.referrer}</td>
                <td>{e.country}</td>
                <td>{e.source === "qr" ? "QR scan" : "Link"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function LinkDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const [tab, setTab] = useState("analytics");
  const { data, error, reload } = useLoad(() => api(`/api/links/${id}`), [id]);
  const [link, setLink] = useState(null);
  const [msg, setMsg] = useState(null);
  const [disableReason, setDisableReason] = useState("");
  useEffect(() => { if (data) setLink(data); }, [data]);

  if (error) return <Notice tone="error">{error.status === 404 ? "This link doesn't exist or belongs to someone else." : error.message}</Notice>;
  if (!link) return <p className="muted">Loading link…</p>;

  async function act(fn, ok) {
    setMsg(null);
    try { const res = await fn(); if (res?.id) setLink(res); else reload(); setMsg(["success", ok]); }
    catch (err) { setMsg(["error", err.message]); }
  }
  const canEdit = link.status !== "disabled" || user.role === "admin";

  return (
    <>
      <div className="page-head">
        <div>
          <div className="row"><h1 className="code" style={{ fontSize: "1.6rem" }}>/{link.code}</h1><StatusBadge status={link.effective_status} /></div>
          <p className="muted">{link.title || "Untitled link"}{link.campaign && <> in <Link to={`/campaigns/${link.campaign.id}`}>{link.campaign.name}</Link></>}</p>
          <div style={{ marginTop: 6 }}><Tags tags={link.tags} /></div>
        </div>
        <div className="row">
          <CopyButton text={link.short_url} label="Copy short link" />
          {canEdit && link.status === "active" && <button className="btn secondary small" onClick={() => act(() => api(`/api/links/${id}`, { method: "PATCH", body: { status: "paused" } }), "Link paused. Visitors now see a paused page.")}>Pause</button>}
          {canEdit && ["paused", "archived"].includes(link.status) && <button className="btn secondary small" onClick={() => act(() => api(`/api/links/${id}`, { method: "PATCH", body: { status: "active" } }), "Link is live again.")}>Resume</button>}
          {canEdit && link.status !== "archived" && <button className="btn secondary small" onClick={() => window.confirm("Archive this link? It stops working, but its analytics are kept.") && act(() => api(`/api/links/${id}`, { method: "DELETE" }), "Link archived.").then(() => nav("/links"))}>Archive</button>}
        </div>
      </div>

      {msg && <div style={{ marginBottom: 16 }}><Notice tone={msg[0]}>{msg[1]}</Notice></div>}
      {link.status === "disabled" && <div style={{ marginBottom: 16 }}><Notice tone="error">Disabled by an administrator: {link.disabled_reason}</Notice></div>}
      {link.health_status === "broken" && <div style={{ marginBottom: 16 }}><Notice tone="warning">The destination looks broken ({link.health_detail}). Checked {timeAgo(link.health_checked_at)}.</Notice></div>}

      <div className="panel panel-body" style={{ marginBottom: 20 }}>
        <div className="grid-3">
          <div><div className="small muted">Destination</div><a className="dest" style={{ wordBreak: "break-all" }} href={link.destination} target="_blank" rel="noreferrer">{link.destination}</a></div>
          <div><div className="small muted">Rules</div><div className="small">
            {link.has_password && <div>Password protected</div>}
            {link.click_cap && <div>{link.click_count} of {link.click_cap} clicks used</div>}
            {link.starts_at && <div>Live from {fmtDate(link.starts_at)}</div>}
            {link.expires_at && <div>Expires {fmtDate(link.expires_at)}</div>}
            {link.targets.length > 0 && <div>{link.targets.length} routing rule{link.targets.length > 1 ? "s" : ""}</div>}
            {!link.has_password && !link.click_cap && !link.expires_at && !link.starts_at && !link.targets.length && <div className="muted">None. Every visitor is redirected.</div>}
          </div></div>
          <div><div className="small muted">Created</div><div className="small">{fmtDate(link.created_at, false)}{user.role === "admin" && <> by {link.owner_email}</>}</div></div>
        </div>
      </div>

      {user.role === "admin" && (
        <div className="panel panel-body row" style={{ marginBottom: 20, justifyContent: "space-between" }}>
          <div><h3>Administrator</h3><p className="small muted">Disabling stops redirects on the very next visit. Analytics are kept.</p></div>
          {link.status === "disabled" ? (
            <button className="btn secondary" onClick={() => act(() => api(`/api/admin/links/${id}/enable`, { method: "POST" }), "Link enabled.")}>Enable link</button>
          ) : (
            <div className="row">
              <input placeholder="Reason, for example a phishing report" value={disableReason} onChange={(e) => setDisableReason(e.target.value)} style={{ width: 280 }} aria-label="Reason for disabling" />
              <button className="btn danger" disabled={disableReason.trim().length < 3}
                onClick={() => act(() => api(`/api/admin/links/${id}/disable`, { method: "POST", body: { reason: disableReason } }), "Link disabled. Redirects stopped.")}>Disable link</button>
            </div>
          )}
        </div>
      )}

      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>)}
      </div>
      {tab === "analytics" && <Analytics id={id} />}
      {tab === "settings" && (canEdit ? <Settings key={link.updated_at} link={link} onSaved={setLink} /> : <Notice tone="error">An administrator disabled this link, so it can't be edited.</Notice>)}
      {tab === "share" && <Share link={link} />}
      {tab === "simulator" && <Simulator link={link} />}
      {tab === "visits" && <Visits id={id} />}
    </>
  );
}
