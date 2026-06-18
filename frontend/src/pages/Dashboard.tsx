import { ActionStatus, DecisionTable, HorizonStrip, type DecisionColumn } from "../components/DecisionTable";
import { Facts, MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import {
  asArray,
  asDict,
  formatCurrency,
  formatPercent,
  modelDecision,
  text,
  useSnapshot,
  type Dict,
} from "../lib/data";

const actionColumns: DecisionColumn[] = [
  { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "Action", render: (row) => <ActionStatus row={row} /> },
  { label: "Long horizon", render: (row) => <Status value={asDict(row.long_horizon).state} /> },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "Timing", render: (row) => <Status value={asDict(row.timing).state} /> },
  { label: "Target weight", render: (row) => text(modelDecision(row).target_weight_range_pct) },
];

export default function Dashboard() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/dashboard");
  const payload = asDict(data?.payload);
  const account = asDict(payload.account);
  const model = asDict(payload.multi_horizon_snapshot);
  const modelSummary = asDict(model.summary);
  const modelSymbols = asArray(model.symbols).map(asDict);
  const approved = modelSymbols.filter((row) => ["ACCUMULATE", "PROBE", "TRIM", "EXIT"].includes(text(modelDecision(row).action, "").toUpperCase()));
  const conflicts = modelSymbols.filter((row) => {
    const longState = text(asDict(row.long_horizon).state, "").toUpperCase();
    const timingState = text(asDict(row.timing).state, "").toUpperCase();
    return longState === "ATTRACTIVE" && ["DETERIORATING", "FAILED"].includes(timingState);
  });
  const discipline = asDict(payload.discipline_snapshot);
  const dataHealth = asDict(payload.data_health_snapshot);
  const planQuality = asDict(payload.plan_quality_snapshot);
  const modelStatus = text(data?.summary.multi_horizon_status ?? model.status ?? asDict(model.model).status, "MODEL_NOT_READY");
  const headline = modelStatus !== "READY"
    ? "Train the long-horizon model before using trade recommendations."
    : approved.length
      ? `${approved.length} approved action${approved.length === 1 ? "" : "s"} require review.`
      : "No strong action. Keep positions unchanged.";

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className={`decision-brief ${approved.length ? "action" : ""}`}>
        <div>
          <span className="eyebrow">Tomorrow's decision brief</span>
          <h2>{headline}</h2>
          <p>Long-horizon ranking, entry timing, portfolio discipline, and risk gate are fused before an action reaches this list.</p>
        </div>
        <Status value={modelStatus} />
      </section>

      <MetricStrip items={[
        { label: "Total capital", value: formatCurrency(account.total_capital), hint: `Cash ${formatCurrency(account.cash_available)}` },
        { label: "Exposure", value: formatPercent(account.exposure_pct), hint: `${text(data?.summary.holding_count, "0")} positions` },
        { label: "Discipline", value: text(discipline.regime, "UNKNOWN"), hint: `Risk ${text(discipline.risk_regime, "UNKNOWN")}` },
        { label: "Model conflicts", value: text(modelSummary.conflict_count, "0"), hint: "Attractive long term, weak timing" },
      ]} />

      <Panel title="Approved actions" subtitle="Only fused, risk-approved actions appear here. Expand any row for the full horizon distribution.">
        <DecisionTable rows={approved} columns={actionColumns} emptyText="No approved trades in the latest model snapshot." />
      </Panel>

      <div className="split-layout">
        <Panel title="Signal disagreements" subtitle="These are not sell signals by themselves.">
          <DecisionTable
            rows={conflicts}
            columns={actionColumns.slice(0, 5)}
            emptyText="No long-horizon and timing conflicts."
          />
        </Panel>
        <Panel title="Trust checks" subtitle="Recommendation quality depends on these controls.">
          <Facts rows={[
            ["Model", <Status value={modelStatus} />],
            ["Data health", <Status value={asDict(dataHealth.summary).status ?? dataHealth.status ?? "UNKNOWN"} />],
            ["Plan quality", <Status value={asDict(planQuality.summary).status ?? planQuality.status ?? "UNKNOWN"} />],
            ["Last model run", text(model.generated_at)],
            ["Model version", text(asDict(model.model).version ?? asDict(model.model).trained_at)],
          ]} />
        </Panel>
      </div>
    </SnapshotFrame>
  );
}
