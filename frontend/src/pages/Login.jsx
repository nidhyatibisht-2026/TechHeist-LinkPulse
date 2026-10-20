import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { PulseMark } from "../components/Layout.jsx";
import { Notice } from "../components/ui.jsx";

const PULSE = [18, 34, 26, 58, 40, 92, 64, 120, 70, 44, 82, 52, 30, 46, 22];

// Seeded demo accounts (backend/scripts/seed.py), so visitors can try the app in one click.
const DEMO = {
  user: { email: "demo@linkpulse.dev", password: "Demo@12345", label: "Marketing user" },
  admin: { email: "admin@linkpulse.dev", password: "Admin@12345", label: "Admin" },
};

const FEATURES = [
  ["Rules on every redirect", "Expiry, click limits, passwords and device targeting, checked in order."],
  ["Live click analytics", "Devices, sources and campaigns, with bots filtered out."],
  ["One-step takedown", "Disable a bad link or domain; its history stays."],
];

export default function Login() {
  const { user, signIn } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", name: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={location.state?.from || "/"} replace />;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function run(kind, body) {
    setBusy(true);
    setError("");
    try {
      await signIn(kind, body);
      nav(location.state?.from || "/", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function submit(e) {
    e.preventDefault();
    run(mode, mode === "login" ? { email: form.email, password: form.password } : form);
  }

  function tryDemo(kind) {
    const { email, password } = DEMO[kind];
    setMode("login");
    setForm({ email, password, name: "" });
    run("login", { email, password });
  }

  return (
    <div className="auth-page">
      <aside className="auth-side">
        <div className="brand" style={{ padding: 0 }}><PulseMark />LinkPulse</div>
        <div>
          <div className="big-pulse" aria-hidden="true">{PULSE.map((h, i) => <span key={i} style={{ height: h }} />)}</div>
          <h1>Every link, every click, one place.</h1>
          <p>Create short links with rules, see who clicks them, and switch off a bad link in one step.</p>
          <ul className="auth-features">
            {FEATURES.map(([t, d]) => (
              <li key={t}><strong>{t}</strong><span>{d}</span></li>
            ))}
          </ul>
          <button type="button" className="btn demo-cta" disabled={busy} onClick={() => tryDemo("user")}>
            {busy ? "Signing in…" : "Try the live demo →"}
          </button>
        </div>
        <p className="small">Built by TechHeist · short links at lnkp.antideploy.app</p>
      </aside>
      <div className="auth-form">
        <form onSubmit={submit}>
          <h2>{mode === "login" ? "Sign in" : "Create your account"}</h2>
          <Notice tone="error">{error}</Notice>
          {mode === "login" && (
            <div className="demo-box">
              <span className="small muted">Try it with a demo account, one click:</span>
              <div className="demo-buttons">
                {Object.entries(DEMO).map(([kind, d]) => (
                  <button key={kind} type="button" className="btn secondary" disabled={busy} onClick={() => tryDemo(kind)}>
                    {d.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {mode === "register" && (
            <label className="field">Name<input value={form.name} onChange={set("name")} autoComplete="name" /></label>
          )}
          <label className="field">Email<input type="email" required value={form.email} onChange={set("email")} autoComplete="email" /></label>
          <label className="field">
            Password
            <input type="password" required minLength={mode === "register" ? 8 : 1} value={form.password}
              onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} />
            {mode === "register" && <span className="hint">At least 8 characters.</span>}
          </label>
          <button className="btn" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
          <p className="small muted">
            {mode === "login" ? "New to LinkPulse? " : "Already have an account? "}
            <button type="button" className="btn ghost small" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
              {mode === "login" ? "Create an account" : "Sign in"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
