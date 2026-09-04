import { useCallback, useEffect, useState } from "react";
import { fetchApi, type ApiEnvelope } from "../api";

export type Dict = Record<string, unknown>;

export const asDict = (value: unknown): Dict => value && typeof value === "object" && !Array.isArray(value) ? value as Dict : {};
export const asArray = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
export const text = (value: unknown, fallback = "-"): string => value === undefined || value === null || value === "" ? fallback : String(value);

export function numberValue(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function money(value: unknown, digits = 2): string {
  const parsed = numberValue(value);
  return parsed === null ? "-" : parsed.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: digits });
}

export function percent(value: unknown, digits = 1): string {
  const parsed = numberValue(value);
  return parsed === null ? "-" : `${(Math.abs(parsed) <= 1 ? parsed * 100 : parsed).toFixed(digits)}%`;
}

export function dateTime(value: unknown): string {
  const raw = text(value, "");
  if (!raw) return "-";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function useSnapshot<T = Dict>(path: string, pollMs = 0) {
  const [data, setData] = useState<ApiEnvelope<T> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      setData(await fetchApi<T>(path));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    void reload();
    if (!pollMs) return;
    const timer = window.setInterval(() => void reload(true), pollMs);
    return () => window.clearInterval(timer);
  }, [pollMs, reload]);
  return { data, error, loading, reload };
}
