import { useMemo, useState } from "react";
import { ActionStatus, DecisionTable, HorizonStrip, ModelDetail, type DecisionColumn } from "../components/DecisionTable";
import { LlmExplanation } from "../components/LlmExplanation";
import { MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { asArray, asDict, formatCurrency, formatPercent, modelDecision, text, useSnapshot, type Dict } from "../lib/data";

const columns: DecisionColumn[] = [
  { label: "Rank", render: (row, index) => text(row.satellite_rank ?? index + 1) },
  { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "Long score", render: (row) => formatPercent(asDict(row.long_horizon).blended_rank ?? row.long_horizon_rank) },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "Timing", render: (row) => <Status value={asDict(row.timing).state ?? row.timing_state} /> },
  { label: "Risk", render: (row) => <Status value={asDict(row.risk).regime ?? row.risk_level ?? "NORMAL"} /> },
  { label: "State", render: (row) => <ActionStatus row={row} /> },
];

export default function SatelliteRadar() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/satellite-radar");
  const payload = asDict(data?.payload);
  const top = asArray(payload.top_recommendations);
  const pool = asArray(payload.candidate_pool);
  const currentHoldings = asArray(payload.current_holdings);
  const [query, setQuery] = useState("");
  const filteredPool = useMemo(() => {
    const normalized = query.trim().toUpperCase();
    if (!normalized) return pool;
    return pool.filter((item) => text(asDict(item).symbol, "").toUpperCase().includes(normalized));
  }, [pool, query]);
  const approved = top.map(asDict).filter((row) => ["ACCUMULATE", "PROBE"].includes(text(modelDecision(row).action, "").toUpperCase()));
  const detail = (row: Dict) => (
    <>
      <ModelDetail row={row} />
      <LlmExplanation endpoint="/api/actions/explain-satellite" payload={{ symbol: text(row.symbol) }} />
    </>
  );

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "Top 3", value: top.map((row) => text(asDict(row).symbol, "")).filter(Boolean).join(", ") || "-", hint: "Maximum satellite shortlist" },
        { label: "Approved entries", value: approved.length, hint: "No strong signal means no trade" },
        { label: "Ranked pool", value: pool.length, hint: "Capped by model configuration" },
        { label: "Current non-core", value: currentHoldings.length, hint: "Existing positions tracked separately from new candidates" },
      ]} />
      <Panel title="Current non-core holdings" subtitle="Existing positions are monitored here; they are intentionally excluded from the new-entry Top 3 competition.">
        <DecisionTable
          rows={currentHoldings}
          columns={[
            { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
            { label: "Account weight", render: (row) => formatPercent(row.current_weight_pct) },
            { label: "Value", render: (row) => formatCurrency(row.current_value, 2) },
            { label: "Long score", render: (row) => formatPercent(asDict(row.long_horizon).blended_rank) },
            { label: "Timing", render: (row) => <Status value={asDict(row.timing).state ?? row.timing_state} /> },
            { label: "Action", render: (row) => <ActionStatus row={row} /> },
          ]}
          emptyText="No current holdings sit outside the configured Core ETF universe."
        />
      </Panel>
      <Panel title="Top 3 satellite candidates" subtitle="These are the only non-core candidates eligible for a new-entry action.">
        <DecisionTable rows={top} columns={columns} detail={detail} emptyText="No neural Top 3 yet. Train or run the multi-horizon model." />
      </Panel>
      <Panel
        title="Ranked research funnel"
        subtitle="Candidates outside Top 3 remain WATCH even when their raw score is attractive."
        action={<input className="compact-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter symbol" />}
      >
        <DecisionTable rows={filteredPool} columns={columns} detail={detail} emptyText="No candidate pool is available." />
      </Panel>
    </SnapshotFrame>
  );
}
