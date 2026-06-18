import { useEffect, useState } from "react";
import { postApi } from "../api";
import { ActionStatus, DecisionTable, HorizonStrip, ModelDetail, type DecisionColumn } from "../components/DecisionTable";
import { Facts, MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import {
  asArray,
  asDict,
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
  modelDecision,
  numberValue,
  text,
  timing,
  useSnapshot,
  type Dict,
} from "../lib/data";

function positionColumns(totalCapital: number): DecisionColumn[] {
  return [
    { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
    { label: "Current weight", render: (row) => {
      const value = (numberValue(row.shares) ?? 0) * (numberValue(row.current_price) ?? numberValue(row.cost) ?? 0);
      return totalCapital > 0 ? formatPercent(value / totalCapital) : "-";
    } },
    { label: "Target", render: (row) => text(modelDecision(row).target_weight_range_pct) },
    { label: "Long horizon", render: (row) => <Status value={row.long_horizon_state} /> },
    { label: "Timing", render: (row) => <Status value={timing(row).state ?? row.timing_state} /> },
    { label: "Action", render: (row) => <ActionStatus row={row} /> },
    { label: "P/L", render: (row) => {
      const price = numberValue(row.current_price);
      const cost = numberValue(row.cost);
      return price !== null && cost !== null && cost !== 0 ? formatPercent((price - cost) / cost) : "-";
    } },
  ];
}

const watchColumns: DecisionColumn[] = [
  { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "Price", render: (row) => formatCurrency(row.last_price, 2) },
  { label: "Long horizon", render: (row) => <Status value={row.long_horizon_state} /> },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "Timing", render: (row) => <Status value={row.timing_state} /> },
  { label: "Action", render: (row) => <ActionStatus row={row} /> },
];

export default function Portfolio() {
  const { data, error, loading, reload } = useSnapshot<Dict>("/api/portfolio");
  const payload = asDict(data?.payload);
  const account = asDict(payload.account);
  const summary = data?.summary ?? {};
  const holdings = asArray(payload.holdings);
  const watchlist = asArray(payload.watchlist);
  const transactions = asArray(payload.recent_transactions);
  const totalCapital = numberValue(account.total_capital) ?? 0;
  const [cash, setCash] = useState("");
  const [brokerTotal, setBrokerTotal] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  useEffect(() => {
    if (data) setCash(account.cash_available === null || account.cash_available === undefined ? "" : String(account.cash_available));
  }, [data?.generated_at]);

  async function saveCalibration() {
    setBusy(true);
    setResult("");
    try {
      const request: Dict = {};
      if (cash.trim()) request.cash_available = Number(cash);
      if (brokerTotal.trim()) request.broker_total_capital = Number(brokerTotal);
      await postApi("/api/actions/save-account-calibration", request);
      setBrokerTotal("");
      setResult("Account calibration saved.");
      reload();
    } catch (exc) {
      setResult((exc as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SnapshotFrame snapshot={data} loading={loading} error={error} onReload={reload}>
      <MetricStrip items={[
        { label: "Total capital", value: formatCurrency(account.total_capital), hint: "Cash plus marked holdings" },
        { label: "Available cash", value: formatCurrency(account.cash_available), hint: `Deployable ${formatCurrency(account.deployable_cash)}` },
        { label: "Holdings value", value: formatCurrency(account.holdings_market_value), hint: `${holdings.length} positions` },
        { label: "Unrealized P/L", value: formatCurrency(account.unrealized_pl), hint: formatPercent(account.unrealized_pl_pct) },
      ]} />

      <Panel title="Position decisions" subtitle="The model cannot sell a long-term attractive holding solely because short-term timing weakened.">
        <DecisionTable rows={holdings} columns={positionColumns(totalCapital)} detail={(row) => (
          <div className="position-detail">
            <ModelDetail row={row} />
            <Facts rows={[
              ["Shares", formatNumber(row.shares, 3)],
              ["Average cost", formatCurrency(row.cost, 2)],
              ["Current price", formatCurrency(row.current_price, 2)],
              ["Market value", formatCurrency((numberValue(row.shares) ?? 0) * (numberValue(row.current_price) ?? 0), 2)],
            ]} />
          </div>
        )} emptyText="No reconciled holdings." />
      </Panel>

      <Panel title="Watchlist decisions" subtitle="A satellite action is allowed only for the current neural Top 3; other candidates remain WATCH.">
        <DecisionTable rows={watchlist} columns={watchColumns} emptyText="Watchlist is empty." />
      </Panel>

      <div className="split-layout">
        <Panel title="Account calibration" subtitle="Robinhood activity files contain trades, not a reliable live account value.">
          <div className="form-grid">
            <label>Available cash<input value={cash} onChange={(event) => setCash(event.target.value)} inputMode="decimal" /></label>
            <label>Optional broker total<input value={brokerTotal} onChange={(event) => setBrokerTotal(event.target.value)} inputMode="decimal" /></label>
          </div>
          <button disabled={busy || (!cash.trim() && !brokerTotal.trim())} onClick={saveCalibration}>{busy ? "Saving..." : "Save calibration"}</button>
          {result ? <p className="form-result">{result}</p> : null}
        </Panel>
        <Panel title="Ledger summary" subtitle="Latest imported and reconciled activity.">
          <Facts rows={[
            ["Latest day", text(summary.latest_transaction_day)],
            ["Trades", text(summary.latest_trade_count, "0")],
            ["Realized P/L", formatCurrency(summary.latest_realized_pl)],
            ["Review", <Status value={summary.post_close_review_status ?? "PENDING"} />],
            ["Model snapshot", <Status value={summary.multi_horizon_status ?? "MODEL_NOT_READY"} />],
          ]} />
        </Panel>
      </div>

      <Panel title="Recent transactions" subtitle="The portfolio is reconciled from this ledger after Robinhood CSV import.">
        <DecisionTable
          rows={transactions}
          columns={[
            { label: "Date", render: (row) => formatDate(row.date) },
            { label: "Type", render: (row) => <Status value={row.record_type ?? row.event_type} /> },
            { label: "Symbol", className: "symbol-cell", render: (row) => text(row.symbol) },
            { label: "Side", render: (row) => text(row.side ?? row.event_type) },
            { label: "Shares", render: (row) => formatNumber(row.shares, 3) },
            { label: "Price", render: (row) => formatCurrency(row.price, 2) },
          ]}
          detail={(row) => <Facts rows={[["Source", text(row.source ?? row.source_file)], ["P/L", formatCurrency(row.pl, 2)]]} />}
          emptyText="No transaction records. Import a Robinhood CSV from Operations."
        />
      </Panel>
    </SnapshotFrame>
  );
}
