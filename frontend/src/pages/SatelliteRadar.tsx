import { useMemo, useState } from "react";
import { ActionStatus, DecisionTable, HorizonStrip, ModelDetail, type DecisionColumn } from "../components/DecisionTable";
import { LlmExplanation } from "../components/LlmExplanation";
import { MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { averageCost, asArray, asDict, currentPrice, formatCurrency, formatPercent, modelDecision, text, useSnapshot, type Dict } from "../lib/data";

function averageLastCell(row: Dict) {
  return (
    <span className="stacked-cell">
      <b>{formatCurrency(averageCost(row), 2)}</b>
      <small>{formatCurrency(currentPrice(row), 2)}</small>
    </span>
  );
}

const columns: DecisionColumn[] = [
  { label: "排名", render: (row, index) => text(row.satellite_rank ?? index + 1) },
  { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "长期分数", render: (row) => formatPercent(asDict(row.long_horizon).blended_rank ?? row.long_horizon_rank) },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "入场时机", render: (row) => <Status value={asDict(row.timing).state ?? row.timing_state} /> },
  { label: "风险", render: (row) => <Status value={asDict(row.risk).regime ?? row.risk_level ?? "NORMAL"} /> },
  { label: "状态", render: (row) => <ActionStatus row={row} /> },
];

export default function SatelliteRadar() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/satellite-radar");
  const payload = asDict(data?.payload);
  const top = asArray(payload.top_recommendations);
  const pool = asArray(payload.candidate_pool);
  const currentHoldings = asArray(payload.current_holdings);
  const [query, setQuery] = useState("");
  const filteredPool = useMemo(() => {
    const normalized = query.trim().toUpperCase();
    if (!normalized) return pool;
    return pool.filter((item) => text(asDict(item).symbol, "").toUpperCase().includes(normalized));
  }, [pool, query]);
  const approved = top.map(asDict).filter((row) => ["ACCUMULATE", "PROBE"].includes(text(modelDecision(row).action, "").toUpperCase()));
  const detail = (row: Dict) => (
    <>
      <ModelDetail row={row} />
      <LlmExplanation endpoint="/api/actions/explain-satellite" payload={{ symbol: text(row.symbol) }} />
    </>
  );

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "前三候选", value: top.map((row) => text(asDict(row).symbol, "")).filter(Boolean).join(", ") || "-", hint: "最多保留三个卫星候选" },
        { label: "通过买入", value: approved.length, hint: "没有强信号就不交易" },
        { label: "候选池", value: pool.length, hint: "由模型配置限制容量" },
        { label: "现有非核心持仓", value: currentHoldings.length, hint: "现有持仓与新候选分开跟踪" },
      ]} />
      <Panel title="当前非核心持仓" subtitle="这些是已有卫星/非核心仓位，会被监控，但不会和新建仓前三候选混在一起。">
        <DecisionTable
          rows={currentHoldings}
          columns={[
            { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
            { label: "账户权重", render: (row) => formatPercent(row.current_weight_pct) },
            { label: "成本/现价", render: averageLastCell },
            { label: "市值", render: (row) => formatCurrency(row.current_value, 2) },
            { label: "长期分数", render: (row) => formatPercent(asDict(row.long_horizon).blended_rank) },
            { label: "入场时机", render: (row) => <Status value={asDict(row.timing).state ?? row.timing_state} /> },
            { label: "动作", render: (row) => <ActionStatus row={row} /> },
          ]}
          emptyText="当前没有核心ETF池外的持仓。"
        />
      </Panel>
      <Panel title="前三卫星候选" subtitle="只有这些非核心候选有资格产生新建仓动作。">
        <DecisionTable rows={top} columns={columns} detail={detail} emptyText="还没有基础模型前三结果。请运行夜间流程或周末研究。" />
      </Panel>
      <Panel
        title="研究候选漏斗"
        subtitle="前三以外的候选即使原始分数不错，也保持观察，不直接触发买入。"
        action={<input className="compact-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选代码" />}
      >
        <DecisionTable rows={filteredPool} columns={columns} detail={detail} emptyText="当前没有候选池数据。" />
      </Panel>
    </SnapshotFrame>
  );
}
