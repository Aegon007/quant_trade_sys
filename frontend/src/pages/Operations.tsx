import { useEffect, useState } from "react";
import { postApi } from "../api";
import { DecisionTable } from "../components/DecisionTable";
import { Panel, Status } from "../components/Primitives";
import { asArray, asDict, formatDate, text, useSnapshot, type Dict } from "../lib/data";

export default function Operations() {
  const jobs = useSnapshot<Dict>("/api/job-status");
  const health = useSnapshot<Dict>("/api/data-health");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState("");
  const [replaceLedger, setReplaceLedger] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(jobs.reload, 5000);
    return () => window.clearInterval(timer);
  }, []);

  async function run(name: string, path: string, payload?: unknown) {
    setBusy(name);
    setResult("");
    try {
      const response = await postApi<Dict>(path, payload);
      setResult(JSON.stringify(response, null, 2));
      jobs.reload();
      health.reload();
    } catch (exc) {
      setResult((exc as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function importCsv(file: File | null) {
    if (!file) return;
    await run("robinhood", "/api/actions/import-robinhood-csv", {
      filename: file.name,
      csv_text: await file.text(),
      replace_existing: replaceLedger,
    });
  }

  const jobRows = Object.values(asDict(asDict(jobs.data?.payload).jobs));
  const healthRows = asArray(asDict(health.data?.payload).symbols);
  return (
    <>
      <div className="split-layout">
        <Panel title="Run system jobs" subtitle="Heavy computation stays behind the API and never blocks page navigation.">
          <div className="button-row">
            <button disabled={!!busy} onClick={() => run("refresh", "/api/actions/refresh-market", { force_source_refresh: true })}>Force market refresh</button>
            <button disabled={!!busy} onClick={() => run("nightly", "/api/actions/run-nightly-once")}>Run full nightly pipeline</button>
            <button disabled={!!busy} onClick={() => run("weekend", "/api/actions/run-weekend-research-once")}>Run weekend research</button>
            <button disabled={!!busy} onClick={() => run("model", "/api/actions/train-multi-horizon")}>Train neural model</button>
          </div>
        </Panel>
        <Panel title="Robinhood ledger import" subtitle="Append mode deduplicates. Rebuild mode backs up and replaces the local ledger.">
          <label className="check-line">
            <input type="checkbox" checked={replaceLedger} onChange={(event) => setReplaceLedger(event.target.checked)} />
            Rebuild ledger from this CSV
          </label>
          <label className="file-input">
            <input type="file" accept=".csv,text/csv" onChange={(event) => importCsv(event.target.files?.[0] ?? null)} />
            Select Account Activity CSV
          </label>
        </Panel>
      </div>
      <Panel title="Job status" subtitle="Background work is observable without keeping a terminal in view.">
        <DecisionTable rows={jobRows} columns={[
          { label: "Job", render: (row) => text(row.name) },
          { label: "State", render: (row) => <Status value={row.state} /> },
          { label: "Detail", render: (row) => text(row.detail) },
          { label: "Updated", render: (row) => formatDate(row.updated_at) },
        ]} />
      </Panel>
      <Panel title="Data-source health" subtitle="Missing, stale, and fallback data remain explicit.">
        <DecisionTable rows={healthRows} columns={[
          { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
          { label: "State", render: (row) => <Status value={row.status} /> },
          { label: "Source", render: (row) => text(row.source) },
          { label: "Reason", render: (row) => text(row.reason) },
        ]} />
      </Panel>
      <Panel title="Latest command result" subtitle={busy ? `Running ${busy}...` : "No web request performs heavy quant work inline."}>
        <pre>{result || "No manual command run in this session."}</pre>
      </Panel>
    </>
  );
}
