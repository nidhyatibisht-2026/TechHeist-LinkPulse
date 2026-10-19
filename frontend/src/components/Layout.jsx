import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth.jsx";

const icon = (d) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);

const NAV = [
  { to: "/", label: "Dashboard", end: true, d: "M3 12h4l3-8 4 16 3-8h4" },
  { to: "/links", label: "Links", d: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" },
  { to: "/campaigns", label: "Campaigns", d: "M4 5h16M4 12h10M4 19h6" },
  { to: "/import", label: "Bulk import", d: "M12 4v11m0 0-4-4m4 4 4-4M5 20h14" },
];

export function PulseMark({ heights = [7, 13, 20, 10] }) {
  return (
    <span className="pulse-mark" aria-hidden="true">
      {heights.map((h, i) => <span key={i} style={{ height: h }} />)}
    </span>
  );
}

export default function Layout() {
  const { user, signOut } = useAuth();
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <NavLink to="/" className="brand"><PulseMark />LinkPulse</NavLink>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className="nav-link">{icon(n.d)}{n.label}</NavLink>
        ))}
        {user?.role === "admin" && (
          <NavLink to="/admin" className="nav-link">{icon("M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z")}Admin</NavLink>
        )}
        <div className="nav-gap" />
        <div className="whoami">
          <strong>{user?.name || user?.email}</strong>
          {user?.role === "admin" ? "Administrator" : "Member"}
          <br />
          <button type="button" onClick={signOut}>Sign out</button>
        </div>
      </nav>
      <main className="main" id="content"><Outlet /></main>
    </div>
  );
}
