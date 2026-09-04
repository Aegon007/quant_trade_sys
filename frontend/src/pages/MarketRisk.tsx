import { Badge, Empty, Section, SnapshotState, StatRow, label } from "../components/Primitives";
import { asArray, asDict, percent, text, useSnapshot, type Dict } from "../lib/data";

export default function MarketRisk() {
  const riskState = useSnapshot<Dict>("/api/market-risk");
  const healthState = useSnapshot<Dict>("/api/data-health");
  const calibrationState = useSnapshot<Dict>("/api/calibration");
  const risk = asDict(riskState.data?.payload);
  const metrics = asDict(risk.metrics);
  const health = asDict(healthState.data?.payload);
  const healthSummary = asDict(health.summary);
  const priceCache = asDict(healthSummary.price_cache);
  const historySources = asDict(healthSummary.history_source_counts);
  const latestSources = asDict(priceCache.source_counts);
  const calibration = asDict(calibrationState.data?.payload);

  return <>
    <SnapshotState snapshot={riskState.data} loading={riskState.loading} error={riskState.error} reload={() => void riskState.reload()} />
    <section className="risk-hero">
      <div><span>市场环境</span><h2>{risk.regime ? <Badge value={risk.regime} /> : "尚未计算"}</h2><p>风险分越高，超跌候选需要更大的安全边际和更强的基本面证据。</p></div>
      <strong>{text(risk.risk_score, "-")}<small>/100</small></strong>
    </section>
    <StatRow items={[
      { label: "标普20日", value: percent(metrics.spy_return_20d) },
      { label: "标普60日", value: percent(metrics.spy_return_60d) },
      { label: "纳指100 20日", value: percent(metrics.qqq_return_20d) },
      { label: "VIX", value: text(metrics.vix) },
      { label: "数据状态", value: <Badge value={health.status ?? "MISSING"} /> },
    ]} />
    <div className="two-column">
      <Section title="风险驱动因素">
        <ul className="plain-list large">{asArray(risk.drivers).length
          ? asArray(risk.drivers).map((item, index) => <li key={index}>{text(item)}</li>)
          : <li>{risk.regime ? "当前没有明显的系统性风险触发项。" : "尚未计算市场风险，请先运行完整估值研究。"}</li>}
        </ul>
      </Section>
      <Section title="数据可靠性">
        <dl className="definition-grid compact">
          <div><dt>最新价缓存</dt><dd><Badge value={priceCache.status ?? "MISSING"} /> · {text(priceCache.symbol_count, "0")} 个标的{Object.keys(latestSources).length ? ` · ${Object.entries(latestSources).map(([source, count]) => `${label(source)} ${count}`).join("；")}` : ""}</dd></div>
          <div><dt>本次历史行情来源</dt><dd>{Object.entries(historySources).map(([source, count]) => `${label(source)} ${count}`).join("；") || "尚无记录"}</dd></div>
          <div><dt>完成估值</dt><dd>{text(healthSummary.valuation_count, "0")}</dd></div>
          <div><dt>LLM路由</dt><dd>{text(healthSummary.llm_route_count, "0")}</dd></div>
          <div><dt>标的级异常</dt><dd>{text(healthSummary.error_count, "0")}</dd></div>
        </dl>
        <p className="muted">{text(healthSummary.reason, "尚未运行健康检查")}</p>
        {healthSummary.warnings ? <p className="muted">提示：{text(healthSummary.warnings)}</p> : null}
      </Section>
    </div>
    <Section title="历史推荐校准" note="周末任务同时衡量推荐是否跑赢短期国债代理SGOV，以及是否取得相对SPY的市场超额。">
      {Object.keys(asDict(calibration.horizons)).length ? <div className="calibration-list">{Object.entries(asDict(calibration.horizons)).map(([horizon, value]) => {
        const row = asDict(value);
        return <div key={horizon}><b>{horizon}日</b><span>样本 {text(row.count, "0")}</span><span>跑赢短债 {percent(row.risk_free_win_rate)}</span><span>跑赢SPY {percent(row.market_win_rate)}</span><span>对短债超额 {percent(row.median_excess_over_risk_free)}</span><span>对SPY超额 {percent(row.median_excess_over_market)}</span></div>;
      })}</div> : <Empty>推荐样本尚未达到第一个63交易日观察窗口。</Empty>}
    </Section>
  </>;
}
