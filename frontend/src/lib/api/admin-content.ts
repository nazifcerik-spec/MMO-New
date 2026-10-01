import { apiFetch } from "./client";

export interface ModuleType {
  entity_type: string;
  counts: Record<string, number>;
  pending_drafts: number;
  can_edit: boolean;
  can_publish: boolean;
}
export interface ContentModule {
  module: string;
  types: ModuleType[];
}
export interface EntityRow {
  code: string;
  status: string;
  revision_no: number;
  version: number;
  published_at: string | null;
  updated_at: string;
}
export interface EntityView {
  code: string;
  status: string;
  revision_no: number;
  name_key: string;
  description_key: string | null;
  published_at: string | null;
  has_pending_changes: boolean;
  edit_version: number;
  data: Record<string, unknown>;
  live_data: Record<string, unknown> | null;
}
export interface Issue {
  level: "error" | "warning";
  code: string;
  message: string;
  path: string;
}
export interface WorkflowState {
  stage: "draft" | "review" | "approved" | "published" | "archived";
  edit_version: number;
  review: { status: string; requested_by: number | null; reviewed_by: number | null; note: string | null; reviewed_at: string | null } | null;
  review_required: boolean;
}
export interface References {
  total: number;
  by_type: Record<string, number>;
  items: { entity_type: string; code: string; status: string; via: string }[];
  outgoing: { entity_type: string; code: string }[];
}
export interface HistoryRow {
  revision_no: number;
  status: string;
  release_version: number;
  created_at: string;
  change_summary: string | null;
}
export interface PendingRow {
  entity_type: string;
  code: string;
  status: string;
  new: boolean;
  updated_at: string;
}

const C = "/admin/content";
const enc = encodeURIComponent;

export const contentApi = {
  modules: () => apiFetch<ContentModule[]>(`${C}/modules`),
  pending: () => apiFetch<PendingRow[]>(`${C}/pending`),
  list: (type: string, q: { search?: string; status?: string; offset?: number }) =>
    apiFetch<{ items: EntityRow[]; total: number; limit: number; offset: number }>(`${C}/${type}`, { query: { ...q, limit: 50 } }),
  get: (type: string, code: string) => apiFetch<EntityView>(`${C}/${type}/${enc(code)}`),
  create: (type: string, code: string, data: unknown) => apiFetch<EntityView>(`${C}/${type}`, { method: "POST", body: { code, data } }),
  update: (type: string, code: string, data: unknown, expected_version: number) =>
    apiFetch<EntityView>(`${C}/${type}/${enc(code)}`, { method: "PUT", body: { data, expected_version } }),
  discard: (type: string, code: string) => apiFetch<void>(`${C}/${type}/${enc(code)}/draft`, { method: "DELETE" }),
  remove: (type: string, code: string) => apiFetch<void>(`${C}/${type}/${enc(code)}`, { method: "DELETE" }),
  validate: (type: string, code: string) => apiFetch<{ ok: boolean; issues: Issue[] }>(`${C}/${type}/${enc(code)}/validate`, { method: "POST" }),
  workflow: (type: string, code: string) => apiFetch<WorkflowState>(`${C}/${type}/${enc(code)}/workflow`),
  requestReview: (type: string, code: string) => apiFetch<WorkflowState>(`${C}/${type}/${enc(code)}/review/request`, { method: "POST" }),
  approve: (type: string, code: string, note?: string) => apiFetch<WorkflowState>(`${C}/${type}/${enc(code)}/review/approve`, { method: "POST", body: { note: note ?? null } }),
  reject: (type: string, code: string, note?: string) => apiFetch<WorkflowState>(`${C}/${type}/${enc(code)}/review/reject`, { method: "POST", body: { note: note ?? null } }),
  publish: (items: { entity_type: string; code: string }[], label?: string, acknowledge_warnings = false) =>
    apiFetch<{ release_version: number }>(`${C}/releases`, { method: "POST", body: { items, label: label ?? null, acknowledge_warnings } }),
  status: (type: string, code: string, status: "published" | "disabled" | "archived", acknowledge_references = false) =>
    apiFetch<{ status: string }>(`${C}/${type}/${enc(code)}/status`, { method: "POST", body: { status, acknowledge_references } }),
  references: (type: string, code: string) => apiFetch<References>(`${C}/${type}/${enc(code)}/references`),
  history: (type: string, code: string) => apiFetch<HistoryRow[]>(`${C}/${type}/${enc(code)}/history`),
  diff: (type: string, code: string, from_rev: number) =>
    apiFetch<{ path: string; before: unknown; after: unknown }[]>(`${C}/${type}/${enc(code)}/diff`, { query: { from_rev } }),
  rollback: (type: string, code: string, revision_no: number) => apiFetch<EntityView>(`${C}/${type}/${enc(code)}/rollback`, { method: "POST", body: { revision_no, acknowledge_warnings: true } }),
};

export interface LocaleStats {
  total: number;
  missing: number;
  draft: number;
  reviewed: number;
  published: number;
  present_pct: number;
  reviewed_pct: number;
}

const L = "/admin/localization";
export const l10nAdminApi = {
  dashboard: (namespace?: string) => apiFetch<{ locales: Record<string, LocaleStats> }>(`${L}/dashboard`, { query: { namespace } }),
  namespaces: () => apiFetch<{ namespace: string; keys: number }[]>(`${L}/namespaces`),
  keys: (q: { namespace?: string; search?: string; missing_locale?: string; offset?: number }) =>
    apiFetch<{ items: { key: string; values: Record<string, { value: string; status: string; version: number }> }[]; total: number }>(`${L}/keys`, { query: { ...q, limit: 50 } }),
  set: (key: string, locale: string, value: string, status: string, expected_version: number | null) =>
    apiFetch<{ version: number }>(`${L}/keys/${enc(key)}/${locale}`, { method: "PUT", body: { value, status, expected_version } }),
  exportJson: (namespace?: string) => apiFetch<{ rows: { key: string; locale: string; value: string; status: string }[] }>(`${L}/export`, { query: { namespace } }),
  import: (rows: unknown[], dry_run: boolean, overwrite_reviewed = false) =>
    apiFetch<Record<string, unknown>>(`${L}/import`, { method: "POST", body: { rows, dry_run, overwrite_reviewed } }),
};
