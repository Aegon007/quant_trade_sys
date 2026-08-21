import { useEffect, useState } from "react";
import { postApi } from "../api";
import { ActionStatus, DecisionTable, HorizonStrip, ModelDetail, type DecisionColumn } from "../components/DecisionTable";
import { Facts, MetricStrip, Panel, SnapshotFrame, Status } from "../components/Primitives";
import {
  averageCost,
  asArray,
  asDict,
  currentPrice,
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
    { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
    { label: "当前仓位", render: (row) => {
      const value = (numberValue(row.shares) ?? 0) * (currentPrice(row) ?? averageCost(row) ?? 0);
      return totalCapital > 0 ? formatPercent(value / totalCapital) : "-";
    } },
    { label: "成本/现价", render: (row) => (
      <span className="stacked-cell">
        <b>{formatCurrency(averageCost(row), 2)}</b>
        <small>{formatCurrency(currentPrice(row), 2)}</small>
      </span>
    ) },
    { label: "目标仓位", render: (row) => text(modelDecision(row).target_weight_range_pct) },
    { label: "长期判断", render: (row) => <Status value={row.long_horizon_state} /> },
    { label: "入场时机", render: (row) => <Status value={timing(row).state ?? row.timing_state} /> },
    { label: "动作", render: (row) => <ActionStatus row={row} /> },
    { label: "盈亏", render: (row) => {
      const price = currentPrice(row);
      const cost = averageCost(row);
      return price !== null && cost !== null && cost !== 0 ? formatPercent((price - cost) / cost) : "-";
    } },
  ];
}

const watchColumns: DecisionColumn[] = [
  { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
  { label: "现价", render: (row) => formatCurrency(row.last_price, 2) },
  { label: "长期判断", render: (row) => <Status value={row.long_horizon_state} /> },
  { label: "63 / 126 / 252", render: (row) => <HorizonStrip row={row} /> },
  { label: "入场时机", render: (row) => <Status value={row.timing_state} /> },
  { label: "动作", render: (row) => <ActionStatus row={row} /> },
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
      setResult("账户校准已保存。");
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
        { label: "总资产", value: formatCurrency(account.total_capital), hint: "现金加持仓市值" },
        { label: "可用现金", value: formatCurrency(account.cash_available), hint: `可部署 ${formatCurrency(account.deployable_cash)}` },
        { label: "持仓市值", value: formatCurrency(account.holdings_market_value), hint: `${holdings.length} 个持仓` },
        { label: "未实现盈亏", value: formatCurrency(account.unrealized_pl), hint: formatPercent(account.unrealized_pl_pct) },
      ]} />

      <Panel title="持仓决策" subtitle="如果长期逻辑仍然有吸引力，模型不能仅因短期时机转弱就直接建议卖出。">
        <DecisionTable rows={holdings} columns={positionColumns(totalCapital)} detail={(row) => (
          <div className="position-detail">
            <ModelDetail row={row} />
            <Facts rows={[
              ["股数", formatNumber(row.shares, 3)],
              ["平均成本", formatCurrency(averageCost(row), 2)],
              ["当前价格", formatCurrency(currentPrice(row), 2)],
              ["市值", formatCurrency((numberValue(row.shares) ?? 0) * (currentPrice(row) ?? 0), 2)],
            ]} />
          </div>
        )} emptyText="没有已同步的持仓。" />
      </Panel>

      <Panel title="关注列表决策" subtitle="只有当前神经模型前三候选才允许产生卫星仓动作，其他候选保持观察。">
        <DecisionTable rows={watchlist} columns={watchColumns} emptyText="关注列表为空。" />
      </Panel>

      <div className="split-layout">
        <Panel title="账户校准" subtitle="Robinhood流水主要包含交易记录，不一定包含可靠的实时账户总值。">
          <div className="form-grid">
            <label>可用现金<input value={cash} onChange={(event) => setCash(event.target.value)} inputMode="decimal" /></label>
            <label>可选券商总资产<input value={brokerTotal} onChange={(event) => setBrokerTotal(event.target.value)} inputMode="decimal" /></label>
          </div>
          <button disabled={busy || (!cash.trim() && !brokerTotal.trim())} onClick={saveCalibration}>{busy ? "保存中..." : "保存校准"}</button>
          {result ? <p className="form-result">{result}</p> : null}
        </Panel>
        <Panel title="交易流水摘要" subtitle="最近导入并完成持仓重建的活动。">
          <Facts rows={[
            ["最近交易日", text(summary.latest_transaction_day)],
            ["交易数", text(summary.latest_trade_count, "0")],
            ["已实现盈亏", formatCurrency(summary.latest_realized_pl)],
            ["复盘状态", <Status value={summary.post_close_review_status ?? "PENDING"} />],
            ["模型快照", <Status value={summary.multi_horizon_status ?? "MODEL_NOT_READY"} />],
          ]} />
        </Panel>
      </div>

      <Panel title="最近交易记录" subtitle="导入Robinhood CSV后，系统会基于这份流水重建当前持仓。">
        <DecisionTable
          rows={transactions}
          columns={[
            { label: "日期", render: (row) => formatDate(row.date) },
            { label: "类型", render: (row) => <Status value={row.record_type ?? row.event_type} /> },
            { label: "代码", className: "symbol-cell", render: (row) => text(row.symbol) },
            { label: "方向", render: (row) => text(row.side ?? row.event_type) },
            { label: "股数", render: (row) => formatNumber(row.shares, 3) },
            { label: "价格", render: (row) => formatCurrency(row.price, 2) },
          ]}
          detail={(row) => <Facts rows={[["来源", text(row.source ?? row.source_file)], ["盈亏", formatCurrency(row.pl, 2)]]} />}
          emptyText="没有交易记录。请在运行操作页导入Robinhood CSV。"
        />
      </Panel>
    </SnapshotFrame>
  );
}
