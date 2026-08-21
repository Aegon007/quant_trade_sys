import { ActionStatus, DecisionTable, HorizonStrip, ModelDetail, type DecisionColumn } from "../components/DecisionTable";
import { LlmExplanation } from "../components/LlmExplanation";
import { MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { averageCost, asArray, asDict, currentPrice, formatCurrency, formatPercent, modelDecision, numberValue, text, useSnapshot, type Dict } from "../lib/data";

function averageLastCell(row: Dict) {
  return (
    <span className="stacked-cell">
      <b>{formatCurrency(averageCost(row), 2)}</b>
      <small>{formatCurrency(currentPrice(row), 2)}</small>
    </span>
  );
}

const columns: DecisionColumn[] = [
  { label: "ETF", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "定位", render: (row) => text(row.role ?? row.portfolio_role) },
  { label: "当前仓位", render: (row) => formatPercent(row.current_weight_pct ?? row.current_weight) },
  { label: "成本/现价", render: averageLastCell },
  { label: "目标仓位", render: (row) => text(modelDecision(row).target_weight_range_pct ?? row.target_weight_range_pct) },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "入场时机", render: (row) => <Status value={asDict(row.timing).state ?? row.timing_state} /> },
  { label: "动作", render: (row) => <ActionStatus row={row} /> },
];

export default function CoreEtfs() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/core-etfs");
  const payload = asDict(data?.payload);
  const rows = Array.isArray(payload.symbols) ? payload.symbols : [];
  const uncovered = asArray(payload.unrepresented_holdings);
  const account = asDict(payload.portfolio_context);
  const actionable = rows.map(asDict).filter((row) => !["", "HOLD", "WATCH"].includes(text(modelDecision(row).action ?? row.action, "").toUpperCase()));
  const averageRank = rows.length
    ? rows.map(asDict).reduce((total, row) => total + (numberValue(asDict(row.long_horizon).blended_rank) ?? 0), 0) / rows.length
    : null;

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "核心池数量", value: rows.length, hint: "来自配置，不在UI写死" },
        { label: "通过动作", value: actionable.length, hint: "小幅变化保持持有" },
        { label: "平均长期排名", value: formatPercent(averageRank), hint: "横截面分位" },
        { label: "账户暴露", value: formatPercent(account.exposure_pct), hint: `${uncovered.length} 个持仓不在核心池` },
      ]} />
      <Panel title="核心ETF配置板" subtitle="用于判断核心ETF是否适合加仓、暂停或保持。展开行可查看分位数、原因和回撤估计。">
        <DecisionTable
          rows={rows}
          columns={columns}
          detail={(row) => (
            <>
              <ModelDetail row={row} />
              <LlmExplanation endpoint="/api/actions/explain-core-etf" payload={{ symbol: text(row.symbol) }} />
            </>
          )}
          emptyText="请运行模型推理来生成核心ETF配置板。"
        />
      </Panel>
      <Panel title="组合覆盖缺口" subtitle="这些当前持仓不在核心ETF配置池中。如果某个ETF应由核心引擎管理，请到设置页加入。">
        <DecisionTable
          rows={uncovered}
          columns={[
            { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
            { label: "股数", render: (row) => text(row.current_shares) },
            { label: "成本/现价", render: averageLastCell },
            { label: "市值", render: (row) => formatCurrency(row.current_value, 2) },
            { label: "账户权重", render: (row) => formatPercent(row.current_weight_pct) },
          ]}
          detail={() => <div className="decision-detail"><p>该持仓不会被核心ETF配置引擎直接调整。</p></div>}
          emptyText="所有当前持仓都已被核心ETF配置池覆盖。"
        />
      </Panel>
      <div className="notice">
        核心ETF的战术调整仍受3%最小调整阈值、连续确认和组合风险门控约束。DCA_ACCUMULATE 是长期核心ETF低配时允许定投加仓的例外。
      </div>
    </SnapshotFrame>
  );
}
