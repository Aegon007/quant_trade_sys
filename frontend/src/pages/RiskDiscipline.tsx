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
  { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "Long horizon", render: (row) => <Status value={asDict(row.long_horizon).state} /> },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "Timing", render: (row) => <Status value={asDict(row.timing).state} /> },
  { label: "Final action", render: (row) => <Status value={asDict(row.decision).action} /> },
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

  return (
    <SnapshotFrame snapshot={risk.data} loading={risk.loading} error={risk.error} onReload={() => { risk.reload(); model.reload(); }}>
      <MetricStrip items={[
        { label: "Discipline", value: text(payload.regime ?? summary.regime, "UNKNOWN"), hint: "Heavy / normal / light / stop" },
        { label: "Risk regime", value: text(payload.risk_regime ?? summary.risk_regime, "UNKNOWN"), hint: "Final veto authority" },
        { label: "Actual exposure", value: formatPercent(account.exposure_pct ?? summary.actual_exposure_pct), hint: `Target ${formatPercent(payload.target_exposure_pct ?? summary.target_exposure_pct)}` },
        { label: "Available cash", value: formatCurrency(account.cash_available, 2), hint: `Total capital ${formatCurrency(account.total_capital, 2)}` },
      ]} />
      <Panel title="Live position concentration" subtitle="Calculated from the latest Portfolio holdings and current prices, not from a stale nightly copy.">
        <DecisionTable
          rows={holdings}
          columns={[
            { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
            { label: "Shares", render: (row) => text(row.current_shares) },
            { label: "Avg / Last", render: averageLastCell },
            { label: "Value", render: (row) => formatCurrency(row.current_value, 2) },
            { label: "Account weight", render: (row) => formatPercent(row.current_weight_pct) },
            { label: "Limit", render: () => formatPercent(account.max_single_position_pct) },
            { label: "Status", render: (row) => <Status value={Number(row.current_weight_pct ?? 0) > Number(account.max_single_position_pct ?? 0) ? "OVER LIMIT" : "OK"} /> },
          ]}
          detail={() => <div className="decision-detail"><p>Position limits use total capital: available cash plus current market value.</p></div>}
          emptyText="No current holdings are available."
        />
      </Panel>
      <Panel title="Signal conflicts" subtitle="A short-term deterioration does not independently liquidate a strong long-term asset.">
        <DecisionTable rows={conflicts} columns={conflictColumns} emptyText="No model conflicts in the latest snapshot." />
      </Panel>
      <div className="split-layout">
        <Panel title="Risk rules and alerts" subtitle="Raw model output must pass these controls.">
          <DecisionTable
            rows={riskRows}
            columns={[
              { label: "Level", render: (row) => <Status value={row.level ?? row.severity ?? row.status} /> },
              { label: "Area", render: (row) => text(row.category ?? row.type ?? row.name) },
              { label: "Message", render: (row) => text(row.message ?? row.reason ?? row.description) },
              { label: "Action", render: (row) => text(row.action ?? row.recommended_action) },
            ]}
          />
        </Panel>
        <Panel title="Discipline feedback" subtitle="Monthly calibration remains observational, never auto-rewrites risk rules.">
          <Facts rows={[
            ["Monthly status", <Status value={asDict(payload.monthly_review).status ?? "PENDING"} />],
            ["Can open core", text(payload.can_open_new_core_positions)],
            ["Can open satellite", text(payload.can_open_new_satellite_positions)],
            ["Model status", <Status value={modelPayload.status ?? asDict(modelPayload.model).status ?? "MODEL_NOT_READY"} />],
          ]} />
        </Panel>
      </div>
      <Panel title="LLM risk interpretation" subtitle="Uses current risk controls and cached news evidence. It cannot override the risk gate.">
        <LlmExplanation endpoint="/api/actions/explain-risk" label="Explain current risk" />
      </Panel>
    </SnapshotFrame>
  );
}
