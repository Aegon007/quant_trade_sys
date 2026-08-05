import { useState } from "react";
import { postApi } from "../api";
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

function readableNewsLines(value: unknown): string[] {
  const lines = text(value, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const cleaned: string[] = [];
  let headers: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const next = lines[index + 1] ?? "";
    const cells = line.startsWith("|") ? line.replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()).filter(Boolean) : [];
    const nextIsSeparator = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(next);
    if (cells.length && nextIsSeparator) {
      headers = cells;
      index += 1;
      continue;
    }
    if (/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line)) continue;
    if (cells.length) {
      if (headers.length === cells.length) {
        cleaned.push(headers.map((header, cellIndex) => `${header}: ${cells[cellIndex]}`).join("；"));
      } else {
        cleaned.push(cells.join("；"));
      }
      continue;
    }
    cleaned.push(line.replace(/\|---|---\|/g, "").trim());
  }
  return cleaned.filter(Boolean);
}

export default function Dashboard() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/dashboard");
  const payload = asDict(data?.payload);
  const account = asDict(payload.account);
  const model = asDict(payload.multi_horizon_snapshot);
  const modelSummary = asDict(model.summary);
  const modelSymbols = asArray(model.symbols).map(asDict);
  const approved = modelSymbols.filter((row) => ["ACCUMULATE", "PROBE", "TRIM", "EXIT"].includes(text(modelDecision(row).action, "").toUpperCase()));
  const tradePlan = asDict(payload.trade_plan);
  const planItems = asArray(tradePlan.items).map(asDict);
  const blockedPlanItems = asArray(tradePlan.blocked_items).map(asDict);
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
  const decisionBrief = asDict(payload.decision_brief);
  const briefLlm = asDict(decisionBrief.llm);
  const marketSentiment = asDict(payload.market_sentiment);
  const systemicRisk = asDict(payload.systemic_risk);
  const financialsIntelligence = asDict(payload.financials_intelligence);
  const financialsSummary = asDict(financialsIntelligence.summary);
  const modelInfo = asDict(model.model);
  const [refreshingBrief, setRefreshingBrief] = useState(false);
  const [briefError, setBriefError] = useState("");
  const modelStatus = text(data?.summary.multi_horizon_status ?? model.status ?? asDict(model.model).status, "MODEL_NOT_READY");
  const headline = modelStatus !== "READY"
    ? "Train the long-horizon model before using trade recommendations."
    : planItems.length
      ? `${planItems.length} executable next-day plan item${planItems.length === 1 ? "" : "s"} require review.`
      : "No executable action. Keep positions unchanged unless an intraday emergency alert fires.";

  async function refreshDecisionBrief() {
    setRefreshingBrief(true);
    setBriefError("");
    try {
      await postApi("/api/actions/refresh-decision-brief");
      await reload();
    } catch (exc) {
      setBriefError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRefreshingBrief(false);
    }
  }

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className={`decision-brief ${approved.length ? "action" : ""}`}>
        <div>
          <span className="eyebrow">Tomorrow's decision brief</span>
          <h2>{headline}</h2>
          <p>Model candidates are not execution orders. A trade reaches tomorrow's plan only after entry timing, portfolio discipline, risk gates, and invalidation rules agree.</p>
        </div>
        <Status value={modelStatus} />
      </section>

      <Panel
        title="LLM portfolio decision summary"
        subtitle={`All quant signals, portfolio controls, changes, and evidence · ${text(decisionBrief.status, "NOT READY")} · ${text(briefLlm.model, "structured fallback")}`}
        action={<button className="quiet-button" disabled={refreshingBrief} onClick={refreshDecisionBrief}>{refreshingBrief ? "Refreshing..." : "Refresh LLM summary"}</button>}
      >
        <div className={`llm-home-brief ${Number(decisionBrief.high_priority_change_count ?? 0) > 0 ? "alert" : ""}`}>
          <p>{text(decisionBrief.executive_summary, "Run the nightly pipeline or refresh this summary after configuring the remote LLM.")}</p>
          <div>
            <Status value={decisionBrief.trigger ?? "WAITING"} />
            <span>{text(decisionBrief.approved_action_count, "0")} actions</span>
            <span>{text(decisionBrief.conflict_count, "0")} conflicts</span>
            <span>{text(decisionBrief.high_priority_change_count, "0")} high-priority changes</span>
            <span>{text(decisionBrief.generated_at, "-")}</span>
          </div>
        </div>
        {briefError ? <div className="notice negative">{briefError}</div> : null}
      </Panel>

      <MetricStrip items={[
        { label: "Total capital", value: formatCurrency(account.total_capital), hint: `Cash ${formatCurrency(account.cash_available)}` },
        { label: "Exposure", value: formatPercent(account.exposure_pct), hint: `${text(data?.summary.holding_count, "0")} positions` },
        { label: "Model", value: text(modelInfo.backend_family ?? modelInfo.model_family, "UNKNOWN"), hint: `${text(modelInfo.backend, "no backend")} · ${text(modelInfo.authority, "governed")}` },
        { label: "AI capex stress", value: text(systemicRisk.ai_capex_stress, "UNKNOWN"), hint: `Score ${text(systemicRisk.systemic_risk_score, "-")}` },
        { label: "Financials", value: text(financialsIntelligence.status, "NO DATA"), hint: `${text(financialsSummary.covered_count, "0")} covered · ${text(financialsSummary.stress_count, "0")} stress` },
      ]} />

      <Panel
        title="Recommendation consistency"
        subtitle="This separates raw model candidates from the executable next-day trade plan."
      >
        <Facts rows={[
          ["Consistency", <Status value={data?.summary.recommendation_consistency_status ?? "UNKNOWN"} />],
          ["Explanation", text(data?.summary.recommendation_consistency_message, "-")],
          ["Model candidates", text(data?.summary.model_candidate_action_count, "0")],
          ["Executable plan items", text(data?.summary.executable_plan_action_count, "0")],
          ["Blocked by risk/discipline", text(data?.summary.blocked_plan_count, "0")],
          ["Trade plan decision", <Status value={data?.summary.trade_plan_decision ?? "UNKNOWN"} />],
        ]} />
      </Panel>

      <div className="split-layout">
        <Panel title="Market sentiment" subtitle="Breadth, volatility, risk appetite, and event tone are used as model covariates or risk overlay.">
          <Facts rows={[
            ["Risk appetite", <Status value={marketSentiment.risk_appetite_state ?? "UNKNOWN"} />],
            ["Sentiment score", text(marketSentiment.market_sentiment_score, "-")],
            ["Breadth", <Status value={marketSentiment.breadth_state ?? "UNKNOWN"} />],
            ["Confidence", formatPercent(marketSentiment.sentiment_confidence)],
            ["Drivers", text(marketSentiment.main_sentiment_drivers)],
          ]} />
        </Panel>
        <Panel title="Systemic risk early warning" subtitle="AI capex, market concentration, correlation, news pressure, and risk-off conditions.">
          <Facts rows={[
            ["AI capex stress", <Status value={systemicRisk.ai_capex_stress ?? "UNKNOWN"} />],
            ["Systemic score", text(systemicRisk.systemic_risk_score, "-")],
            ["AI correlation", text(systemicRisk.ai_supply_chain_correlation, "Unavailable")],
            ["Hard financial data", <Status value={asDict(systemicRisk.data_freshness).hard_financial_data ?? "MISSING"} />],
            ["Confidence", formatPercent(systemicRisk.confidence)],
            ["Drivers", text(systemicRisk.top_drivers)],
          ]} />
        </Panel>
      </div>

      <Panel
        title="Financial statement intelligence"
        subtitle={`Cash-flow, capex, debt, and revenue-growth stress · ${text(financialsIntelligence.status, "NOT_READY")} · ${text(asDict(financialsIntelligence.llm).model, "structured fallback")}`}
      >
        <div className={`news-brief ${Number(financialsSummary.stress_count ?? 0) > 0 ? "negative" : ""}`}>
          {readableNewsLines(financialsIntelligence.executive_summary).length
            ? readableNewsLines(financialsIntelligence.executive_summary).map((line, index) => <p key={index}>{line}</p>)
            : <p>Run the nightly pipeline to build statement-aware financial intelligence.</p>}
          <div>
            <Status value={financialsSummary.hard_financial_data ?? "MISSING"} />
            <span>{text(financialsSummary.covered_count, "0")} covered</span>
            <span>{text(financialsSummary.caution_count, "0")} caution</span>
            <span>{text(financialsSummary.stress_count, "0")} stress</span>
            <span>{text(financialsIntelligence.generated_at, "-")}</span>
          </div>
        </div>
      </Panel>

      <Panel title="Tomorrow executable plan" subtitle="Only these rows passed the execution planner. If this is empty, the system's active recommendation is no trade.">
        <DecisionTable rows={planItems} columns={[
          { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
          { label: "Plan", render: (row) => <Status value={row.plan_action} /> },
          { label: "Buy zone", render: (row) => `${text(row.buy_zone_low, "-")} - ${text(row.buy_zone_high, "-")}` },
          { label: "Risk break", render: (row) => text(row.risk_break_level, "-") },
          { label: "Weight delta", render: (row) => text(row.plan_weight_delta_pct, "-") },
          { label: "Valid until", render: (row) => text(row.plan_valid_until, "-") },
        ]} emptyText={text(tradePlan.summary_reason, "No executable next-day plan is available.")} />
      </Panel>

      <Panel title="Model candidate actions" subtitle="These are raw long-horizon/timing candidates. They still need the execution planner before they become a trade plan.">
        <DecisionTable rows={approved} columns={actionColumns} emptyText="No candidate trades in the latest model snapshot." />
        {blockedPlanItems.length ? <div className="notice">Blocked candidate count: {blockedPlanItems.length}. Review risk and discipline before overriding.</div> : null}
      </Panel>

      <Panel
        title="Portfolio news intelligence"
        subtitle={`Evidence-backed summary · ${text(newsIntelligence.status, "NOT_READY")} · ${text(newsLlm.model, "structured only")}`}
      >
        <div className={`news-brief ${text(newsIntelligence.market_risk_level, "").toUpperCase() === "HIGH" ? "negative" : ""}`}>
          {readableNewsLines(newsIntelligence.executive_summary).length
            ? readableNewsLines(newsIntelligence.executive_summary).map((line, index) => <p key={index}>{line}</p>)
            : <p>Run the nightly pipeline to build portfolio-aware news intelligence.</p>}
          <div>
            <Status value={newsIntelligence.market_risk_level ?? "LOW"} />
            <span>{text(newsSource.status, "UNKNOWN")} source</span>
            <span>{text(newsLlm.route_name, "structured")} route</span>
            <span>{text(newsIntelligence.generated_at, "-")}</span>
          </div>
        </div>
        {newsImpacts.length ? (
          <div className="news-impact-list">
            {newsImpacts.slice(0, 5).map((item, index) => {
              const row = asDict(item);
              return (
                <details key={`${text(row.symbol, "news")}-${index}`} className="news-impact-row">
                  <summary>
                    <b>{text(row.symbol)}</b>
                    <Status value={row.direction} />
                    <Status value={row.risk_action ?? "NONE"} />
                    <span>Confidence {formatPercent(row.confidence)}</span>
                    <span>Relevance {text(row.relevance_score)}</span>
                    <em>{readableNewsLines(row.summary)[0] ?? text(row.summary)}</em>
                  </summary>
                  <div className="news-evidence-list">
                    {asArray(row.evidence).map((entry, evidenceIndex) => {
                      const evidence = asDict(entry);
                      return (
                        <p key={evidenceIndex}>
                          <b>{text(evidence.source, "source")}</b>
                          <span>{text(evidence.title)}</span>
                        </p>
                      );
                    })}
                  </div>
                </details>
              );
            })}
          </div>
        ) : (
          <div className="empty-state">No portfolio-relevant active news is available.</div>
        )}
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
            ["Health reason", text(asDict(dataHealth.summary).health_reason, text(data?.summary.data_health_reason, "unknown"))],
            ["Suggested fix", text(asDict(dataHealth.summary).action_required, text(data?.summary.data_health_action_required, "none"))],
            ["Plan quality", <Status value={asDict(planQuality.summary).status ?? planQuality.status ?? "UNKNOWN"} />],
            ["Last model run", text(model.generated_at)],
            ["Model version", text(asDict(model.model).version ?? asDict(model.model).trained_at)],
          ]} />
        </Panel>
      </div>
    </SnapshotFrame>
  );
}
