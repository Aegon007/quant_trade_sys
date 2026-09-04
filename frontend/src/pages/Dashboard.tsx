import { asArray, asDict, dateTime, money, percent, text, useSnapshot, type Dict } from "../lib/data";
import { Badge, Empty, Section, SnapshotState, StatRow, label } from "../components/Primitives";

export default function Dashboard() {
  const state = useSnapshot<Dict>("/api/dashboard");
  const payload = asDict(state.data?.payload);
  const recommendation = asDict(payload.recommendations);
  const summary = asDict(recommendation.summary);
  const risk = asDict(payload.market_risk);
  const health = asDict(payload.data_health);
  const brief = asDict(payload.brief);
  const changes = asDict(payload.change_feed);
  const rows = asArray(recommendation.recommendations).map(asDict);
  const actionable = rows.filter((row) => Boolean(row.actionable));
  const decision = text(recommendation.decision, "NO_STRONG_SIGNAL");
  return <>
    <SnapshotState snapshot={state.data} loading={state.loading} error={state.error} reload={() => void state.reload()} />
    <section className={`hero ${actionable.length ? "signal" : "quiet"}`}>
      <div><span className="kicker">今日研究结论</span><h2>{actionable.length ? `发现 ${actionable.length} 个值得深入研究的错定价候选` : "当前没有达到行动门槛的强信号"}</h2><p>{text(brief.summary_text, "请先运行完整估值研究。系统不会为了每天给出答案而制造交易信号。")}</p></div>
      <div className="hero-mark"><Badge value={decision} /><strong>{text(risk.risk_score, "-")}</strong><span>市场风险分</span></div>
    </section>
    <StatRow items={[
      { label: "研究范围", value: text(summary.universe_count, "0"), note: "股票与ETF" },
      { label: "完成初筛", value: text(summary.scanned_count, "0"), note: "价格错位扫描" },
      { label: "深度估值", value: text(summary.analyzed_count, "0"), note: "财报与模型路由" },
      { label: "可研究机会", value: actionable.length, note: "不是交易指令" },
      { label: "数据健康", value: <Badge value={health.status ?? "MISSING"} />, note: text(asDict(health.summary).reason, "等待检查") },
    ]} />
    <Section title="优先研究名单" note="只展示达到深度估值阶段的前列候选；点击公司估值页查看完整假设。">
      {rows.length ? <div className="clean-table"><div className="table-head six"><span>标的</span><span>研究结论</span><span>机会分</span><span>当前价 / 中位价值</span><span>安全边际</span><span>核心依据</span></div>{rows.slice(0, 8).map((row) => { const fair = asDict(row.fair_value); return <div className="table-row six" key={text(row.symbol)}><b>{text(row.symbol)}</b><Badge value={row.recommendation} /><strong>{Number(row.opportunity_score ?? 0).toFixed(0)}</strong><span>{money(row.current_price)} <small>→ {money(fair.p50)}</small></span><span className={Number(row.margin_of_safety) >= .15 ? "up" : ""}>{percent(row.margin_of_safety)}</span><span>{asArray(row.reason_codes).map(label).slice(0, 2).join("；") || "等待更多证据"}</span></div>; })}</div> : <Empty>尚无估值结果。请在系统管理页运行“完整估值研究”。</Empty>}
    </Section>
    <div className="two-column">
      <Section title="市场环境" note="市场风险只调整研究门槛，不根据个人仓位改变结论。"><div className="risk-line"><Badge value={risk.regime ?? "MISSING"} /><strong>{text(risk.risk_score, "-")}</strong><span>/ 100</span></div><ul className="plain-list">{asArray(risk.drivers).length ? asArray(risk.drivers).map((item, index) => <li key={index}>{text(item)}</li>) : <li>{risk.regime ? "当前没有明显的系统性风险触发项。" : "尚未计算市场风险，请先运行完整估值研究。"}</li>}</ul></Section>
      <Section title="重要变化" note={`从上次完整研究到本次，生成于 ${dateTime(changes.generated_at)}`}><ul className="change-list">{asArray(changes.high_items).concat(asArray(changes.medium_items)).slice(0, 6).map((item, index) => { const row = asDict(item); return <li key={index}><Badge value={row.priority} /><div><b>{text(row.title)}</b><span>{text(row.message)}</span></div></li>; })}{!asArray(changes.items).length ? <li><div><b>暂无重要变化</b><span>轻微分数波动不会占据首页。</span></div></li> : null}</ul></Section>
    </div>
  </>;
}
