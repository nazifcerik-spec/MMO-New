import { apiFetch } from "./client";

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export interface EffectDef {
  effect_type: string;
  params: Record<string, Json>;
  schema_version?: number;
}

export interface ItemData {
  category: string;
  subcategory: string | null;
  family: string | null;
  slot: string | null;
  weapon_family: string | null;
  armor_family: string | null;
  tier: number;
  min_level: number;
  rarity: string;
  stack_size: number;
  bind_policy: string;
  tradeable: boolean;
  sellable: boolean;
  vendor_value: number;
  durability: { max: number };
  sockets: { min: number; max: number };
  class_tags: string[];
  allowed_classes: string[];
  blocked_classes: string[];
  allowed_races: string[];
  blocked_races: string[];
  requirement_profile: string | null;
  requirements: { stats: Record<string, number>; profession: { code: string; level: number } | null };
  base_stats: { stat: string; amount: number }[];
  effects: EffectDef[];
  affix_rules: { pool: string[]; min: number | null; max: number | null; fixed: EffectDef[] };
  unique_effect: { key: string; effects: EffectDef[]; mastery_scaling: boolean } | null;
  set_code: string | null;
  salvage: { template_code: string; min_qty: number; max_qty: number; chance_pct: number }[];
  icon: string | null;
  sources: { kind: string; ref: string | null }[];
  short_description_key: string | null;
  lore_key: string | null;
}

export interface Issue {
  level: "error" | "warning";
  code: string;
  message: string;
  path: string;
}

export type TStatus = "missing" | "draft" | "reviewed" | "published";
export type TextField = "name" | "description" | "short_description" | "lore";
export type LocaleTexts = Record<string, { value: string; status: TStatus; version: number }>;

export interface ItemRow {
  code: string;
  name: string;
  category: string;
  slot: string | null;
  family: string | null;
  tier: number;
  min_level: number;
  rarity: string;
  status: string;
  revision_no: number;
  has_pending_changes: boolean;
  class_tags: string[];
  translations: Record<string, TStatus>;
  updated_at: string;
}

export interface Inspector {
  code: string;
  status: string;
  revision_no: number;
  has_pending_changes: boolean;
  edit_version: number;
  data: ItemData;
  live_data: ItemData | null;
  texts: Record<TextField, LocaleTexts>;
  issues: Issue[];
  requirement_budget: { budget: number; required: number; percent: number; warn_pct: number; error_pct: number };
  rarity_budget: { min: number; max: number; unique_required: boolean; mastery_scaling_required: boolean; fixed: boolean };
  tier_gate: { tier: number; min_level: number; max_level: number; rarities: string[]; stat_req_min: number; stat_req_max: number };
  references: Record<string, { code: string; match?: string; via?: string; chance_pct?: number }[]>;
}

export interface Meta {
  primary_stats: string[];
  derived_stats: string[];
  damage_types: string[];
  categories: string[];
  slots: string[];
  slots_by_category: Record<string, string[]>;
  rarities: string[];
  class_tags: string[];
  bind_policies: string[];
  source_kinds: string[];
  weapon_families: { code: string; kind: string; hands: number }[];
  armor_families: string[];
  classes: string[];
  races: string[];
  affixes: { code: string; group: string; kind: string; rarity_min: string; class_tag: string | null }[];
  sets: { code: string; bonuses: { pieces: number; effects: EffectDef[] }[] }[];
  requirement_profiles: Record<string, { primary: string[]; secondary: string; primary_at_600: number; secondary_at_600: number }>;
  rarity_budgets: Record<string, { min: number; max: number; unique_required: boolean; mastery_scaling_required: boolean; fixed: boolean }>;
  tiers: { tier: number; min_level: number; max_level: number; rarities: string[]; stat_req_min: number; stat_req_max: number }[];
  requirement_warn_pct: number;
  requirement_error_pct: number;
  base_stat_value: number;
  points_per_level: number;
  max_sockets: number;
  max_upgrade_level: number;
  upgrade_pct_per_level: number;
}

export interface RegistryEntry {
  effect_type: string;
  schema_version: number;
  category: string;
  description: string;
  params_schema: JsonSchema;
}

