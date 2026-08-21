import { DecisionTable } from "../components/DecisionTable";
import { MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { asArray, asDict, formatCurrency, formatDate, formatPercent, text, useSnapshot, type Dict } from "../lib/data";

export default function MarketMonitor() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/market-monitor");
  const payload = asDict(data?.payload);
  const summary = data?.summary ?? {};
  const benchmarks = asArray(payload.benchmark_rows);
  const tactical = asArray(payload.tactical_rows);
  const events = asArray(payload.events ?? payload.alerts ?? payload.items ?? payload.signals);
  const marketColumns = [
    { label: "代码", className: "symbol-cell", render: (row: Dict) => text(row.symbol) },
    { label: "状态", render: (row: Dict) => <Status value={row.status} /> },
    { label: "价格", render: (row: Dict) => formatCurrency(row.current_price, 2) },
    { label: "涨跌", render: (row: Dict) => formatPercent(row.change_pct) },
    { label: "角色", render: (row: Dict) => text(row.role ?? row.row_type) },
  ];
  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "市场状态", value: text(summary.state ?? payload.status, "MONITOR"), hint: "仅用于盘中覆盖层" },
        { label: "建议动作", value: text(summary.recommended_action, "NONE"), hint: text(summary.recommended_symbol) },
        { label: "紧急事件", value: events.length, hint: "普通噪音会被抑制" },
        { label: "新鲜度", value: data?.freshness_status ?? "-", hint: "记录主源/备用源" },
      ]} />
      <div className="split-layout">
        <Panel title="大盘压力" subtitle="主要指数和波动率监控。">
          <DecisionTable rows={benchmarks} columns={marketColumns} />
        </Panel>
        <Panel title="战术工具" subtitle="反向ETF只作为战术工具，不作为默认长期持仓。">
          <DecisionTable rows={tactical} columns={marketColumns} />
        </Panel>
      </div>
      <Panel title="紧急事件流" subtitle="只有风险破坏和异常波动才应该在盘中打扰你。">
        <DecisionTable rows={events} columns={[
          { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol ?? row.ticker) },
          { label: "类别", render: (row) => <Status value={row.event_class ?? row.classification ?? row.severity} /> },
          { label: "涨跌", render: (row) => formatPercent(row.move_pct ?? row.price_change_pct ?? row.change_pct) },
          { label: "触发原因", render: (row) => text(row.trigger ?? row.reason ?? row.message) },
          { label: "更新时间", render: (row) => formatDate(row.updated_at ?? row.generated_at ?? row.timestamp) },
        ]} />
      </Panel>
      <div className="notice">盘中事件结果会持续记录，用于未来训练“告警是否有价值”的模型。目前尚未上线学习型盘中分类器。</div>
    </SnapshotFrame>
  );
}
