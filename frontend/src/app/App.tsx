import { useState } from "react";
import Dashboard from "../pages/Dashboard";
import Opportunities from "../pages/Opportunities";
import Valuation from "../pages/Valuation";
import MarketRisk from "../pages/MarketRisk";
import System from "../pages/System";

type PageKey = "dashboard" | "opportunities" | "valuation" | "risk" | "system";
const pages: Array<{ key: PageKey; label: string; short: string }> = [
  { key: "dashboard", label: "研究首页", short: "今日结论" },
  { key: "opportunities", label: "超跌机会", short: "寻找错定价" },
  { key: "valuation", label: "公司估值", short: "模型与假设" },
  { key: "risk", label: "市场风险", short: "环境与校准" },
  { key: "system", label: "系统管理", short: "运行与设置" },
];

export default function App() {
  const [active, setActive] = useState<PageKey>("dashboard");
  const meta = pages.find((page) => page.key === active) ?? pages[0];
  return <div className="shell">
    <aside>
      <div className="brand"><i>Q</i><div><b>估值雷达</b><span>基本面与错定价</span></div></div>
      <nav>{pages.map((page) => <button key={page.key} className={active === page.key ? "active" : ""} onClick={() => setActive(page.key)}><b>{page.label}</b><span>{page.short}</span></button>)}</nav>
      <p className="philosophy">价格下跌只是线索。<br />价值、安全边际和基本面才是判断。</p>
    </aside>
    <main>
      <header className="top"><div><span>个人估值研究系统</span><h1>{meta.label}</h1></div><p>独立于个人持仓，只根据市场、财报与估值证据寻找机会。</p></header>
      {active === "dashboard" ? <Dashboard /> : null}
      {active === "opportunities" ? <Opportunities /> : null}
      {active === "valuation" ? <Valuation /> : null}
      {active === "risk" ? <MarketRisk /> : null}
      {active === "system" ? <System /> : null}
    </main>
  </div>;
}
