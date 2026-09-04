import { useEffect, useState } from "react";
import { postApi } from "../api";
import { Badge, Empty, Section, SnapshotState, label } from "../components/Primitives";
import { asArray, asDict, money, percent, text, useSnapshot, type Dict } from "../lib/data";

export default function Valuation() {
  const state = useSnapshot<Dict>("/api/valuations");
  const rows = asArray(asDict(state.data?.payload).valuations).map(asDict);
  const [selected, setSelected] = useState("");
  const [explanation, setExplanation] = useState("");
  const [explaining, setExplaining] = useState(false);
  useEffect(() => { if (!selected && rows.length) setSelected(text(rows[0].symbol)); }, [rows, selected]);
  const row = rows.find((item) => text(item.symbol) === selected) ?? rows[0];

  async function explain() {
    if (!row) return;
    setExplaining(true);
    setExplanation("");
    try {
      const result = await postApi<Dict>("/api/actions/explain-security", { symbol: row.symbol });
      setExplanation(text(result.explanation));
    } catch (reason) {
      setExplanation(`解释失败：${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setExplaining(false);
    }
  }

  return <>
    <SnapshotState snapshot={state.data} loading={state.loading} error={state.error} reload={() => void state.reload()} />
    {!row ? <Empty>尚无公司估值。请运行完整估值研究。</Empty> : <div className="valuation-layout">
      <Section title="已估值标的" note="选择标的查看模型、场景与证据。">
        <div className="symbol-list">{rows.map((item) => <button
          className={text(item.symbol) === text(row.symbol) ? "active" : ""}
          onClick={() => { setSelected(text(item.symbol)); setExplanation(""); }}
          key={text(item.symbol)}
        ><b>{text(item.symbol)}</b><span>{money(item.current_price)}</span><small>{label(item.primary_model)}</small></button>)}</div>
      </Section>
      <div className="valuation-main">
        <section className="valuation-title">
          <div><span>{label(row.archetype)}</span><h2>{text(row.symbol)}</h2><p>财务来源：{label(row.financial_source)} · 财报期间：{text(row.fiscal_period)}</p></div>
          <button onClick={explain} disabled={explaining}>{explaining ? "LLM正在解释..." : "让LLM解释这份估值"}</button>
        </section>
        <div className="valuation-band">
          <div><span>当前价格</span><strong>{money(row.current_price)}</strong></div>
          <div><span>保守价值</span><strong>{money(asDict(row.fair_value).p10)}</strong></div>
          <div className="focus"><span>中位合理价值</span><strong>{money(asDict(row.fair_value).p50)}</strong></div>
          <div><span>乐观价值</span><strong>{money(asDict(row.fair_value).p90)}</strong></div>
        </div>
        <Section title="模型与可信度">
          <dl className="definition-grid">
            <div><dt>主估值模型</dt><dd>{label(row.primary_model)}</dd></div>
            <div><dt>安全边际</dt><dd>{percent(row.margin_of_safety)}</dd></div>
            <div><dt>估值可信度</dt><dd>{percent(row.confidence)}</dd></div>
            <div><dt>区间离散度</dt><dd>{percent(row.dispersion)}</dd></div>
            <div><dt>实际参与模型</dt><dd>{text(row.model_count, "1")} 个</dd></div>
            <div><dt>模型间离散度</dt><dd>{percent(row.model_dispersion)}</dd></div>
            <div><dt>模型选择来源</dt><dd><Badge value={row.route_source} /></dd></div>
            <div><dt>校验提醒</dt><dd>{asArray(row.validation_warnings).map(label).join("；") || "无"}</dd></div>
          </dl>
        </Section>
        <Section title="模型交叉估值" note="只纳入输入完整且与公司类型兼容的模型；模型分歧会降低最终可信度。">
          <div className="assumption-table"><div><b>估值模型</b><b>悲观</b><b>基准</b><b>乐观</b></div>{Object.entries(asDict(row.model_values)).map(([model, value]) => {
            const scenario = asDict(value);
            return <div key={model}><span>{label(model)}</span><span>{money(scenario.bear)}</span><span>{money(scenario.base)}</span><span>{money(scenario.bull)}</span></div>;
          })}</div>
        </Section>
        <Section title="三情景假设" note="LLM负责提取和选择；确定性引擎负责计算。">
          <div className="assumption-table"><div><b>假设</b><b>悲观</b><b>基准</b><b>乐观</b></div>{Object.entries(asDict(row.assumptions)).map(([name, value]) => {
            const scenario = asDict(value);
            const isRate = name.includes("rate") || name.includes("growth") || name.includes("margin");
            return <div key={name}><span>{label(name)}</span><span>{isRate ? percent(scenario.bear) : text(scenario.bear)}</span><span>{isRate ? percent(scenario.base) : text(scenario.base)}</span><span>{isRate ? percent(scenario.bull) : text(scenario.bull)}</span></div>;
          })}</div>
        </Section>
        {explanation ? <Section title="LLM深度解释" note="按需调用，不改变确定性估值结果。"><div className="narrative">{explanation}</div></Section> : null}
      </div>
    </div>}
  </>;
}
