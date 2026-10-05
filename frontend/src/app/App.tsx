import { useState } from "react";
import Dashboard from "../pages/Dashboard";
import Opportunities from "../pages/Opportunities";
import Valuation from "../pages/Valuation";
import MarketRisk from "../pages/MarketRisk";
import System from "../pages/System";
import TrendRadar from "../pages/TrendRadar";
import EtfAllocation from "../pages/EtfAllocation";

type PageKey = "dashboard" | "opportunities" | "trends" | "etfs" | "valuation" | "risk" | "system";
const pages: Array<{ key: PageKey; label: string; short: string }> = [
  { key: "dashboard", label: "研究首页", short: "今日结论" },
  { key: "opportunities", label: "价值反转", short: "超跌与错定价" },
  { key: "trends", label: "趋势雷达", short: "中期加速信号" },
  { key: "etfs", label: "核心ETF", short: "定投与配置节奏" },
  { key: "valuation", label: "公司估值", short: "模型与假设" },
  { key: "risk", label: "市场风险", short: "环境与校准" },
  { key: "system", label: "系统管理", short: "运行与设置" },
];

export default function App() {
  const [active, setActive] = useState<PageKey>("dashboard");
  const meta = pages.find((page) => page.key === active) ?? pages[0];
  return <div className="shell">
    <aside>
      <div className="brand"><i>Q</i><div><b>多策略研究台</b><span>价值 · 趋势 · 配置</span></div></div>
      <nav>{pages.map((page) => <button key={page.key} className={active === page.key ? "active" : ""} onClick={() => setActive(page.key)}><b>{page.label}</b><span>{page.short}</span></button>)}</nav>
      <p className="philosophy">价值回答是否便宜。<br />趋势回答资金是否确认。<br />配置回答该如何投入。</p>
    </aside>
    <main>
      <header className="top"><div><span>个人多策略研究系统</span><h1>{meta.label}</h1></div><p>独立于个人持仓，分别评估价值反转、趋势加速和核心ETF配置，不把不同信号混成一个答案。</p></header>
      {active === "dashboard" ? <Dashboard /> : null}
      {active === "opportunities" ? <Opportunities /> : null}
      {active === "trends" ? <TrendRadar /> : null}
      {active === "etfs" ? <EtfAllocation /> : null}
      {active === "valuation" ? <Valuation /> : null}
      {active === "risk" ? <MarketRisk /> : null}
      {active === "system" ? <System /> : null}
    </main>
  </div>;
}
