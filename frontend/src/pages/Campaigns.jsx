import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { Empty, Notice, fmt, useLoad } from "../components/ui.jsx";

const TAG_COLORS = ["#0B7FB5", "#1F8A5B", "#A86B12", "#B4362A", "#6B4FA0", "#C13584", "#5B6B7E"];

export default function Campaigns() {
  const nav = useNavigate();
  const campaigns = useLoad(() => api("/api/campaigns"), []);
  const tags = useLoad(() => api("/api/tags"), []);
  const [form, setForm] = useState({ name: "", description: "", utm_source: "", utm_medium: "", utm_campaign: "" });
  const [tag, setTag] = useState({ name: "", color: TAG_COLORS[0] });
  const [msg, setMsg] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function createCampaign(e) {
    e.preventDefault();
    setMsg(null);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || (k === "name" || k === "description" ? v : null)]));
      await api("/api/campaigns", { method: "POST", body });
      setForm({ name: "", description: "", utm_source: "", utm_medium: "", utm_campaign: "" });
      campaigns.reload();
      setMsg(["success", "Campaign created."]);
    } catch (err) { setMsg(["error", err.message]); }
  }

  async function createTag(e) {
    e.preventDefault();
    setMsg(null);
    try {
      await api("/api/tags", { method: "POST", body: tag });
      setTag({ name: "", color: tag.color });
      tags.reload();
    } catch (err) { setMsg(["error", err.message]); }
  }

  async function removeTag(t) {
    if (!window.confirm(`Delete the tag "${t.name}"? Links keep working; they just lose this tag.`)) return;
    try { await api(`/api/tags/${t.id}`, { method: "DELETE" }); tags.reload(); }
    catch (err) { setMsg(["error", err.message]); }
  }

  return (
    <>
      <div className="page-head"><div><h1>Campaigns and tags</h1><p className="muted">Group links to compare how each push performs.</p></div></div>
      {msg && <div style={{ marginBottom: 16 }}><Notice tone={msg[0]}>{msg[1]}</Notice></div>}
      <div className="stack">
        <section className="panel">
          <div className="panel-head"><h2>Campaigns</h2></div>
          {campaigns.data?.length === 0 ? (
            <Empty title="No campaigns yet">Create one below, then pick it when you create links.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Name</th><th>Default UTM</th><th className="num">Links</th><th className="num">Clicks</th><th className="num">Unique</th></tr></thead>
                <tbody>
                  {campaigns.data?.map((c) => (
                    <tr key={c.id} className="clickable" onClick={() => nav(`/campaigns/${c.id}`)}>
                      <td><Link to={`/campaigns/${c.id}`} onClick={(e) => e.stopPropagation()}>{c.name}</Link><div className="small muted truncate" style={{ maxWidth: 320 }}>{c.description}</div></td>
                      <td className="small mono muted">{[c.utm_source, c.utm_medium, c.utm_campaign].filter(Boolean).join(" / ") || "None"}</td>
                      <td className="num">{c.links}</td>
                      <td className="num">{fmt.format(c.clicks)}</td>
                      <td className="num">{fmt.format(c.unique)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <div className="grid-2">
          <form className="panel" onSubmit={createCampaign}>
            <div className="panel-head"><h2>New campaign</h2></div>
            <div className="panel-body stack" style={{ gap: 14 }}>
              <label className="field">Name<input required value={form.name} onChange={set("name")} placeholder="Diwali Sale 2026" /></label>
              <label className="field">Description<input value={form.description} onChange={set("description")} /></label>
              <p className="small muted">Default UTM tags are added to links in this campaign unless you change them in the wizard.</p>
              <div className="form-grid">
                <label className="field">UTM source<input value={form.utm_source} onChange={set("utm_source")} placeholder="instagram" /></label>
                <label className="field">UTM medium<input value={form.utm_medium} onChange={set("utm_medium")} placeholder="social" /></label>
                <label className="field full">UTM campaign<input value={form.utm_campaign} onChange={set("utm_campaign")} placeholder="diwali_2026" /></label>
              </div>
              <div><button className="btn">Create campaign</button></div>
            </div>
          </form>

          <section className="panel">
            <div className="panel-head"><h2>Tags</h2></div>
            <div className="panel-body stack" style={{ gap: 14 }}>
              <div className="row">
                {tags.data?.length ? tags.data.map((t) => (
                  <span key={t.id} className="tag" style={{ fontSize: "0.85rem", padding: "3px 8px" }}>
                    <i style={{ background: t.color }} />{t.name}
                    <button type="button" className="btn ghost small" style={{ padding: "0 0 0 6px" }} onClick={() => removeTag(t)} aria-label={`Delete tag ${t.name}`}>✕</button>
                  </span>
                )) : <span className="small muted">No tags yet.</span>}
              </div>
              <form className="row" onSubmit={createTag}>
                <input required value={tag.name} onChange={(e) => setTag({ ...tag, name: e.target.value })} placeholder="New tag" style={{ maxWidth: 200 }} aria-label="Tag name" />
                <div className="row" role="radiogroup" aria-label="Tag colour" style={{ gap: 6 }}>
                  {TAG_COLORS.map((c) => (
                    <button key={c} type="button" role="radio" aria-checked={tag.color === c} aria-label={c} onClick={() => setTag({ ...tag, color: c })}
                      style={{ width: 22, height: 22, borderRadius: 4, background: c, cursor: "pointer", border: tag.color === c ? "2px solid var(--text)" : "2px solid transparent" }} />
                  ))}
                </div>
                <button className="btn secondary small">Add tag</button>
              </form>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
