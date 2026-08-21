import { useEffect, useMemo, useState } from "react";
import { downloadApi, postApi } from "../api";
import { DecisionTable } from "../components/DecisionTable";
import { Panel, Status } from "../components/Primitives";
import { asArray, asDict, formatDate, text, useSnapshot, type Dict } from "../lib/data";
import { zhStatus } from "../lib/i18n";

type JobDefinition = {
  key: string;
  registryName: string;
  label: string;
  description: string;
  endpoint?: string;
  payload?: unknown;
};

const manualJobs: JobDefinition[] = [
  {
    key: "refresh",
    registryName: "manual-market-refresh",
    label: "强制刷新市场数据",
    description: "绕过缓存，更新关注标的价格，并重建数据健康状态。",
    endpoint: "/api/actions/refresh-market",
    payload: { force_source_refresh: true },
  },
  {
    key: "nightly",
    registryName: "manual-nightly-run",
    label: "运行完整夜间流程",
    description: "运行模型、计划、风险、新闻情报、报告和通知。",
    endpoint: "/api/actions/run-nightly-once",
  },
  {
    key: "weekend",
    registryName: "manual-weekend-research",
    label: "运行周末研究",
    description: "在交易循环之外运行长期研究和策略验证。",
    endpoint: "/api/actions/run-weekend-research-once",
  },
];

const scheduledJobs: JobDefinition[] = [
  {
    key: "auto-refresh",
    registryName: "scheduled-market-refresh",
    label: "自动市场刷新",
    description: "由 jobs.run_all 触发的价格、新闻和健康度刷新。",
  },
  {
    key: "auto-nightly",
    registryName: "scheduled-nightly-run",
    label: "自动夜间流程",
    description: "系统触发的夜间报告、交易计划、风险和通知流程。",
  },
  {
    key: "auto-weekend",
    registryName: "weekend-research",
    label: "自动周末研究",
    description: "系统触发的周末研究流程。",
  },
];

function isActive(job: Dict): boolean {
  return ["started", "running", "queued"].includes(text(job.state, "").toLowerCase());
}

function elapsed(value: unknown): string {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "-";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
}

