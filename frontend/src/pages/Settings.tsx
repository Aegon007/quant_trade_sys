import { useEffect, useState, type ReactNode } from "react";
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

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      {children}
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="settings-toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

export default function Settings() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/settings");
  const payload = asDict(data?.payload);
  const schedule = asDict(payload.runtime_schedule);
  const modelConfig = asDict(payload.multi_horizon_config);
  const notification = asDict(payload.notification_config);
  const registry = asDict(payload.model_registry);
  const [config, setConfig] = useState<Dict>({});
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState("");
  const [testingRoute, setTestingRoute] = useState("");
  const [llmTestResults, setLlmTestResults] = useState<Dict>({});

  useEffect(() => {
    setConfig(notification);
  }, [data?.generated_at]);

  const slack = asDict(config.slack);
  const email = asDict(config.email);
  const llm = asDict(config.llm);
  const slm = asDict(config.local_slm);
  const alerts = asDict(config.alert_settings);
  const remoteTestResult = text(llmTestResults.remote, "");
  const localTestResult = text(llmTestResults.local, "");
  const remoteStatus = remoteTestResult.startsWith("SUCCESS")
    ? "TESTED OK"
    : remoteTestResult.startsWith("FAILED")
      ? "TEST FAILED"
      : llm.enabled && llm.api_key_configured
        ? "CONFIGURED"
        : "NOT CONFIGURED";
  const localStatus = localTestResult.startsWith("SUCCESS")
    ? "TESTED OK"
    : localTestResult.startsWith("FAILED")
      ? "TEST FAILED"
      : slm.enabled
        ? "CONFIGURED"
        : "DISABLED";

  function updateSection(section: string, key: string, value: unknown) {
    setConfig((current) => ({
      ...current,
      [section]: {
        ...asDict(current[section]),
        [key]: value,
      },
    }));
  }

  function applyRemotePreset(provider: "openai" | "openrouter") {
    const preset = provider === "openrouter"
      ? { provider, base_url: "https://openrouter.ai/api/v1", model: "openrouter/free" }
      : { provider, base_url: "https://api.openai.com/v1", model: "gpt-5-mini" };
    setConfig((current) => ({
      ...current,
      llm: { ...asDict(current.llm), ...preset },
    }));
  }

  function applyLmStudioPreset() {
    setConfig((current) => ({
      ...current,
      local_slm: {
        ...asDict(current.local_slm),
        enabled: true,
        provider: "openai",
        base_url: "http://127.0.0.1:1234/v1",
        api_key: "lm-studio",
      },
    }));
  }

  async function saveConnections() {
    setSaving(true);
    setSaveResult("");
    try {
      await postApi("/api/actions/save-notification-config", config);
      setSaveResult("Connections and delivery settings saved.");
      await reload();
    } catch (exc) {
      setSaveResult((exc as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function testLlm(route: "remote" | "local") {
    setTestingRoute(route);
    setLlmTestResults((current) => ({ ...current, [route]: "Testing..." }));
    try {
      await postApi("/api/actions/save-notification-config", config);
      const response = await postApi<Dict>("/api/actions/test-llm", { route });
      const result = asDict(response.result);
      setLlmTestResults((current) => ({
        ...current,
        [route]: `${result.ok ? "SUCCESS" : "FAILED"}: ${text(result.message)}`,
      }));
    } catch (exc) {
      setLlmTestResults((current) => ({ ...current, [route]: `FAILED: ${(exc as Error).message}` }));
    } finally {
      setTestingRoute("");
    }
  }

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <Panel
        title="Connection settings"
        subtitle="All messaging and AI connections live here. Stored secrets are never returned to the browser."
        action={<button disabled={saving} onClick={saveConnections}>{saving ? "Saving..." : "Save connections"}</button>}
      >
        <Facts rows={[
          ["Slack", <Status value={slack.enabled && slack.webhook_configured ? "READY" : "NOT CONFIGURED"} />],
          ["Email", <Status value={email.enabled && email.smtp_host_configured && email.password_configured ? "READY" : "NOT CONFIGURED"} />],
          ["Remote LLM", <Status value={remoteStatus} />],
          ["Local SLM", <Status value={localStatus} />],
        ]} />
        {saveResult ? <p className="form-result settings-save-result">{saveResult}</p> : null}
      </Panel>

      <div className="settings-grid">
        <Panel title="Slack notifications" subtitle="Incoming Webhook used for alerts, reports, and summaries.">
          <Toggle label="Enable Slack notifications" checked={Boolean(slack.enabled)} onChange={(value) => updateSection("slack", "enabled", value)} />
          <Field label="Webhook URL" hint={slack.webhook_configured ? "A webhook is stored. Leave blank to keep it, or enter a new value to replace it." : "Paste the Slack Incoming Webhook URL."}>
            <input
              type="password"
              value={text(slack.webhook_url, "")}
              placeholder={slack.webhook_configured ? "Stored webhook remains unchanged" : "https://hooks.slack.com/services/..."}
              onChange={(event) => updateSection("slack", "webhook_url", event.target.value)}
            />
          </Field>
        </Panel>

        <Panel title="Email notifications" subtitle="SMTP delivery for nightly reports and urgent intraday alerts.">
          <Toggle label="Enable email notifications" checked={Boolean(email.enabled)} onChange={(value) => updateSection("email", "enabled", value)} />
          <div className="settings-form-grid">
            <Field label="SMTP host">
              <input value={text(email.smtp_host, "")} onChange={(event) => updateSection("email", "smtp_host", event.target.value)} />
            </Field>
            <Field label="SMTP port">
              <input type="number" value={text(email.smtp_port, "587")} onChange={(event) => updateSection("email", "smtp_port", Number(event.target.value))} />
            </Field>
            <Field label="Username">
              <input value={text(email.username, "")} onChange={(event) => updateSection("email", "username", event.target.value)} />
            </Field>
            <Field label="Password" hint={email.password_configured ? "Stored password remains unchanged when blank." : "For Outlook, use the account/app password."}>
              <input
                type="password"
                value={text(email.password, "")}
                placeholder={email.password_configured ? "Stored password remains unchanged" : "SMTP password"}
                onChange={(event) => updateSection("email", "password", event.target.value)}
              />
            </Field>
            <Field label="From address">
              <input value={text(email.from_email, "")} onChange={(event) => updateSection("email", "from_email", event.target.value)} />
            </Field>
            <Field label="Recipients" hint="Separate multiple addresses with commas.">
              <input
                value={asArray(email.to_emails).map(String).join(", ")}
                onChange={(event) => updateSection("email", "to_emails", event.target.value)}
              />
            </Field>
          </div>
          <Toggle label="Use STARTTLS" checked={Boolean(email.use_starttls)} onChange={(value) => updateSection("email", "use_starttls", value)} />
        </Panel>

        <Panel
          title="Remote LLM"
          subtitle="OpenAI-compatible API for complex explanations, research, and fallback when the local SLM is unavailable."
          action={<div className="button-row"><button className="quiet-button" onClick={() => applyRemotePreset("openai")}>OpenAI preset</button><button className="quiet-button" onClick={() => applyRemotePreset("openrouter")}>OpenRouter preset</button></div>}
        >
          <Toggle label="Enable remote LLM" checked={Boolean(llm.enabled)} onChange={(value) => updateSection("llm", "enabled", value)} />
          <div className="settings-form-grid">
            <Field label="Provider">
              <select value={text(llm.provider, "openai")} onChange={(event) => updateSection("llm", "provider", event.target.value)}>
                <option value="openai">OpenAI</option>
                <option value="openrouter">OpenRouter</option>
                <option value="openai-compatible">Other OpenAI-compatible</option>
              </select>
            </Field>
            <Field label="Model">
              <input value={text(llm.model, "")} onChange={(event) => updateSection("llm", "model", event.target.value)} />
              {text(llm.provider) === "openrouter" ? (
                <small>Use openrouter/free, or copy the exact model slug including its :free suffix.</small>
              ) : null}
            </Field>
            <Field label="Base URL">
              <input value={text(llm.base_url, "")} onChange={(event) => updateSection("llm", "base_url", event.target.value)} />
            </Field>
            <Field label="API key" hint={llm.api_key_configured ? "Stored key remains unchanged when blank." : "Required by most remote providers."}>
              <input
                type="password"
                value={text(llm.api_key, "")}
                placeholder={llm.api_key_configured ? "Stored key remains unchanged" : "API key"}
                onChange={(event) => updateSection("llm", "api_key", event.target.value)}
              />
            </Field>
            <Field label="Temperature">
              <input type="number" min="0" step="0.1" value={text(llm.temperature, "0.2")} onChange={(event) => updateSection("llm", "temperature", Number(event.target.value))} />
            </Field>
            <Field label="Max tokens">
              <input type="number" min="1" value={text(llm.max_tokens, "300")} onChange={(event) => updateSection("llm", "max_tokens", Number(event.target.value))} />
            </Field>
            <Field label="Timeout (seconds)">
              <input type="number" min="1" value={text(llm.timeout_seconds, "30")} onChange={(event) => updateSection("llm", "timeout_seconds", Number(event.target.value))} />
            </Field>
            <Field label="Application name">
              <input value={text(llm.app_name, "quant-trade-system")} onChange={(event) => updateSection("llm", "app_name", event.target.value)} />
            </Field>
          </div>
          <div className="editor-footer">
            <button disabled={testingRoute === "remote"} onClick={() => testLlm("remote")}>
              {testingRoute === "remote" ? "Testing..." : "Test remote LLM"}
            </button>
            <span>{text(llmTestResults.remote, "Sends a minimal real chat request.")}</span>
          </div>
        </Panel>

        <Panel
          title="LM Studio / Local SLM"
          subtitle="Local narration endpoint. The remote LLM remains the fallback for complex work."
          action={<button className="quiet-button" onClick={applyLmStudioPreset}>LM Studio preset</button>}
        >
          <Toggle label="Enable local SLM" checked={Boolean(slm.enabled)} onChange={(value) => updateSection("local_slm", "enabled", value)} />
          <div className="settings-form-grid">
            <Field label="Base URL" hint="LM Studio normally exposes port 1234.">
              <input value={text(slm.base_url, "")} onChange={(event) => updateSection("local_slm", "base_url", event.target.value)} />
            </Field>
            <Field label="Model name" hint="Use the model identifier shown by LM Studio.">
              <input value={text(slm.model, "")} onChange={(event) => updateSection("local_slm", "model", event.target.value)} />
            </Field>
            <Field label="API key" hint={slm.api_key_configured ? "Stored value remains unchanged when blank." : "LM Studio usually accepts any non-empty value."}>
              <input
                type="password"
                value={text(slm.api_key, "")}
                placeholder={slm.api_key_configured ? "Stored value remains unchanged" : "lm-studio"}
                onChange={(event) => updateSection("local_slm", "api_key", event.target.value)}
              />
            </Field>
            <Field label="Timeout (seconds)">
              <input type="number" min="1" value={text(slm.timeout_seconds, "20")} onChange={(event) => updateSection("local_slm", "timeout_seconds", Number(event.target.value))} />
            </Field>
            <Field label="Temperature">
              <input type="number" min="0" step="0.1" value={text(slm.temperature, "0.1")} onChange={(event) => updateSection("local_slm", "temperature", Number(event.target.value))} />
            </Field>
            <Field label="Max tokens">
              <input type="number" min="1" value={text(slm.max_tokens, "220")} onChange={(event) => updateSection("local_slm", "max_tokens", Number(event.target.value))} />
            </Field>
          </div>
          <div className="editor-footer">
            <button disabled={testingRoute === "local"} onClick={() => testLlm("local")}>
              {testingRoute === "local" ? "Testing..." : "Test narration"}
            </button>
            <span>{text(llmTestResults.local, "Runs a real one-sentence narration request.")}</span>
          </div>
        </Panel>
      </div>

      <Panel title="Alert delivery policy" subtitle="Choose which scheduled outputs should reach Slack and email.">
        <div className="settings-toggle-grid">
          <Toggle label="Daily summary" checked={Boolean(alerts.send_daily_summary)} onChange={(value) => updateSection("alert_settings", "send_daily_summary", value)} />
          <Toggle label="Premarket brief" checked={Boolean(alerts.send_premarket_brief)} onChange={(value) => updateSection("alert_settings", "send_premarket_brief", value)} />
          <Toggle label="Intraday urgent alerts" checked={Boolean(alerts.send_intraday_alerts)} onChange={(value) => updateSection("alert_settings", "send_intraday_alerts", value)} />
          <Toggle label="Hourly market summary" checked={Boolean(alerts.send_hourly_market_summary)} onChange={(value) => updateSection("alert_settings", "send_hourly_market_summary", value)} />
          <Toggle label="Hourly summary during market hours only" checked={Boolean(alerts.send_hourly_market_summary_market_hours_only)} onChange={(value) => updateSection("alert_settings", "send_hourly_market_summary_market_hours_only", value)} />
          <Toggle label="Weekend research" checked={Boolean(alerts.enable_weekend_research)} onChange={(value) => updateSection("alert_settings", "enable_weekend_research", value)} />
          <Toggle label="Send weekend research summary" checked={Boolean(alerts.send_weekend_research_summary)} onChange={(value) => updateSection("alert_settings", "send_weekend_research_summary", value)} />
        </div>
        <div className="settings-form-grid compact-settings">
          <Field label="Alert cooldown (hours)">
            <input type="number" min="0" step="0.5" value={text(alerts.cooldown_hours, "6")} onChange={(event) => updateSection("alert_settings", "cooldown_hours", Number(event.target.value))} />
          </Field>
          <Field label="Weekend history period">
            <input value={text(alerts.weekend_research_history_period, "5y")} onChange={(event) => updateSection("alert_settings", "weekend_research_history_period", event.target.value)} />
          </Field>
        </div>
        <div className="editor-footer"><button disabled={saving} onClick={saveConnections}>{saving ? "Saving..." : "Save delivery policy"}</button><span>{saveResult}</span></div>
      </Panel>

      <div className="split-layout editors">
        <JsonEditor
          title="Runtime schedule"
          subtitle="Advanced: market monitor, nightly, and weekend cadence."
          value={schedule}
          onSave={async (value) => { await postApi("/api/actions/save-runtime-schedule", value); reload(); }}
        />
        <JsonEditor
          title="Multi-horizon model"
          subtitle="Advanced: universe size, architecture, training cadence, and artifact paths."
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
