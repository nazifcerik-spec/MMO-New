"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { EffectList } from "@/components/effects/effect-text";
import { ApiError } from "@/lib/api/client";
import { useErrorMessage } from "@/lib/api/errors";
import { nodeLockReason, talentApi, type TalentsView } from "@/lib/api/talents";

export function TalentTrees({ characterId }: { characterId: number }) {
  const t = useTranslations("talents");
  const tc = useTranslations("common");
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const key = ["talents", characterId];
  const { data: view, isLoading, isError } = useQuery({ queryKey: key, queryFn: () => talentApi.view(characterId) });
  const [pending, setPending] = useState<Record<string, number>>({});
  const refresh = (v?: TalentsView) => {
    setPending({});
    if (v) qc.setQueryData(key, v);
    else qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["progression", characterId] });
  };
  const allocate = useMutation({
    mutationFn: () => {
      const merged: Record<string, number> = {};
      for (const tree of view!.trees) for (const n of tree.nodes) if (pending[n.code]) merged[n.code] = pending[n.code];
      return talentApi.allocate(characterId, merged, view!.version);
    },
    onSuccess: (v) => refresh(v),
    onError: (e) => e instanceof ApiError && e.code === "version_conflict" && refresh(),
  });
  const reset = useMutation({ mutationFn: () => talentApi.reset(characterId), onSuccess: () => refresh() });

  if (isLoading) return <p>{tc("loading")}</p>;
  if (isError || !view) return <p role="alert">{tc("error")}</p>;
  const rankOf = (code: string, base: number) => pending[code] ?? base;
  const pendingSpent = view.trees.flatMap((tr) => tr.nodes).reduce((s, n) => s + rankOf(n.code, n.rank), 0);
  const remaining = view.points_available - pendingSpent;
  const err = allocate.error ?? reset.error;
  const q = view.reset_quote;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono" data-testid="talent-points">
          {t("points", { spent: pendingSpent, available: view.points_available, max: view.total_max })}
        </span>
        <button
          type="button"
          disabled={pendingSpent === view.points_spent || allocate.isPending}
          onClick={() => allocate.mutate()}
          className="rounded bg-accent px-3 py-1 text-sm font-semibold text-bg disabled:opacity-50"
        >
          {t("apply")}
        </button>
        <button type="button" onClick={() => setPending({})} className="text-sm underline">
          {t("clear")}
        </button>
        {view.points_spent > 0 ? (
          <span className="ml-auto flex items-center gap-2 text-xs text-muted">
            {t("resetCost", {
              gold: q.gold,
              material: q.material_code ? t("resetMaterial", { qty: q.material_qty, material: q.material_code }) : "",
            })}
            <button type="button" className="underline" onClick={() => window.confirm(t("resetConfirm")) && reset.mutate()}>
              {t("reset")}
            </button>
          </span>
        ) : null}
      </div>
      {err ? (
        <p role="alert" className="text-sm text-bad" data-testid="talent-error">
          {errorMessage(err)}
        </p>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-3">
        {view.trees.map((tree) => {
          const treeSpent = tree.nodes.reduce((s, n) => s + rankOf(n.code, n.rank), 0);
          const tiers = [...new Set(tree.nodes.map((n) => n.tier))].sort((a, b) => a - b);
          return (
            <section key={tree.code} aria-label={tree.name} data-testid={`tree-${tree.code}`} className="rounded border border-border bg-panel p-3">
              <header className="mb-2 flex items-baseline justify-between gap-2">
                <h2 className="font-semibold">{tree.name}</h2>
                <span className="font-mono text-xs">{t("treeSpent", { spent: treeSpent, max: view.per_tree_max })}</span>
              </header>
              <p className="mb-2 text-xs text-muted">{tree.focus}</p>
              {tiers.map((tier) => (
                <div key={tier} className="mb-2">
                  <p className="text-[11px] uppercase text-muted">{tier === 6 ? t("capstone") : t("tier", { tier })}</p>
                  <ul className="space-y-1">
                    {tree.nodes
                      .filter((n) => n.tier === tier)
                      .map((n) => {
                        const rank = rankOf(n.code, n.rank);
                        const lock = nodeLockReason(n, tree, pending, view.level);
                        const canAdd = !lock && rank < n.max_rank && remaining > 0 && treeSpent < view.per_tree_max;
                        return (
                          <li
                            key={n.code}
                            data-testid={`node-${n.code}`}
                            className={`rounded border p-2 text-sm ${n.is_capstone ? "border-legendary" : "border-border"} ${lock ? "opacity-60" : ""}`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className={n.is_capstone ? "font-semibold text-legendary" : ""}>{n.name}</span>
                              <span className="flex items-center gap-1 font-mono text-xs">
                                {t("rank", { rank, max: n.max_rank })}
                                <button
                                  type="button"
                                  aria-label={t("increase", { name: n.name })}
                                  disabled={!canAdd}
                                  onClick={() => setPending({ ...pending, [n.code]: rank + 1 })}
                                  className="h-6 w-6 rounded border border-border disabled:opacity-40"
                                >
                                  +
                                </button>
                              </span>
                            </div>
                            {n.description ? <p className="text-xs text-muted">{n.description}</p> : null}
                            <EffectList effects={n.effects} labels={view.labels} />
                            {lock === "points" ? (
                              <p className="text-[11px] text-muted">{t("needsPoints", { points: n.required_points_in_tree })}</p>
                            ) : lock === "level" ? (
                              <p className="text-[11px] text-muted">{t("needsLevel", { level: n.required_level })}</p>
                            ) : null}
                          </li>
                        );
                      })}
                  </ul>
                </div>
              ))}
            </section>
          );
        })}
      </div>
    </div>
  );
}
