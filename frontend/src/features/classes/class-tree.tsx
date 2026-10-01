"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { classApi, type ClassView } from "@/lib/api/classes";
import { useErrorMessage } from "@/lib/api/errors";

function StageTimeline({ view }: { view: ClassView }) {
  const t = useTranslations("classes");
  return (
    <ol className="flex flex-wrap gap-2" aria-label={t("title")} data-testid="class-stages">
      {view.stages.map((s) => {
        const state = s.completed_at ? "completed" : s.unlocked ? "unlocked" : "locked";
        return (
          <li
            key={s.stage}
            data-state={state}
            className={`rounded border px-2 py-1 text-xs ${
              state === "completed" ? "border-good text-good" : state === "unlocked" ? "border-accent" : "border-border text-muted"
            }`}
          >
            <span className="font-semibold">{s.name}</span> · {t("stageAt", { level: s.min_level })} · {t(state)}
          </li>
        );
      })}
    </ol>
  );
}

export function ClassTree({ characterId }: { characterId: number }) {
  const t = useTranslations("classes");
  const tc = useTranslations("common");
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const key = ["class", characterId];
  const { data: view, isLoading, isError } = useQuery({ queryKey: key, queryFn: () => classApi.view(characterId) });
  const onSuccess = (v: ClassView) => {
    qc.setQueryData(key, v);
    qc.invalidateQueries({ queryKey: ["progression", characterId] });
  };
  const promote = useMutation({ mutationFn: (code: string) => classApi.promote(characterId, code), onSuccess });
  const specialize = useMutation({ mutationFn: (code: string) => classApi.specialize(characterId, code), onSuccess });

  if (isLoading) return <p>{tc("loading")}</p>;
  if (isError || !view) return <p role="alert">{tc("error")}</p>;
  const cls = view.base_class;
  const promotionLevel = view.stages.find((s) => s.stage === "promotion")?.min_level ?? 100;
  const specLevel = view.stages.find((s) => s.stage === "specialization")?.min_level ?? 300;
  const err = promote.error ?? specialize.error;

  return (
    <div className="space-y-4">
      <p className="font-mono text-lg" data-testid="class-title">
        {t("classTitle", { title: view.class_title })}
      </p>
      <StageTimeline view={view} />
      {err ? (
        <p role="alert" className="text-sm text-bad">
          {errorMessage(err)}
        </p>
      ) : null}
      <section className="rounded border border-border bg-panel p-4" aria-label={cls.name}>
        <h2 className="text-center font-mono font-bold">{cls.name}</h2>
        <div className="mt-4 grid gap-4 @xl:grid-cols-2" data-testid="class-tree">
          {cls.branches.map((b) => {
            const chosen = view.branch_code === b.code;
            const otherChosen = view.branch_code !== null && !chosen;
            return (
              <div
                key={b.code}
                data-testid={`branch-${b.code}`}
                className={`rounded border p-3 ${chosen ? "border-accent" : "border-border"} ${otherChosen ? "opacity-50" : ""}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    <span className="font-semibold">{b.name}</span> <span className="text-xs text-muted">{b.role}</span>
                  </span>
                  {chosen ? (
                    <span className="text-xs text-good">{t("current")}</span>
                  ) : view.can_promote ? (
                    <button
                      type="button"
                      className="rounded bg-accent px-2 py-0.5 text-xs font-semibold text-bg"
                      onClick={() => window.confirm(t("confirmPromote", { name: b.name })) && promote.mutate(b.code)}
                    >
                      {t("promote")}
                    </button>
                  ) : view.branch_code === null ? (
                    <span className="text-xs text-muted">{t("requiresLevel", { level: promotionLevel })}</span>
                  ) : null}
                </div>
                <ul className="mt-2 space-y-1 border-l border-border pl-3">
                  {b.specializations.map((s) => {
                    const specChosen = view.specialization_code === s.code;
                    return (
                      <li key={s.code} data-testid={`spec-${s.code}`} className="flex items-center justify-between gap-2 text-sm">
                        <span className={specChosen ? "text-accent" : ""}>
                          {s.name} <span className="text-xs text-muted">{s.role}</span>
                        </span>
                        {specChosen ? (
                          <span className="text-xs text-good">{t("current")}</span>
                        ) : chosen && view.can_specialize ? (
                          <button
                            type="button"
                            className="rounded border border-accent px-2 py-0.5 text-xs"
                            onClick={() => window.confirm(t("confirmSpecialize", { name: s.name })) && specialize.mutate(s.code)}
                          >
                            {t("specialize")}
                          </button>
                        ) : chosen && !view.specialization_code ? (
                          <span className="text-xs text-muted">{t("requiresLevel", { level: specLevel })}</span>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      </section>
      <p className="text-xs text-muted">
        {view.path_change.free
          ? t("pathChangeFree")
          : t("pathChange", { gold: view.path_change.branch_change_gold, spec: view.path_change.spec_change_gold })}
      </p>
    </div>
  );
}