function resultText(job: Dict): string {
  const summary = asDict(job.result_summary);
  if (!Object.keys(summary).length) return text(job.detail, "暂无结果。");
  return Object.entries(summary)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${text(value)}`)
    .join(" · ");
}

export default function Operations() {
  const jobs = useSnapshot<Dict>("/api/job-status");
  const health = useSnapshot<Dict>("/api/data-health");
  const [submitting, setSubmitting] = useState("");
  const [commandResult, setCommandResult] = useState("");
  const [replaceLedger, setReplaceLedger] = useState(false);
  const jobMap = asDict(asDict(jobs.data?.payload).jobs);
  const hasActiveJobs = Object.values(jobMap).map(asDict).some(isActive);

  useEffect(() => {
    const timer = window.setInterval(() => {
      jobs.reload(true);
      if (hasActiveJobs) health.reload(true);
    }, hasActiveJobs ? 1000 : 5000);
    return () => window.clearInterval(timer);
  }, [hasActiveJobs, health.reload, jobs.reload]);

  async function run(definition: JobDefinition) {
    if (!definition.endpoint) return;
    const current = asDict(jobMap[definition.registryName]);
    if (isActive(current)) return;
    setSubmitting(definition.key);
    setCommandResult(`${definition.label}：正在提交...`);
    try {
      const response = await postApi<Dict>(definition.endpoint, definition.payload);
      const accepted = Boolean(response.accepted);
      setCommandResult(
        accepted
          ? `${definition.label}：已接受。实时状态见下方。`
          : `${definition.label}：请求未被接受。${text(response.error, "")}`,
      );
      await jobs.reload(true);
      await health.reload(true);
    } catch (exc) {
      setCommandResult(`${definition.label}：${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setSubmitting("");
    }
  }

  async function importCsv(file: File | null) {
    if (!file) return;
    setSubmitting("robinhood");
    setCommandResult("Robinhood CSV：正在导入...");
    try {
      const response = await postApi<Dict>("/api/actions/import-robinhood-csv", {
        filename: file.name,
        csv_text: await file.text(),
        replace_existing: replaceLedger,
      });
      const result = asDict(response.result);
      setCommandResult(`Robinhood CSV：${text(result.message, response.accepted ? "已完成" : "失败")}`);
      await jobs.reload(true);
      await health.reload(true);
    } catch (exc) {
      setCommandResult(`Robinhood CSV：${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setSubmitting("");
    }
  }

  async function downloadDiagnostics() {
    setSubmitting("diagnostics");
    setCommandResult("诊断包：正在生成...");
    try {
      await downloadApi("/api/downloads/diagnostics-bundle", "quant-diagnostics.zip");
      setCommandResult("诊断包已下载。如果Jetson上需要深度诊断，把这个zip带回来即可。");
    } catch (exc) {
      setCommandResult(`诊断包：${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setSubmitting("");
    }
  }

  const taskRows = useMemo(
    () => [...manualJobs, ...scheduledJobs].map((definition) => ({
      ...definition,
      ...asDict(jobMap[definition.registryName]),
      name: definition.registryName,
      display_state: asDict(jobMap[definition.registryName]).state ?? "not run",
    })),
    [jobMap],
  );
  const healthRows = asArray(asDict(health.data?.payload).symbols);

  return (
    <>
      <Panel title="系统任务" subtitle="每个任务都会显示排队、运行、完成或失败状态。运行中的任务每秒刷新。">
        <div className="job-control-list">
          {manualJobs.map((definition) => {
            const job = asDict(jobMap[definition.registryName]);
            const active = isActive(job);
            const progress = Number(job.progress_pct ?? 0);
            return (
              <article className={`job-control ${active ? "running" : ""}`} key={definition.key}>
                <div className="job-control-main">
                  <div>
                    <h3>{definition.label}</h3>
                    <p>{definition.description}</p>
                  </div>
                  <Status value={job.state ?? "NOT RUN"} />
                </div>
                <div className="job-progress">
                  <span style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }} />
                </div>
                <div className="job-control-meta">
                  <span>阶段：{text(job.stage, "-")}</span>
                  <span>进度：{job.progress_pct === undefined ? "-" : `${progress.toFixed(0)}%`}</span>
                  <span>耗时：{elapsed(job.elapsed_seconds)}</span>
                  <span>更新：{formatDate(job.updated_at)}</span>
                </div>
                <p className="job-result">{resultText(job)}</p>
                <button disabled={!!submitting || active} onClick={() => run(definition)}>
                  {submitting === definition.key ? "提交中..." : active ? "运行中..." : definition.label}
                </button>
              </article>
            );
          })}
        </div>
      </Panel>

      <Panel title="自动调度状态" subtitle="即使任务由系统自动触发，这里也会记录最近一次运行状态。">
        <DecisionTable rows={scheduledJobs.map((definition) => ({
          ...definition,
          ...asDict(jobMap[definition.registryName]),
          name: definition.registryName,
          display_state: asDict(jobMap[definition.registryName]).state ?? "not run",
        }))} columns={[
          { label: "任务", render: (row) => text(row.label ?? row.name) },
          { label: "状态", render: (row) => <Status value={row.display_state ?? row.state} /> },
          { label: "最近详情", render: (row) => text(row.detail, "还没有调度事件") },
          { label: "更新时间", render: (row) => formatDate(row.updated_at) },
          { label: "耗时", render: (row) => elapsed(row.elapsed_seconds) },
        ]} />
      </Panel>

      <Panel title="Robinhood交易流水导入" subtitle="追加模式会自动去重；重建模式会备份并替换本地交易流水。">
        <label className="check-line">
          <input type="checkbox" checked={replaceLedger} onChange={(event) => setReplaceLedger(event.target.checked)} />
          用这个CSV重建交易流水
        </label>
        <label className="file-input">
          <input disabled={!!submitting} type="file" accept=".csv,text/csv" onChange={(event) => importCsv(event.target.files?.[0] ?? null)} />
          选择Account Activity CSV
        </label>
      </Panel>

      <Panel title="便携诊断包" subtitle="从部署机器下载安全快照包；密钥不会包含在内。">
        <div className="notice">
          当Jetson显示数据健康度下降、建议过期或页面不一致时使用。诊断包包含数据健康、价格缓存摘要、任务状态、计划、模型快照和变化流。
        </div>
        <button disabled={!!submitting} onClick={downloadDiagnostics}>
          {submitting === "diagnostics" ? "正在生成诊断包..." : "下载诊断包"}
        </button>
      </Panel>

      <Panel title="详细任务历史" subtitle="持久化状态会保留在页面刷新和浏览器重启之后。">
        <DecisionTable rows={taskRows} columns={[
          { label: "任务", render: (row) => text(row.label ?? row.name) },
          { label: "状态", render: (row) => <Status value={row.display_state ?? row.state} /> },
          { label: "阶段", render: (row) => text(row.stage) },
          { label: "进度", render: (row) => row.progress_pct === undefined ? "-" : `${Number(row.progress_pct).toFixed(0)}%` },
          { label: "耗时", render: (row) => elapsed(row.elapsed_seconds) },
          { label: "更新", render: (row) => formatDate(row.updated_at) },
        ]} detail={(row) => <div className="decision-detail"><p><b>结果</b><span>{resultText(row)}</span></p></div>} />
      </Panel>

      <Panel title="数据源健康度" subtitle="刷新任务完成后，结果会立即显示在这里。">
        <div className="notice">
          状态：<b>{zhStatus(asDict(health.data?.summary).data_health_status ?? asDict(asDict(health.data?.payload).summary).status ?? "UNKNOWN")}</b>
          {" · "}原因：<b>{text(asDict(asDict(health.data?.payload).summary).health_reason, "unknown")}</b>
          {" · "}动作：<b>{text(asDict(asDict(health.data?.payload).summary).action_required, "none")}</b>
        </div>
        <DecisionTable rows={healthRows} columns={[
          { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
          { label: "状态", render: (row) => <Status value={row.status} /> },
          { label: "数据源", render: (row) => text(row.source) },
          { label: "原因", render: (row) => text(row.reason) },
        ]} />
      </Panel>

      <Panel title="最近命令回执" subtitle="这里确认提交结果；权威完成状态请看系统任务。">
        <div className="notice">{commandResult || "本浏览器会话还没有手动运行命令。"}</div>
      </Panel>
    </>
  );
}
