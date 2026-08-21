import type React from "react";
import { asDict, formatCurrency, formatPercent, longHorizon, modelDecision, text, timing, type Dict } from "../lib/data";
import { zhReasonCodes, zhStatus } from "../lib/i18n";
import { EmptyState, Status } from "./Primitives";

export type DecisionColumn = {
  label: string;
  className?: string;
  render: (row: Dict, index: number) => React.ReactNode;
};

export function HorizonStrip({ row }: { row: Dict }) {
  const horizons = asDict(longHorizon(row).horizons);
  return (
    <div className="horizon-strip">
      {[63, 126, 252].map((horizon) => {
        const item = asDict(horizons[String(horizon)]);
        return (
          <span key={horizon}>
            <small>{horizon}天</small>
            <b>{formatPercent(item.rank)}</b>
          </span>
        );
      })}
    </div>
  );
}

export function ModelDetail({ row }: { row: Dict }) {
  const long = longHorizon(row);
  const horizonRows = asDict(long.horizons);
  const decision = modelDecision(row);
  const risk = asDict(row.risk ?? asDict(row.multi_horizon).risk);
  return (
    <div className="decision-detail">
      <div>
        <h4>多周期预测</h4>
        {[63, 126, 252].map((horizon) => {
          const item = asDict(horizonRows[String(horizon)]);
          const range = asDict(item.return_range);
          const prices = asDict(item.price_range);
          return (
            <p key={horizon}>
              <b>{horizon}d</b>
              <span>
                上涨概率 {formatPercent(item.positive_return_probability)}
                {" · "}跑赢短债 {formatPercent(item.risk_free_outperformance_probability)}
                {" · "}跑赢SPY {formatPercent(item.market_outperformance_probability)}
                {" · "}收益P10/P50/P90 {formatPercent(range.p10)} / {formatPercent(range.p50)} / {formatPercent(range.p90)}
                {Object.keys(prices).length ? ` · 价格 ${formatCurrency(prices.p10, 2)} / ${formatCurrency(prices.p50, 2)} / ${formatCurrency(prices.p90, 2)}` : ""}
              </span>
            </p>
          );
        })}
      </div>
      <div>
        <h4>决策证据</h4>
        <p><b>入场时机</b><span>{zhStatus(timing(row).state)}</span></p>
        <p><b>目标仓位</b><span>{text(decision.target_weight_range_pct)}</span></p>
        <p><b>潜在回撤</b><span>{formatPercent(risk.maximum_adverse_excursion)}</span></p>
        <p><b>原因</b><span>{zhReasonCodes(decision.reason_codes)}</span></p>
        <p><b>模型时间</b><span>{text(row.model_generated_at ?? asDict(row.multi_horizon).generated_at)}</span></p>
      </div>
    </div>
  );
}

export function DecisionTable({
  rows,
  columns,
  emptyText = "最新快照里没有可显示的数据。",
  detail = (row) => <ModelDetail row={row} />,
}: {
  rows: unknown[];
  columns: DecisionColumn[];
  emptyText?: string;
  detail?: (row: Dict) => React.ReactNode;
}) {
  const normalized = rows.map(asDict);
  if (!normalized.length) return <EmptyState>{emptyText}</EmptyState>;
  return (
    <div className="decision-table">
      <div className="decision-header" style={{ "--column-count": columns.length } as React.CSSProperties}>
        {columns.map((column) => <span key={column.label}>{column.label}</span>)}
      </div>
      {normalized.map((row, index) => (
        <details key={`${text(row.symbol, "row")}-${index}`} className="decision-row">
          <summary style={{ "--column-count": columns.length } as React.CSSProperties}>
            {columns.map((column) => (
              <span className={column.className ?? ""} key={column.label} data-label={column.label}>
                {column.render(row, index)}
              </span>
            ))}
          </summary>
          {detail(row)}
        </details>
      ))}
    </div>
  );
}

export function ActionStatus({ row }: { row: Dict }) {
  return <Status value={modelDecision(row).action ?? row.final_action ?? row.action ?? row.signal} />;
}
