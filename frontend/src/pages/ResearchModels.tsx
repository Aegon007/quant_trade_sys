import { useEffect, useState } from "react";
import { postApi } from "../api";
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
  const jobs = useSnapshot<Dict>("/api/job-status");
  const payload = asDict(data?.payload);
  const snapshot = asDict(payload.multi_horizon_snapshot);
  const validation = asDict(payload.validation);
  const candidate = asDict(validation.candidate);
  const baseline = asDict(validation.relative_strength_baseline);
  const scratch = asDict(validation.scratch);
  const governance = asDict(validation.governance);
  const lifecycle = asDict(payload.governance);
  const registry = asDict(payload.model_registry);
  const trainingJob = asDict(
    asDict(asDict(jobs.data?.payload).jobs)["manual-multi-horizon-training"],
  );
  const jobState = text(trainingJob.state, "").toLowerCase();
  const isTraining = ["started", "running"].includes(jobState);
  const [launching, setLaunching] = useState(false);
  const [result, setResult] = useState("");

  useEffect(() => {
    const timer = window.setInterval(jobs.reload, isTraining ? 2000 : 5000);
    return () => window.clearInterval(timer);
  }, [isTraining]);

  useEffect(() => {
    if (jobState === "completed") reload();
  }, [jobState]);

  async function trainModel() {
    setLaunching(true);
    setResult("");
    try {
      const response = await postApi<Dict>("/api/actions/train-multi-horizon");
      setResult(text(response.message, "Training accepted."));
      jobs.reload();
    } catch (exc) {
      setResult((exc as Error).message);
    } finally {
      setLaunching(false);
    }
  }

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "Model status", value: text(snapshot.status ?? asDict(snapshot.model).status, "MODEL_NOT_READY"), hint: text(asDict(snapshot.model).trained_at, "No checkpoint") },
        { label: "Validation", value: text(validation.status, "PENDING"), hint: `${text(validation.fold_count, "0")} walk-forward folds` },
        { label: "MoE routing", value: asDict(candidate.moe).collapsed ? "COLLAPSED" : "STABLE", hint: "Expert usage is monitored" },
        { label: "Lifecycle", value: text(lifecycle.status, "RESEARCH"), hint: "Promotion is manual only" },
      ]} />

      <Panel
        title="Finance multi-asset Transformer"
        subtitle="Patch temporal encoder, cross-asset attention, sparse regime experts, and multi-horizon quantile heads."
        action={
          <button disabled={launching || isTraining} onClick={trainModel}>
            {launching ? "Starting..." : isTraining ? "Training in progress..." : "Train and validate model"}
          </button>
        }
      >
        <div className="training-progress">
          <div>
            <Status value={jobState || "IDLE"} />
            <strong>{text(trainingJob.detail, "No active training job")}</strong>
            <span>
              {text(trainingJob.stage, "idle")}
              {trainingJob.device ? ` · ${text(trainingJob.device)}` : ""}
              {trainingJob.epoch ? ` · epoch ${text(trainingJob.epoch)}/${text(trainingJob.epochs)}` : ""}
              {trainingJob.loss !== undefined ? ` · loss ${Number(trainingJob.loss).toFixed(4)}` : ""}
            </span>
          </div>
          <progress max="100" value={Number(trainingJob.progress_pct ?? 0)} />
          <b>{Number(trainingJob.progress_pct ?? 0).toFixed(0)}%</b>
        </div>
        <Facts rows={[
          ["Model ID", text(asDict(snapshot.model).model_id, "finance_multi_asset_transformer")],
          ["Horizons", text(snapshot.horizons ?? asDict(payload.config).horizons, "63, 126, 252")],
          ["Symbols", text(asDict(snapshot.summary).symbol_count, "0")],
          ["Pretraining", text(asDict(asDict(snapshot.training).pretraining).checkpoint_path, "Not run")],
          ["Result", result || text(trainingJob.detail, "Ready to train")],
        ]} />
      </Panel>

      <div className="three-layout">
        <Panel title="Neural candidate" subtitle="Pretrained architecture, out of sample.">
          <DecisionTable rows={horizonRows(candidate)} columns={[
            { label: "Horizon", render: (row) => `${text(row.horizon)}d` },
            { label: "Rank IC", render: (row) => formatPercent(row.rank_ic) },
            { label: "Top 3 excess", render: (row) => formatPercent(row.top_k_excess_return) },
          ]} />
        </Panel>
        <Panel title="Same model from scratch" subtitle="Measures pretraining's incremental value.">
          <DecisionTable rows={horizonRows(scratch)} columns={[
            { label: "Horizon", render: (row) => `${text(row.horizon)}d` },
            { label: "Rank IC", render: (row) => formatPercent(row.rank_ic) },
            { label: "Top 3 excess", render: (row) => formatPercent(row.top_k_excess_return) },
          ]} />
        </Panel>
        <Panel title="Relative-strength baseline" subtitle="Simple control, not a production model.">
          <DecisionTable rows={horizonRows(baseline)} columns={[
            { label: "Horizon", render: (row) => `${text(row.horizon)}d` },
            { label: "Rank IC", render: (row) => formatPercent(row.rank_ic) },
            { label: "Top 3 excess", render: (row) => formatPercent(row.top_k_excess_return) },
          ]} />
        </Panel>
      </div>

      <div className="split-layout">
        <Panel title="Promotion gates" subtitle="Training success is not production approval.">
          <Facts rows={[
            ["Beats baseline", <Status value={governance.beats_baseline_252d_top_k ? "PASS" : "REVIEW"} />],
            ["Pretraining incremental", <Status value={governance.pretraining_incremental_252d_top_k ? "PASS" : "REVIEW"} />],
            ["MoE collapsed", <Status value={governance.moe_collapsed ? "FAILED" : "PASS"} />],
            ["Automatic promotion", <Status value="DISABLED" />],
            ["Shadow outcomes", <Status value={asDict(lifecycle.shadow_outcomes).status ?? "OBSERVING"} />],
          ]} />
        </Panel>
        <Panel title="Model registry" subtitle="Only validated neural models may enter the production decision path.">
          <DecisionTable rows={asArray(registry.models)} columns={[
            { label: "Model", render: (row) => text(row.display_name ?? row.model_id) },
            { label: "Role", render: (row) => text(row.role) },
            { label: "State", render: (row) => <Status value={row.is_default ? "DEFAULT" : "OPTIONAL"} /> },
          ]} />
        </Panel>
      </div>
    </SnapshotFrame>
  );
}
