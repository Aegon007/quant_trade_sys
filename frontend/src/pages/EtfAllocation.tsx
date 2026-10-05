import { Badge, Empty, Section, SnapshotState, label } from "../components/Primitives";
import { asArray, asDict, money, percent, text, useSnapshot, type Dict } from "../lib/data";

export default function EtfAllocation() {
  const state = useSnapshot<Dict>("/api/etf-allocation");
  const rows = asArray(asDict(state.data?.payload).allocations).map(asDict);
  return <>
    <SnapshotState snapshot={state.data} loading={state.loading} error={state.error} reload={() => void state.reload()} />
    <Section title="核心ETF配置节奏" note="回答定投、额外加仓或放慢投入，而不是用一个静态点估值假装预测下一次市场低点。">
      {rows.length ? <div className="signal-list">{rows.map((row) => {
        const trend = asDict(row.trend); const expected = asDict(row.expected_annual_return); const zones = asDict(row.price_zones); const reference = asDict(row.valuation_reference);
        return <details key={text(row.symbol)} open={rows.length <= 4}>
          <summary className="etf-summary"><b>{text(row.symbol)}</b><Badge value={row.action} /><span><strong>{Number(row.allocation_score ?? 0).toFixed(0)}</strong><small>配置分</small></span><span>{label(row.valuation_state)}<small>估值位置</small></span><span>{label(trend.trend_state)}<small>中期趋势</small></span><span>{percent(expected.central)}<small>3-5年年化中枢</small></span></summary>
          <div className="opportunity-detail"><dl><div><dt>当前价格</dt><dd>{money(row.current_price)}</dd></div><div><dt>常规定投区间</dt><dd>{asArray(zones.regular_buy).map((value) => money(value)).join(" – ")}</dd></div><div><dt>回撤加仓观察区</dt><dd>{asArray(zones.add_on_pullback).map((value) => money(value)).join(" – ")}</dd></div><div><dt>避免一次性投入高于</dt><dd>{money(zones.avoid_lump_sum_above)}</dd></div><div><dt>当前 / 长期盈利收益率</dt><dd>{percent(reference.current_earnings_yield)} / {percent(reference.historical_earnings_yield)}</dd></div><div><dt>市场风险分</dt><dd>{text(row.market_risk_score)}</dd></div></dl><p><b>长期回报情景：</b>{percent(expected.low)} 至 {percent(expected.high)}，中枢 {percent(expected.central)}。{text(expected.method, "")}</p><p><b>依据：</b>{asArray(row.reasoning).map((value) => text(value)).join("；")}</p></div>
        </details>;
      })}</div> : <Empty>尚无ETF配置快照，请先在系统设置中配置核心ETF并运行完整研究。</Empty>}
    </Section>
  </>;
}
