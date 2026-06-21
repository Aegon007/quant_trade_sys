import { ActionStatus, DecisionTable, HorizonStrip, type DecisionColumn } from "../components/DecisionTable";
import { Facts, MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import {
  asArray,
  asDict,
  formatCurrency,
  formatPercent,
  modelDecision,
  text,
  useSnapshot,
  type Dict,
} from "../lib/data";

const actionColumns: DecisionColumn[] = [
  { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "Action", render: (row) => <ActionStatus row={row} /> },
  { label: "Long horizon", render: (row) => <Status value={asDict(row.long_horizon).state} /> },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "Timing", render: (row) => <Status value={asDict(row.timing).state} /> },
  { label: "Target weight", render: (row) => text(modelDecision(row).target_weight_range_pct) },
];

export default function Dashboard() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/dashboard");
  const payload = asDict(data?.payload);
  const account = asDict(payload.account);
  const model = asDict(payload.multi_horizon_snapshot);
  const modelSummary = asDict(model.summary);
  const modelSymbols = asArray(model.symbols).map(asDict);
  const approved = modelSymbols.filter((row) => ["ACCUMULATE", "PROBE", "TRIM", "EXIT"].includes(text(modelDecision(row).action, "").toUpperCase()));
  const conflicts = modelSymbols.filter((row) => {
    const longState = text(asDict(row.long_horizon).state, "").toUpperCase();
    const timingState = text(asDict(row.timing).state, "").toUpperCase();
    return longState === "ATTRACTIVE" && ["DETERIORATING", "FAILED"].includes(timingState);
  });
  const discipline = asDict(payload.discipline_snapshot);
  const dataHealth = asDict(payload.data_health_snapshot);
  const planQuality = asDict(payload.plan_quality_snapshot);
  const newsIntelligence = asDict(payload.news_intelligence);
  const newsImpacts = asArray(newsIntelligence.portfolio_impacts);
  const newsLlm = asDict(newsIntelligence.llm);
  const newsSource = asDict(newsIntelligence.source_status);
  const modelStatus = text(data?.summary.multi_horizon_status ?? model.status ?? asDict(model.model).status, "MODEL_NOT_READY");
  const headline = modelStatus !== "READY"
    ? "Train the long-horizon model before using trade recommendations."
    : approved.length
      ? `${approved.length} approved action${approved.length === 1 ? "" : "s"} require review.`
      : "No strong action. Keep positions unchanged.";

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className={`decision-brief ${approved.length ? "action" : ""}`}>
        <div>
          <span className="eyebrow">Tomorrow's decision brief</span>
          <h2>{headline}</h2>
          <p>Long-horizon ranking, entry timing, portfolio discipline, and risk gate are fused before an action reaches this list.</p>
        </div>
        <Status value={modelStatus} />
      </section>

      <MetricStrip items={[
        { label: "Total capital", value: formatCurrency(account.total_capital), hint: `Cash ${formatCurrency(account.cash_available)}` },
        { label: "Exposure", value: formatPercent(account.exposure_pct), hint: `${text(data?.summary.holding_count, "0")} positions` },
        { label: "Discipline", value: text(discipline.regime, "UNKNOWN"), hint: `Risk ${text(discipline.risk_regime, "UNKNOWN")}` },
        { label: "Model conflicts", value: text(modelSummary.conflict_count, "0"), hint: "Attractive long term, weak timing" },
      ]} />

      <Panel title="Approved actions" subtitle="Only fused, risk-approved actions appear here. Expand any row for the full horizon distribution.">
        <DecisionTable rows={approved} columns={actionColumns} emptyText="No approved trades in the latest model snapshot." />
      </Panel>

      <Panel
        title="Portfolio news intelligence"
        subtitle={`Evidence-backed summary · ${text(newsIntelligence.status, "NOT_READY")} · ${text(newsLlm.model, "structured only")}`}
      >
        <div className={`notice ${text(newsIntelligence.market_risk_level, "").toUpperCase() === "HIGH" ? "negative" : ""}`}>
          {text(newsIntelligence.executive_summary, "Run the nightly pipeline to build portfolio-aware news intelligence.")}
        </div>
        <DecisionTable
          rows={newsImpacts.slice(0, 6)}
          columns={[
            { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
            { label: "Direction", render: (row) => <Status value={row.direction} /> },
            { label: "Relevance", render: (row) => text(row.relevance_score) },
            { label: "Confidence", render: (row) => formatPercent(row.confidence) },
            { label: "Risk action", render: (row) => <Status value={row.risk_action} /> },
            { label: "Evidence summary", render: (row) => text(row.summary) },
          ]}
          detail={(row) => (
            <div className="decision-detail">
              <div>
                <h4>Source evidence</h4>
                {asArray(row.evidence).map((item, index) => {
                  const evidence = asDict(item);
                  return <p key={index}><b>{text(evidence.source, "source")}</b><span>{text(evidence.title)}</span></p>;
                })}
              </div>
              <div>
                <h4>Provenance</h4>
                <p><b>News source</b><span>{text(newsSource.status, "UNKNOWN")}</span></p>
                <p><b>LLM route</b><span>{text(newsLlm.route_name, "structured")}</span></p>
                <p><b>Generated</b><span>{text(newsIntelligence.generated_at)}</span></p>
              </div>
            </div>
          )}
          emptyText="No portfolio-relevant active news is available."
        />
      </Panel>

      <div className="split-layout">
        <Panel title="Signal disagreements" subtitle="These are not sell signals by themselves.">
          <DecisionTable
            rows={conflicts}
            columns={actionColumns.slice(0, 5)}
            emptyText="No long-horizon and timing conflicts."
          />
        </Panel>
        <Panel title="Trust checks" subtitle="Recommendation quality depends on these controls.">
          <Facts rows={[
            ["Model", <Status value={modelStatus} />],
            ["Data health", <Status value={asDict(dataHealth.summary).status ?? dataHealth.status ?? "UNKNOWN"} />],
            ["Plan quality", <Status value={asDict(planQuality.summary).status ?? planQuality.status ?? "UNKNOWN"} />],
            ["Last model run", text(model.generated_at)],
            ["Model version", text(asDict(model.model).version ?? asDict(model.model).trained_at)],
          ]} />
        </Panel>
      </div>
    </SnapshotFrame>
  );
}
