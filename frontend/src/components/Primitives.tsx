import type React from "react";
import type { ApiEnvelope } from "../api";
import { formatDate, text } from "../lib/data";
import { zhStatus } from "../lib/i18n";

function statusClass(value: unknown): string {
  const normalized = text(value).toLowerCase();
  if (["ready", "ok", "pass", "completed", "normal", "accumulate", "confirmed"].some((item) => normalized.includes(item))) return "positive";
  if (["error", "missing", "failed", "blocked", "risk_off", "stop", "trim", "exit"].some((item) => normalized.includes(item))) return "negative";
  return "caution";
}

export function Status({ value }: { value: unknown }) {
  return <span className={`status ${statusClass(value)}`}>{zhStatus(value)}</span>;
}

export function Panel({
  title,
  subtitle,
  action,
  children,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

export function MetricStrip({ items }: { items: Array<{ label: string; value: React.ReactNode; hint?: string }> }) {
  return (
    <section className="metric-strip">
      {items.map((item) => (
        <div key={item.label}>
          <span>{item.label}</span>
          <strong>{typeof item.value === "string" || typeof item.value === "number" || typeof item.value === "boolean" ? zhStatus(item.value) : item.value}</strong>
          {item.hint ? <small>{item.hint}</small> : null}
        </div>
      ))}
    </section>
  );
}

export function SnapshotFrame({
  snapshot,
  loading,
  error,
  onReload,
  children,
}: {
  snapshot: ApiEnvelope<unknown> | null;
  loading: boolean;
  error: string;
  onReload: () => void;
  children: React.ReactNode;
}) {
  return (
    <>
      <div className="snapshot-line">
        <div>
          <Status value={snapshot?.freshness_status ?? (loading ? "LOADING" : "UNAVAILABLE")} />
          <span>{snapshot ? `更新时间 ${formatDate(snapshot.generated_at)}` : "等待快照生成"}</span>
        </div>
        <button className="quiet-button" type="button" onClick={onReload}>刷新页面</button>
      </div>
      {error ? <div className="notice negative">API 不可用：{error}</div> : null}
      {loading && !snapshot ? <div className="empty-state">正在加载最新快照...</div> : children}
    </>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function Facts({ rows }: { rows: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="facts">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? zhStatus(value) : value}</dd>
        </div>
      ))}
    </dl>
  );
}
