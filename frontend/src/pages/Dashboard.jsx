import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import Report from "../components/Report.jsx";
import { Empty, Notice, PeriodPicker, useLoad } from "../components/ui.jsx";

export default function Dashboard() {
  const { user } = useAuth();
  const [days, setDays] = useState(30);
  const { data, error, loading } = useLoad(() => api(`/api/analytics/overview?days=${days}`), [days]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">
            {user.role === "admin" ? "All links on the platform" : "Your links"}
            {data && <>, {data.total_links} in total</>}
          </p>
        </div>
        <div className="row">
          <PeriodPicker value={days} onChange={setDays} />
          <Link className="btn" to="/links/new">Create link</Link>
        </div>
      </div>
      <Notice tone="error">{error?.message}</Notice>
      {loading && !data && <p className="muted">Loading analytics…</p>}
      {data && data.total_links === 0 ? (
        <div className="panel">
          <Empty title="No links yet" action={<Link className="btn" to="/links/new">Create your first link</Link>}>
            Create a short link and every click on it will show up here.
          </Empty>
        </div>
      ) : data && <Report report={data} />}
    </>
  );
}
