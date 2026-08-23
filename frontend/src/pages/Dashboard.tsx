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
  { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "动作", render: (row) => <ActionStatus row={row} /> },
  { label: "长期判断", render: (row) => <Status value={asDict(row.long_horizon).state} /> },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "入场时机", render: (row) => <Status value={asDict(row.timing).state} /> },
  { label: "目标仓位", render: (row) => text(modelDecision(row).target_weight_range_pct) },
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
  const approved = modelSymbols.filter((row) => ["ACCUMULATE", "DCA_ACCUMULATE", "PROBE", "TRIM", "EXIT"].includes(text(modelDecision(row).action, "").toUpperCase()));
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
  const finalDecision = asDict(payload.final_decision);
  const strategySections = asDict(finalDecision.strategy_sections);
  const coreSection = asDict(strategySections.core_etf);
  const satelliteSection = asDict(strategySections.satellite);
  const riskSection = asDict(strategySections.risk_discipline);
  const correlationSection = asDict(strategySections.weekend_correlation);
  const briefLlm = asDict(decisionBrief.llm);
  const marketSentiment = asDict(payload.market_sentiment);
  const systemicRisk = asDict(payload.systemic_risk);
  const financialsIntelligence = asDict(payload.financials_intelligence);
  const financialsSummary = asDict(financialsIntelligence.summary);
  const modelInfo = asDict(model.model);
  const [refreshingBrief, setRefreshingBrief] = useState(false);
  const [briefError, setBriefError] = useState("");
  const modelStatus = text(data?.summary.multi_horizon_status ?? model.status ?? modelInfo.status, "MODEL_NOT_READY");
  const modelRuntimeStatus = text(model.status ?? modelInfo.status, "MODEL_NOT_READY").toUpperCase();
  const modelFreshnessStatus = text(data?.summary.multi_horizon_status, "").toUpperCase();
  const dataHealthStatus = text(data?.summary.data_health_status ?? asDict(dataHealth.summary).status ?? dataHealth.status, "").toUpperCase();
  const modelStatusDetail = [
    `运行状态 ${text(model.status ?? modelInfo.status, "MODEL_NOT_READY")}`,
    `快照状态 ${text(data?.summary.multi_horizon_status, "UNKNOWN")}`,
    `后端 ${text(modelInfo.backend ?? modelInfo.backend_family ?? modelInfo.model_family, "UNKNOWN")}`,
    `时间 ${text(model.generated_at, "-")}`,
  ].join(" · ");
  const finalDecisionValue = text(finalDecision.final_decision, "").toUpperCase();
  const headline = finalDecisionValue === "WAIT"
    ? "建议等待：先处理数据或风险问题。"
    : finalDecisionValue === "STOP"
      ? "纪律层停手：当前不应新增仓位。"
      : finalDecisionValue === "ACTION"
        ? `有 ${planItems.length} 条明日可执行计划需要你复核。`
        : dataHealthStatus === "BROKEN"
          ? "数据健康异常：请先强制刷新市场数据，再参考交易建议。"
          : modelFreshnessStatus === "STALE"
            ? "模型快照已过期：建议先运行夜间流程或刷新模型快照，再参考交易建议。"
            : modelRuntimeStatus !== "READY"
              ? `模型运行快照未就绪（${text(model.status ?? modelInfo.status, "MODEL_NOT_READY")}），暂不应使用交易建议。`
          : "没有强交易信号。除非盘中出现紧急告警，否则建议保持仓位不动。";
  const headlineReason = dataHealthStatus === "BROKEN"
    ? `数据健康原因：${text(data?.summary.data_health_reason, "价格缺失或数据源异常")}。建议先到运行操作页执行强制刷新市场数据。`
    : modelFreshnessStatus === "STALE"
      ? `模型快照状态：${modelStatus}。建议运行完整夜间流程，让模型、风险、交易计划和新闻摘要重新对齐。`
      : modelRuntimeStatus !== "READY"
        ? `${modelStatusDetail}。在 Jetson 上通常需要先到“运行操作”页执行“运行完整夜间流程”，或到“模型研究/Settings”确认 foundation model 已下载并可加载。`
        : text(asArray(finalDecision.top_reasons)[0], "模型候选不是交易指令。只有当入场时机、组合纪律、风险门控和失效条件都通过后，才会进入明日计划。");

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
          <span className="eyebrow">{text(finalDecision.system_identity, "明日决策简报")}</span>
          <h2>{headline}</h2>
          <p>{headlineReason}</p>
        </div>
        <Status value={finalDecision.final_decision ?? modelStatus} />
      </section>

      <Panel title="统一策略视图" subtitle="系统现在只保留一个最终口径：核心ETF配置、卫星趋势雷达、风险纪律门控共同决定行动；周末相关性和LLM只提供线索/解释。">
        <MetricStrip items={[
          { label: "最终结论", value: text(finalDecision.final_decision, "UNKNOWN"), hint: text(finalDecision.generated_at, "-") },
          { label: "核心ETF动作", value: text(coreSection.action_count, "0"), hint: text(coreSection.role, "长期主仓") },
          { label: "卫星仓动作", value: text(satelliteSection.action_count, "0"), hint: text(satelliteSection.role, "前三候选") },
          { label: "风险纪律", value: text(riskSection.regime, "UNKNOWN"), hint: `风险 ${text(riskSection.risk_regime, "UNKNOWN")}` },
          { label: "相关性线索", value: text(correlationSection.high_correlation_pair_count, "0"), hint: "周末计算，不直接交易" },
        ]} />
        <Facts rows={[
          ["系统主线", text(asDict(finalDecision.system_scope).primary, "核心ETF配置 + 卫星仓雷达 + 风险纪律层")],
          ["排除范围", text(asDict(finalDecision.system_scope).excluded, "高频交易，不把统计套利作为主交易引擎")],
          ["周末研究定位", text(asDict(finalDecision.system_scope).weekend_research_role, "相关性研究只输出风险和机会线索")],
          ["可用现金", formatCurrency(asDict(finalDecision.capital).cash_available)],
          ["当前暴露", formatPercent(asDict(finalDecision.capital).exposure_pct)],
        ]} />
      </Panel>

      <Panel
        title="LLM组合决策摘要"
        subtitle={`汇总量化信号、仓位纪律、风险变化和证据 · ${text(decisionBrief.status, "NOT READY")} · ${text(briefLlm.model, "结构化兜底")}`}
        action={<button className="quiet-button" disabled={refreshingBrief} onClick={refreshDecisionBrief}>{refreshingBrief ? "刷新中..." : "刷新LLM摘要"}</button>}
      >
        <div className={`llm-home-brief ${Number(decisionBrief.high_priority_change_count ?? 0) > 0 ? "alert" : ""}`}>
          <p>{text(decisionBrief.executive_summary, "请先配置远程LLM，然后运行夜间流程或手动刷新摘要。")}</p>
          <div>
            <Status value={decisionBrief.trigger ?? "WAITING"} />
            <span>{text(decisionBrief.approved_action_count, "0")} 个动作</span>
            <span>{text(decisionBrief.conflict_count, "0")} 个冲突</span>
            <span>{text(decisionBrief.high_priority_change_count, "0")} 个高优先级变化</span>
            <span>{text(decisionBrief.generated_at, "-")}</span>
          </div>
        </div>
        {briefError ? <div className="notice negative">{briefError}</div> : null}
      </Panel>

      <MetricStrip items={[
        { label: "总资产", value: formatCurrency(account.total_capital), hint: `现金 ${formatCurrency(account.cash_available)}` },
        { label: "仓位暴露", value: formatPercent(account.exposure_pct), hint: `${text(data?.summary.holding_count, "0")} 个持仓` },
        { label: "模型", value: text(modelInfo.backend_family ?? modelInfo.model_family, "UNKNOWN"), hint: `${text(modelInfo.backend, "无后端")} · ${text(modelInfo.authority, "受治理")}` },
        { label: "AI资本开支压力", value: text(systemicRisk.ai_capex_stress, "UNKNOWN"), hint: `分数 ${text(systemicRisk.systemic_risk_score, "-")}` },
        { label: "财务数据", value: text(financialsIntelligence.status, "NO DATA"), hint: `${text(financialsSummary.covered_count, "0")} 已覆盖 · ${text(financialsSummary.stress_count, "0")} 压力` },
      ]} />

      <Panel
        title="建议一致性"
        subtitle="这里区分原始模型候选和真正可执行的明日交易计划。"
      >
        <Facts rows={[
          ["一致性", <Status value={data?.summary.recommendation_consistency_status ?? "UNKNOWN"} />],
          ["解释", text(data?.summary.recommendation_consistency_message, "-")],
          ["模型候选数", text(data?.summary.model_candidate_action_count, "0")],
          ["可执行计划数", text(data?.summary.executable_plan_action_count, "0")],
          ["被风险/纪律阻断", text(data?.summary.blocked_plan_count, "0")],
          ["交易计划结论", <Status value={data?.summary.trade_plan_decision ?? "UNKNOWN"} />],
        ]} />
      </Panel>

      <div className="split-layout">
        <Panel title="市场情绪" subtitle="市场宽度、波动率、风险偏好和事件语气会作为模型协变量或风险覆盖层。">
          <Facts rows={[
            ["风险偏好", <Status value={marketSentiment.risk_appetite_state ?? "UNKNOWN"} />],
            ["情绪分数", text(marketSentiment.market_sentiment_score, "-")],
            ["市场宽度", <Status value={marketSentiment.breadth_state ?? "UNKNOWN"} />],
            ["置信度", formatPercent(marketSentiment.sentiment_confidence)],
            ["主要驱动", text(marketSentiment.main_sentiment_drivers)],
          ]} />
        </Panel>
        <Panel title="系统性风险预警" subtitle="跟踪AI资本开支、市场集中度、相关性、新闻压力和风险关闭状态。">
          <Facts rows={[
            ["AI资本开支压力", <Status value={systemicRisk.ai_capex_stress ?? "UNKNOWN"} />],
            ["系统性分数", text(systemicRisk.systemic_risk_score, "-")],
            ["AI产业链相关性", text(systemicRisk.ai_supply_chain_correlation, "不可用")],
            ["硬财务数据", <Status value={asDict(systemicRisk.data_freshness).hard_financial_data ?? "MISSING"} />],
            ["置信度", formatPercent(systemicRisk.confidence)],
            ["主要驱动", text(systemicRisk.top_drivers)],
          ]} />
        </Panel>
      </div>

      <Panel
        title="财报与财务压力分析"
        subtitle={`现金流、资本开支、债务和收入增长压力 · ${text(financialsIntelligence.status, "NOT_READY")} · ${text(asDict(financialsIntelligence.llm).model, "结构化兜底")}`}
      >
        <div className={`news-brief ${Number(financialsSummary.stress_count ?? 0) > 0 ? "negative" : ""}`}>
          {readableNewsLines(financialsIntelligence.executive_summary).length
            ? readableNewsLines(financialsIntelligence.executive_summary).map((line, index) => <p key={index}>{line}</p>)
            : <p>请运行夜间流程来生成财报/财务压力分析。</p>}
          <div>
            <Status value={financialsSummary.hard_financial_data ?? "MISSING"} />
            <span>{text(financialsSummary.covered_count, "0")} 已覆盖</span>
            <span>{text(financialsSummary.caution_count, "0")} 谨慎</span>
            <span>{text(financialsSummary.stress_count, "0")} 压力</span>
            <span>{text(financialsIntelligence.generated_at, "-")}</span>
          </div>
        </div>
      </Panel>

      <Panel title="明日可执行计划" subtitle="只有这些标的通过了执行计划器。如果为空，系统当前建议就是不交易。">
        <DecisionTable rows={planItems} columns={[
          { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
          { label: "计划", render: (row) => <Status value={row.plan_action} /> },
          { label: "买入区间", render: (row) => `${text(row.buy_zone_low, "-")} - ${text(row.buy_zone_high, "-")}` },
          { label: "风险破坏位", render: (row) => text(row.risk_break_level, "-") },
          { label: "仓位变化", render: (row) => text(row.plan_weight_delta_pct, "-") },
          { label: "有效期", render: (row) => text(row.plan_valid_until, "-") },
        ]} emptyText={text(tradePlan.summary_reason, "当前没有可执行的明日计划。")} />
      </Panel>

      <Panel title="模型候选动作" subtitle="这些只是长期/时机模型的原始候选，仍需执行计划器确认后才会成为交易计划。">
        <DecisionTable rows={approved} columns={actionColumns} emptyText="最新模型快照里没有交易候选。" />
        {blockedPlanItems.length ? <div className="notice">被阻断候选数：{blockedPlanItems.length}。如果要人工覆盖，请先复核风险与纪律层。</div> : null}
      </Panel>

      <Panel
        title="组合新闻情报"
        subtitle={`基于证据的新闻摘要 · ${text(newsIntelligence.status, "NOT_READY")} · ${text(newsLlm.model, "结构化输出")}`}
      >
        <div className={`news-brief ${text(newsIntelligence.market_risk_level, "").toUpperCase() === "HIGH" ? "negative" : ""}`}>
          {readableNewsLines(newsIntelligence.executive_summary).length
            ? readableNewsLines(newsIntelligence.executive_summary).map((line, index) => <p key={index}>{line}</p>)
            : <p>请运行夜间流程来生成组合相关的新闻情报。</p>}
          <div>
            <Status value={newsIntelligence.market_risk_level ?? "LOW"} />
            <span>{text(newsSource.status, "UNKNOWN")} 数据源</span>
            <span>{text(newsLlm.route_name, "structured")} 路由</span>
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
                    <span>置信度 {formatPercent(row.confidence)}</span>
                    <span>相关性 {text(row.relevance_score)}</span>
                    <em>{readableNewsLines(row.summary)[0] ?? text(row.summary)}</em>
                  </summary>
                  <div className="news-evidence-list">
                    {asArray(row.evidence).map((entry, evidenceIndex) => {
                      const evidence = asDict(entry);
                      return (
                        <p key={evidenceIndex}>
                          <b>{text(evidence.source, "来源")}</b>
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
          <div className="empty-state">当前没有组合相关的活跃新闻。</div>
        )}
      </Panel>

      <div className="split-layout">
        <Panel title="信号冲突" subtitle="这些冲突本身并不等于卖出信号。">
          <DecisionTable
            rows={conflicts}
            columns={actionColumns.slice(0, 5)}
            emptyText="长期判断和入场时机之间没有冲突。"
          />
        </Panel>
        <Panel title="可信度检查" subtitle="建议质量依赖这些控制项。">
          <Facts rows={[
            ["模型运行状态", <Status value={model.status ?? modelInfo.status ?? "MODEL_NOT_READY"} />],
            ["模型快照状态", <Status value={data?.summary.multi_horizon_status ?? "UNKNOWN"} />],
            ["数据健康度", <Status value={asDict(dataHealth.summary).status ?? dataHealth.status ?? "UNKNOWN"} />],
            ["健康度原因", text(asDict(dataHealth.summary).health_reason, text(data?.summary.data_health_reason, "unknown"))],
            ["建议修复", text(asDict(dataHealth.summary).action_required, text(data?.summary.data_health_action_required, "none"))],
            ["计划质量", <Status value={asDict(planQuality.summary).status ?? planQuality.status ?? "UNKNOWN"} />],
            ["上次模型运行", text(model.generated_at)],
            ["模型版本", text(asDict(model.model).version ?? asDict(model.model).trained_at)],
          ]} />
        </Panel>
      </div>
    </SnapshotFrame>
  );
}
