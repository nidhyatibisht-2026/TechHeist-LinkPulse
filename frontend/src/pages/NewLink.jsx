import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { API_URL, api, blobUrl, download } from "../api.js";
import { CopyButton, Issues, Notice, fromLocalInput, useLoad } from "../components/ui.jsx";

const DEVICE_VALUES = ["mobile", "tablet", "desktop"];
const OS_VALUES = ["ios", "android", "windows", "macos", "linux"];
const UTM_KEYS = [["utm_source", "Source", "instagram"], ["utm_medium", "Medium", "social"], ["utm_campaign", "Campaign", "diwali_2026"]];

function withUtm(url, utm) {
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(url) ? url : `https://${url}`);
    Object.entries(utm).forEach(([k, v]) => v?.trim() && u.searchParams.set(k, v.trim()));
    return u.toString();
  } catch {
    return url;
  }
}

export function TargetEditor({ targets, onChange }) {
  const set = (i, patch) => onChange(targets.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  return (
    <div className="stack" style={{ gap: 10 }}>
      {targets.map((t, i) => (
        <div key={i} className="row" style={{ alignItems: "flex-end" }}>
          <label className="field" style={{ width: 120 }}>When
            <select value={t.kind} onChange={(e) => set(i, { kind: e.target.value, value: e.target.value === "device" ? "mobile" : e.target.value === "os" ? "ios" : "" })}>
              <option value="device">Device</option><option value="os">OS</option><option value="country">Country</option>
            </select>
          </label>
          <label className="field" style={{ width: 130 }}>is
            {t.kind === "country" ? (
              <input value={t.value} maxLength={2} placeholder="IN" onChange={(e) => set(i, { value: e.target.value.toUpperCase() })} />
            ) : (
              <select value={t.value} onChange={(e) => set(i, { value: e.target.value })}>
                {(t.kind === "device" ? DEVICE_VALUES : OS_VALUES).map((v) => <option key={v}>{v}</option>)}
              </select>
            )}
          </label>
          <label className="field" style={{ flex: 1, minWidth: 220 }}>send visitors to
            <input value={t.destination} placeholder="https://apps.apple.com/…" onChange={(e) => set(i, { destination: e.target.value })} />
          </label>
          <button type="button" className="btn ghost small" onClick={() => onChange(targets.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <div>
        <button type="button" className="btn secondary small"
          onClick={() => onChange([...targets, { kind: "os", value: "ios", destination: "", priority: targets.length }])}>
          Add routing rule
        </button>
      </div>
      {targets.length > 0 && <p className="small muted">Rules are checked top to bottom; the first match wins. Everyone else goes to the main destination.</p>}
    </div>
  );
}

export default function NewLink() {
  const nav = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({ destination: "", alias: "", title: "" });
  const [opts, setOpts] = useState({ campaign_id: "", tag_ids: [], expires_at: "", expired_url: "", starts_at: "",
                                     click_cap: "", password: "", targets: [] });
  const [utm, setUtm] = useState({ utm_source: "", utm_medium: "", utm_campaign: "" });
  const [check, setCheck] = useState(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [created, setCreated] = useState(null);
  const [qr, setQr] = useState(null);

  const campaigns = useLoad(() => api("/api/campaigns"), []);
  const tags = useLoad(() => api("/api/tags"), []);

  // Picking a campaign pre-fills its UTM defaults (users can still edit them).
  useEffect(() => {
    const c = campaigns.data?.find((x) => String(x.id) === String(opts.campaign_id));
    if (c) setUtm({ utm_source: c.utm_source || "", utm_medium: c.utm_medium || "", utm_campaign: c.utm_campaign || "" });
  }, [opts.campaign_id, campaigns.data]);

  const finalUrl = useMemo(() => withUtm(check?.destination || form.destination, utm), [check, form.destination, utm]);
  const setF = (k) => (e) => { setForm({ ...form, [k]: e.target.value }); setCheck(null); };
  const setO = (k) => (e) => setOpts({ ...opts, [k]: e.target.value });

  async function runCheck(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api("/api/links/validate", { method: "POST", body: { destination: form.destination, alias: form.alias || null } });
      setCheck(res);
      setAck(false);
      if (res.ok) setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function publish(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      destination: check.destination,
      alias: form.alias || null,
      title: form.title,
      campaign_id: opts.campaign_id ? Number(opts.campaign_id) : null,
      tag_ids: opts.tag_ids,
      expires_at: fromLocalInput(opts.expires_at),
      expired_url: opts.expired_url || null,
      starts_at: fromLocalInput(opts.starts_at),
      click_cap: opts.click_cap ? Number(opts.click_cap) : null,
      password: opts.password || null,
      targets: opts.targets.filter((t) => t.destination).map((t, i) => ({ ...t, priority: i })),
      utm: Object.values(utm).some((v) => v.trim()) ? utm : null,
    };
    try {
      const link = await api("/api/links", { method: "POST", body });
      setCreated(link);
      setStep(3);
      setQr(await blobUrl(`/api/links/${link.id}/qr?fmt=png`));
    } catch (err) {
      setError(err.body?.detail?.errors?.length ? err.body.detail : err.message);
      if (err.body?.detail?.errors?.some((x) => x.field === "alias")) setStep(1);
    } finally {
      setBusy(false);
    }
  }

  const warnings = check?.warnings || [];
  const steps = [["Destination", 1], ["Options and review", 2], ["Share", 3]];

  return (
    <>
      <div className="page-head">
        <div><h1>Create link</h1><p className="muted">Problems are checked before anything is published.</p></div>
        <Link to="/links" className="btn secondary">Cancel</Link>
      </div>
      <div className="steps" aria-label="Progress">
        {steps.map(([label, n]) => (
          <div key={n} className={step === n ? "current" : step > n ? "done" : ""}><b>{step > n ? "✓" : n}</b>{label}</div>
        ))}
      </div>

      {typeof error === "string" && <Notice tone="error">{error}</Notice>}
      {error?.errors && <div className="notice error"><Issues errors={error.errors} /></div>}

      {step === 1 && (
        <form className="panel panel-body stack" onSubmit={runCheck} style={{ maxWidth: 720 }}>
          <label className="field">Destination URL
            <input value={form.destination} onChange={setF("destination")} required autoFocus placeholder="https://example.com/landing-page" />
          </label>
          <label className="field">Custom alias <span className="hint">Optional. Leave empty for a random 7-character code. Not case-sensitive.</span>
            <div className="input-prefix"><span>{API_URL.replace(/^https?:\/\//, "")}/</span>
              <input value={form.alias} onChange={setF("alias")} placeholder="summer-sale" maxLength={50} /></div>
          </label>
          <label className="field">Title <span className="hint">Only you see this.</span>
            <input value={form.title} onChange={setF("title")} maxLength={200} placeholder="Summer sale, Instagram bio" />
          </label>
          {check && !check.ok && <div className="notice error"><Issues errors={check.errors} warnings={check.warnings} /></div>}
          <div><button className="btn" disabled={busy}>{busy ? "Checking…" : "Check and continue"}</button></div>
        </form>
      )}

      {step === 2 && check && (
        <form className="stack" onSubmit={publish} style={{ maxWidth: 860 }}>
          <section className="panel">
            <div className="panel-head"><h2>Organize</h2></div>
            <div className="panel-body form-grid">
              <label className="field">Campaign
                <select value={opts.campaign_id} onChange={setO("campaign_id")}>
                  <option value="">No campaign</option>
                  {campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              <div className="field"><span style={{ fontWeight: 500, fontSize: "0.9rem" }}>Tags</span>
                <div className="row">
                  {tags.data?.length ? tags.data.map((t) => (
                    <label key={t.id} className="check">
                      <input type="checkbox" checked={opts.tag_ids.includes(t.id)}
                        onChange={(e) => setOpts({ ...opts, tag_ids: e.target.checked ? [...opts.tag_ids, t.id] : opts.tag_ids.filter((x) => x !== t.id) })} />
                      {t.name}
                    </label>
                  )) : <span className="small muted">No tags yet. Add them on the Campaigns page.</span>}
                </div>
              </div>
              {UTM_KEYS.map(([k, label, ph]) => (
                <label key={k} className="field">UTM {label.toLowerCase()}
                  <input value={utm[k]} placeholder={ph} onChange={(e) => setUtm({ ...utm, [k]: e.target.value })} />
                </label>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head"><h2>Rules</h2><span className="small muted">Checked on every visit, in this order</span></div>
            <div className="panel-body form-grid">
              <label className="field">Goes live at <span className="hint">Optional</span>
                <input type="datetime-local" value={opts.starts_at} onChange={setO("starts_at")} />
              </label>
              <label className="field">Expires at <span className="hint">Optional</span>
                <input type="datetime-local" value={opts.expires_at} onChange={setO("expires_at")} />
              </label>
              <label className="field full">After expiry, send visitors to <span className="hint">Optional. Without it, visitors see an "expired" page.</span>
                <input value={opts.expired_url} onChange={setO("expired_url")} placeholder="https://example.com/offer-ended" disabled={!opts.expires_at} />
              </label>
              <label className="field">Click limit <span className="hint">Bots never count toward it.</span>
                <input type="number" min={1} value={opts.click_cap} onChange={setO("click_cap")} placeholder="No limit" />
              </label>
              <label className="field">Password <span className="hint">Visitors must enter it first.</span>
                <input type="password" minLength={4} value={opts.password} onChange={setO("password")} autoComplete="new-password" placeholder="No password" />
              </label>
              <div className="full">
                <h3 style={{ marginBottom: 10 }}>Device and location routing</h3>
                <TargetEditor targets={opts.targets} onChange={(targets) => setOpts({ ...opts, targets })} />
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panel-head"><h2>Review</h2></div>
            <div className="panel-body stack" style={{ gap: 12 }}>
              <div><div className="small muted">Short link</div><div className="code">{check.preview_short_url}</div></div>
              <div><div className="small muted">Visitors go to</div><div className="dest" style={{ maxWidth: "100%", wordBreak: "break-all" }}>{finalUrl}</div></div>
              {warnings.length > 0 && (
                <div className="notice warning stack" style={{ gap: 10 }}>
                  <Issues warnings={warnings} />
                  <label className="check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I've reviewed these warnings</label>
                </div>
              )}
              <div className="row">
                <button type="button" className="btn secondary" onClick={() => setStep(1)}>Back</button>
                <button className="btn" disabled={busy || (warnings.length > 0 && !ack)}>{busy ? "Publishing…" : "Publish link"}</button>
              </div>
            </div>
          </section>
        </form>
      )}

      {step === 3 && created && (
        <section className="panel panel-body stack" style={{ maxWidth: 720 }}>
          <Notice tone="success">Published. The link works now.</Notice>
          <div className="copy-line"><span className="code truncate">{created.short_url}</span><CopyButton text={created.short_url} /></div>
          <div className="qr-box">
            {qr && <img src={qr} alt={`QR code for ${created.short_url}`} />}
            <div className="stack" style={{ gap: 10 }}>
              <p className="muted small">Scans are tracked separately from clicks, and every rule applies to them too.</p>
              <div className="row">
                <button type="button" className="btn secondary small" onClick={() => download(`/api/links/${created.id}/qr?fmt=png&download=true`, `linkpulse-${created.code}.png`)}>Download PNG</button>
                <button type="button" className="btn secondary small" onClick={() => download(`/api/links/${created.id}/qr?fmt=svg&download=true`, `linkpulse-${created.code}.svg`)}>Download SVG</button>
              </div>
            </div>
          </div>
          <div className="row">
            <button className="btn" onClick={() => nav(`/links/${created.id}`)}>Open link details</button>
            <button className="btn secondary" onClick={() => window.location.reload()}>Create another</button>
          </div>
        </section>
      )}
    </>
  );
}
