import { DecisionTable, HorizonStrip, type DecisionColumn } from "../components/DecisionTable";
import { Facts, MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { LlmExplanation } from "../components/LlmExplanation";
import { averageCost, asArray, asDict, currentPrice, formatCurrency, formatPercent, text, useSnapshot, type Dict } from "../lib/data";

function averageLastCell(row: Dict) {
  return (
    <span className="stacked-cell">
      <b>{formatCurrency(averageCost(row), 2)}</b>
      <small>{formatCurrency(currentPrice(row), 2)}</small>
    </span>
  );
}

const conflictColumns: DecisionColumn[] = [
  { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "长期判断", render: (row) => <Status value={asDict(row.long_horizon).state} /> },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "入场时机", render: (row) => <Status value={asDict(row.timing).state} /> },
  { label: "最终动作", render: (row) => <Status value={asDict(row.decision).action} /> },
];

export default function RiskDiscipline() {
  const risk = useSnapshot<Dict>("/api/risk");
  const model = useSnapshot<Dict>("/api/multi-horizon");
  const payload = asDict(risk.data?.payload);
  const summary = risk.data?.summary ?? asDict(payload.summary);
  const modelPayload = asDict(model.data?.payload);
  const modelRows = asArray(modelPayload.symbols).map(asDict);
  const conflicts = modelRows.filter((row) => {
    const longState = text(asDict(row.long_horizon).state, "").toUpperCase();
    const timingState = text(asDict(row.timing).state, "").toUpperCase();
    return longState === "ATTRACTIVE" && ["DETERIORATING", "FAILED"].includes(timingState);
  });
  const riskRows = asArray(payload.risk_items ?? payload.items ?? payload.alerts ?? payload.rules);
  const account = asDict(payload.account);
  const holdings = asArray(payload.holdings);
  const marketSentiment = asDict(payload.market_sentiment);
  const systemicRisk = asDict(payload.systemic_risk);
  const financialsIntelligence = asDict(payload.financials_intelligence);
  const financialsSummary = asDict(financialsIntelligence.summary);

  return (
    <SnapshotFrame snapshot={risk.data} loading={risk.loading} error={risk.error} onReload={() => { risk.reload(); model.reload(); }}>
      <MetricStrip items={[
        { label: "纪律状态", value: text(payload.regime ?? summary.regime, "UNKNOWN"), hint: "重仓 / 正常 / 轻仓 / 停手" },
        { label: "风险状态", value: text(payload.risk_regime ?? summary.risk_regime, "UNKNOWN"), hint: "最终否决权" },
        { label: "市场情绪", value: text(marketSentiment.risk_appetite_state, "UNKNOWN"), hint: `分数 ${text(marketSentiment.market_sentiment_score, "-")}` },
        { label: "AI资本开支压力", value: text(systemicRisk.ai_capex_stress, "UNKNOWN"), hint: `系统性 ${text(systemicRisk.systemic_risk_score, "-")}` },
        { label: "财务压力", value: text(financialsSummary.hard_financial_data, "MISSING"), hint: `${text(financialsSummary.stress_count, "0")} 个压力项` },
      ]} />
      <div className="split-layout">
        <Panel title="市场情绪覆盖层" subtitle="当市场进入风险关闭状态时，用于降低置信度并阻止激进加仓。">
          <Facts rows={[
            ["风险偏好", <Status value={marketSentiment.risk_appetite_state ?? "UNKNOWN"} />],
            ["市场宽度", <Status value={marketSentiment.breadth_state ?? "UNKNOWN"} />],
            ["高于50日线", formatPercent(marketSentiment.breadth_above_50d_pct)],
            ["高于200日线", formatPercent(marketSentiment.breadth_above_200d_pct)],
            ["主要驱动", text(marketSentiment.main_sentiment_drivers)],
          ]} />
        </Panel>
        <Panel title="AI资本开支/系统性预警" subtitle="保守评估市场集中度、相关性、AI资本开支叙事压力和风险关闭状态。">
          <Facts rows={[
            ["压力状态", <Status value={systemicRisk.ai_capex_stress ?? "UNKNOWN"} />],
            ["分数", text(systemicRisk.systemic_risk_score, "-")],
            ["AI相关性", text(systemicRisk.ai_supply_chain_correlation, "不可用")],
            ["数据新鲜度", text(systemicRisk.data_freshness)],
            ["财务压力", text(systemicRisk.financial_statement_stress)],
            ["预警", text(systemicRisk.warnings)],
          ]} />
        </Panel>
      </div>
      <Panel title="财报压力" subtitle="公司层面的现金流、资本开支、债务和收入增长检查。ETF通常没有财报数据。">
        <Facts rows={[
          ["状态", <Status value={financialsIntelligence.status ?? "NOT_READY"} />],
          ["硬数据", <Status value={financialsSummary.hard_financial_data ?? "MISSING"} />],
          ["覆盖/缺失", `${text(financialsSummary.covered_count, "0")} / ${text(financialsSummary.missing_count, "0")}`],
          ["谨慎/压力", `${text(financialsSummary.caution_count, "0")} / ${text(financialsSummary.stress_count, "0")}`],
          ["主要压力标的", text(financialsSummary.top_stress_symbols)],
          ["摘要", text(financialsIntelligence.executive_summary)],
        ]} />
      </Panel>
      <Panel title="实时持仓集中度" subtitle="基于最新持仓和当前价格计算，而不是依赖过期的夜间副本。">
        <DecisionTable
          rows={holdings}
          columns={[
            { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
            { label: "股数", render: (row) => text(row.current_shares) },
            { label: "成本/现价", render: averageLastCell },
            { label: "市值", render: (row) => formatCurrency(row.current_value, 2) },
            { label: "账户权重", render: (row) => formatPercent(row.current_weight_pct) },
            { label: "上限", render: () => formatPercent(account.max_single_position_pct) },
            { label: "状态", render: (row) => <Status value={Number(row.current_weight_pct ?? 0) > Number(account.max_single_position_pct ?? 0) ? "OVER LIMIT" : "OK"} /> },
          ]}
          detail={() => <div className="decision-detail"><p>仓位上限使用总资产计算：可用现金加当前持仓市值。</p></div>}
          emptyText="当前没有持仓数据。"
        />
      </Panel>
      <Panel title="信号冲突" subtitle="短期转弱不会独立触发卖出长期仍强的资产。">
        <DecisionTable rows={conflicts} columns={conflictColumns} emptyText="最新快照里没有模型冲突。" />
      </Panel>
      <div className="split-layout">
        <Panel title="风险规则与告警" subtitle="原始模型输出必须通过这些控制项。">
          <DecisionTable
            rows={riskRows}
            columns={[
              { label: "级别", render: (row) => <Status value={row.level ?? row.severity ?? row.status} /> },
              { label: "区域", render: (row) => text(row.category ?? row.type ?? row.name) },
              { label: "信息", render: (row) => text(row.message ?? row.reason ?? row.description) },
              { label: "动作", render: (row) => text(row.action ?? row.recommended_action) },
            ]}
          />
        </Panel>
        <Panel title="纪律反馈" subtitle="月度校准只用于观察，不会自动重写风险规则。">
          <Facts rows={[
            ["月度状态", <Status value={asDict(payload.monthly_review).status ?? "PENDING"} />],
            ["可开核心仓", text(payload.can_open_new_core_positions)],
            ["可开卫星仓", text(payload.can_open_new_satellite_positions)],
            ["模型状态", <Status value={modelPayload.status ?? asDict(modelPayload.model).status ?? "MODEL_NOT_READY"} />],
          ]} />
        </Panel>
      </div>
      <Panel title="LLM风险解读" subtitle="使用当前风险控制和缓存新闻证据。它不能覆盖风险门控。">
        <LlmExplanation endpoint="/api/actions/explain-risk" label="解释当前风险" />
      </Panel>
    </SnapshotFrame>
  );
}
