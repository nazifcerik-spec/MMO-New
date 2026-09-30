import { apiFetch } from "./client";

export interface HealthCheck {
  status: "ok" | "error";
  latency_ms?: number;
  error?: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  env: string;
  checks: { database: HealthCheck; redis: HealthCheck };
}

export const getHealth = () => apiFetch<HealthResponse>("/health");
