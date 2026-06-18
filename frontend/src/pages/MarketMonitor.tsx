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
    { label: "Symbol", className: "symbol-cell", render: (row: Dict) => text(row.symbol) },
    { label: "State", render: (row: Dict) => <Status value={row.status} /> },
    { label: "Price", render: (row: Dict) => formatCurrency(row.current_price, 2) },
    { label: "Move", render: (row: Dict) => formatPercent(row.change_pct) },
    { label: "Role", render: (row: Dict) => text(row.role ?? row.row_type) },
  ];
  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "Market state", value: text(summary.state ?? payload.status, "MONITOR"), hint: "Intraday overlay only" },
        { label: "Recommended action", value: text(summary.recommended_action, "NONE"), hint: text(summary.recommended_symbol) },
        { label: "Emergency events", value: events.length, hint: "Normal noise is suppressed" },
        { label: "Freshness", value: data?.freshness_status ?? "-", hint: "Primary/fallback source recorded" },
      ]} />
      <div className="split-layout">
        <Panel title="Benchmark pressure" subtitle="Broad market and volatility gauges.">
          <DecisionTable rows={benchmarks} columns={marketColumns} />
        </Panel>
        <Panel title="Tactical instruments" subtitle="Inverse ETFs are tactical tools, never default long-term holdings.">
          <DecisionTable rows={tactical} columns={marketColumns} />
        </Panel>
      </div>
      <Panel title="Emergency event stream" subtitle="Only risk breaks and exceptional moves should interrupt the user intraday.">
        <DecisionTable rows={events} columns={[
          { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol ?? row.ticker) },
          { label: "Class", render: (row) => <Status value={row.event_class ?? row.classification ?? row.severity} /> },
          { label: "Move", render: (row) => formatPercent(row.move_pct ?? row.price_change_pct ?? row.change_pct) },
          { label: "Trigger", render: (row) => text(row.trigger ?? row.reason ?? row.message) },
          { label: "Updated", render: (row) => formatDate(row.updated_at ?? row.generated_at ?? row.timestamp) },
        ]} />
      </Panel>
      <div className="notice">Event outcomes continue to be logged for future alert-value modeling. No learned intraday classifier is promoted yet.</div>
    </SnapshotFrame>
  );
}
