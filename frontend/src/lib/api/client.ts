/** Minimal typed fetch wrapper for the backend REST API (same-origin `/api/v1`). */

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown; correlation_id?: string | null };
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
    public readonly correlationId?: string | null,
  ) {
    super(message);
  }
}

const API_BASE = "/api/v1";

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : undefined;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  idempotencyKey?: string;
  query?: Record<string, string | number | boolean | undefined | null>;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, idempotencyKey, query, headers, ...rest } = options;
  const method = (rest.method ?? "GET").toUpperCase();
  // Offline mode is read-only: never queue or fake gameplay results client-side (server is authoritative).
  if (method !== "GET" && typeof navigator !== "undefined" && navigator.onLine === false) {
    throw new ApiError(0, "offline", "You are offline");
  }
  const url = new URL(`${API_BASE}${path}`, typeof window === "undefined" ? "http://localhost" : window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
  }
  const h = new Headers(headers);
  if (body !== undefined) h.set("Content-Type", "application/json");
  const csrf = readCookie("csrf_token");
  if (csrf) h.set("X-CSRF-Token", csrf);
  if (idempotencyKey) h.set("Idempotency-Key", idempotencyKey);
  const res = await fetch(typeof window === "undefined" ? url.toString() : url.pathname + url.search, {
    ...rest,
    headers: h,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as ApiErrorBody | null)?.error;
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? res.statusText, err?.details, err?.correlation_id);
  }
  return data as T;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
