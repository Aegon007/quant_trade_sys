import { asArray, text } from "./data";

const STATUS_LABELS: Record<string, string> = {
  ACCUMULATE: "加仓",
  ACTION: "有动作",
  ATTRACTIVE: "有吸引力",
  AVOID: "避免买入",
  BLOCKED: "已阻断",
  BUY: "买入",
  CAUTION: "谨慎",
  CACHED: "已缓存",
  COMPLETED: "已完成",
  CONFIGURED: "已配置",
  CONFIRMED: "已确认",
  DCA_ACCUMULATE: "定投加仓",
  DEGRADED: "健康度下降",
  DISABLED: "已禁用",
  DOWNLOADED: "已下载",
  ERROR: "错误",
  EXIT: "退出",
  FAILED: "失败",
  FALSE: "否",
  FRESH: "新鲜",
  GOVERNED: "受治理",
  HEAVY: "重仓",
  HIGH: "高",
  HOLD: "持有",
  LIGHT: "轻仓",
  LOADING: "加载中",
  LOW: "低",
  MEDIUM: "中",
  MISSING: "缺失",
  MODEL_NOT_READY: "模型未就绪",
  MONITOR: "监控中",
  NEUTRAL: "中性",
  NO: "否",
  NO_ACTION: "无动作",
  NO_DATA: "无数据",
  NONE: "无",
  NORMAL: "正常",
  NOT_CONFIGURED: "未配置",
  NOT_INGESTED: "未接入",
  NOT_READY: "未就绪",
  NOT_RUN: "未运行",
  OK: "正常",
  OVER_LIMIT: "超限",
  PASS: "通过",
  PAUSE_BUY: "暂停买入",
  PENDING: "待处理",
  PRIMARY: "主源",
  PROBE: "试探建仓",
  QUEUED: "排队中",
  READY: "就绪",
  RISK_EXIT: "风险退出",
  RISK_OFF: "风险关闭",
  RUNNING: "运行中",
  SELL: "卖出",
  STALE: "过期",
  STARTED: "已启动",
  STOP: "停止",
  STRONG: "强",
  TEST_FAILED: "测试失败",
  TESTED_OK: "测试通过",
  TRIM: "减仓",
  TRUE: "是",
  UNAVAILABLE: "不可用",
  UNKNOWN: "未知",
  WAITING: "等待中",
  WAIT: "等待",
  WATCH: "观察",
  WEAK: "偏弱",
  YES: "是",
  EXECUTABLE_ACTIONS: "有可执行动作",
  CANDIDATES_BLOCKED: "候选被阻断",
  CANDIDATES_ONLY: "仅有模型候选",
};

const REASON_LABELS: Record<string, string> = {
  CORE_FORECAST_BEATS_RISK_FREE: "核心ETF预测优于短债收益",
  CORE_PATIENT_HOLD: "核心ETF适合耐心持有",
  CORE_WEAK_FORECAST: "核心ETF预测偏弱",
  DCA_UNDERWEIGHT_CORE: "核心ETF低于目标仓位，允许定投加仓",
  MARKET_SENTIMENT_RISK_OFF: "市场情绪偏风险关闭",
  OUTSIDE_SATELLITE_TOP3: "未进入卫星仓前三候选",
  PORTFOLIO_DISCIPLINE_BLOCK: "组合纪律层阻断",
  RISK_GATE_BLOCK: "风险门控阻断",
  SATELLITE_HIGH_UPSIDE: "卫星仓上涨空间较高",
  SATELLITE_NOT_STRONG_ENOUGH: "卫星仓信号不够强",
  SATELLITE_WEAK_FORECAST: "卫星仓预测偏弱",
  SECTOR_MOMENTUM_CONFIRMED: "行业动量确认",
  SEMI_SECTOR_CONFIRMATION: "半导体板块强势确认",
  SHORT_TERM_MOMENTUM_EXPANSION: "短期动量扩散",
  TIMING_DETERIORATING: "入场时机转弱",
  TREND_CONFIRMED: "趋势确认",
};

function normalizeKey(value: string): string {
  return value.trim().replaceAll("-", "_").replaceAll(" ", "_").toUpperCase();
}

export function zhStatus(value: unknown, fallback = "-"): string {
  const raw = text(value, fallback);
  if (!raw || raw === "-") return raw;
  if (raw.startsWith("SUCCESS:")) return raw.replace("SUCCESS:", "成功：");
  if (raw.startsWith("FAILED:")) return raw.replace("FAILED:", "失败：");
  if (raw.startsWith("Testing")) return "测试中...";
  const normalized = normalizeKey(raw);
  return STATUS_LABELS[normalized] ?? raw;
}

export function zhReasonCodes(value: unknown): string {
  const values = asArray(value).length ? asArray(value).map(String) : text(value, "").split(",");
  const translated = values
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => REASON_LABELS[normalizeKey(item)] ?? item);
  return translated.length ? translated.join("，") : "-";
}
