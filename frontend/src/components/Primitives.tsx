import type { ReactNode } from "react";
import type { ApiEnvelope } from "../api";
import { dateTime, text } from "../lib/data";

const LABELS: Record<string, string> = {
  READY: "就绪", OK: "正常", STALE: "已过期", MISSING: "缺失", DEGRADED: "需关注", PARTIAL: "部分可用",
  NORMAL: "正常", CAUTION: "谨慎", HIGH_RISK: "高风险", DEEP_RESEARCH: "值得深入研究", WATCH: "继续观察",
  WAIT_FOR_STABILIZATION: "等待企稳", FUNDAMENTALS_DAMAGED: "基本面受损", VALUE_TRAP_RISK: "价值陷阱风险",
  LLM_REVIEW_REQUIRED: "等待模型复核", STRONG_OPPORTUNITY: "强估值机会", ACCUMULATE: "可分批研究",
  INSUFFICIENT_DATA: "数据不足", OVERVALUED: "估值偏高", FAIR_VALUE_NOT_OVERSOLD: "未明显超跌",
  OPPORTUNITIES_FOUND: "发现估值机会", NO_STRONG_SIGNAL: "暂无强信号", COLLECTING_DATA: "积累样本中",
  HIGH: "高优先级", MEDIUM: "中优先级", LOW: "低优先级", llm: "远程LLM", rules: "规则降级",
  fcff_multistage: "多阶段自由现金流折现", revenue_growth_dcf: "成长型收入折现", residual_income: "剩余收益模型",
  normalized_earnings: "标准化盈利估值", revenue_multiple: "收入倍数估值", reit_ffo_nav: "REIT现金流与净资产估值",
  sum_of_parts: "分部估值", distress_weighted: "困境概率加权估值", etf_risk_premium: "ETF风险溢价估值",
  etf_yield_duration: "ETF收益率久期估值", etf_spot_carry: "现货持有成本估值",
  mature_profitable: "成熟盈利公司", mature_growth: "成熟成长公司", high_growth_profitable: "高增长盈利公司",
  financial_service: "金融服务公司", reit: "房地产信托", cyclical: "周期型公司", commodity: "商品型公司",
  unprofitable_growth: "未盈利成长公司", conglomerate: "多元化集团", distressed: "困境公司",
  broad_market_etf: "宽基ETF", sector_etf: "行业ETF", bond_etf: "债券ETF", commodity_etf: "商品ETF",
  growth_rate: "增长率", discount_rate: "贴现率", terminal_growth: "永续增长率", target_margin: "目标利润率",
  normalized_multiple: "标准化估值倍数", VALUATION_MARGIN: "估值安全边际", ABNORMAL_SELLOFF: "异常下跌",
  EVENT_LIKELY_TEMPORARY: "事件更可能是暂时冲击", PRICE_STABILIZING: "价格正在企稳",
  route_corrected: "估值路线已校正", assumptions_sanitized: "假设已通过边界校验", missing_evidence: "证据不足",
  llm_route_unavailable: "LLM路线不可用", llm_route_invalid: "LLM路线格式无效",
  LLM_ROUTE_REQUIRED: "行动候选必须经过LLM复核", missing_valuation_inputs: "估值输入不完整",
  sec_companyfacts: "SEC公司财报", yfinance_fallback: "Yahoo财务数据备用源", configured_etf_metadata: "ETF配置元数据", yfinance_etf_metadata: "ETF市场元数据",
  stooq: "Stooq主源", yfinance: "Yahoo备用源", local_history_cache: "本地行情缓存", unknown: "来源未知",
  sec_edgar_filing: "SEC财报原文", UNAVAILABLE: "暂不可用", not_tested: "尚未测试", stale: "状态过期",
  completed: "已完成", running: "运行中", queued: "排队中", started: "已启动", failed: "失败", skipped: "未启用",
};

export const label = (value: unknown): string => LABELS[text(value, "")] ?? text(value);

export function Badge({ value }: { value: unknown }) {
  const raw = text(value, "UNKNOWN").toLowerCase();
  const tone = /ready|ok|normal|deep_research|completed/.test(raw) ? "good" : /failed|missing|damaged|trap|high_risk/.test(raw) ? "bad" : "warn";
  return <span className={`badge ${tone}`}>{label(value)}</span>;
}

export function Section({ title, note, action, children }: { title: string; note?: string; action?: ReactNode; children: ReactNode }) {
  return <section className="section"><header><div><h2>{title}</h2>{note ? <p>{note}</p> : null}</div>{action}</header>{children}</section>;
}

export function SnapshotState({ snapshot, loading, error, reload }: { snapshot: ApiEnvelope<unknown> | null; loading: boolean; error: string; reload: () => void }) {
  const generated = Boolean(snapshot?.generated_at);
  const status = error || !generated ? "MISSING" : snapshot?.freshness_status ?? "READY";
  return <div className="snapshot-state"><span>{loading ? "正在读取" : error ? "读取失败" : generated ? `更新于 ${dateTime(snapshot?.generated_at)}` : "尚未生成"}</span><Badge value={status} /><button className="text-button" onClick={reload}>刷新显示</button>{error ? <b>{error}</b> : null}</div>;
}

export function StatRow({ items }: { items: Array<{ label: string; value: ReactNode; note?: string }> }) {
  return <div className="stat-row">{items.map((item) => <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong>{item.note ? <small>{item.note}</small> : null}</div>)}</div>;
}

export function Empty({ children }: { children: ReactNode }) { return <div className="empty">{children}</div>; }

export function Progress({ value }: { value: unknown }) {
  const width = Math.max(0, Math.min(Number(value) || 0, 100));
  return <div className="progress"><i style={{ width: `${width}%` }} /></div>;
}
