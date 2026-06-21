import { useEffect, useMemo, useState } from "react";
import { postApi } from "../api";
import { DecisionTable } from "../components/DecisionTable";
import { Panel, Status } from "../components/Primitives";
import { asArray, asDict, formatDate, text, useSnapshot, type Dict } from "../lib/data";

type JobDefinition = {
  key: string;
  registryName: string;
  label: string;
  description: string;
  endpoint: string;
  payload?: unknown;
};

const manualJobs: JobDefinition[] = [
  {
    key: "refresh",
    registryName: "manual-market-refresh",
    label: "Force market refresh",
    description: "Bypass cache, update tracked prices, and rebuild data-health status.",
    endpoint: "/api/actions/refresh-market",
    payload: { force_source_refresh: true },
  },
  {
    key: "nightly",
    registryName: "manual-nightly-run",
    label: "Run full nightly pipeline",
    description: "Run models, plans, risk, news intelligence, reports, and notifications.",
    endpoint: "/api/actions/run-nightly-once",
  },
  {
    key: "weekend",
    registryName: "manual-weekend-research",
    label: "Run weekend research",
    description: "Run long-horizon research and strategy validation outside the trading loop.",
    endpoint: "/api/actions/run-weekend-research-once",
  },
  {
    key: "model",
    registryName: "manual-multi-horizon-training",
    label: "Train neural model",
    description: "Train and validate the multi-horizon neural candidate model.",
    endpoint: "/api/actions/train-multi-horizon",
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
  if (!Object.keys(summary).length) return text(job.detail, "No result yet.");
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
    const current = asDict(jobMap[definition.registryName]);
    if (isActive(current)) return;
    setSubmitting(definition.key);
    setCommandResult(`${definition.label}: submitting...`);
    try {
      const response = await postApi<Dict>(definition.endpoint, definition.payload);
      const accepted = Boolean(response.accepted);
      setCommandResult(
        accepted
          ? `${definition.label}: accepted. Live status is shown below.`
          : `${definition.label}: request was not accepted. ${text(response.error, "")}`,
      );
      await jobs.reload(true);
      await health.reload(true);
    } catch (exc) {
      setCommandResult(`${definition.label}: ${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setSubmitting("");
    }
  }

  async function importCsv(file: File | null) {
    if (!file) return;
    setSubmitting("robinhood");
    setCommandResult("Robinhood CSV: importing...");
    try {
      const response = await postApi<Dict>("/api/actions/import-robinhood-csv", {
        filename: file.name,
        csv_text: await file.text(),
        replace_existing: replaceLedger,
      });
      const result = asDict(response.result);
      setCommandResult(`Robinhood CSV: ${text(result.message, response.accepted ? "completed" : "failed")}`);
      await jobs.reload(true);
      await health.reload(true);
    } catch (exc) {
      setCommandResult(`Robinhood CSV: ${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setSubmitting("");
    }
  }

  const taskRows = useMemo(
    () => manualJobs.map((definition) => ({
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
      <Panel title="System jobs" subtitle="Each task reports queued, running, completed, or failed state. Active jobs refresh every second.">
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
                  <span>Stage: {text(job.stage, "-")}</span>
                  <span>Progress: {job.progress_pct === undefined ? "-" : `${progress.toFixed(0)}%`}</span>
                  <span>Elapsed: {elapsed(job.elapsed_seconds)}</span>
                  <span>Updated: {formatDate(job.updated_at)}</span>
                </div>
                <p className="job-result">{resultText(job)}</p>
                <button disabled={!!submitting || active} onClick={() => run(definition)}>
                  {submitting === definition.key ? "Submitting..." : active ? "Running..." : definition.label}
                </button>
              </article>
            );
          })}
        </div>
      </Panel>

      <Panel title="Robinhood ledger import" subtitle="Append mode deduplicates. Rebuild mode backs up and replaces the local ledger.">
        <label className="check-line">
          <input type="checkbox" checked={replaceLedger} onChange={(event) => setReplaceLedger(event.target.checked)} />
          Rebuild ledger from this CSV
        </label>
        <label className="file-input">
          <input disabled={!!submitting} type="file" accept=".csv,text/csv" onChange={(event) => importCsv(event.target.files?.[0] ?? null)} />
          Select Account Activity CSV
        </label>
      </Panel>

      <Panel title="Detailed job history" subtitle="Persistent status survives page refreshes and browser restarts.">
        <DecisionTable rows={taskRows} columns={[
          { label: "Job", render: (row) => text(row.label ?? row.name) },
          { label: "State", render: (row) => <Status value={row.display_state ?? row.state} /> },
          { label: "Stage", render: (row) => text(row.stage) },
          { label: "Progress", render: (row) => row.progress_pct === undefined ? "-" : `${Number(row.progress_pct).toFixed(0)}%` },
          { label: "Elapsed", render: (row) => elapsed(row.elapsed_seconds) },
          { label: "Updated", render: (row) => formatDate(row.updated_at) },
        ]} detail={(row) => <div className="decision-detail"><p><b>Result</b><span>{resultText(row)}</span></p></div>} />
      </Panel>

      <Panel title="Data-source health" subtitle="Refresh results become visible here as soon as the task completes.">
        <DecisionTable rows={healthRows} columns={[
          { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
          { label: "State", render: (row) => <Status value={row.status} /> },
          { label: "Source", render: (row) => text(row.source) },
          { label: "Reason", render: (row) => text(row.reason) },
        ]} />
      </Panel>

      <Panel title="Latest command acknowledgement" subtitle="This confirms submission; authoritative completion state is shown in System jobs.">
        <div className="notice">{commandResult || "No manual command run in this browser session."}</div>
      </Panel>
    </>
  );
}
