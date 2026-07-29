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
  const marketSentiment = asDict(payload.market_sentiment);
  const systemicRisk = asDict(payload.systemic_risk);
  const financialsIntelligence = asDict(payload.financials_intelligence);
  const financialsSummary = asDict(financialsIntelligence.summary);

  return (
    <SnapshotFrame snapshot={risk.data} loading={risk.loading} error={risk.error} onReload={() => { risk.reload(); model.reload(); }}>
      <MetricStrip items={[
        { label: "Discipline", value: text(payload.regime ?? summary.regime, "UNKNOWN"), hint: "Heavy / normal / light / stop" },
        { label: "Risk regime", value: text(payload.risk_regime ?? summary.risk_regime, "UNKNOWN"), hint: "Final veto authority" },
        { label: "Market mood", value: text(marketSentiment.risk_appetite_state, "UNKNOWN"), hint: `Score ${text(marketSentiment.market_sentiment_score, "-")}` },
        { label: "AI capex stress", value: text(systemicRisk.ai_capex_stress, "UNKNOWN"), hint: `Systemic ${text(systemicRisk.systemic_risk_score, "-")}` },
        { label: "Financials", value: text(financialsSummary.hard_financial_data, "MISSING"), hint: `${text(financialsSummary.stress_count, "0")} stress` },
      ]} />
      <div className="split-layout">
        <Panel title="Market sentiment overlay" subtitle="Used to reduce confidence and block aggressive adds during risk-off tape.">
          <Facts rows={[
            ["Risk appetite", <Status value={marketSentiment.risk_appetite_state ?? "UNKNOWN"} />],
            ["Breadth state", <Status value={marketSentiment.breadth_state ?? "UNKNOWN"} />],
            ["Above 50d", formatPercent(marketSentiment.breadth_above_50d_pct)],
            ["Above 200d", formatPercent(marketSentiment.breadth_above_200d_pct)],
            ["Drivers", text(marketSentiment.main_sentiment_drivers)],
          ]} />
        </Panel>
        <Panel title="AI capex / systemic early warning" subtitle="A conservative overlay for concentration, correlation, AI capex narrative pressure, and risk-off regimes.">
          <Facts rows={[
            ["Stress state", <Status value={systemicRisk.ai_capex_stress ?? "UNKNOWN"} />],
            ["Score", text(systemicRisk.systemic_risk_score, "-")],
            ["AI correlation", text(systemicRisk.ai_supply_chain_correlation, "Unavailable")],
            ["Data freshness", text(systemicRisk.data_freshness)],
            ["Financial stress", text(systemicRisk.financial_statement_stress)],
            ["Warnings", text(systemicRisk.warnings)],
          ]} />
        </Panel>
      </div>
      <Panel title="Financial statement pressure" subtitle="Company-level cash-flow, capex, debt, and revenue-growth checks. ETFs often have no statement data.">
        <Facts rows={[
          ["Status", <Status value={financialsIntelligence.status ?? "NOT_READY"} />],
          ["Hard data", <Status value={financialsSummary.hard_financial_data ?? "MISSING"} />],
          ["Covered / missing", `${text(financialsSummary.covered_count, "0")} / ${text(financialsSummary.missing_count, "0")}`],
          ["Caution / stress", `${text(financialsSummary.caution_count, "0")} / ${text(financialsSummary.stress_count, "0")}`],
          ["Top stress", text(financialsSummary.top_stress_symbols)],
          ["Summary", text(financialsIntelligence.executive_summary)],
        ]} />
      </Panel>
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
