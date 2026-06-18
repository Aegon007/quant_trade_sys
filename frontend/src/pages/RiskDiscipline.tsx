import { DecisionTable, HorizonStrip, type DecisionColumn } from "../components/DecisionTable";
import { Facts, MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { asArray, asDict, formatPercent, text, useSnapshot, type Dict } from "../lib/data";

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

  return (
    <SnapshotFrame snapshot={risk.data} loading={risk.loading} error={risk.error} onReload={() => { risk.reload(); model.reload(); }}>
      <MetricStrip items={[
        { label: "Discipline", value: text(payload.regime ?? summary.regime, "UNKNOWN"), hint: "Heavy / normal / light / stop" },
        { label: "Risk regime", value: text(payload.risk_regime ?? summary.risk_regime, "UNKNOWN"), hint: "Final veto authority" },
        { label: "Target exposure", value: formatPercent(payload.target_exposure_pct ?? summary.target_exposure_pct), hint: "Portfolio-level output" },
        { label: "Model conflicts", value: conflicts.length, hint: "Long strong, timing weak" },
      ]} />
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
    </SnapshotFrame>
  );
}
