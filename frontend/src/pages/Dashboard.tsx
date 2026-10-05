import { asArray, asDict, dateTime, money, percent, text, useSnapshot, type Dict } from "../lib/data";
import { Badge, Empty, Section, SnapshotState, StatRow, label } from "../components/Primitives";

export default function Dashboard() {
  const state = useSnapshot<Dict>("/api/dashboard");
  const payload = asDict(state.data?.payload);
  const recommendation = asDict(payload.recommendations);
  const trendSnapshot = asDict(payload.trends);
  const etfSnapshot = asDict(payload.etf_allocation);
  const summary = asDict(recommendation.summary);
  const risk = asDict(payload.market_risk);
  const health = asDict(payload.data_health);
  const brief = asDict(payload.brief);
  const changes = asDict(payload.change_feed);
  const valueRows = asArray(recommendation.recommendations).map(asDict);
  const trendRows = asArray(trendSnapshot.trends).map(asDict);
  const etfRows = asArray(etfSnapshot.allocations).map(asDict);
  const valueActionable = valueRows.filter((row) => Boolean(row.actionable));
  const trendActionable = trendRows.filter((row) => Boolean(row.actionable));
  const strongCount = valueActionable.length + trendActionable.length;
  return <>
    <SnapshotState snapshot={state.data} loading={state.loading} error={state.error} reload={() => void state.reload()} />
    <section className={`hero ${strongCount ? "signal" : "quiet"}`}>
      <div><span className="kicker">今日跨引擎结论</span><h2>{strongCount ? `发现 ${strongCount} 个通过各自门槛的研究信号` : "当前没有达到行动门槛的强信号"}</h2><p>{text(brief.summary_text, "请先运行完整研究。三个引擎不会为了每天给出交易答案而相互迁就门槛。")}</p></div>
      <div className="hero-mark"><Badge value={risk.regime ?? "MISSING"} /><strong>{text(risk.risk_score, "-")}</strong><span>市场风险分</span></div>
    </section>
    <StatRow items={[
      { label: "研究范围", value: text(summary.universe_count, "0"), note: "股票与ETF" },
      { label: "价值机会", value: valueActionable.length, note: "超跌且估值通过" },
      { label: "趋势确认", value: trendActionable.length, note: "相对强度与基本面" },
      { label: "核心ETF", value: etfRows.length, note: "配置节奏已计算" },
      { label: "数据健康", value: <Badge value={health.status ?? "MISSING"} />, note: text(asDict(health.summary).reason, "等待检查") },
    ]} />
    <Section title="三个研究引擎" note="每条通道回答不同问题；没有任何单一分数可以替代另外两条通道。">
      <div className="lane-grid">
        <article className="research-lane"><header><div><span>01</span><h3>价值反转</h3></div><b>{valueActionable.length}</b></header><p>异常下跌后，价格是否显著低于基本面支持的价值区间。</p><ul>{valueRows.slice(0, 4).map((row) => <li key={text(row.symbol)}><b>{text(row.symbol)}</b><Badge value={row.recommendation} /><span>{percent(row.margin_of_safety)}</span></li>)}{!valueRows.length ? <li>等待完整研究</li> : null}</ul></article>
        <article className="research-lane"><header><div><span>02</span><h3>趋势加速</h3></div><b>{trendActionable.length}</b></header><p>哪些股票正在持续跑赢市场；过热时只观察，不追涨。</p><ul>{trendRows.slice(0, 4).map((row) => <li key={text(row.symbol)}><b>{text(row.symbol)}</b><Badge value={row.recommendation} /><span>{text(row.signal_score)}</span></li>)}{!trendRows.length ? <li>等待完整研究</li> : null}</ul></article>
        <article className="research-lane"><header><div><span>03</span><h3>核心ETF配置</h3></div><b>{etfRows.length}</b></header><p>区分常规定投与额外投入，根据估值、趋势和市场风险调整节奏。</p><ul>{etfRows.slice(0, 4).map((row) => <li key={text(row.symbol)}><b>{text(row.symbol)}</b><Badge value={row.action} /><span>{money(row.current_price)}</span></li>)}{!etfRows.length ? <li>等待完整研究</li> : null}</ul></article>
      </div>
    </Section>
    <Section title="价值反转优先名单" note="这里只展示价值反转通道；正在上涨的中期机会请查看趋势雷达。">
      {valueRows.length ? <div className="clean-table"><div className="table-head six"><span>标的</span><span>研究结论与门槛</span><span>机会分</span><span>当前价 / 中位价值</span><span>安全边际</span><span>核心依据</span></div>{valueRows.slice(0, 8).map((row) => { const fair = asDict(row.fair_value); const insufficient = text(row.recommendation) === "INSUFFICIENT_DATA"; return <div className="table-row six" key={text(row.symbol)}><b>{text(row.symbol)}</b><div className="recommendation-cell"><Badge value={row.recommendation} /><small>{text(row.recommendation_detail, insufficient ? "估值证据未通过质量门槛" : "")}</small></div><strong>{Number(row.opportunity_score ?? 0).toFixed(0)}</strong><span>{money(row.current_price)} <small>→ {money(fair.p50)}</small></span><span className={Number(row.margin_of_safety) >= .15 ? "up" : ""}>{percent(row.margin_of_safety)}</span><span>{asArray(row.reason_codes).map(label).slice(0, 2).join("；") || "等待更多证据"}</span></div>; })}</div> : <Empty>尚无价值反转结果。请在系统管理页运行完整研究。</Empty>}
    </Section>
    <div className="two-column">
      <Section title="市场环境" note="市场风险调整各引擎门槛，不直接制造买卖结论。"><div className="risk-line"><Badge value={risk.regime ?? "MISSING"} /><strong>{text(risk.risk_score, "-")}</strong><span>/ 100</span></div><ul className="plain-list">{asArray(risk.drivers).length ? asArray(risk.drivers).map((item, index) => <li key={index}>{text(item)}</li>) : <li>{risk.regime ? "当前没有明显的系统性风险触发项。" : "尚未计算市场风险。"}</li>}</ul></Section>
      <Section title="重要变化" note={`从上次完整研究到本次，生成于 ${dateTime(changes.generated_at)}`}><ul className="change-list">{asArray(changes.high_items).concat(asArray(changes.medium_items)).slice(0, 6).map((item, index) => { const row = asDict(item); return <li key={index}><Badge value={row.priority} /><div><b>{text(row.title)}</b><span>{text(row.message)}</span></div></li>; })}{!asArray(changes.items).length ? <li><div><b>暂无重要变化</b><span>轻微分数波动不会占据首页。</span></div></li> : null}</ul></Section>
    </div>
  </>;
}
