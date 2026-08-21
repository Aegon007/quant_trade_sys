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
      setResult("已保存。");
    } catch (exc) {
      setResult((exc as Error).message);
    }
  }
  return (
    <Panel title={title} subtitle={subtitle}>
      <textarea value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} />
      <div className="editor-footer"><button onClick={save}>保存</button><span>{result}</span></div>
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

const CHRONOS_PRESETS = [
  {
    label: "Chronos-2 Small",
    modelName: "autogluon/chronos-2-small",
    size: "28M",
    profile: "适合受限本地推理",
  },
  {
    label: "Chronos-2",
    modelName: "amazon/chronos-2",
    size: "120M",
    profile: "默认通用模型",
  },
];

export default function Settings() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/settings");
  const jobs = useSnapshot<Dict>("/api/job-status");
  const payload = asDict(data?.payload);
  const schedule = asDict(payload.runtime_schedule);
  const foundationConfig = asDict(payload.foundation_model_config);
  const financialsConfig = asDict(payload.financials_config);
  const coreEtfUniverse = asDict(payload.core_etf_universe);
  const eventSourceConfig = asDict(payload.event_source_config);
  const eventSourceStatus = asDict(payload.event_source_status);
  const analystStatus = asDict(payload.analyst_consensus_status);
  const notification = asDict(payload.notification_config);
  const registry = asDict(payload.model_registry);
  const [config, setConfig] = useState<Dict>({});
  const [foundationDraft, setFoundationDraft] = useState<Dict>({});
  const [saving, setSaving] = useState(false);
  const [savingFoundation, setSavingFoundation] = useState(false);
  const [saveResult, setSaveResult] = useState("");
  const [foundationSaveResult, setFoundationSaveResult] = useState("");
  const [testingRoute, setTestingRoute] = useState("");
  const [llmTestResults, setLlmTestResults] = useState<Dict>({});

  useEffect(() => {
    setConfig(notification);
    setFoundationDraft(foundationConfig);
  }, [data?.generated_at]);

  const slack = asDict(config.slack);
  const email = asDict(config.email);
  const llm = asDict(config.llm);
  const slm = asDict(config.local_slm);
  const alerts = asDict(config.alert_settings);
  const foundationBackends = asDict(foundationDraft.backends);
  const chronos = asDict(foundationBackends.chronos);
  const foundationPriority = asArray(foundationDraft.backend_priority).map(String).filter(Boolean);
  const selectedChronosModel = text(chronos.model_name, "amazon/chronos-2");
  const warmupJob = asDict(asDict(asDict(jobs.data?.payload).jobs)["settings-foundation-model-warmup"]);
  const warmupState = text(warmupJob.state, "NOT RUN");
  const warmupActive = ["started", "running", "queued"].includes(warmupState.toLowerCase());
  const warmupProgress = Number(warmupJob.progress_pct ?? 0);
  const remoteTestResult = text(llmTestResults.remote, "");
  const localTestResult = text(llmTestResults.local, "");
  const remoteStatus = remoteTestResult.startsWith("SUCCESS") || remoteTestResult.startsWith("成功")
    ? "TESTED OK"
    : remoteTestResult.startsWith("FAILED") || remoteTestResult.startsWith("失败")
      ? "TEST FAILED"
      : llm.enabled && llm.api_key_configured
        ? "CONFIGURED"
        : "NOT CONFIGURED";
  const localStatus = localTestResult.startsWith("SUCCESS") || localTestResult.startsWith("成功")
    ? "TESTED OK"
    : localTestResult.startsWith("FAILED") || localTestResult.startsWith("失败")
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

  function updateChronos(key: string, value: unknown) {
    setFoundationDraft((current) => {
      const backends = asDict(current.backends);
      return {
        ...current,
        backends: {
          ...backends,
          chronos: {
            ...asDict(backends.chronos),
            [key]: value,
          },
        },
      };
    });
  }

  function applyChronosPreset(modelName: string) {
    setFoundationDraft((current) => {
      const backends = asDict(current.backends);
      const priority = asArray(current.backend_priority).map(String).filter(Boolean);
      return {
        ...current,
        enabled: true,
        default_backend: "auto",
        backend_priority: ["chronos", ...priority.filter((name) => name !== "chronos")],
        backends: {
          ...backends,
          chronos: {
            ...asDict(backends.chronos),
            enabled: true,
            model_name: modelName,
          },
        },
      };
    });
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
    setLlmTestResults((current) => ({ ...current, [route]: "测试中..." }));
    try {
      await postApi("/api/actions/save-notification-config", config);
      const response = await postApi<Dict>("/api/actions/test-llm", { route });
      const result = asDict(response.result);
      setLlmTestResults((current) => ({
        ...current,
        [route]: `${result.ok ? "成功" : "失败"}：${text(result.message)}`,
      }));
    } catch (exc) {
      setLlmTestResults((current) => ({ ...current, [route]: `失败：${(exc as Error).message}` }));
    } finally {
      setTestingRoute("");
    }
  }

  async function saveFoundationModel() {
    setSavingFoundation(true);
    setFoundationSaveResult("");
    try {
      await postApi("/api/actions/save-foundation-model-config", foundationDraft);
      await postApi("/api/actions/warmup-foundation-model");
      setFoundationSaveResult("模型设置已保存，下方已开始缓存检查/下载/预热。");
      await reload();
      await jobs.reload(true);
    } catch (exc) {
      setFoundationSaveResult((exc as Error).message);
    } finally {
      setSavingFoundation(false);
    }
  }

  useEffect(() => {
    if (!warmupActive) return undefined;
    const timer = window.setInterval(() => jobs.reload(true), 1000);
    return () => window.clearInterval(timer);
  }, [jobs.reload, warmupActive]);

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <Panel
        title="连接设置"
        subtitle="Slack、Email、LLM和本地SLM都在这里配置。已保存的密钥不会回传到浏览器。"
        action={<button disabled={saving} onClick={saveConnections}>{saving ? "保存中..." : "保存连接"}</button>}
      >
        <Facts rows={[
          ["Slack", <Status value={slack.enabled && slack.webhook_configured ? "READY" : "NOT CONFIGURED"} />],
          ["Email", <Status value={email.enabled && email.smtp_host_configured && email.password_configured ? "READY" : "NOT CONFIGURED"} />],
          ["远程LLM", <Status value={remoteStatus} />],
          ["本地SLM", <Status value={localStatus} />],
        ]} />
        {saveResult ? <p className="form-result settings-save-result">{saveResult}</p> : null}
      </Panel>

      <Panel
        title="基础模型选择"
        subtitle="选择核心ETF、卫星雷达和风险页使用的真实Chronos-2时间序列基础模型。保存后会检查本地缓存，必要时下载，并执行后端预热。"
        action={<button disabled={savingFoundation || warmupActive} onClick={saveFoundationModel}>{savingFoundation ? "保存中..." : warmupActive ? "预热中..." : "保存模型"}</button>}
      >
        <Facts rows={[
          ["配置模型", selectedChronosModel],
          ["后端顺序", foundationPriority.join(" -> ") || "chronos"],
          ["设备", text(chronos.device, "auto")],
          ["上下文/批量", `${text(chronos.context_length, "512")} / ${text(chronos.batch_size, "8")}`],
          ["版本", text(chronos.revision, "使用提供方默认最新版")],
        ]} />
        <div className="model-preset-grid">
          {CHRONOS_PRESETS.map((preset) => {
            const selected = selectedChronosModel === preset.modelName;
            return (
              <button
                key={preset.modelName}
                type="button"
                className={selected ? "model-preset selected" : "model-preset"}
                onClick={() => applyChronosPreset(preset.modelName)}
              >
                <b>{preset.label}</b>
                <span>{preset.size}</span>
                <small>{preset.profile}</small>
              </button>
            );
          })}
        </div>
        <div className="settings-form-grid">
          <Field label="模型名称" hint="填写Hugging Face缓存中已有或可在线下载的Chronos-2兼容模型ID。">
            <input value={selectedChronosModel} onChange={(event) => updateChronos("model_name", event.target.value)} />
          </Field>
          <Field label="版本" hint="可选commit hash、branch或tag。留空表示使用提供方默认最新版。">
            <input value={text(chronos.revision, "")} onChange={(event) => updateChronos("revision", event.target.value)} />
          </Field>
          <Field label="设备" hint="auto会优先CUDA，其次MPS，再到CPU。Jetson只有在NVIDIA版PyTorch安装正确时才会显示CUDA。">
            <select value={text(chronos.device, "auto")} onChange={(event) => updateChronos("device", event.target.value)}>
              <option value="auto">auto</option>
              <option value="cuda">cuda</option>
              <option value="mps">mps</option>
              <option value="cpu">cpu</option>
            </select>
          </Field>
          <Field label="Torch dtype" hint="auto会在CUDA可用时优先使用bfloat16。">
            <select value={text(chronos.torch_dtype, "auto")} onChange={(event) => updateChronos("torch_dtype", event.target.value)}>
              <option value="auto">auto</option>
              <option value="float32">float32</option>
              <option value="float16">float16</option>
              <option value="bfloat16">bfloat16</option>
            </select>
          </Field>
          <Field label="上下文长度">
            <input type="number" min="64" value={text(chronos.context_length, "512")} onChange={(event) => updateChronos("context_length", Number(event.target.value))} />
          </Field>
          <Field label="批量大小">
            <input type="number" min="1" value={text(chronos.batch_size, "8")} onChange={(event) => updateChronos("batch_size", Number(event.target.value))} />
          </Field>
          <Field label="训练数据保留天数" hint="每日模型输入会归档，用于未来Chronos-2微调数据集。">
            <input
              type="number"
              min="30"
              value={text(asDict(foundationDraft.training_data).retention_days, "1825")}
              onChange={(event) => setFoundationDraft((current) => ({
                ...current,
                training_data: {
                  ...asDict(current.training_data),
                  enabled: true,
                  retention_days: Number(event.target.value),
                },
              }))}
            />
          </Field>
          <Toggle label="启用Chronos-2跨序列学习推理" checked={Boolean(chronos.cross_learning)} onChange={(value) => updateChronos("cross_learning", value)} />
        </div>
        <div className="editor-footer">
          <button disabled={savingFoundation || warmupActive} onClick={saveFoundationModel}>{savingFoundation ? "保存中..." : warmupActive ? "模型预热中..." : "保存基础模型"}</button>
          <span>{foundationSaveResult || "建议默认使用Chronos-2。如果Jetson显存紧张，请降低batch size或切换到Chronos-2 Small。"}</span>
        </div>
        <div className={`model-warmup ${warmupActive ? "running" : ""}`}>
          <div className="model-warmup-main">
            <div>
              <b>后端切换与模型预热</b>
              <span>{text(warmupJob.detail, "还没有执行预热。")}</span>
            </div>
            <Status value={warmupState} />
          </div>
          <div className="job-progress">
            <span style={{ width: `${Math.max(0, Math.min(warmupProgress, 100))}%` }} />
          </div>
          <div className="job-control-meta">
            <span>阶段：{text(warmupJob.stage, "-")}</span>
            <span>进度：{warmupJob.progress_pct === undefined ? "-" : `${warmupProgress.toFixed(0)}%`}</span>
            <span>模型：{text(warmupJob.model_name, selectedChronosModel)}</span>
            <span>缓存：{text(warmupJob.cache_status, "-")}</span>
            <span>设备：{text(warmupJob.runtime_device ?? warmupJob.device, text(chronos.device, "auto"))}</span>
          </div>
          {warmupJob.cache_path ? <p className="model-cache-path">缓存路径：{text(warmupJob.cache_path)}</p> : null}
        </div>
      </Panel>

      <div className="settings-grid">
        <Panel title="Slack通知" subtitle="使用Incoming Webhook发送告警、报告和摘要。">
          <Toggle label="启用Slack通知" checked={Boolean(slack.enabled)} onChange={(value) => updateSection("slack", "enabled", value)} />
          <Field label="Webhook URL" hint={slack.webhook_configured ? "已有webhook保存。留空表示沿用，输入新值则替换。" : "粘贴Slack Incoming Webhook URL。"}>
            <input
              type="password"
              value={text(slack.webhook_url, "")}
              placeholder={slack.webhook_configured ? "已保存webhook，留空不变" : "https://hooks.slack.com/services/..."}
              onChange={(event) => updateSection("slack", "webhook_url", event.target.value)}
            />
          </Field>
        </Panel>

        <Panel title="Email通知" subtitle="通过SMTP发送夜间报告和盘中紧急告警。">
          <Toggle label="启用Email通知" checked={Boolean(email.enabled)} onChange={(value) => updateSection("email", "enabled", value)} />
          <div className="settings-form-grid">
            <Field label="SMTP host">
              <input value={text(email.smtp_host, "")} onChange={(event) => updateSection("email", "smtp_host", event.target.value)} />
            </Field>
            <Field label="SMTP port">
              <input type="number" value={text(email.smtp_port, "587")} onChange={(event) => updateSection("email", "smtp_port", Number(event.target.value))} />
            </Field>
            <Field label="用户名">
              <input value={text(email.username, "")} onChange={(event) => updateSection("email", "username", event.target.value)} />
            </Field>
            <Field label="密码" hint={email.password_configured ? "留空表示沿用已保存密码。" : "Outlook建议使用账户/应用密码。"}>
              <input
                type="password"
                value={text(email.password, "")}
                placeholder={email.password_configured ? "已保存密码，留空不变" : "SMTP密码"}
                onChange={(event) => updateSection("email", "password", event.target.value)}
              />
            </Field>
            <Field label="发件地址">
              <input value={text(email.from_email, "")} onChange={(event) => updateSection("email", "from_email", event.target.value)} />
            </Field>
            <Field label="收件人" hint="多个地址用英文逗号分隔。">
              <input
                value={asArray(email.to_emails).map(String).join(", ")}
                onChange={(event) => updateSection("email", "to_emails", event.target.value)}
              />
            </Field>
          </div>
          <Toggle label="使用STARTTLS" checked={Boolean(email.use_starttls)} onChange={(value) => updateSection("email", "use_starttls", value)} />
        </Panel>

        <Panel
          title="远程LLM"
          subtitle="OpenAI兼容API，用于复杂解释、调研，以及本地SLM不可用时的兜底。"
          action={<div className="button-row"><button className="quiet-button" onClick={() => applyRemotePreset("openai")}>OpenAI预设</button><button className="quiet-button" onClick={() => applyRemotePreset("openrouter")}>OpenRouter预设</button></div>}
        >
          <Toggle label="启用远程LLM" checked={Boolean(llm.enabled)} onChange={(value) => updateSection("llm", "enabled", value)} />
          <div className="settings-form-grid">
            <Field label="服务商">
              <select value={text(llm.provider, "openai")} onChange={(event) => updateSection("llm", "provider", event.target.value)}>
                <option value="openai">OpenAI</option>
                <option value="openrouter">OpenRouter</option>
                <option value="openai-compatible">其他OpenAI兼容接口</option>
              </select>
            </Field>
            <Field label="模型">
              <input value={text(llm.model, "")} onChange={(event) => updateSection("llm", "model", event.target.value)} />
              {text(llm.provider) === "openrouter" ? (
                <small>可以使用 openrouter/free，或复制包含 :free 后缀的完整模型slug。</small>
              ) : null}
            </Field>
            <Field label="Base URL">
              <input value={text(llm.base_url, "")} onChange={(event) => updateSection("llm", "base_url", event.target.value)} />
            </Field>
            <Field label="API key" hint={llm.api_key_configured ? "留空表示沿用已保存key。" : "多数远程服务商都需要API key。"}>
              <input
                type="password"
                value={text(llm.api_key, "")}
                placeholder={llm.api_key_configured ? "已保存key，留空不变" : "API key"}
                onChange={(event) => updateSection("llm", "api_key", event.target.value)}
              />
            </Field>
            <Field label="温度">
              <input type="number" min="0" step="0.1" value={text(llm.temperature, "0.2")} onChange={(event) => updateSection("llm", "temperature", Number(event.target.value))} />
            </Field>
            <Field label="默认最大输出tokens" hint="用于普通短解释。组合决策简报在下方有单独的大预算。">
              <input type="number" min="1" value={text(llm.max_tokens, "300")} onChange={(event) => updateSection("llm", "max_tokens", Number(event.target.value))} />
            </Field>
            <Field label="上下文窗口tokens" hint="所选模型宣称支持的输入加输出总容量。">
              <input type="number" min="1024" value={text(llm.context_window_tokens, "200000")} onChange={(event) => updateSection("llm", "context_window_tokens", Number(event.target.value))} />
            </Field>
            <Field label="超时秒数">
              <input type="number" min="1" value={text(llm.timeout_seconds, "30")} onChange={(event) => updateSection("llm", "timeout_seconds", Number(event.target.value))} />
            </Field>
            <Field label="应用名称">
              <input value={text(llm.app_name, "quant-trade-system")} onChange={(event) => updateSection("llm", "app_name", event.target.value)} />
            </Field>
          </div>
          <div className="editor-footer">
            <button disabled={testingRoute === "remote"} onClick={() => testLlm("remote")}>
              {testingRoute === "remote" ? "测试中..." : "测试远程LLM"}
            </button>
            <span>{text(llmTestResults.remote, "会发送一次最小真实聊天请求。")}</span>
          </div>
        </Panel>

        <Panel
          title="LM Studio / 本地SLM"
          subtitle="本地转述端点。复杂任务仍由远程LLM兜底。"
          action={<button className="quiet-button" onClick={applyLmStudioPreset}>LM Studio预设</button>}
        >
          <Toggle label="启用本地SLM" checked={Boolean(slm.enabled)} onChange={(value) => updateSection("local_slm", "enabled", value)} />
          <div className="settings-form-grid">
            <Field label="Base URL" hint="LM Studio通常使用1234端口。">
              <input value={text(slm.base_url, "")} onChange={(event) => updateSection("local_slm", "base_url", event.target.value)} />
            </Field>
            <Field label="模型名称" hint="使用LM Studio中显示的模型标识。">
              <input value={text(slm.model, "")} onChange={(event) => updateSection("local_slm", "model", event.target.value)} />
            </Field>
            <Field label="API key" hint={slm.api_key_configured ? "留空表示沿用已保存值。" : "LM Studio通常接受任意非空值。"}>
              <input
                type="password"
                value={text(slm.api_key, "")}
                placeholder={slm.api_key_configured ? "已保存，留空不变" : "lm-studio"}
                onChange={(event) => updateSection("local_slm", "api_key", event.target.value)}
              />
            </Field>
            <Field label="超时秒数">
              <input type="number" min="1" value={text(slm.timeout_seconds, "20")} onChange={(event) => updateSection("local_slm", "timeout_seconds", Number(event.target.value))} />
            </Field>
            <Field label="温度">
              <input type="number" min="0" step="0.1" value={text(slm.temperature, "0.1")} onChange={(event) => updateSection("local_slm", "temperature", Number(event.target.value))} />
            </Field>
            <Field label="最大tokens">
              <input type="number" min="1" value={text(slm.max_tokens, "220")} onChange={(event) => updateSection("local_slm", "max_tokens", Number(event.target.value))} />
            </Field>
          </div>
          <div className="editor-footer">
            <button disabled={testingRoute === "local"} onClick={() => testLlm("local")}>
              {testingRoute === "local" ? "测试中..." : "测试转述"}
            </button>
            <span>{text(llmTestResults.local, "会运行一次真实的单句转述请求。")}</span>
          </div>
        </Panel>
      </div>

      <Panel title="告警发送策略" subtitle="选择哪些自动输出需要发送到Slack和Email。">
        <div className="settings-toggle-grid">
          <Toggle label="发送每日摘要" checked={Boolean(alerts.send_daily_summary)} onChange={(value) => updateSection("alert_settings", "send_daily_summary", value)} />
          <Toggle label="发送盘前简报" checked={Boolean(alerts.send_premarket_brief)} onChange={(value) => updateSection("alert_settings", "send_premarket_brief", value)} />
          <Toggle label="发送盘中紧急告警" checked={Boolean(alerts.send_intraday_alerts)} onChange={(value) => updateSection("alert_settings", "send_intraday_alerts", value)} />
          <Toggle label="发送小时市场摘要" checked={Boolean(alerts.send_hourly_market_summary)} onChange={(value) => updateSection("alert_settings", "send_hourly_market_summary", value)} />
          <Toggle label="小时摘要仅限交易时段" checked={Boolean(alerts.send_hourly_market_summary_market_hours_only)} onChange={(value) => updateSection("alert_settings", "send_hourly_market_summary_market_hours_only", value)} />
          <Toggle label="启用周末研究" checked={Boolean(alerts.enable_weekend_research)} onChange={(value) => updateSection("alert_settings", "enable_weekend_research", value)} />
          <Toggle label="发送周末研究摘要" checked={Boolean(alerts.send_weekend_research_summary)} onChange={(value) => updateSection("alert_settings", "send_weekend_research_summary", value)} />
          <Toggle label="启用LLM组合摘要" checked={Boolean(alerts.enable_llm_decision_brief)} onChange={(value) => updateSection("alert_settings", "enable_llm_decision_brief", value)} />
          <Toggle label="重大信号变化时刷新LLM摘要" checked={Boolean(alerts.refresh_llm_brief_on_material_change)} onChange={(value) => updateSection("alert_settings", "refresh_llm_brief_on_material_change", value)} />
          <Toggle label="将变化后的LLM摘要发送到Slack/Email" checked={Boolean(alerts.send_llm_brief_on_material_change)} onChange={(value) => updateSection("alert_settings", "send_llm_brief_on_material_change", value)} />
        </div>
        <div className="settings-form-grid compact-settings">
          <Field label="告警冷却小时数">
            <input type="number" min="0" step="0.5" value={text(alerts.cooldown_hours, "6")} onChange={(event) => updateSection("alert_settings", "cooldown_hours", Number(event.target.value))} />
          </Field>
          <Field label="周末研究历史窗口">
            <input value={text(alerts.weekend_research_history_period, "5y")} onChange={(event) => updateSection("alert_settings", "weekend_research_history_period", event.target.value)} />
          </Field>
          <Field label="决策简报最大输出tokens" hint="全系统LLM摘要使用的独立大输出预算。">
            <input type="number" min="512" value={text(alerts.decision_brief_max_output_tokens, "16000")} onChange={(event) => updateSection("alert_settings", "decision_brief_max_output_tokens", Number(event.target.value))} />
          </Field>
          <Field label="决策简报总超时秒数" hint="避免慢速免费路由阻塞夜间任务；结构化兜底仍可用。">
            <input type="number" min="10" value={text(alerts.decision_brief_wall_timeout_seconds, "90")} onChange={(event) => updateSection("alert_settings", "decision_brief_wall_timeout_seconds", Number(event.target.value))} />
          </Field>
        </div>
        <div className="editor-footer"><button disabled={saving} onClick={saveConnections}>{saving ? "保存中..." : "保存发送策略"}</button><span>{saveResult}</span></div>
      </Panel>

      <Panel title="财经情报数据源" subtitle="新闻会在市场数据刷新和夜间流程中更新。分析师覆盖目前是推荐共识，不是完整研报文本。">
        <Facts rows={[
          ["新闻刷新", <Status value={eventSourceStatus.status ?? "NOT RUN"} />],
          ["活跃新闻事件", text(eventSourceStatus.event_count, "0")],
          ["新闻源成功/失败", `${text(eventSourceStatus.successful_source_count, "0")} / ${text(eventSourceStatus.failed_source_count, "0")}`],
          ["分析师缓存更新时间", text(analystStatus.last_updated, "NOT RUN")],
          ["分析师覆盖标的", text(Object.keys(asDict(analystStatus.recommendations)).length, "0")],
          ["研报正文", <Status value="NOT INGESTED" />],
        ]} />
      </Panel>

      <div className="split-layout editors">
        <JsonEditor
          title="核心ETF候选池"
          subtitle="如果QQQM、XLK或其他ETF需要由核心ETF引擎管理，请在这里加入。保存后重新运行夜间分析。"
          value={coreEtfUniverse}
          onSave={async (value) => { await postApi("/api/actions/save-core-etf-universe", value); reload(); }}
        />
        <JsonEditor
          title="运行调度"
          subtitle="高级配置：市场监控、夜间流程和周末研究的运行节奏。"
          value={schedule}
          onSave={async (value) => { await postApi("/api/actions/save-runtime-schedule", value); reload(); }}
        />
      </div>
      <JsonEditor
        title="财经新闻源"
        subtitle="启用或禁用本地、yfinance/Yahoo等新闻适配器。某个源失败时会保留旧缓存。"
        value={eventSourceConfig}
        onSave={async (value) => { await postApi("/api/actions/save-event-sources", value); reload(); }}
      />
      <JsonEditor
        title="基础模型高级JSON"
        subtitle="高级逃生口。正常切换模型请优先使用上方可视化选择器。"
        value={foundationDraft}
        onSave={async (value) => { await postApi("/api/actions/save-foundation-model-config", value); reload(); }}
      />
      <JsonEditor
        title="财报压力分析配置"
        subtitle="公司现金流、资本开支、债务和收入增长压力阈值。ETF缺失财报数据会显示为缺失，不会被当成看空。"
        value={financialsConfig}
        onSave={async (value) => { await postApi("/api/actions/save-financials-config", value); reload(); }}
      />
      <Panel title="模型角色" subtitle="基础量化引擎是当前唯一登记的决策引擎。旧基准模型训练控制已移除。">
        <DecisionTable rows={asArray(registry.models)} columns={[
          { label: "模型", render: (row) => text(row.display_name ?? row.model_id) },
          { label: "角色", render: (row) => text(row.role) },
          { label: "默认", render: (row) => <Status value={row.is_default ? "YES" : "NO"} /> },
          { label: "启用", render: (row) => <Status value={row.enabled ? "YES" : "NO"} /> },
        ]} />
      </Panel>
    </SnapshotFrame>
  );
}
