import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Notice, StatusBadge, fmtDate, useLoad } from "../components/ui.jsx";

function Users() {
  const { user: me } = useAuth();
  const { data, reload } = useLoad(() => api("/api/admin/users"), []);
  const [msg, setMsg] = useState(null);
  async function setRole(u, role) {
    try { await api(`/api/admin/users/${u.id}/role`, { method: "PATCH", body: { role } }); reload(); }
    catch (err) { setMsg(err.message); }
  }
  return (
    <section className="panel">
      <Notice tone="error">{msg}</Notice>
      <div className="table-wrap"><table>
        <thead><tr><th>User</th><th>Role</th><th>Joined</th><th></th></tr></thead>
        <tbody>{data?.map((u) => (
          <tr key={u.id}>
            <td>{u.name || u.email}<div className="small muted">{u.email}</div></td>
            <td>{u.role === "admin" ? "Administrator" : "Member"}</td>
            <td className="small">{fmtDate(u.created_at, false)}</td>
            <td>{u.id !== me.id && (
              <button className="btn secondary small" onClick={() => setRole(u, u.role === "admin" ? "user" : "admin")}>
                {u.role === "admin" ? "Make member" : "Make administrator"}
              </button>
            )}</td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}

function Blocklist() {
  const { data, reload } = useLoad(() => api("/api/admin/blocklist"), []);
  const [form, setForm] = useState({ domain: "", reason: "", disable_existing: true });
  const [msg, setMsg] = useState(null);
  async function add(e) {
    e.preventDefault();
    setMsg(null);
    try {
      const r = await api("/api/admin/blocklist", { method: "POST", body: form });
      setMsg(["success", `${r.domain} blocked. ${r.affected_links} existing link${r.affected_links === 1 ? "" : "s"} stopped redirecting${r.disabled ? " and were marked disabled" : ""}.`]);
      setForm({ domain: "", reason: "", disable_existing: true });
      reload();
    } catch (err) { setMsg(["error", err.message]); }
  }
  async function remove(b) {
    if (!window.confirm(`Unblock ${b.domain}? New links to it will be allowed again.`)) return;
    try { await api(`/api/admin/blocklist/${b.id}`, { method: "DELETE" }); reload(); }
    catch (err) { setMsg(["error", err.message]); }
  }
  return (
    <div className="stack">
      <form className="panel panel-body stack" onSubmit={add} style={{ gap: 14 }}>
        <p className="small muted">Blocking a domain also blocks its subdomains. Links to it can't be created, and existing links stop redirecting immediately.</p>
        <div className="form-grid">
          <label className="field">Domain<input required value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} placeholder="phishing-site.com" /></label>
          <label className="field">Reason<input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="Reported phishing" /></label>
          <label className="check full"><input type="checkbox" checked={form.disable_existing} onChange={(e) => setForm({ ...form, disable_existing: e.target.checked })} />Also mark existing links to this domain as disabled, so their owners can see why</label>
        </div>
        {msg && <Notice tone={msg[0]}>{msg[1]}</Notice>}
        <div><button className="btn danger">Block domain</button></div>
      </form>
      <section className="panel"><div className="table-wrap"><table>
        <thead><tr><th>Domain</th><th>Reason</th><th>Added</th><th></th></tr></thead>
        <tbody>
          {data?.length === 0 && <tr><td colSpan={4} className="muted">No blocked domains.</td></tr>}
          {data?.map((b) => (
            <tr key={b.id}><td className="mono">{b.domain}</td><td className="small">{b.reason}</td><td className="small">{fmtDate(b.created_at, false)}</td>
              <td><button className="btn ghost small" onClick={() => remove(b)}>Unblock</button></td></tr>
          ))}
        </tbody>
      </table></div></section>
    </div>
  );
}

function Moderation() {
  const disabled = useLoad(() => api("/api/links?status=disabled&page_size=100"), []);
  const report = useLoad(() => api("/api/analytics/overview?days=7"), []);
  const risky = (report.data?.alerts || []).filter((a) => ["disabled_traffic", "password_attempts", "spike", "bot_heavy", "broken_destination"].includes(a.kind));
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head"><h2>Signals worth reviewing</h2><span className="small muted">Last 7 days, platform-wide</span></div>
        {risky.length === 0 ? <p className="panel-body small muted">Nothing unusual right now.</p> : risky.map((a, i) => (
          <div className="alert-row" key={i}>
            <span className={`badge ${a.severity === "high" ? "bad" : a.severity === "medium" ? "warn" : "idle"}`}>{a.kind.replace(/_/g, " ")}</span>
            <span><Link to={`/links/${a.link_id}`} className="code">/{a.code}</Link> <span className="muted">{a.message}</span></span>
            <Link to={`/links/${a.link_id}`} className="btn secondary small">Review</Link>
          </div>
        ))}
      </section>
      <section className="panel">
        <div className="panel-head"><h2>Disabled links</h2></div>
        <div className="table-wrap"><table>
          <thead><tr><th>Link</th><th>Owner</th><th>Reason</th><th>Status</th></tr></thead>
          <tbody>
            {disabled.data?.items.length === 0 && <tr><td colSpan={4} className="muted">No disabled links.</td></tr>}
            {disabled.data?.items.map((l) => (
              <tr key={l.id}><td><Link to={`/links/${l.id}`} className="code">/{l.code}</Link><div className="dest truncate">{l.destination}</div></td>
                <td className="small">{l.owner_email}</td><td className="small">{l.disabled_reason}</td><td><StatusBadge status={l.effective_status} /></td></tr>
            ))}
          </tbody>
        </table></div>
      </section>
    </div>
  );
}

function Audit() {
  const { data } = useLoad(() => api("/api/admin/audit?limit=200"), []);
  return (
    <section className="panel"><div className="table-wrap"><table>
      <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
      <tbody>
        {data?.length === 0 && <tr><td colSpan={5} className="muted">No actions recorded yet.</td></tr>}
        {data?.map((a) => (
          <tr key={a.id}><td className="small nowrap">{fmtDate(a.created_at)}</td><td className="small">{a.actor}</td>
            <td className="mono small">{a.action}</td><td className="small">{a.target_type} {a.target_id}</td><td className="small">{a.detail}</td></tr>
        ))}
      </tbody>
    </table></div></section>
  );
}

const TABS = [["moderation", "Moderation", Moderation], ["blocklist", "Domain blocklist", Blocklist], ["users", "Users", Users], ["audit", "Audit log", Audit]];

export default function Admin() {
  const [tab, setTab] = useState("moderation");
  const Current = TABS.find((t) => t[0] === tab)[2];
  return (
    <>
      <div className="page-head"><div><h1>Admin</h1><p className="muted">Platform safety, users and a record of every admin action.</p></div></div>
      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>)}
      </div>
      <Current />
    </>
  );
}
