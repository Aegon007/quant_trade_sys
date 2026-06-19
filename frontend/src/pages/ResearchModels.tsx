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

const TRAINING_PHASES = [
  ["Data", 15],
  ["Panel", 25],
  ["Validation", 65],
  ["Pretrain", 78],
  ["Final train", 96],
  ["Inference", 100],
] as const;

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
  const promotionGates = asDict(governance.promotion_gates);
  const registry = asDict(payload.model_registry);
  const training = asDict(snapshot.training);
  const trainingJob = asDict(
    asDict(asDict(jobs.data?.payload).jobs)["manual-multi-horizon-training"],
  );
  const jobState = text(trainingJob.state, "").toLowerCase();
  const isTraining = ["started", "running"].includes(jobState);
  const [launching, setLaunching] = useState(false);
  const [promoting, setPromoting] = useState(false);
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

  async function promoteModel() {
    setPromoting(true);
    setResult("");
    try {
      const response = await postApi<Dict>("/api/actions/promote-multi-horizon");
      if (response.accepted === false) {
        throw new Error(text(response.error, "Model promotion was rejected."));
      }
      setResult(text(response.message, "Model promoted."));
      reload();
    } catch (exc) {
      setResult((exc as Error).message);
    } finally {
      setPromoting(false);
    }
  }

  const progress = Number(trainingJob.progress_pct ?? 0);
  const canPromote = text(lifecycle.status, "").toUpperCase() === "ELIGIBLE_FOR_MANUAL_PROMOTION";
  const isProduction = Boolean(lifecycle.production_authorized);

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
          <div className="training-progress-copy">
            <Status value={jobState || "IDLE"} />
            <strong>{text(trainingJob.detail, "No active training job")}</strong>
            <span>
              {text(trainingJob.stage, "idle")}
              {trainingJob.device ? ` · ${text(trainingJob.device)}` : ""}
              {trainingJob.epoch ? ` · epoch ${text(trainingJob.epoch)}/${text(trainingJob.epochs)}` : ""}
              {trainingJob.loss !== undefined ? ` · loss ${Number(trainingJob.loss).toFixed(4)}` : ""}
            </span>
          </div>
          <div className="training-track" aria-label={`Training progress ${progress.toFixed(0)}%`}>
            <i style={{ width: `${Math.min(Math.max(progress, 0), 100)}%` }} />
          </div>
          <b>{progress.toFixed(0)}%</b>
          <ol className="training-phases">
            {TRAINING_PHASES.map(([label, threshold]) => (
              <li key={label} className={progress >= threshold ? "complete" : progress > threshold - 20 ? "active" : ""}>
                <span />
                {label}
              </li>
            ))}
          </ol>
        </div>
        <Facts rows={[
          ["Model ID", text(asDict(snapshot.model).model_id, "finance_multi_asset_transformer")],
          ["Horizons", text(snapshot.horizons ?? asDict(payload.config).horizons, "63, 126, 252")],
          ["Symbols", text(asDict(snapshot.summary).symbol_count, "0")],
          ["Risk-free benchmark", text(asDict(snapshot.benchmarks).risk_free ?? asDict(payload.config).risk_free_benchmark, "BIL")],
          ["Pretraining", text(asDict(training.pretraining).checkpoint_path, "Not run")],
          ["Final fit loss", text(training.loss, "Not trained")],
          ["Return quantile loss", text(training.quantile_loss, "Not trained")],
          ["Upside probability loss", text(training.positive_return_loss, "Not trained")],
          ["BIL probability loss", text(training.risk_free_outperformance_loss, "Not trained")],
          ["Result", result || text(trainingJob.detail, "Ready to train")],
        ]} />
      </Panel>

      <div className="three-layout">
        <Panel title="Neural candidate" subtitle="Pretrained architecture, out of sample.">
          <DecisionTable rows={horizonRows(candidate)} columns={[
            { label: "Horizon", render: (row) => `${text(row.horizon)}d` },
            { label: "Up accuracy", render: (row) => formatPercent(row.directional_accuracy) },
            { label: "BIL accuracy", render: (row) => formatPercent(row.risk_free_directional_accuracy) },
            { label: "Return MAE", render: (row) => formatPercent(row.median_return_mae) },
            { label: "Top 3 vs BIL", render: (row) => formatPercent(row.top_k_risk_free_excess_return) },
          ]} />
        </Panel>
        <Panel title="Same model from scratch" subtitle="Measures pretraining's incremental value.">
          <DecisionTable rows={horizonRows(scratch)} columns={[
            { label: "Horizon", render: (row) => `${text(row.horizon)}d` },
            { label: "Up accuracy", render: (row) => formatPercent(row.directional_accuracy) },
            { label: "BIL accuracy", render: (row) => formatPercent(row.risk_free_directional_accuracy) },
            { label: "Return MAE", render: (row) => formatPercent(row.median_return_mae) },
            { label: "Top 3 vs BIL", render: (row) => formatPercent(row.top_k_risk_free_excess_return) },
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
        <Panel
          title="Validation & promotion"
          subtitle="Only purged walk-forward PASS models can be manually authorized for trading advice."
          action={
            <button disabled={!canPromote || promoting || isProduction} onClick={promoteModel}>
              {isProduction ? "Production authorized" : promoting ? "Promoting..." : "Promote to production"}
            </button>
          }
        >
          <Facts rows={[
            ["3+ walk-forward folds", <Status value={promotionGates.minimum_walk_forward_folds ? "PASS" : "REVIEW"} />],
            ["Up/down better than chance", <Status value={promotionGates.absolute_direction_better_than_chance ? "PASS" : "REVIEW"} />],
            ["Up probability calibrated", <Status value={promotionGates.absolute_probability_calibrated ? "PASS" : "REVIEW"} />],
            ["BIL direction better than chance", <Status value={promotionGates.risk_free_direction_better_than_chance ? "PASS" : "REVIEW"} />],
            ["BIL probability calibrated", <Status value={promotionGates.risk_free_probability_calibrated ? "PASS" : "REVIEW"} />],
            ["Return error bounded", <Status value={promotionGates.median_return_error_bounded ? "PASS" : "REVIEW"} />],
            ["Positive Top 3 vs BIL", <Status value={promotionGates.positive_top_k_risk_free_excess ? "PASS" : "REVIEW"} />],
            ["Positive 252d Rank IC", <Status value={promotionGates.positive_rank_ic ? "PASS" : "REVIEW"} />],
            ["Positive Top 3 vs SPY", <Status value={promotionGates.positive_top_k_excess_return ? "PASS" : "REVIEW"} />],
            ["Beats SPY-relative baseline", <Status value={promotionGates.beats_baseline_top_k ? "PASS" : "REVIEW"} />],
            ["Pretraining incremental", <Status value={promotionGates.pretraining_incremental ? "PASS" : "REVIEW"} />],
            ["MoE stable", <Status value={promotionGates.moe_stable ? "PASS" : "REVIEW"} />],
            ["Automatic promotion", <Status value="DISABLED" />],
            ["Decision authority", <Status value={isProduction ? "PRODUCTION" : "SHADOW ONLY"} />],
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