export interface JsonSchema {
  type?: string;
  enum?: Json[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  anyOf?: JsonSchema[];
  default?: Json;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  title?: string;
  maxItems?: number;
}

export interface Filters {
  q?: string;
  category?: string;
  tier?: number;
  rarity?: string;
  slot?: string;
  family?: string;
  class_tag?: string;
  status?: string;
  translation?: "complete" | "incomplete";
  missing_locale?: string;
  sort?: string;
  order?: "asc" | "desc";
}

export interface HistoryEntry {
  revision_no: number;
  status: string;
  created_at: string;
  created_by: number | null;
  change_summary: string | null;
  release_version?: number;
}

export interface PreviewResult {
  profile: { code: string; class: string; level: number };
  requirements_met: boolean;
  unmet: { kind: string; stat?: string; required?: number; have?: number }[];
  rolled_affixes: { code: string; value: number | null }[];
  deltas: Record<string, number>;
  before: Record<string, number>;
}

export interface ImportReport {
  summary: { rows: number; creates: number; updates: number; errors: number; warnings: number; dry_run: boolean; committed: boolean };
  report: { code: string; action: string | null; issues: Issue[] }[];
}

export interface GeneratorParams {
  category: "weapon" | "armor" | "accessory";
  slot: string;
  weapon_family?: string | null;
  armor_family?: string | null;
  tier_from: number;
  tier_to: number;
  rarity_weights: Record<string, number>;
  requirement_profile?: string | null;
  count: number;
  code_pattern: string;
  name_patterns: Record<string, string>;
  theme: { code: string; names: Record<string, string> };
  affix_pool: string[];
  class_tags: string[];
  salvage_material?: string | null;
}

export interface GeneratorResult {
  summary: { count: number; errors: number; warnings: number; committed: boolean; env: string };
  rows: {
    code: string;
    name: string;
    tier: number;
    rarity: string;
    min_level: number;
    base_stats: { stat: string; amount: number }[];
    requirements: Record<string, number>;
    issues: Issue[];
  }[];
}

const C = "/admin/content/item_template";
const I = "/admin/items";

export const adminItemsApi = {
  list: (f: Filters, offset: number, limit = 100) =>
    apiFetch<{ items: ItemRow[]; total: number; offset: number; limit: number }>(I, { query: { ...f, offset, limit } }),
  meta: () => apiFetch<Meta>(`${I}/meta`),
  registry: () => apiFetch<RegistryEntry[]>("/admin/content/effects/registry"),
  profiles: () => apiFetch<{ code: string; class: string; level: number }[]>(`${I}/preview-profiles`),
  inspector: (code: string) => apiFetch<Inspector>(`${I}/${encodeURIComponent(code)}`),
  create: (code: string, data: Partial<ItemData>) => apiFetch<{ code: string }>(C, { method: "POST", body: { code, data } }),
  save: (code: string, data: ItemData, expected_version: number) =>
    apiFetch<{ edit_version: number }>(`${C}/${encodeURIComponent(code)}`, { method: "PUT", body: { data, expected_version } }),
  validate: (code: string) => apiFetch<{ ok: boolean; issues: Issue[] }>(`${C}/${encodeURIComponent(code)}/validate`, { method: "POST" }),
  publish: (code: string, acknowledge_warnings: boolean) =>
    apiFetch<{ release_version: number }>("/admin/content/releases", {
      method: "POST",
      body: { items: [{ entity_type: "item_template", code }], acknowledge_warnings },
    }),
  setStatus: (code: string, status: "disabled" | "archived" | "published") =>
    apiFetch(`${C}/${encodeURIComponent(code)}/status`, { method: "POST", body: { status } }),
  history: (code: string) => apiFetch<HistoryEntry[]>(`${C}/${encodeURIComponent(code)}/history`),
  diff: (code: string, from_rev: number, to_rev: number) =>
    apiFetch<{ diff: { path: string; from: Json; to: Json }[] }>(`${C}/${encodeURIComponent(code)}/diff`, { query: { from_rev, to_rev } }),
  rollback: (code: string, revision_no: number) =>
    apiFetch(`${C}/${encodeURIComponent(code)}/rollback`, { method: "POST", body: { revision_no, acknowledge_warnings: true } }),
  clone: (code: string, new_code: string) => apiFetch<{ code: string }>(`${I}/${encodeURIComponent(code)}/clone`, { method: "POST", body: { new_code } }),
  preview: (code: string, profile: string) => apiFetch<PreviewResult>(`${I}/${encodeURIComponent(code)}/preview`, { method: "POST", body: { profile } }),
  setText: (code: string, field: TextField, locale: string, value: string, expected_version: number) =>
    apiFetch<{ version: number; status: TStatus }>(`${I}/${encodeURIComponent(code)}/texts/${field}/${locale}`, {
      method: "PUT",
      body: { value, status: "draft", expected_version },
    }),
  bulkEdit: (codes: string[], patch: Partial<ItemData>, expected_versions: Record<string, number>) =>
    apiFetch(`${I}/bulk-edit`, { method: "POST", body: { codes, patch, expected_versions } }),
  bulkTranslationStatus: (codes: string[], locale: string, status: string) =>
    apiFetch<{ changed: number }>(`${I}/bulk-translation-status`, { method: "POST", body: { codes, locale, status } }),
  importItems: (format: "json" | "csv", content: string, dry_run: boolean) =>
    apiFetch<ImportReport>(`${I}/import`, { method: "POST", body: { format, content, dry_run } }),
  generator: (params: GeneratorParams, commit: boolean) =>
    apiFetch<GeneratorResult>(`${I}/generator`, { method: "POST", body: { params, commit } }),
  exportUrl: (f: Filters, format: "json" | "csv") => {
    const q = new URLSearchParams(Object.entries({ ...f, format }).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
    return `/api/v1${I}/export?${q.toString()}`;
  },
};

/** Client estimate of the requirement budget (server validator is authoritative). */
export function requirementPercent(meta: Pick<Meta, "base_stat_value" | "points_per_level" | "primary_stats">, level: number, reqs: Record<string, number>) {
  const budget = meta.base_stat_value * meta.primary_stats.length + (level - 1) * meta.points_per_level;
  const total = Object.values(reqs).reduce((a, b) => a + (b || 0), 0);
  return { budget, total, percent: budget ? (100 * total) / budget : 0 };
}

export function downloadText(filename: string, text: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
