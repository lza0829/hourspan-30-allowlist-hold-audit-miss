import React from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview.jsx";
import Ingest from "./pages/Ingest.jsx";
import Detect from "./pages/Detect.jsx";
import History from "./pages/History.jsx";
import Current from "./pages/Current.jsx";
import Proofs from "./pages/Proofs.jsx";
import Settings from "./pages/Settings.jsx";

const links = [
  ["/", "总览"],
  ["/ingest", "入档"],
  ["/detect", "变更检测"],
  ["/history", "历史维"],
  ["/current", "当前镜"],
  ["/proofs", "核证"],
  ["/settings", "站规"],
];

export default function App() {
  return (
    <div className="app-shell">
      <aside className="side">
        <div className="brand">
          <div className="mark">时档</div>
          <div className="sub">门店营业维 · Type2 开闭 · 当前镜互证</div>
        </div>
        <nav className="nav">
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/ingest" element={<Ingest />} />
          <Route path="/detect" element={<Detect />} />
          <Route path="/history" element={<History />} />
          <Route path="/current" element={<Current />} />
          <Route path="/proofs" element={<Proofs />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
