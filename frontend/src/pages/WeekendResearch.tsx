import { useEffect, useMemo, useState } from "react";
import { postApi } from "../api";
import { DecisionTable } from "../components/DecisionTable";
import { Facts, MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { asArray, asDict, formatDate, formatNumber, formatPercent, text, useSnapshot, type Dict } from "../lib/data";

function jobIsActive(job: Dict): boolean {
  return ["started", "running", "queued"].includes(text(job.state, "").toLowerCase());
}

function elapsed(value: unknown): string {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "-";
  if (seconds < 60) return `${seconds.toFixed(0)}秒`;
  return `${Math.floor(seconds / 60)}分 ${Math.floor(seconds % 60)}秒`;
}

export default function WeekendResearch() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/weekend-research");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const payload = asDict(data?.payload);
  const weekend = asDict(payload.weekend_research);
  const correlation = asDict(payload.weekend_correlation);
  const universe = asDict(payload.research_universe);
  const job = asDict(payload.job);
  const summary = asDict(weekend.summary);
  const corrSummary = asDict(correlation.summary);
  const active = jobIsActive(job);
  const progress = Math.max(0, Math.min(Number(job.progress_pct ?? 0), 100));
  const sourceCounts = asDict(universe.source_counts);

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => reload(true), 1500);
    return () => window.clearInterval(timer);
  }, [active, reload]);

  async function runWeekendResearch() {
    setSubmitting(true);
    setMessage("周末研究：正在提交后台任务...");
    try {
      const response = await postApi<Dict>("/api/actions/run-weekend-research-once");
      setMessage(response.accepted ? "周末研究已启动。请观察下方进度。" : `启动失败：${text(response.error)}`);
      await reload(true);
    } catch (exc) {
      setMessage(`启动失败：${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setSubmitting(false);
    }
  }

  const sourceRows = useMemo(
    () => Object.entries(sourceCounts).map(([source, count]) => ({ source, count })),
    [sourceCounts],
  );

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "任务状态", value: text(job.state, "NOT RUN"), hint: text(job.stage, "等待周末任务") },
        { label: "研究宇宙", value: formatNumber(universe.symbol_count, 0), hint: `上限 ${formatNumber(universe.max_symbols, 0)}` },
        { label: "高相关对", value: formatNumber(corrSummary.high_correlation_pair_count, 0), hint: "集中度线索" },
        { label: "低相关强势", value: formatNumber(corrSummary.independent_strength_count, 0), hint: "机会线索" },
        { label: "相关性簇", value: formatNumber(corrSummary.cluster_count, 0), hint: "主题/拥挤线索" },
      ]} />

      <Panel
        title="周末长任务控制台"
        subtitle="周末研究用于扫描更大的股票/ETF/商品/避险资产宇宙，输出风险与机会线索，不直接下交易指令。"
        action={<button disabled={submitting || active} onClick={runWeekendResearch}>{active ? "运行中..." : "立即运行周末研究"}</button>}
      >
        {message ? <div className="notice">{message}</div> : null}
        <div className="job-control running">
          <div className="job-control-main">
            <div>
              <h3>{text(job.detail, "等待周末研究任务")}</h3>
              <p>阶段：{text(job.stage, "-")} · 更新：{formatDate(job.updated_at)} · 耗时：{elapsed(job.elapsed_seconds)}</p>
            </div>
            <Status value={job.state ?? "NOT RUN"} />
          </div>
          <div className="job-progress"><span style={{ width: `${progress}%` }} /></div>
          <div className="job-control-meta">
            <span>进度：{progress ? `${progress.toFixed(0)}%` : "-"}</span>
            <span>请求标的：{formatNumber(job.symbol_count ?? universe.symbol_count, 0)}</span>
            <span>可用数据：{formatNumber(job.usable_symbol_count ?? corrSummary.symbol_count, 0)}</span>
            <span>失败/缺失：{formatNumber(job.failed_symbol_count ?? corrSummary.missing_symbol_count, 0)}</span>
          </div>
        </div>
      </Panel>

      <Panel title="研究宇宙" subtitle="如果未来要扫几千/上万只标的，扩展 storage/config/weekend_research_universe.json 即可。">
        <Facts rows={[
          ["选中标的", formatNumber(universe.symbol_count, 0)],
          ["上限", formatNumber(universe.max_symbols, 0)],
          ["截断", universe.truncated ? "是" : "否"],
          ["下周偏向", text(summary.next_week_bias, "-")],
          ["研究角色", text(corrSummary.research_role, "RISK_AND_OPPORTUNITY_CLUES")],
        ]} />
        <DecisionTable rows={sourceRows} columns={[
          { label: "来源", render: (row) => text(row.source) },
          { label: "数量", render: (row) => formatNumber(row.count, 0) },
        ]} emptyText="暂无研究宇宙来源。" detail={(row) => <div className="decision-detail"><p><b>来源说明</b><span>{text(row.source)} 贡献了 {formatNumber(row.count, 0)} 个标的。</span></p></div>} />
      </Panel>

      <Panel title="算法阶段" subtitle="这里追踪周末研究到底跑了哪些数据挖掘步骤。">
        <DecisionTable rows={asArray(correlation.research_stages)} columns={[
          { label: "阶段", render: (row) => text(row.name) },
          { label: "状态", render: (row) => <Status value={row.status} /> },
          { label: "标的/列", render: (row) => formatNumber(row.symbol_count ?? row.column_count, 0) },
          { label: "结果", render: (row) => formatNumber(row.result_count, 0) },
        ]} emptyText="还没有阶段记录。运行一次周末研究后会显示。" detail={(row) => <div className="decision-detail"><p><b>阶段详情</b><span>{JSON.stringify(row)}</span></p></div>} />
      </Panel>

      <Panel title="组合冗余与高相关风险" subtitle="这些是减少重复押注和行业拥挤度的线索，不是自动卖出指令。">
        <DecisionTable rows={asArray(correlation.portfolio_redundancy)} columns={[
          { label: "标的A", render: (row) => text(row.left) },
          { label: "标的B", render: (row) => text(row.right) },
          { label: "相关性", render: (row) => formatNumber(row.correlation, 2) },
          { label: "合计仓位", render: (row) => formatPercent(row.combined_weight_pct) },
        ]} emptyText="当前持仓没有检测到明显高相关冗余。" detail={(row) => <div className="decision-detail"><p><b>研究备注</b><span>{text(row.research_note)}</span></p></div>} />
      </Panel>

      <Panel title="低相关强势候选" subtitle="这类标的可能是下周值得研究的卫星仓线索，但必须再经过趋势、基本面和风险纪律确认。">
        <DecisionTable rows={asArray(correlation.independent_strength)} columns={[
          { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
          { label: "强度分", render: (row) => formatNumber(row.independent_strength_score, 3) },
          { label: "超额SPY", render: (row) => formatPercent(row.excess_vs_spy) },
          { label: "相关SPY", render: (row) => formatNumber(row.correlation_to_spy, 2) },
        ]} emptyText="暂无低相关强势候选。" detail={(row) => <div className="decision-detail"><p><b>研究备注</b><span>{text(row.research_note)}</span></p></div>} />
      </Panel>

      <Panel title="相关性簇" subtitle="用于识别同一主题、同一风险暴露或同涨同跌资产包。">
        <DecisionTable rows={asArray(correlation.correlation_clusters)} columns={[
          { label: "成员", render: (row) => text(row.members) },
          { label: "数量", render: (row) => formatNumber(row.member_count, 0) },
          { label: "边数", render: (row) => formatNumber(row.edge_count, 0) },
          { label: "均值相关", render: (row) => formatNumber(row.average_correlation, 2) },
        ]} emptyText="暂无相关性簇。" detail={(row) => <div className="decision-detail"><p><b>研究备注</b><span>{text(row.research_note)}</span></p></div>} />
      </Panel>
    </SnapshotFrame>
  );
}
