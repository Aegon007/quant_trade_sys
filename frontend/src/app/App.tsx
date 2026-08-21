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
  { key: "dashboard", label: "决策首页", detail: "买、卖、等" },
  { key: "portfolio", label: "持仓账户", detail: "仓位与流水" },
  { key: "core", label: "核心ETF", detail: "配置与轮动" },
  { key: "satellite", label: "卫星雷达", detail: "前三候选" },
  { key: "risk", label: "风险纪律", detail: "最终门控" },
  { key: "monitor", label: "盘中监控", detail: "紧急信号" },
  { key: "research", label: "模型研究", detail: "质量治理" },
  { key: "operations", label: "运行操作", detail: "任务与导入" },
  { key: "settings", label: "系统设置", detail: "全部配置" },
];

export default function App() {
  const [active, setActive] = useState<PageKey>("dashboard");
  const meta = pages.find((page) => page.key === active) ?? pages[0];
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>Quant Trade</span>
          <b>交易辅助系统</b>
          <small>长期逻辑优先，入场时机其次，风险永远在前。</small>
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
            <span className="eyebrow">个人量化投研与交易决策工作台</span>
            <h1>{meta.label}</h1>
          </div>
          <p>后台任务负责计算稳定快照，前端只读取结果，尽量保持快速和可信。</p>
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
