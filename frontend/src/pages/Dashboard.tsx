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
  const [refreshingBrief, setRefreshingBrief] = useState(false);
  const [briefError, setBriefError] = useState("");
  const modelStatus = text(data?.summary.multi_horizon_status ?? model.status ?? asDict(model.model).status, "MODEL_NOT_READY");
  const headline = modelStatus !== "READY"
    ? "Train the long-horizon model before using trade recommendations."
    : approved.length
      ? `${approved.length} approved action${approved.length === 1 ? "" : "s"} require review.`
      : "No strong action. Keep positions unchanged.";

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
          <p>Long-horizon ranking, entry timing, portfolio discipline, and risk gate are fused before an action reaches this list.</p>
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
            ["Plan quality", <Status value={asDict(planQuality.summary).status ?? planQuality.status ?? "UNKNOWN"} />],
            ["Last model run", text(model.generated_at)],
            ["Model version", text(asDict(model.model).version ?? asDict(model.model).trained_at)],
          ]} />
        </Panel>
      </div>
    </SnapshotFrame>
  );
}
