import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { fetchApi, postApi, type ApiEnvelope } from "./api";
import "./styles.css";

type Dict = Record<string, unknown>;
type PageKey = "dashboard" | "portfolio" | "core" | "satellite" | "risk" | "monitor" | "operations" | "settings";
type Column = {
  label: string;
  keys?: string[];
  render?: (row: Dict) => React.ReactNode;
};

const pages: Array<{ key: PageKey; label: string; detail: string }> = [
  { key: "dashboard", label: "Dashboard", detail: "Today" },
  { key: "portfolio", label: "Portfolio", detail: "Activity" },
  { key: "core", label: "Core ETFs", detail: "Rotation" },
  { key: "satellite", label: "Satellite Radar", detail: "Top 3" },
  { key: "risk", label: "Risk & Discipline", detail: "Gate" },
  { key: "monitor", label: "Market Monitor", detail: "Intraday" },
  { key: "operations", label: "Operations", detail: "Run jobs" },
  { key: "settings", label: "Settings", detail: "Config" },
];

function asDict(value: unknown): Dict {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Dict) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function pick(row: Dict, keys: string[]): unknown {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && String(value) !== "") return value;
  }
  return undefined;
}

function text(value: unknown, fallback = "-"): string {
  if (value === undefined || value === null || value === "") return fallback;
  if (Array.isArray(value)) return value.map((item) => text(item, "")).filter(Boolean).join(", ") || fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function numberValue(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatCurrency(value: unknown): string {
  const parsed = numberValue(value);
  if (parsed === null) return "-";
  return parsed.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function formatPercent(value: unknown): string {
  const parsed = numberValue(value);
  if (parsed === null) return "-";
  const valueToShow = Math.abs(parsed) <= 1 ? parsed * 100 : parsed;
  return `${valueToShow.toFixed(1)}%`;
}

function formatNumber(value: unknown, digits = 1): string {
  const parsed = numberValue(value);
  if (parsed === null) return "-";
  return parsed.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function formatDate(value: unknown): string {
  const raw = text(value, "");
  if (!raw) return "-";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function statusClass(status: unknown): string {
  const normalized = text(status).toLowerCase();
  if (["ok", "completed", "started", "normal", "hold", "running"].some((item) => normalized.includes(item))) return "ok";
  if (["fail", "error", "missing", "stale", "stop", "blocked"].some((item) => normalized.includes(item))) return "bad";
  return "warn";
}

function useSnapshot<TPayload = Dict>(path: string) {
  const [data, setData] = useState<ApiEnvelope<TPayload> | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const reload = () => {
    setLoading(true);
    setError("");
    fetchApi<TPayload>(path)
      .then(setData)
      .catch((exc: Error) => setError(exc.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    reload();
  }, [path]);

  return { data, error, loading, reload };
}

function MetricCard({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: string }) {
  return (
    <article className={`metric-card ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </article>
  );
}

function StatusPill({ value }: { value: unknown }) {
  return <span className={`pill ${statusClass(value)}`}>{text(value)}</span>;
}

function SnapshotFrame({
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
      <div className="snapshot-bar">
        <div>
          <span className="muted">Snapshot</span>
          <b>{snapshot ? snapshot.name : loading ? "loading" : "unavailable"}</b>
          <span className="muted">Generated {snapshot ? formatDate(snapshot.generated_at) : "-"}</span>
        </div>
        <div className="snapshot-actions">
          {snapshot ? <StatusPill value={snapshot.freshness_status} /> : null}
          <button type="button" onClick={onReload}>Refresh View</button>
        </div>
      </div>
      {error ? <div className="error">API unavailable: {error}</div> : null}
      {loading && !snapshot ? <div className="placeholder">Loading snapshot...</div> : children}
    </>
  );
}

function DataTable({ rows, columns, emptyText = "No rows in the latest snapshot." }: { rows: unknown[]; columns: Column[]; emptyText?: string }) {
  const normalizedRows = rows.map(asDict);
  if (normalizedRows.length === 0) return <div className="placeholder">{emptyText}</div>;
  return (
    <div className="table-card">
      <table>
        <thead>
          <tr>
            {columns.map((column) => <th key={column.label}>{column.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {normalizedRows.map((row, index) => (
            <tr key={`${text(row.symbol, "row")}-${index}`}>
              {columns.map((column) => (
                <td key={column.label}>{column.render ? column.render(row) : text(pick(row, column.keys ?? []))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function listFromPayload(payload: unknown, keys: string[]): unknown[] {
  const record = asDict(payload);
  for (const key of keys) {
    const rows = asArray(record[key]);
    if (rows.length > 0) return rows;
  }
  return [];
}

function DashboardPage() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/dashboard");
  const summary = data?.summary ?? {};
  const payload = asDict(data?.payload);
  const account = asDict(payload.account);
  const changes = data?.items ?? [];
  const coreRows = listFromPayload(asDict(payload.core_etf_snapshot), ["symbols"]);
  const satelliteRows = listFromPayload(asDict(payload.satellite_candidate_snapshot), ["top_recommendations", "symbols"]).slice(0, 3);
  const dataHealth = asDict(payload.data_health_snapshot);
  const planQuality = asDict(payload.plan_quality_snapshot);
  const marketMonitor = asDict(payload.market_monitor_snapshot);
  const strategyGovernance = asDict(payload.strategy_governance_snapshot);

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className="metric-grid">
        <MetricCard label="Total Capital" value={formatCurrency(summary.total_capital)} hint={`Cash ${formatCurrency(summary.cash_available)}`} />
        <MetricCard label="Exposure" value={formatPercent(summary.exposure_pct)} hint="Current holding exposure" />
        <MetricCard label="Discipline" value={text(summary.discipline_regime, "UNKNOWN")} hint={`Risk ${text(summary.risk_regime, "UNKNOWN")}`} />
        <MetricCard label="Actionable Core ETFs" value={text(summary.actionable_core_count)} hint="Non-HOLD actions" />
      </section>
      <section className="metric-grid">
        <MetricCard label="Data Health" value={text(summary.data_health_status, "UNKNOWN")} hint={`Missing ${text(summary.missing_price_count, "0")} · Invalid ${text(summary.invalid_price_count, "0")}`} />
        <MetricCard label="Plan Quality" value={text(summary.plan_quality_status, "UNKNOWN")} hint={`Execution ${formatPercent(summary.plan_execution_rate)}`} />
        <MetricCard label="Market Monitor" value={text(summary.market_monitor_status, "UNKNOWN")} hint={`Action ${text(summary.market_monitor_action, "NONE")}`} />
        <MetricCard label="Strategy Governance" value={text(summary.strategy_governance_status, "UNKNOWN")} hint="No auto strategy switching" />
      </section>

      <section className="two-column">
        <Panel title="High-Priority Change Feed" subtitle="Only material changes should appear here.">
          <SignalList rows={changes.slice(0, 8)} />
        </Panel>
        <Panel title="Account Snapshot" subtitle="Computed from cash plus marked holdings.">
          <dl className="facts">
            <dt>Cash</dt><dd>{formatCurrency(account.cash_available)}</dd>
            <dt>Holdings Value</dt><dd>{formatCurrency(account.holdings_value)}</dd>
            <dt>Positions</dt><dd>{text(account.holding_count)}</dd>
            <dt>Watchlist</dt><dd>{text(account.watchlist_count)}</dd>
          </dl>
        </Panel>
      </section>

      <section className="two-column">
        <Panel title="Core ETF Board" subtitle="Compact daily action board.">
          <DataTable rows={coreRows.slice(0, 8)} columns={coreColumns} />
        </Panel>
        <Panel title="Top Satellite Candidates" subtitle="Formal Top 3 scoring output.">
          <DataTable rows={satelliteRows} columns={satelliteColumns} />
        </Panel>
      </section>
      <section className="two-column">
        <Panel title="Reliability Summary" subtitle="Trust the recommendation only when these are healthy.">
          <dl className="facts">
            <dt>Data</dt><dd>{text(asDict(dataHealth.summary).status ?? dataHealth.status, "UNKNOWN")}</dd>
            <dt>Missing / Invalid</dt><dd>{text(asDict(dataHealth.summary).missing_price_count, "0")} / {text(asDict(dataHealth.summary).invalid_price_count, "0")}</dd>
            <dt>Plan</dt><dd>{text(asDict(planQuality.summary).status ?? planQuality.status, "UNKNOWN")}</dd>
            <dt>Missed Reachable</dt><dd>{text(asDict(planQuality.summary).missed_reachable_count, "0")}</dd>
          </dl>
        </Panel>
        <Panel title="Governance & Tactical" subtitle="Advanced checks stay advisory, not automatic execution.">
          <dl className="facts">
            <dt>Market State</dt><dd>{text(asDict(marketMonitor.summary).state, "UNKNOWN")} · {text(asDict(marketMonitor.summary).recommended_action, "NONE")}</dd>
            <dt>Tactical Symbol</dt><dd>{text(asDict(marketMonitor.summary).recommended_symbol, "-")}</dd>
            <dt>Strategy Default</dt><dd>{text(asDict(strategyGovernance.summary).default_strategy_id, "-")}</dd>
            <dt>Promotion Watch</dt><dd>{text(asDict(strategyGovernance.summary).promotion_watch_count, "0")}</dd>
          </dl>
        </Panel>
      </section>
    </SnapshotFrame>
  );
}

function PortfolioPage() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/portfolio");
  const payload = asDict(data?.payload);
  const summary = data?.summary ?? {};
  const account = asDict(payload.account);
  const holdings = asArray(payload.holdings);
  const watchlist = asArray(payload.watchlist);
  const transactions = asArray(payload.recent_transactions);
  const dailyActivity = asDict(payload.daily_activity);
  const review = asDict(payload.post_close_review);
  const reviewItems = asArray(review.items);
  const unplannedTrades = asArray(review.unplanned_trades);
  const planQuality = asDict(payload.plan_quality_snapshot);
  const planQualitySummary = asDict(planQuality.summary);
  const quantAnalysis = asDict(payload.quant_analysis_snapshot);
  const quantSummary = asDict(quantAnalysis.summary);

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className="metric-grid">
        <MetricCard label="Total Capital" value={formatCurrency(account.total_capital)} hint={`Cash ${formatCurrency(account.cash_available)}`} />
        <MetricCard label="Holdings" value={text(summary.holding_count, "0")} hint={`Value ${formatCurrency(account.holdings_value)}`} />
        <MetricCard label="Recent Activity Day" value={text(summary.latest_transaction_day, "-")} hint={`${text(summary.latest_trade_count, "0")} trades`} />
        <MetricCard label="Realized P/L" value={formatCurrency(summary.latest_realized_pl)} hint="Latest imported activity day" />
      </section>
      <section className="metric-grid">
        <MetricCard label="Post-Close Review" value={text(summary.post_close_review_status, "PENDING")} hint={`Unplanned ${text(summary.unplanned_trade_count, "0")}`} />
        <MetricCard label="Plan Quality" value={text(summary.plan_quality_status, "UNKNOWN")} hint={`Execution ${formatPercent(planQualitySummary.execution_rate)}`} />
        <MetricCard label="Quant Snapshot" value={formatDate(summary.quant_analysis_generated_at)} hint={`Top buy ${text(asArray(quantSummary.top_buy_symbols)[0], "-")}`} />
        <MetricCard label="Transactions" value={text(summary.transaction_count, "0")} hint={`${text(summary.recent_transaction_count, "0")} shown`} />
      </section>

      <section className="two-column">
        <Panel title="Holdings" subtitle="Current reconciled portfolio after Robinhood CSV import.">
          <DataTable rows={holdings} columns={[
            { label: "Symbol", keys: ["symbol"] },
            { label: "Shares", render: (row) => formatNumber(row.shares, 3) },
            { label: "Avg Cost", render: (row) => formatCurrency(row.cost) },
            { label: "Current", render: (row) => formatCurrency(row.current_price) },
            { label: "Value", render: (row) => {
              const shares = numberValue(row.shares) ?? 0;
              const price = numberValue(row.current_price) ?? numberValue(row.cost) ?? 0;
              return formatCurrency(shares * price);
            } },
            { label: "Sector", keys: ["sector"] },
          ]} emptyText="No holdings yet. Import Robinhood CSV or add positions first." />
        </Panel>
        <Panel title="Watchlist" subtitle="Symbols not currently held, kept for future review.">
          <DataTable rows={watchlist} columns={[
            { label: "Symbol", keys: ["symbol"] },
            { label: "Last Price", render: (row) => formatCurrency(row.last_price) },
            { label: "Notes", keys: ["notes", "llm_notes"] },
          ]} emptyText="Watchlist is empty." />
        </Panel>
      </section>

      <Panel title="Recent Transactions" subtitle="Latest imported Robinhood records and manual portfolio actions.">
        <DataTable rows={transactions} columns={[
          { label: "Date", render: (row) => formatDate(row.date) },
          { label: "Type", render: (row) => <StatusPill value={row.record_type ?? row.event_type} /> },
          { label: "Symbol", keys: ["symbol"] },
          { label: "Side", keys: ["side", "event_type"] },
          { label: "Shares", render: (row) => formatNumber(row.shares, 3) },
          { label: "Price", render: (row) => formatCurrency(row.price) },
          { label: "P/L", render: (row) => formatCurrency(row.pl) },
          { label: "Source", keys: ["source", "source_file"] },
        ]} emptyText="No transaction records yet. Upload Robinhood Account Activity CSV in Operations." />
      </Panel>

      <section className="two-column">
        <Panel title="Latest Imported Day Summary" subtitle="Daily activity summary from transaction records.">
          <dl className="facts">
            <dt>Day</dt><dd>{text(dailyActivity.day, "-")}</dd>
            <dt>Buys / Sells</dt><dd>{text(dailyActivity.buy_count, "0")} / {text(dailyActivity.sell_count, "0")}</dd>
            <dt>Symbols</dt><dd>{text(dailyActivity.symbols, "-")}</dd>
            <dt>Realized P/L</dt><dd>{formatCurrency(dailyActivity.realized_pl)}</dd>
          </dl>
        </Panel>
        <Panel title="Post-Close Review" subtitle="Compares imported trades with the latest trade plan when available.">
          <dl className="facts">
            <dt>Status</dt><dd>{text(review.status, "PENDING")}</dd>
            <dt>Review Day</dt><dd>{text(review.review_day, "-")}</dd>
            <dt>Executed / Missed</dt><dd>{text(review.executed_count, "0")} / {text(review.missed_count, "0")}</dd>
            <dt>Unplanned</dt><dd>{text(review.unplanned_trade_count, "0")}</dd>
          </dl>
        </Panel>
      </section>

      <section className="two-column">
        <Panel title="Plan Review Items" subtitle="Execution match details for plan items.">
          <DataTable rows={reviewItems} columns={[
            { label: "Symbol", keys: ["symbol"] },
            { label: "Plan", keys: ["plan_action"] },
            { label: "Status", render: (row) => <StatusPill value={row.status} /> },
            { label: "Avg Price", render: (row) => formatCurrency(row.avg_execution_price) },
            { label: "Reachable", keys: ["opportunity_status"] },
          ]} emptyText="No plan review items. This is normal if there was no prior trade plan." />
        </Panel>
        <Panel title="Unplanned Trades" subtitle="Trades imported from Robinhood that did not match the latest plan.">
          <DataTable rows={unplannedTrades} columns={[
            { label: "Symbol", keys: ["symbol"] },
            { label: "Side", keys: ["side"] },
            { label: "Shares", render: (row) => formatNumber(row.shares, 3) },
            { label: "Price", render: (row) => formatCurrency(row.price) },
          ]} emptyText="No unplanned trades for the reviewed day." />
        </Panel>
      </section>

      <Panel title="Latest Quant Analysis Snapshot" subtitle="This updates when full quant analysis/nightly pipeline runs. CSV import only updates portfolio and execution review.">
        <dl className="facts">
          <dt>Generated</dt><dd>{formatDate(quantAnalysis.generated_at)}</dd>
          <dt>Analyzed</dt><dd>{text(quantSummary.analyzed_symbols, "0")} / {text(quantSummary.total_symbols, "0")}</dd>
          <dt>Buy / Sell / Hold</dt><dd>{text(quantSummary.buy_count, "0")} / {text(quantSummary.sell_count, "0")} / {text(quantSummary.hold_count, "0")}</dd>
          <dt>Top Buys</dt><dd>{text(quantSummary.top_buy_symbols, "-")}</dd>
        </dl>
      </Panel>
    </SnapshotFrame>
  );
}

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <article className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {children}
    </article>
  );
}

function SignalList({ rows }: { rows: unknown[] }) {
  if (rows.length === 0) return <div className="placeholder">No material changes in the latest snapshot.</div>;
  return (
    <div className="signal-list">
      {rows.map((item, index) => {
        const row = asDict(item);
        return (
          <div className="signal-row" key={index}>
            <StatusPill value={row.priority ?? row.severity ?? row.level ?? "INFO"} />
            <div>
              <b>{text(row.title ?? row.message ?? row.symbol ?? `Change ${index + 1}`)}</b>
              <span>{text(row.reason ?? row.detail ?? row.description ?? row.category ?? "", "")}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const coreColumns: Column[] = [
  { label: "Symbol", keys: ["symbol"] },
  { label: "Action", render: (row) => <StatusPill value={pick(row, ["action", "decision"])} /> },
  { label: "Target", render: (row) => formatPercent(pick(row, ["target_weight_pct", "target_weight", "suggested_weight_pct"])) },
  { label: "Score", render: (row) => formatNumber(pick(row, ["score", "rotation_score", "final_score"]), 0) },
  { label: "Buy Zone", keys: ["buy_zone", "buy_price_range", "suggested_buy_range"] },
  { label: "Reason", keys: ["reason", "primary_reason", "summary"] },
];

const satelliteColumns: Column[] = [
  { label: "Symbol", keys: ["symbol"] },
  { label: "Signal", render: (row) => <StatusPill value={pick(row, ["recommendation", "action", "signal"])} /> },
  { label: "Score", render: (row) => formatNumber(pick(row, ["score", "final_score", "composite_score"]), 0) },
  { label: "Trend", render: (row) => formatNumber(pick(row, ["trend_score", "momentum_score"]), 0) },
  { label: "Risk", keys: ["risk_level", "risk_regime", "risk"] },
  { label: "Why", keys: ["reason", "summary", "explanation"] },
];

function CoreEtfPage() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/core-etfs");
  const rows = listFromPayload(data?.payload, ["symbols", "items"]);
  const summary = data?.summary ?? asDict(asDict(data?.payload).summary);
  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className="metric-grid three">
        <MetricCard label="Universe" value={text(summary.symbol_count ?? rows.length)} hint="Configurable core ETF pool" />
        <MetricCard label="Actionable" value={text(summary.actionable_count ?? "-")} hint="After thresholds and risk gate" />
        <MetricCard label="Regime" value={text(summary.regime ?? summary.risk_regime ?? "UNKNOWN")} hint="Rotation context" />
      </section>
      <Panel title="Today Action Board" subtitle="Designed for quick morning review, not intraday overtrading.">
        <DataTable rows={rows} columns={coreColumns} />
      </Panel>
      <Placeholder title="Rotation Backtest" text="The backend snapshot is ready for this section; detailed equity curve visualization will land in a later frontend pass." />
    </SnapshotFrame>
  );
}

function SatelliteRadarPage() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/satellite-radar");
  const rows = listFromPayload(data?.payload, ["top_recommendations", "symbols", "candidates"]);
  const poolRows = listFromPayload(data?.payload, ["candidate_pool", "pool"]).slice(0, 20);
  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className="metric-grid three">
        <MetricCard label="Top 3" value={rows.slice(0, 3).map((item) => text(asDict(item).symbol, "")).filter(Boolean).join(", ") || "-"} hint="Formal satellite picks" />
        <MetricCard label="Pool Size" value={text(data?.summary.pool_size ?? poolRows.length)} hint="Nightly candidate pool" />
        <MetricCard label="Freshness" value={data ? data.freshness_status : "-"} hint="Use only fresh snapshots for action" />
      </section>
      <Panel title="Top Recommendations" subtitle="Satellite仓只做少量高质量候选，不替代 ETF core.">
        <DataTable rows={rows} columns={satelliteColumns} />
      </Panel>
      <Panel title="Candidate Pool Preview" subtitle="Top pool entries for research, not automatic trades.">
        <DataTable rows={poolRows} columns={satelliteColumns} emptyText="Candidate pool is empty. Run nightly or weekend research first." />
      </Panel>
    </SnapshotFrame>
  );
}

function RiskPage() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/risk");
  const payload = asDict(data?.payload);
  const summary = data?.summary ?? asDict(payload.summary);
  const rows = listFromPayload(payload, ["risk_items", "items", "alerts", "rules"]);
  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className="metric-grid">
        <MetricCard label="Discipline Regime" value={text(payload.regime ?? summary.regime ?? "UNKNOWN")} hint="Heavy / normal / light / stop" />
        <MetricCard label="Risk Regime" value={text(payload.risk_regime ?? summary.risk_regime ?? "UNKNOWN")} hint="Market and portfolio gate" />
        <MetricCard label="Target Exposure" value={formatPercent(payload.target_exposure_pct ?? summary.target_exposure_pct)} hint="Position discipline output" />
        <MetricCard label="Monthly Review" value={text(asDict(payload.monthly_review).status ?? "PENDING")} hint="Follow vs ignore feedback loop" />
      </section>
      <Panel title="Risk Rules & Alerts" subtitle="Raw signal must pass this gate before it becomes an approved action.">
        <DataTable rows={rows} columns={[
          { label: "Level", render: (row) => <StatusPill value={pick(row, ["level", "severity", "priority", "status"])} /> },
          { label: "Area", keys: ["category", "type", "name"] },
          { label: "Message", keys: ["message", "reason", "description", "detail"] },
          { label: "Action", keys: ["action", "recommended_action"] },
        ]} />
      </Panel>
    </SnapshotFrame>
  );
}

function MarketMonitorPage() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/market-monitor");
  const payload = asDict(data?.payload);
  const eventRows = listFromPayload(payload, ["events", "alerts", "items", "signals"]);
  const benchmarkRows = listFromPayload(payload, ["benchmark_rows"]);
  const tacticalRows = listFromPayload(payload, ["tactical_rows"]);
  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className="metric-grid three">
        <MetricCard label="Mode" value={text(payload.status ?? data?.summary.state ?? "monitor")} hint="Intraday tactical overlay" />
        <MetricCard label="Emergency Alerts" value={text(data?.summary.emergency_count ?? eventRows.length)} hint="Only urgent signals should notify" />
        <MetricCard label="Market Data" value={text(data?.freshness_status ?? "-")} hint="Primary/fallback source is reported in snapshots" />
      </section>
      <section className="two-column">
        <Panel title="Benchmark State" subtitle="Core market pressure gauges.">
          <DataTable rows={benchmarkRows} columns={marketMonitorColumns} />
        </Panel>
        <Panel title="Tactical Tools" subtitle="Inverse ETFs are tactical tools, not default holdings.">
          <DataTable rows={tacticalRows} columns={marketMonitorColumns} />
        </Panel>
      </section>
      <Panel title="Intraday Tactical Events" subtitle="This page monitors, but does not encourage routine day trading.">
        <DataTable rows={eventRows} columns={[
          { label: "Symbol", keys: ["symbol", "ticker"] },
          { label: "Class", render: (row) => <StatusPill value={pick(row, ["event_class", "classification", "severity", "action"])} /> },
          { label: "Move", render: (row) => formatPercent(pick(row, ["move_pct", "price_change_pct", "change_pct"])) },
          { label: "Trigger", keys: ["trigger", "reason", "message"] },
          { label: "Updated", render: (row) => formatDate(pick(row, ["updated_at", "generated_at", "timestamp"])) },
        ]} />
      </Panel>
      <Placeholder title="Training Data Collection" text="Intraday event outcomes are logged for future classifier training; the classifier itself is intentionally not trained yet." />
    </SnapshotFrame>
  );
}

const marketMonitorColumns: Column[] = [
  { label: "Symbol", keys: ["symbol"] },
  { label: "Status", render: (row) => <StatusPill value={row.status} /> },
  { label: "Price", render: (row) => formatCurrency(row.current_price) },
  { label: "Move", render: (row) => formatPercent(row.change_pct) },
  { label: "Role", keys: ["role", "row_type"] },
];

function OperationsPage() {
  const { data: jobs, reload } = useSnapshot<Dict>("/api/job-status");
  const { data: dataHealth, reload: reloadDataHealth } = useSnapshot<Dict>("/api/data-health");
  const { data: planQuality, reload: reloadPlanQuality } = useSnapshot<Dict>("/api/plan-quality");
  const [result, setResult] = useState<string>("");
  const [busy, setBusy] = useState<string>("");

  useEffect(() => {
    const timer = window.setInterval(() => {
      reload();
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  async function runAction(name: string, path: string, payload?: unknown) {
    setBusy(name);
    setResult("");
    try {
      const response = await postApi(path, payload);
      setResult(JSON.stringify(response, null, 2));
      reload();
      reloadDataHealth();
      reloadPlanQuality();
    } catch (exc) {
      setResult((exc as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function importCsv(file: File | null) {
    if (!file) return;
    const csvText = await file.text();
    await runAction("robinhood", "/api/actions/import-robinhood-csv", { filename: file.name, csv_text: csvText });
  }

  const jobRows = Object.values(asDict(asDict(jobs?.payload).jobs));
  const dataHealthPayload = asDict(dataHealth?.payload);
  const planQualityPayload = asDict(planQuality?.payload);
  const planGroups = Object.entries(asDict(planQualityPayload.groups)).map(([name, row]) => ({ name, ...asDict(row) }));
  return (
    <>
      <section className="ops-grid">
        <Panel title="Manual System Actions" subtitle="Use these when you want fresh data immediately instead of waiting for scheduler.">
          <div className="button-stack">
            <button disabled={!!busy} onClick={() => runAction("refresh", "/api/actions/refresh-market", { force_source_refresh: true })}>Force Fresh Market Data</button>
            <button disabled={!!busy} onClick={() => runAction("nightly", "/api/actions/run-nightly-once")}>Run Full Nightly Pipeline</button>
            <button disabled={!!busy} onClick={() => runAction("weekend", "/api/actions/run-weekend-research-once")}>Run Weekend Research</button>
          </div>
        </Panel>
        <Panel title="Robinhood CSV Import" subtitle="Import Account Activity CSV; then review holdings, transactions, and execution review on Portfolio.">
          <label className="file-box">
            <input type="file" accept=".csv,text/csv" onChange={(event) => importCsv(event.target.files?.[0] ?? null)} />
            Upload CSV and reconcile portfolio
          </label>
        </Panel>
      </section>
      <Panel title="Job Status" subtitle="Current background and manual job registry.">
        <DataTable rows={jobRows} columns={[
          { label: "Job", keys: ["name"] },
          { label: "State", render: (row) => <StatusPill value={row.state} /> },
          { label: "Detail", keys: ["detail"] },
          { label: "Updated", render: (row) => formatDate(row.updated_at) },
        ]} />
      </Panel>
      <section className="two-column">
        <Panel title="Data Health Details" subtitle="Missing, invalid, stale, and fallback source diagnostics.">
          <DataTable rows={listFromPayload(dataHealthPayload, ["symbols"])} columns={[
            { label: "Symbol", keys: ["symbol"] },
            { label: "Status", render: (row) => <StatusPill value={row.status} /> },
            { label: "Price", render: (row) => formatCurrency(row.price) },
            { label: "Source", keys: ["source"] },
            { label: "Reason", keys: ["reason"] },
          ]} emptyText="No data-health snapshot yet. Force market data refresh or run nightly." />
        </Panel>
        <Panel title="Plan Quality Groups" subtitle="Execution quality grouped by decision layer.">
          <DataTable rows={planGroups} columns={[
            { label: "Group", keys: ["name"] },
            { label: "Planned", keys: ["planned_count"] },
            { label: "Executed", keys: ["executed_count"] },
            { label: "Missed Reachable", keys: ["missed_reachable_count"] },
            { label: "Invalidated", keys: ["invalidated_count"] },
          ]} emptyText="No plan-quality snapshot yet. Run nightly after importing activity CSV." />
        </Panel>
      </section>
      <Panel title="Latest Action Result" subtitle={busy ? `Running ${busy}...` : "CSV import updates Portfolio immediately; full backtest snapshots update after Run Full Nightly Pipeline."}>
        <pre>{result || "No manual action run yet."}</pre>
      </Panel>
    </>
  );
}

function SettingsPage() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/settings");
  const payload = asDict(data?.payload);
  const runtimeSchedule = asDict(payload.runtime_schedule);
  const notification = asDict(payload.notification_config);
  const modelRegistry = asDict(payload.model_registry);
  const [scheduleText, setScheduleText] = useState("");
  const [saveResult, setSaveResult] = useState("");

  useEffect(() => {
    if (Object.keys(runtimeSchedule).length > 0) {
      setScheduleText(JSON.stringify(runtimeSchedule, null, 2));
    }
  }, [data?.generated_at]);

  async function saveSchedule() {
    try {
      const parsed = JSON.parse(scheduleText) as Dict;
      const response = await postApi("/api/actions/save-runtime-schedule", parsed);
      setSaveResult(JSON.stringify(response, null, 2));
      reload();
    } catch (exc) {
      setSaveResult((exc as Error).message);
    }
  }

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <section className="two-column">
        <Panel title="Runtime Schedule" subtitle="Controls market monitor, nightly, weekend, and notification cadence.">
          <textarea value={scheduleText} onChange={(event) => setScheduleText(event.target.value)} spellCheck={false} />
          <button type="button" onClick={saveSchedule}>Save Runtime Schedule</button>
        </Panel>
        <Panel title="Connections" subtitle="Secrets stay in env/file config; this panel shows safe status only.">
          <ConnectionFacts notification={notification} />
        </Panel>
      </section>
      <Panel title="Model Registry" subtitle="Unified model interface; default changes are not automatic.">
        <DataTable rows={asArray(modelRegistry.models)} columns={[
          { label: "Model", keys: ["display_name", "model_id"] },
          { label: "Role", keys: ["role"] },
          { label: "Default", render: (row) => <StatusPill value={row.is_default ? "DEFAULT" : "CANDIDATE"} /> },
          { label: "Enabled", render: (row) => <StatusPill value={row.enabled ? "ENABLED" : "DISABLED"} /> },
          { label: "Adapter", keys: ["adapter_path"] },
        ]} emptyText="No model registry entries found." />
      </Panel>
      <Panel title="Save Result" subtitle="Settings writes are tracked through the local job registry.">
        <pre>{saveResult || "No settings saved in this session."}</pre>
      </Panel>
    </SnapshotFrame>
  );
}

function ConnectionFacts({ notification }: { notification: Dict }) {
  const slack = asDict(notification.slack);
  const email = asDict(notification.email);
  const llm = asDict(notification.llm);
  const localSlm = asDict(notification.local_slm);
  return (
    <dl className="facts">
      <dt>Slack</dt><dd>{text(slack.enabled)} · webhook {text(slack.webhook_configured)}</dd>
      <dt>Email</dt><dd>{text(email.enabled)} · SMTP {text(email.smtp_host_configured)} · password {text(email.password_configured)}</dd>
      <dt>Remote LLM</dt><dd>{text(llm.enabled)} · {text(llm.model)} · key {text(llm.api_key_configured)}</dd>
      <dt>Local SLM</dt><dd>{text(localSlm.enabled)} · {text(localSlm.model)} · {text(localSlm.base_url)}</dd>
    </dl>
  );
}

function Placeholder({ title, text: body }: { title: string; text: string }) {
  return (
    <article className="placeholder-box">
      <b>{title}</b>
      <span>{body}</span>
    </article>
  );
}

function App() {
  const [activePage, setActivePage] = useState<PageKey>("dashboard");
  const activeMeta = pages.find((page) => page.key === activePage) ?? pages[0];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>Quant Trade</span>
          <b>V3 Workbench</b>
        </div>
        <nav>
          {pages.map((page) => (
            <button
              key={page.key}
              className={page.key === activePage ? "active" : ""}
              type="button"
              onClick={() => setActivePage(page.key)}
            >
              <b>{page.label}</b>
              <span>{page.detail}</span>
            </button>
          ))}
        </nav>
      </aside>
      <section className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">FastAPI + React, no Streamlit rerun</p>
            <h1>{activeMeta.label}</h1>
          </div>
          <div className="top-note">Read snapshots fast. Run heavy jobs intentionally.</div>
        </header>
        {activePage === "dashboard" ? <DashboardPage /> : null}
        {activePage === "portfolio" ? <PortfolioPage /> : null}
        {activePage === "core" ? <CoreEtfPage /> : null}
        {activePage === "satellite" ? <SatelliteRadarPage /> : null}
        {activePage === "risk" ? <RiskPage /> : null}
        {activePage === "monitor" ? <MarketMonitorPage /> : null}
        {activePage === "operations" ? <OperationsPage /> : null}
        {activePage === "settings" ? <SettingsPage /> : null}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
