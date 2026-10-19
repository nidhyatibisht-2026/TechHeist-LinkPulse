import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import Report from "../components/Report.jsx";
import { Notice, PeriodPicker, useLoad } from "../components/ui.jsx";

export default function CampaignDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [days, setDays] = useState(30);
  const { data, error } = useLoad(() => api(`/api/campaigns/${id}?days=${days}`), [id, days]);

  async function remove() {
    if (!window.confirm("Delete this campaign? Its links keep working and keep their analytics.")) return;
    await api(`/api/campaigns/${id}`, { method: "DELETE" });
    nav("/campaigns");
  }

  if (error) return <Notice tone="error">{error.status === 404 ? "This campaign doesn't exist or belongs to someone else." : error.message}</Notice>;
  if (!data) return <p className="muted">Loading campaign…</p>;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{data.name}</h1>
          <p className="muted">{data.description || "No description"}</p>
          {(data.utm_source || data.utm_medium || data.utm_campaign) &&
            <p className="small mono muted" style={{ marginTop: 4 }}>{[data.utm_source, data.utm_medium, data.utm_campaign].filter(Boolean).join(" / ")}</p>}
        </div>
        <div className="row">
          <PeriodPicker value={days} onChange={setDays} />
          <Link className="btn secondary" to={`/links?campaign_id=${id}`}>View {data.links} links</Link>
          <button className="btn secondary" onClick={remove}>Delete campaign</button>
        </div>
      </div>
      <Report report={data.report} showCampaigns={false} />
    </>
  );
}
