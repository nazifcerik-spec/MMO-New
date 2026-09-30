"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/lib/api/errors";
import { adminItemsApi, downloadText, type Filters, type ImportReport, type ItemRow } from "@/lib/api/admin-items";
import { LOCALES } from "@/lib/i18n/config";

import { VirtualRows } from "./virtual-rows";

const ctl = "w-full rounded border border-border bg-bg px-2 py-1 text-sm";
const SAVED_KEY = "itemStudio.savedFilters";
const ROW_H = 36;

const SAVED_EVENT = "itemStudio.saved";

function readSaved(): string {
  try {
    return window.localStorage.getItem(SAVED_KEY) ?? "{}";
  } catch {
    return "{}";
  }
}

function subscribeSaved(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(SAVED_EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(SAVED_EVENT, cb);
  };
}

function writeSaved(next: Record<string, Filters>) {
  try {
    window.localStorage.setItem(SAVED_KEY, JSON.stringify(next));
  } catch {}
  window.dispatchEvent(new Event(SAVED_EVENT));
}

/** Saved filters are a per-viewer convenience (localStorage), read via an external-store subscription. */
function useSavedFilters(): Record<string, Filters> {
  const raw = useSyncExternalStore(subscribeSaved, readSaved, () => "{}");
  return useMemo(() => {
    try {
      return JSON.parse(raw) as Record<string, Filters>;
    } catch {
      return {};
    }
  }, [raw]);
}

const RARITY_CLASS: Record<string, string> = {
  worn: "text-muted",
  common: "",
  fine: "text-good",
  rare: "text-accent",
  epic: "text-epic",
  legendary: "text-legendary",
  mythic: "text-legendary font-semibold",
  relic: "text-bad font-semibold",
};

