import { useState } from "react";
import CoreEtfs from "../pages/CoreEtfs";
import Dashboard from "../pages/Dashboard";
import MarketMonitor from "../pages/MarketMonitor";
import Operations from "../pages/Operations";
import Portfolio from "../pages/Portfolio";
import ResearchModels from "../pages/ResearchModels";
import RiskDiscipline from "../pages/RiskDiscipline";
import SatelliteRadar from "../pages/SatelliteRadar";
import Settings from "../pages/Settings";

type PageKey = "dashboard" | "portfolio" | "core" | "satellite" | "risk" | "monitor" | "research" | "operations" | "settings";

const pages: Array<{ key: PageKey; label: string; detail: string }> = [
  { key: "dashboard", label: "Decision Brief", detail: "Act or wait" },
  { key: "portfolio", label: "Portfolio", detail: "Positions" },
  { key: "core", label: "Core ETFs", detail: "Allocation" },
  { key: "satellite", label: "Satellite Radar", detail: "Top 3" },
  { key: "risk", label: "Risk & Discipline", detail: "Final gate" },
  { key: "monitor", label: "Market Monitor", detail: "Intraday" },
  { key: "research", label: "Research & Models", detail: "Governance" },
  { key: "operations", label: "Operations", detail: "Jobs" },
  { key: "settings", label: "Settings", detail: "All config" },
];

export default function App() {
  const [active, setActive] = useState<PageKey>("dashboard");
  const meta = pages.find((page) => page.key === active) ?? pages[0];
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>Quant Trade</span>
          <b>Decision System</b>
          <small>Long horizon first. Timing second. Risk always.</small>
        </div>
        <nav>
          {pages.map((page) => (
            <button key={page.key} className={page.key === active ? "active" : ""} onClick={() => setActive(page.key)}>
              <b>{page.label}</b><span>{page.detail}</span>
            </button>
          ))}
        </nav>
      </aside>
      <section className="content">
        <header className="topbar">
          <div>
            <span className="eyebrow">Personal research and decision workbench</span>
            <h1>{meta.label}</h1>
          </div>
          <p>Heavy jobs write stable snapshots. This interface reads them immediately.</p>
        </header>
        {active === "dashboard" ? <Dashboard /> : null}
        {active === "portfolio" ? <Portfolio /> : null}
        {active === "core" ? <CoreEtfs /> : null}
        {active === "satellite" ? <SatelliteRadar /> : null}
        {active === "risk" ? <RiskDiscipline /> : null}
        {active === "monitor" ? <MarketMonitor /> : null}
        {active === "research" ? <ResearchModels /> : null}
        {active === "operations" ? <Operations /> : null}
        {active === "settings" ? <Settings /> : null}
      </section>
    </main>
  );
}
