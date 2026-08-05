import { DecisionTable } from "../components/DecisionTable";
import { Facts, MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { asArray, asDict, formatPercent, text, useSnapshot, type Dict } from "../lib/data";

function horizonRows(section: Dict): unknown[] {
  return Object.entries(asDict(section.horizons)).map(([horizon, metrics]) => ({
    horizon,
    ...asDict(metrics),
  }));
}

export default function ResearchModels() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/research-models");
  const payload = asDict(data?.payload);
  const snapshot = asDict(payload.multi_horizon_snapshot);
  const foundationSnapshot = asDict(payload.foundation_model_snapshot);
  const foundationConfig = asDict(payload.foundation_config);
  const validation = asDict(payload.validation);
  const candidate = asDict(validation.candidate);
  const registry = asDict(payload.model_registry);
  const model = asDict(snapshot.model);
  const summary = asDict(snapshot.summary);
  const marketSentiment = asDict(snapshot.market_sentiment);
  const systemicRisk = asDict(snapshot.systemic_risk);

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "Engine", value: text(model.backend_family ?? model.model_family, "FOUNDATION"), hint: text(model.backend ?? foundationConfig.default_backend, "auto") },
        { label: "Status", value: text(snapshot.status ?? model.status, "MODEL_NOT_READY"), hint: text(model.authority, "governed") },
        { label: "Symbols", value: text(summary.symbol_count, "0"), hint: text(snapshot.generated_at, "No snapshot yet") },
        { label: "Validation archive", value: text(validation.status, "OPTIONAL"), hint: `${text(validation.fold_count, "0")} historical folds` },
      ]} />

      <Panel
        title="Foundation quant engine"
        subtitle="The legacy self-trained benchmark has been retired. Nightly/weekend jobs now use the foundation-model-first engine and write the shared signal snapshot."
      >
        <Facts rows={[
          ["Snapshot source", text(foundationSnapshot.status ? "foundation_model_snapshot" : "shared_signal_snapshot")],
          ["Backend", text(model.backend, text(foundationConfig.default_backend, "auto"))],
          ["Backend family", text(model.backend_family ?? model.model_family, "UNKNOWN")],
          ["Authority", text(model.authority, "governed")],
          ["Horizons", text(snapshot.horizons ?? foundationConfig.horizons, "63, 126, 252")],
          ["History period", text(foundationConfig.history_period, "10y")],
          ["Risk appetite", text(marketSentiment.risk_appetite_state, "-")],
          ["AI capex stress", text(systemicRisk.ai_capex_stress, "-")],
        ]} />
      </Panel>

      <Panel title="Current signal quality archive" subtitle="Read-only historical validation kept for reference. It no longer promotes or deploys a benchmark model.">
        <DecisionTable rows={horizonRows(candidate)} columns={[
          { label: "Horizon", render: (row) => `${text(row.horizon)}d` },
          { label: "Up accuracy", render: (row) => formatPercent(row.directional_accuracy) },
          { label: "BIL accuracy", render: (row) => formatPercent(row.risk_free_directional_accuracy) },
          { label: "Return MAE", render: (row) => formatPercent(row.median_return_mae) },
          { label: "Top 3 vs BIL", render: (row) => formatPercent(row.top_k_risk_free_excess_return) },
        ]} emptyText="No archived validation metrics are available." />
      </Panel>

      <Panel title="Model registry" subtitle="Only active decision engines are registered here.">
        <DecisionTable rows={asArray(registry.models)} columns={[
          { label: "Model", render: (row) => text(row.display_name ?? row.model_id) },
          { label: "Role", render: (row) => text(row.role) },
          { label: "Default", render: (row) => <Status value={row.is_default ? "YES" : "NO"} /> },
          { label: "Enabled", render: (row) => <Status value={row.enabled ? "YES" : "NO"} /> },
        ]} />
      </Panel>
    </SnapshotFrame>
  );
}
