import { useEffect, useState } from "react";
import { postApi } from "../api";
import { DecisionTable } from "../components/DecisionTable";
import { Facts, Panel, SnapshotFrame, Status } from "../components/Primitives";
import { asArray, asDict, text, useSnapshot, type Dict } from "../lib/data";

function JsonEditor({
  title,
  subtitle,
  value,
  onSave,
}: {
  title: string;
  subtitle: string;
  value: Dict;
  onSave: (value: Dict) => Promise<void>;
}) {
  const [content, setContent] = useState("");
  const [result, setResult] = useState("");
  useEffect(() => setContent(JSON.stringify(value, null, 2)), [JSON.stringify(value)]);
  async function save() {
    try {
      await onSave(JSON.parse(content) as Dict);
      setResult("Saved.");
    } catch (exc) {
      setResult((exc as Error).message);
    }
  }
  return (
    <Panel title={title} subtitle={subtitle}>
      <textarea value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} />
      <div className="editor-footer"><button onClick={save}>Save</button><span>{result}</span></div>
    </Panel>
  );
}

export default function Settings() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/settings");
  const payload = asDict(data?.payload);
  const schedule = asDict(payload.runtime_schedule);
  const modelConfig = asDict(payload.multi_horizon_config);
  const notification = asDict(payload.notification_config);
  const registry = asDict(payload.model_registry);
  const slack = asDict(notification.slack);
  const email = asDict(notification.email);
  const llm = asDict(notification.llm);
  const slm = asDict(notification.local_slm);

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <Panel title="Connections" subtitle="Connection status is centralized here; secrets remain outside API responses.">
        <Facts rows={[
          ["Slack", <Status value={slack.enabled && slack.webhook_configured ? "READY" : "NOT CONFIGURED"} />],
          ["Email", <Status value={email.enabled && email.smtp_host_configured ? "READY" : "NOT CONFIGURED"} />],
          ["Remote LLM", <Status value={llm.enabled && llm.api_key_configured ? "READY" : "NOT CONFIGURED"} />],
          ["Local SLM", <Status value={slm.enabled ? "ENABLED" : "DISABLED"} />],
          ["Local endpoint", text(slm.base_url)],
          ["Local model", text(slm.model)],
        ]} />
      </Panel>
      <div className="split-layout editors">
        <JsonEditor
          title="Runtime schedule"
          subtitle="Market monitor, nightly, and weekend cadence."
          value={schedule}
          onSave={async (value) => { await postApi("/api/actions/save-runtime-schedule", value); reload(); }}
        />
        <JsonEditor
          title="Multi-horizon model"
          subtitle="Universe size, architecture, training cadence, and artifact paths."
          value={modelConfig}
          onSave={async (value) => { await postApi("/api/actions/save-multi-horizon-config", value); reload(); }}
        />
      </div>
      <Panel title="Model roles" subtitle="The multi-horizon Transformer is the sole production decision model.">
        <DecisionTable rows={asArray(registry.models)} columns={[
          { label: "Model", render: (row) => text(row.display_name ?? row.model_id) },
          { label: "Role", render: (row) => text(row.role) },
          { label: "Default", render: (row) => <Status value={row.is_default ? "YES" : "NO"} /> },
          { label: "Enabled", render: (row) => <Status value={row.enabled ? "YES" : "NO"} /> },
        ]} />
      </Panel>
    </SnapshotFrame>
  );
}
