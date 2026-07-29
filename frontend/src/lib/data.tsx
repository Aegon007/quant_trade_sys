import { useCallback, useEffect, useState } from "react";
import { fetchApi, type ApiEnvelope } from "../api";

export type Dict = Record<string, unknown>;

export function asDict(value: unknown): Dict {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Dict) : {};
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function pick(row: Dict, keys: string[]): unknown {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && String(value) !== "") return value;
  }
  return undefined;
}

export function text(value: unknown, fallback = "-"): string {
  if (value === undefined || value === null || value === "") return fallback;
  if (Array.isArray(value)) return value.map((item) => text(item, "")).filter(Boolean).join(", ") || fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function numberValue(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatCurrency(value: unknown, digits = 0): string {
  const parsed = numberValue(value);
  if (parsed === null) return "-";
  return parsed.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
  });
}

export function formatPercent(value: unknown, digits = 1): string {
  const parsed = numberValue(value);
  if (parsed === null) return "-";
  const valueToShow = Math.abs(parsed) <= 1 ? parsed * 100 : parsed;
  return `${valueToShow.toFixed(digits)}%`;
}

export function formatNumber(value: unknown, digits = 1): string {
  const parsed = numberValue(value);
  return parsed === null ? "-" : parsed.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function formatDate(value: unknown): string {
  const raw = text(value, "");
  if (!raw) return "-";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function averageCost(row: Dict): number | null {
  return numberValue(row.average_cost ?? row.cost);
}

export function currentPrice(row: Dict): number | null {
  return numberValue(row.current_price ?? row.last_price);
}

export function listFromPayload(payload: unknown, keys: string[]): unknown[] {
  const record = asDict(payload);
  for (const key of keys) {
    const rows = asArray(record[key]);
    if (rows.length > 0) return rows;
  }
  return [];
}

export function modelDecision(row: Dict): Dict {
  return asDict(row.model_decision ?? row.decision);
}

export function longHorizon(row: Dict): Dict {
  return asDict(row.long_horizon ?? asDict(row.multi_horizon).long_horizon);
}

export function timing(row: Dict): Dict {
  return asDict(row.timing ?? asDict(row.multi_horizon).timing);
}

export function useSnapshot<TPayload = Dict>(path: string) {
  const [data, setData] = useState<ApiEnvelope<TPayload> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const reload = useCallback((silent = false) => {
    if (!silent) setLoading(true);
    setError("");
    return fetchApi<TPayload>(path)
      .then(setData)
      .catch((exc: Error) => setError(exc.message))
      .finally(() => setLoading(false));
  }, [path]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, loading, reload };
}
