import { useState } from "react";
import { Badge, Empty, Section, SnapshotState, label } from "../components/Primitives";
import { asArray, asDict, money, percent, text, useSnapshot, type Dict } from "../lib/data";

export default function Opportunities() {
  const state = useSnapshot<Dict>("/api/opportunities");
  const [query, setQuery] = useState("");
  const [onlyActionable, setOnlyActionable] = useState(false);
  const rows = asArray(asDict(state.data?.payload).opportunities)
    .map(asDict)
    .filter((row) => (!query || text(row.symbol).includes(query.toUpperCase())) && (!onlyActionable || Boolean(row.actionable)));

  return <>
    <SnapshotState snapshot={state.data} loading={state.loading} error={state.error} reload={() => void state.reload()} />
    <div className="toolbar">
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选股票代码" />
      <label><input type="checkbox" checked={onlyActionable} onChange={(event) => setOnlyActionable(event.target.checked)} /> 只看达到研究门槛的机会</label>
      <span>共 {rows.length} 项</span>
    </div>
    <Section title="超跌与错定价候选" note="先识别相对市场和行业的异常下跌，再检查基本面损伤、事件性质和确定性估值。">
      {rows.length ? <div className="opportunity-list">{rows.map((row) => {
        const dislocation = asDict(row.dislocation);
        const fair = asDict(row.fair_value);
        const event = asDict(row.event);
        return <details key={text(row.symbol)}>
          <summary>
            <b>{text(row.symbol)}</b><Badge value={row.recommendation} />
            <span><strong>{Number(row.opportunity_score ?? 0).toFixed(0)}</strong><small>机会分</small></span>
            <span>{money(row.current_price)}<small>当前价</small></span>
            <span className="up">{percent(row.margin_of_safety)}<small>安全边际</small></span>
            <span className="down">{percent(dislocation.drawdown_52w)}<small>距52周高点</small></span>
          </summary>
          <div className="opportunity-detail">
            <dl>
              <div><dt>合理价值区间</dt><dd>{money(fair.p10)} 至 {money(fair.p90)}</dd></div>
              <div><dt>估值模型</dt><dd>{label(row.valuation_model)}</dd></div>
              <div><dt>估值可信度</dt><dd>{percent(row.valuation_confidence)}</dd></div>
              <div><dt>基本面质量 / 损伤</dt><dd>{text(row.quality_score)} / {text(row.damage_score)}</dd></div>
              <div><dt>下跌暂时性概率</dt><dd>{percent(event.transience_probability)}</dd></div>
              <div><dt>财报期间</dt><dd>{text(row.fiscal_period)}</dd></div>
              <div><dt>最新SEC申报</dt><dd>{row.latest_filing_form ? `${text(row.latest_filing_form)} · ${text(row.latest_filing_date)}` : "未取得原文"}</dd></div>
            </dl>
            <p><b>事件判断：</b>{text(event.summary, "暂无可验证事件摘要")}</p>
            {text(row.filing_summary, "") ? <p><b>财报判断：</b>{text(row.filing_summary)}</p> : null}
            <p><b>判定依据：</b>{asArray(row.reason_codes).map(label).join("；") || "证据不足"}</p>
          </div>
        </details>;
      })}</div> : <Empty>没有符合当前筛选条件的标的。</Empty>}
    </Section>
  </>;
}
