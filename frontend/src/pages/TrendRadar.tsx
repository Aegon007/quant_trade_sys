import { useState } from "react";
import { Badge, Empty, Section, SnapshotState, label } from "../components/Primitives";
import { asArray, asDict, money, percent, text, useSnapshot, type Dict } from "../lib/data";

export default function TrendRadar() {
  const state = useSnapshot<Dict>("/api/trends");
  const [query, setQuery] = useState("");
  const rows = asArray(asDict(state.data?.payload).trends).map(asDict).filter((row) => !query || text(row.symbol).includes(query.toUpperCase()));
  return <>
    <SnapshotState snapshot={state.data} loading={state.loading} error={state.error} reload={() => void state.reload()} />
    <div className="toolbar"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选股票代码" /><span>展示 {rows.length} 项</span></div>
    <Section title="中期趋势与盈利加速雷达" note="独立于低估值筛选。先找相对市场和行业持续走强的标的，再用财报质量与风险门槛过滤；强趋势不等于适合追涨。">
      {rows.length ? <div className="signal-list">{rows.slice(0, 50).map((row) => {
        const trend = asDict(row.trend);
        return <details key={text(row.symbol)}>
          <summary className="trend-summary"><b>{text(row.symbol)}</b><Badge value={row.recommendation} /><span><strong>{Number(row.signal_score ?? 0).toFixed(0)}</strong><small>综合信号</small></span><span>{percent(trend.return_20d)}<small>20日收益</small></span><span>{percent(trend.relative_return_20d)}<small>相对强度</small></span><span>{percent(trend.distance_from_52w_high)}<small>距52周高点</small></span></summary>
          <div className="opportunity-detail"><dl><div><dt>当前价格</dt><dd>{money(row.current_price)}</dd></div><div><dt>趋势状态</dt><dd>{label(trend.trend_state)}</dd></div><div><dt>趋势原始分</dt><dd>{text(trend.trend_score)}</dd></div><div><dt>60日收益</dt><dd>{percent(trend.return_60d)}</dd></div><div><dt>距50日均线</dt><dd>{percent(trend.extension_from_ma50)}</dd></div><div><dt>RSI 14</dt><dd>{text(trend.rsi14)}</dd></div><div><dt>基本面状态</dt><dd>{label(row.fundamental_status)}</dd></div><div><dt>质量 / 损伤</dt><dd>{text(row.quality_score)} / {text(row.damage_score)}</dd></div><div><dt>最新财报日</dt><dd>{text(row.latest_filing_date)}</dd></div></dl><p><b>研究结论：</b>{text(row.recommendation_detail)}</p><p><b>证据：</b>{asArray(row.reason_codes).map(label).join("；") || "尚无足够证据"}</p>{asArray(row.blocking_reasons).length ? <p><b>阻断项：</b>{asArray(row.blocking_reasons).map(label).join("；")}</p> : null}</div>
        </details>;
      })}</div> : <Empty>尚无趋势快照，请运行完整研究。</Empty>}
    </Section>
  </>;
}
