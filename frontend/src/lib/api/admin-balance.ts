import { apiFetch } from "./client";

export interface SimParams {
  level: number;
  race: string;
  base_class: string;
  specialization?: string | null;
  talent_build: string;
  gear_tier?: number | null;
  gear_budget_pct: number;
  zone?: string | null;
  risk: string;
  duration_s: number;
  iterations: number;
  fights: number;
  seed: number;
  profession_node?: string | null;
}
export type Summary = { mean: number; min: number; max: number; stdev: number };
export interface SimResult {
  zone: string;
  metrics: Record<string, Summary>;
  combat: Record<string, number>;
  profession: { node: string; profession: string; materials_per_hour: Record<string, number>; value_per_hour: number; xp_per_hour: number } | null;
  per_iteration: Record<string, number>[];
}
export interface CheckReport {
  level: number;
  warnings: { section: string; subject: string; message: string }[];
  sections: Record<string, unknown>;
}
export interface Telemetry {
  window_days: number;
  min_bucket: number;
  sessions: Record<string, number>;
  zones: Record<string, number>;
  profession_usage: { gathering: Record<string, number>; crafting: Record<string, number> };
  funnel: { step: string; count: number; drop_off_pct: number }[];
}

export const balanceApi = {
  simulate: (p: SimParams) => apiFetch<SimResult>("/admin/balance/simulate", { method: "POST", body: p }),
  simulateCsv: async (p: SimParams): Promise<string> => {
    const csrf = document.cookie.split("; ").find((c) => c.startsWith("csrf_token="))?.split("=")[1];
    const res = await fetch("/api/v1/admin/balance/simulate?format=csv", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}) },
      body: JSON.stringify(p),
    });
    if (!res.ok) throw new Error(String(res.status));
    return res.text();
  },
  check: (level: number, sections: string[], fights?: number) => apiFetch<CheckReport>("/admin/balance/check", { method: "POST", body: { level, sections, fights: fights ?? null } }),
  telemetry: (days: number) => apiFetch<Telemetry>("/admin/telemetry", { query: { days } }),
};
