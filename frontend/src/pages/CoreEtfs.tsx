import { ActionStatus, DecisionTable, HorizonStrip, type DecisionColumn } from "../components/DecisionTable";
import { MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { asDict, formatPercent, modelDecision, numberValue, text, useSnapshot, type Dict } from "../lib/data";

const columns: DecisionColumn[] = [
  { label: "ETF", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "Role", render: (row) => text(row.role ?? row.portfolio_role) },
  { label: "Current weight", render: (row) => formatPercent(row.current_weight_pct ?? row.current_weight) },
  { label: "Target", render: (row) => text(modelDecision(row).target_weight_range_pct ?? row.target_weight_range_pct) },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "Timing", render: (row) => <Status value={asDict(row.timing).state ?? row.timing_state} /> },
  { label: "Action", render: (row) => <ActionStatus row={row} /> },
];

export default function CoreEtfs() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/core-etfs");
  const payload = asDict(data?.payload);
  const rows = Array.isArray(payload.symbols) ? payload.symbols : [];
  const actionable = rows.map(asDict).filter((row) => !["", "HOLD", "WATCH"].includes(text(modelDecision(row).action ?? row.action, "").toUpperCase()));
  const averageRank = rows.length
    ? rows.map(asDict).reduce((total, row) => total + (numberValue(asDict(row.long_horizon).blended_rank) ?? 0), 0) / rows.length
    : null;

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "Core universe", value: rows.length, hint: "Configured, never hard-coded in UI" },
        { label: "Approved changes", value: actionable.length, hint: "Small changes stay HOLD" },
        { label: "Average long rank", value: formatPercent(averageRank), hint: "Cross-sectional percentile" },
        { label: "Decision source", value: payload.model_ranked ? "Neural model" : "Waiting", hint: "63 / 126 / 252-day fusion" },
      ]} />
      <Panel title="Core ETF allocation board" subtitle="One full-width comparison. Expand a row for quantiles, reasons, and downside estimates.">
        <DecisionTable rows={rows} columns={columns} emptyText="Run neural model inference to build the core ETF board." />
      </Panel>
      <div className="notice">
        Core ETF changes remain subject to the 3% minimum adjustment threshold, two-day state confirmation, and the portfolio risk gate.
      </div>
    </SnapshotFrame>
  );
}