export function ItemStudio() {
  const t = useTranslations("itemStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const router = useRouter();
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["item-meta"], queryFn: adminItemsApi.meta });
  const [filters, setFilters] = useState<Filters>({ sort: "code", order: "asc" });
  const [qInput, setQInput] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const saved = useSavedFilters();
  const [showImport, setShowImport] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const id = window.setTimeout(() => setFilters((f) => ({ ...f, q: qInput || undefined })), 250);
    return () => window.clearTimeout(id);
  }, [qInput]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const list = useInfiniteQuery({
    queryKey: ["admin-items", filters],
    queryFn: ({ pageParam }) => adminItemsApi.list(filters, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.limit < last.total ? last.offset + last.limit : undefined),
  });
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const total = list.data?.pages[0]?.total ?? 0;
  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }));
  const toggleSort = (sort: string) => set({ sort, order: filters.sort === sort && filters.order === "asc" ? "desc" : "asc" });
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-items"] });

  const create = useMutation({
    mutationFn: (code: string) => adminItemsApi.create(code, { category: "material", tier: 0, min_level: 1, rarity: "common" }),
    onSuccess: (r) => {
      toast("success", t("created"));
      router.push(`/admin/items/${r.code}`);
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  const bulkL10n = useMutation({
    mutationFn: ({ locale, status }: { locale: string; status: string }) => adminItemsApi.bulkTranslationStatus([...checked], locale, status),
    onSuccess: (r) => {
      toast("success", t("bulkDone", { n: r.changed }));
      refresh();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  const bulkEdit = useMutation({
    mutationFn: async (patch: Record<string, unknown>) => {
      const versions: Record<string, number> = {};
      for (const code of checked) versions[code] = (await adminItemsApi.inspector(code)).edit_version;
      return adminItemsApi.bulkEdit([...checked], patch, versions);
    },
    onSuccess: () => {
      toast("success", t("bulkDone", { n: checked.size }));
      refresh();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });

  const categories = meta.data?.categories ?? [];
  const moveSelection = (delta: number) => {
    const idx = rows.findIndex((r) => r.code === selected);
    const next = rows[Math.min(rows.length - 1, Math.max(0, idx + delta))];
    if (next) setSelected(next.code);
  };

  return (
    <div className="grid gap-3 lg:grid-cols-[14rem_minmax(0,1fr)_20rem]" data-testid="item-studio">
      {/* Left: filters + category tree */}
      <aside className="space-y-2 text-sm" aria-label={t("filters")}>
        <label className="block">
          {t("search")}
          <input ref={searchRef} className={ctl} value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder={t("searchHint")} data-testid="studio-search" />
        </label>
        <nav aria-label={t("categories")}>
          <ul className="space-y-0.5">
            <li>
              <button type="button" className={!filters.category ? "font-semibold" : ""} onClick={() => set({ category: undefined, slot: undefined })}>
                {t("allCategories")}
              </button>
            </li>
            {categories.map((c) => (
              <li key={c}>
                <button type="button" data-testid={`cat-${c}`} className={filters.category === c ? "font-semibold text-accent" : ""} onClick={() => set({ category: c, slot: undefined })}>
                  {t(`category.${c}`)}
                </button>
                {filters.category === c && meta.data?.slots_by_category[c] ? (
                  <ul className="ml-3">
                    {meta.data.slots_by_category[c].map((s) => (
                      <li key={s}>
                        <button type="button" className={filters.slot === s ? "text-accent" : "text-muted"} onClick={() => set({ slot: filters.slot === s ? undefined : s })}>
                          {t(`slot.${s}`)}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        </nav>
        <label className="block">
          {t("tier")}
          <select className={ctl} value={filters.tier ?? ""} onChange={(e) => set({ tier: e.target.value === "" ? undefined : Number(e.target.value) })}>
            <option value="">{t("any")}</option>
            {Array.from({ length: 11 }, (_, i) => (
              <option key={i} value={i}>
                T{i}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          {t("rarity")}
          <select className={ctl} value={filters.rarity ?? ""} onChange={(e) => set({ rarity: e.target.value || undefined })} data-testid="filter-rarity">
            <option value="">{t("any")}</option>
            {(meta.data?.rarities ?? []).map((r) => (
              <option key={r} value={r}>
                {t(`rarityName.${r}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          {t("status")}
          <select className={ctl} value={filters.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
            <option value="">{t("any")}</option>
            {["draft", "published", "disabled", "archived"].map((s) => (
              <option key={s} value={s}>
                {t(`statusName.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          {t("family")}
          <select className={ctl} value={filters.family ?? ""} onChange={(e) => set({ family: e.target.value || undefined })}>
            <option value="">{t("any")}</option>
            {[...(meta.data?.weapon_families.map((w) => w.code) ?? []), ...(meta.data?.armor_families ?? [])].map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          {t("classTag")}
          <select className={ctl} value={filters.class_tag ?? ""} onChange={(e) => set({ class_tag: e.target.value || undefined })}>
            <option value="">{t("any")}</option>
            {(meta.data?.class_tags ?? []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          {t("translation")}
          <select
            className={ctl}
            data-testid="filter-translation"
            value={filters.translation ?? ""}
            onChange={(e) => set({ translation: (e.target.value || undefined) as Filters["translation"] })}
          >
            <option value="">{t("any")}</option>
            <option value="complete">{t("translationComplete")}</option>
            <option value="incomplete">{t("translationIncomplete")}</option>
          </select>
        </label>
        <div className="space-y-1 border-t border-border pt-2">
          <p className="font-semibold">{t("savedFilters")}</p>
          {Object.keys(saved).map((name) => (
            <div key={name} className="flex items-center gap-1">
              <button type="button" className="underline" onClick={() => setFilters(saved[name])}>
                {name}
              </button>
              <button
                type="button"
                aria-label={t("deleteSaved", { name })}
                onClick={() => {
                  const next = { ...saved };
                  delete next[name];
                  writeSaved(next);
                }}
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            className="text-xs underline"
            onClick={() => {
              const name = window.prompt(t("saveFilterPrompt"));
              if (!name) return;
              writeSaved({ ...saved, [name]: filters });
            }}
          >
            {t("saveFilter")}
          </button>
        </div>
      </aside>

      {/* Middle: toolbar + virtualized table */}
      <section className="min-w-0 space-y-2" aria-label={t("items")}>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono text-xs" data-testid="studio-total">
            {t("total", { n: total })}
          </span>
          <button
            type="button"
            data-testid="studio-new"
            className="rounded bg-accent px-2 py-1 font-semibold text-bg"
            onClick={() => {
              const code = window.prompt(t("newCodePrompt"));
              if (code) create.mutate(code.trim());
            }}
          >
            {t("new")}
          </button>
          <Link href="/admin/items/generator" className="underline" data-testid="open-generator">
            {t("generator")}
          </Link>
          <a className="underline" href={adminItemsApi.exportUrl(filters, "csv")} download>
            {t("exportCsv")}
          </a>
          <a className="underline" href={adminItemsApi.exportUrl(filters, "json")} download>
            {t("exportJson")}
          </a>
          <button type="button" className="underline" onClick={() => setShowImport(!showImport)} data-testid="open-import">
            {t("import")}
          </button>
          {checked.size ? (
            <span className="ml-auto flex flex-wrap items-center gap-1 text-xs" data-testid="bulk-bar">
              {t("selected", { n: checked.size })}
              <select
                aria-label={t("bulkTranslation")}
                className="rounded border border-border bg-bg px-1"
                defaultValue=""
                onChange={(e) => {
                  const [locale, status] = e.target.value.split(":");
                  if (locale) bulkL10n.mutate({ locale, status });
                  e.target.value = "";
                }}
              >
                <option value="">{t("bulkTranslation")}</option>
                {LOCALES.flatMap((l) =>
                  ["draft", "reviewed"].map((s) => (
                    <option key={`${l}:${s}`} value={`${l}:${s}`}>
                      {l} → {t(`tstatus.${s}`)}
                    </option>
                  )),
                )}
              </select>
              <button
                type="button"
                className="underline"
                onClick={() => {
                  const v = window.prompt(t("bulkVendorPrompt"));
                  if (v !== null && v !== "" && Number.isFinite(Number(v))) bulkEdit.mutate({ vendor_value: Math.max(0, Math.round(Number(v))) });
                }}
              >
                {t("bulkVendor")}
              </button>
              <button type="button" className="underline" onClick={() => bulkEdit.mutate({ tradeable: false })}>
                {t("bulkUntradeable")}
              </button>
              <button type="button" className="underline" onClick={() => setChecked(new Set())}>
                {t("clearSelection")}
              </button>
            </span>
          ) : null}
        </div>
        {showImport ? <ImportPanel onDone={refresh} /> : null}
        <div className="grid grid-cols-[1.5rem_minmax(8rem,1.4fr)_5rem_3rem_4rem_5.5rem_5rem_4.5rem] gap-1 border-b border-border px-1 text-xs font-semibold" role="row">
          <span />
          {(
            [
              ["code", t("colName")],
              ["category", t("colCategory")],
              ["tier", "T"],
              ["min_level", t("colLevel")],
              ["rarity", t("rarity")],
              ["status", t("status")],
            ] as const
          ).map(([k, label]) => (
            <button key={k} type="button" role="columnheader" className="text-left" onClick={() => toggleSort(k)} aria-sort={filters.sort === k ? (filters.order === "asc" ? "ascending" : "descending") : "none"}>
              {label}
              {filters.sort === k ? (filters.order === "asc" ? " ▲" : " ▼") : ""}
            </button>
          ))}
          <span>{t("colL10n")}</span>
        </div>
        {list.isLoading ? <p>{t("loading")}</p> : null}
        <VirtualRows<ItemRow>
          rows={rows}
          rowHeight={ROW_H}
          height={560}
          label={t("items")}
          onEndReached={() => list.hasNextPage && !list.isFetchingNextPage && list.fetchNextPage()}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "j") moveSelection(1);
            if (e.key === "ArrowUp" || e.key === "k") moveSelection(-1);
            if (e.key === "Enter" && selected) router.push(`/admin/items/${selected}`);
          }}
          render={(r) => (
            <div
              data-testid={`row-${r.code}`}
              aria-selected={selected === r.code}
              onClick={() => setSelected(r.code)}
              onDoubleClick={() => router.push(`/admin/items/${r.code}`)}
              className={`grid h-full cursor-pointer grid-cols-[1.5rem_minmax(8rem,1.4fr)_5rem_3rem_4rem_5.5rem_5rem_4.5rem] items-center gap-1 border-b border-border px-1 text-xs ${selected === r.code ? "bg-accent/15" : ""}`}
            >
              <input
                type="checkbox"
                aria-label={t("select", { code: r.code })}
                checked={checked.has(r.code)}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => {
                  const next = new Set(checked);
                  if (e.target.checked) next.add(r.code);
                  else next.delete(r.code);
                  setChecked(next);
                }}
              />
              <span className="truncate" title={r.code}>
                <span className={RARITY_CLASS[r.rarity] ?? ""}>{r.name}</span> <span className="text-muted">{r.code}</span>
              </span>
              <span className="truncate">{t(`category.${r.category}`)}</span>
              <span>T{r.tier}</span>
              <span>{r.min_level}</span>
              <span className={RARITY_CLASS[r.rarity] ?? ""}>{t(`rarityName.${r.rarity}`)}</span>
              <span>
                {t(`statusName.${r.status}`)}
                {r.has_pending_changes ? " •" : ""}
              </span>
              <span className="font-mono" aria-label={t("translationState")}>
                {LOCALES.map((l) => (r.translations[l] === "missing" ? "·" : r.translations[l] === "reviewed" || r.translations[l] === "published" ? "●" : "○")).join("")}
              </span>
            </div>
          )}
        />
      </section>

      {/* Right: quick inspector */}
      <aside aria-label={t("inspector")} className="text-sm">
        {selected ? <QuickInspector code={selected} /> : <p className="text-muted">{t("pickItem")}</p>}
      </aside>
    </div>
  );
}

function QuickInspector({ code }: { code: string }) {
  const t = useTranslations("itemStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const router = useRouter();
  const q = useQuery({ queryKey: ["item-inspector", code], queryFn: () => adminItemsApi.inspector(code) });
  const clone = useMutation({
    mutationFn: (newCode: string) => adminItemsApi.clone(code, newCode),
    onSuccess: (r) => router.push(`/admin/items/${r.code}`),
    onError: (e) => toast("error", errorMessage(e)),
  });
  if (q.isLoading) return <p>{t("loading")}</p>;
  if (!q.data) return <p role="alert">{t("loadError")}</p>;
  const d = q.data.data;
  const errors = q.data.issues.filter((i) => i.level === "error").length;
  return (
    <div className="space-y-2 rounded border border-border bg-panel p-3" data-testid="quick-inspector">
      <h2 className="font-semibold">{q.data.texts.name.en.value || code}</h2>
      <p className="font-mono text-xs text-muted">
        {code} · r{q.data.revision_no} · {t(`statusName.${q.data.status}`)}
      </p>
      <dl className="grid grid-cols-2 gap-x-2 text-xs">
        <dt className="text-muted">{t("colCategory")}</dt>
        <dd>
          {t(`category.${d.category}`)}
          {d.slot ? ` / ${t(`slot.${d.slot}`)}` : ""}
        </dd>
        <dt className="text-muted">{t("tier")}</dt>
        <dd>
          T{d.tier} · Lv{d.min_level}
        </dd>
        <dt className="text-muted">{t("rarity")}</dt>
        <dd>{t(`rarityName.${d.rarity}`)}</dd>
        <dt className="text-muted">{t("requirementBudget")}</dt>
        <dd>{q.data.requirement_budget.percent}%</dd>
        <dt className="text-muted">{t("baseStats")}</dt>
        <dd>{d.base_stats.map((s) => `${s.stat} ${s.amount}`).join(", ") || "—"}</dd>
      </dl>
      <p className={errors ? "text-bad" : "text-good"} data-testid="inspector-validation">
        {errors ? t("errorsCount", { n: errors }) : t("valid")}
        {q.data.issues.length - errors ? ` · ${t("warningsCount", { n: q.data.issues.length - errors })}` : ""}
      </p>
      <p className="text-xs">
        {LOCALES.map((l) => `${l}: ${t(`tstatus.${q.data!.texts.name[l].status}`)}`).join(" · ")}
      </p>
      <div className="flex gap-2">
        <Link href={`/admin/items/${code}`} className="rounded bg-accent px-2 py-1 font-semibold text-bg" data-testid="open-editor">
          {t("openEditor")}
        </Link>
        <button
          type="button"
          className="underline"
          onClick={() => {
            const newCode = window.prompt(t("clonePrompt"), `${code}_copy`);
            if (newCode) clone.mutate(newCode.trim());
          }}
        >
          {t("clone")}
        </button>
      </div>
    </div>
  );
}

function ImportPanel({ onDone }: { onDone: () => void }) {
  const t = useTranslations("itemStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const [format, setFormat] = useState<"json" | "csv">("json");
  const [text, setText] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);
  const run = useMutation({
    mutationFn: (dry: boolean) => adminItemsApi.importItems(format, text, dry),
    onSuccess: (r) => {
      setReport(r);
      if (r.summary.committed) {
        toast("success", t("importCommitted", { n: r.summary.rows }));
        onDone();
      }
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  return (
    <div className="space-y-2 rounded border border-border bg-panel p-2 text-sm" data-testid="import-panel">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label={t("format")} value={format} onChange={(e) => setFormat(e.target.value as "json" | "csv")} className="rounded border border-border bg-bg px-1">
          <option value="json">JSON</option>
          <option value="csv">CSV</option>
        </select>
        <input
          type="file"
          accept=".json,.csv"
          aria-label={t("importFile")}
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) {
              setText(await f.text());
              setFormat(f.name.endsWith(".csv") ? "csv" : "json");
            }
          }}
        />
      </div>
      <textarea aria-label={t("importContent")} className={`${ctl} h-24 font-mono text-xs`} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="flex gap-2">
        <button type="button" data-testid="import-dry-run" disabled={!text || run.isPending} onClick={() => run.mutate(true)} className="rounded border border-border px-2">
          {t("dryRun")}
        </button>
        <button
          type="button"
          disabled={!report || report.summary.errors > 0 || !report.summary.dry_run || run.isPending}
          onClick={() => run.mutate(false)}
          className="rounded bg-accent px-2 font-semibold text-bg disabled:opacity-50"
        >
          {t("commitImport")}
        </button>
        {report ? (
          <button type="button" className="underline" onClick={() => downloadText("import-report.json", JSON.stringify(report, null, 2))}>
            {t("downloadReport")}
          </button>
        ) : null}
      </div>
      {report ? (
        <div data-testid="import-report" className="text-xs">
          <p>{t("importSummary", { rows: report.summary.rows, creates: report.summary.creates, updates: report.summary.updates, errors: report.summary.errors, warnings: report.summary.warnings })}</p>
          <ul className="max-h-40 overflow-y-auto">
            {report.report
              .filter((r) => r.issues.length)
              .map((r) => (
                <li key={r.code}>
                  <span className="font-mono">{r.code}</span>: {r.issues.map((i) => `${i.level === "error" ? "⛔" : "⚠"} ${i.code}`).join(", ")}
                </li>
              ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
