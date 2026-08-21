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
  const chronosConfig = asDict(asDict(foundationConfig.backends).chronos);
  const configuredModel = text(chronosConfig.model_name, "amazon/chronos-2");
  const runtimeModel = text(model.model_name, configuredModel);
  const revision = text(model.revision ?? chronosConfig.revision, "provider default");
  const runtimeDevice = text(model.runtime_device, text(chronosConfig.device, "auto"));

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "引擎", value: text(model.backend_family ?? model.model_family, "FOUNDATION"), hint: text(model.backend ?? foundationConfig.default_backend, "auto") },
        { label: "模型", value: runtimeModel, hint: `${revision} · ${runtimeDevice}` },
        { label: "状态", value: text(snapshot.status ?? model.status, "MODEL_NOT_READY"), hint: text(model.authority, "governed") },
        { label: "标的数", value: text(summary.symbol_count, "0"), hint: text(snapshot.generated_at, "还没有快照") },
      ]} />

      <Panel
        title="基础量化模型引擎"
        subtitle="旧的自训练基准模型已移除。夜间/周末任务使用基础模型优先的引擎，并写入共享信号快照。注意：模型只是预测组件，最终交易建议仍由风控和纪律层确认。"
      >
        <Facts rows={[
          ["快照来源", text(foundationSnapshot.status ? "foundation_model_snapshot" : "shared_signal_snapshot")],
          ["后端", text(model.backend, text(foundationConfig.default_backend, "auto"))],
          ["后端类型", text(model.backend_family ?? model.model_family, "UNKNOWN")],
          ["配置模型", configuredModel],
          ["快照模型", runtimeModel],
          ["版本", revision],
          ["运行设备", runtimeDevice],
          ["上下文/批量", `${text(model.context_length ?? chronosConfig.context_length, "512")} / ${text(model.batch_size ?? chronosConfig.batch_size, "8")}`],
          ["预测API", text(model.forecast_api, "predict_df / Chronos-2")],
          ["跨序列学习", text(model.cross_learning ?? chronosConfig.cross_learning, "false")],
          ["决策权限", text(model.authority, "governed")],
          ["预测周期", text(snapshot.horizons ?? foundationConfig.horizons, "63, 126, 252")],
          ["历史窗口", text(foundationConfig.history_period, "10y")],
          ["风险偏好", text(marketSentiment.risk_appetite_state, "-")],
          ["AI资本开支压力", text(systemicRisk.ai_capex_stress, "-")],
        ]} />
      </Panel>

      <Panel title="当前信号质量档案" subtitle="只读历史验证指标，用来追踪信号质量；不再负责提升或部署旧基准模型。">
        <DecisionTable rows={horizonRows(candidate)} columns={[
          { label: "周期", render: (row) => `${text(row.horizon)}天` },
          { label: "上涨方向准确率", render: (row) => formatPercent(row.directional_accuracy) },
          { label: "跑赢短债准确率", render: (row) => formatPercent(row.risk_free_directional_accuracy) },
          { label: "收益MAE", render: (row) => formatPercent(row.median_return_mae) },
          { label: "前三相对短债", render: (row) => formatPercent(row.top_k_risk_free_excess_return) },
        ]} emptyText="当前没有已归档的验证指标。" />
      </Panel>

      <Panel title="模型注册表" subtitle="这里只登记当前可用的决策引擎。">
        <DecisionTable rows={asArray(registry.models)} columns={[
          { label: "模型", render: (row) => text(row.display_name ?? row.model_id) },
          { label: "角色", render: (row) => text(row.role) },
          { label: "默认", render: (row) => <Status value={row.is_default ? "YES" : "NO"} /> },
          { label: "启用", render: (row) => <Status value={row.enabled ? "YES" : "NO"} /> },
        ]} />
      </Panel>
    </SnapshotFrame>
  );
}
