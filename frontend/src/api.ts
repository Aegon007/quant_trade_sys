export type ApiEnvelope<TPayload = unknown> = {
  schema_version: number;
  name: string;
  generated_at: string;
  source: string;
  freshness_status: string;
  is_stale: boolean;
  summary: Record<string, unknown>;
  items: unknown[];
  errors: string[];
  warnings: string[];
  data_quality: Record<string, unknown>;
  next_update_hint: string | null;
  payload: TPayload;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export async function fetchApi<TPayload>(path: string): Promise<ApiEnvelope<TPayload>> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`API ${path} failed with ${response.status}`);
  }
  return response.json() as Promise<ApiEnvelope<TPayload>>;
}

export async function postApi<TPayload = unknown>(path: string, payload?: unknown): Promise<TPayload> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`API ${path} failed with ${response.status}${text ? `: ${text}` : ""}`);
  }
  return response.json() as Promise<TPayload>;
}

export async function downloadApi(path: string, fallbackFilename: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`API ${path} failed with ${response.status}`);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match?.[1] || fallbackFilename;
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
