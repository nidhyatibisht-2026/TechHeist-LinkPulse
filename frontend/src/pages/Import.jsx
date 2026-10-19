import { useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../api.js";
import { CopyButton, Notice } from "../components/ui.jsx";

const ROW_TONE = { valid: "ok", warning: "warn", error: "bad" };
const ROW_LABEL = { valid: "Ready", warning: "Ready, with a warning", error: "Will be skipped" };

export default function Import() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all");

  async function check(e) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setError(""); setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      setPreview(await api("/api/import/preview", { method: "POST", form }));
    } catch (err) { setError(err.message); setPreview(null); }
    finally { setBusy(false); }
  }

  async function commit() {
    setBusy(true); setError("");
    try {
      const rows = preview.rows.filter((r) => r.status !== "error").map((r) => r.data);
      setResult(await api("/api/import/commit", { method: "POST", body: { rows } }));
      setPreview(null);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const rows = preview?.rows.filter((r) => filter === "all" || r.status === filter) || [];

  return (
    <>
      <div className="page-head">
        <div><h1>Bulk import</h1><p className="muted">Upload a CSV, review every row, then import only the rows that are ready.</p></div>
        <button className="btn secondary" onClick={() => download("/api/import/template", "linkpulse-import-template.csv")}>Download template</button>
      </div>
      <Notice tone="error">{error}</Notice>

      <form className="panel panel-body stack" onSubmit={check} style={{ maxWidth: 760, marginTop: error ? 16 : 0 }}>
        <p className="small muted">
          Columns: <span className="mono">destination</span> (required), <span className="mono">alias</span>, <span className="mono">title</span>, <span className="mono">campaign</span>, <span className="mono">tags</span> (separate with ;), <span className="mono">expires_at</span> (YYYY-MM-DD), <span className="mono">click_cap</span>. Up to 1,000 rows. New campaign and tag names are created for you.
        </p>
        <div className="row">
          <input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files[0] || null); setPreview(null); }} style={{ maxWidth: 360 }} aria-label="CSV file" />
          <button className="btn" disabled={!file || busy}>{busy && !preview ? "Checking…" : "Check file"}</button>
        </div>
      </form>

      {preview && (
        <section className="panel" style={{ marginTop: 20 }}>
          <div className="panel-head">
            <div className="row">
              <h2>{preview.summary.importable} of {preview.summary.total} rows ready</h2>
              {preview.summary.error > 0 && <span className="badge bad">{preview.summary.error} with errors</span>}
              {preview.summary.warning > 0 && <span className="badge warn">{preview.summary.warning} with warnings</span>}
            </div>
            <div className="row">
              <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Show rows" style={{ width: 170 }}>
                <option value="all">All rows</option><option value="error">Errors only</option><option value="warning">Warnings only</option><option value="valid">Ready only</option>
              </select>
              <button className="btn" disabled={busy || preview.summary.importable === 0} onClick={commit}>
                {busy ? "Importing…" : `Import ${preview.summary.importable} links`}
              </button>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Row</th><th>Destination</th><th>Alias</th><th>Campaign</th><th>Status</th><th>Problems</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.row}>
                    <td className="muted">{r.row}</td>
                    <td><div className="dest truncate" style={{ maxWidth: 280 }}>{r.data.destination}</div></td>
                    <td className="code">{r.data.alias ? `/${r.data.alias}` : <span className="muted small">random</span>}</td>
                    <td className="small">{r.data.campaign}</td>
                    <td><span className={`badge ${ROW_TONE[r.status]}`}>{ROW_LABEL[r.status]}</span></td>
                    <td className="small">
                      {r.errors.map((e, i) => <div key={i} style={{ color: "var(--bad)" }}>{e}</div>)}
                      {r.warnings.map((w, i) => <div key={i} style={{ color: "var(--warn)" }}>{w}</div>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {result && (
        <section className="panel" style={{ marginTop: 20 }}>
          <div className="panel-head"><h2>Imported {result.created.length} links</h2><Link to="/links">View all links</Link></div>
          {result.failed.length > 0 && <div className="panel-body"><Notice tone="warning">{result.failed.length} rows were skipped. Fix them in the file and import again.</Notice></div>}
          <div className="table-wrap">
            <table>
              <thead><tr><th>Row</th><th>Short link</th><th></th></tr></thead>
              <tbody>
                {result.created.map((c) => (
                  <tr key={c.id}>
                    <td className="muted">{c.row}</td>
                    <td><Link to={`/links/${c.id}`} className="code">{c.short_url}</Link></td>
                    <td><CopyButton text={c.short_url} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
