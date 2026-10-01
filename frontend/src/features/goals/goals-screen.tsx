"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/lib/api/errors";
import { goalsApi, STATUS_RARITY_TEXT, type Objective, type QuestView } from "@/lib/api/goals";

type Tab = "quests" | "achievements" | "titles" | "collections";

/** Long-term goals: quest log (graph), achievements + prestige, title selection and collections. */
export function GoalsScreen({ characterId }: { characterId: number }) {
  const t = useTranslations("goals");
  const [tab, setTab] = useState<Tab>("quests");
  return (
    <div className="space-y-3">
      <div role="tablist" className="flex flex-wrap gap-2 text-sm">
        {(["quests", "achievements", "titles", "collections"] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} data-testid={`goals-tab-${k}`} onClick={() => setTab(k)} className={`rounded px-2 py-1 ${tab === k ? "bg-accent text-bg" : "border border-border"}`}>
            {t(`tab.${k}`)}
          </button>
        ))}
      </div>
      {tab === "quests" ? <Quests characterId={characterId} /> : tab === "achievements" ? <Achievements characterId={characterId} /> : tab === "titles" ? <Titles characterId={characterId} /> : <Collections characterId={characterId} />}
    </div>
  );
}

function useRun(keys: (string | number)[][]) {
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  return (fn: () => Promise<unknown>, ok?: string) =>
    fn()
      .then(() => {
        if (ok) toast("success", ok);
        for (const k of keys) qc.invalidateQueries({ queryKey: k });
      })
      .catch((e) => toast("error", errorMessage(e)));
}

function ObjectiveLine({ o, value }: { o: Objective; value: number }) {
  const t = useTranslations("goals");
  const target = o.kind === "level" || o.kind === "profession" ? (o.level ?? 1) : (o.count ?? 1);
  const what = t(`objective.${o.kind}`, { zone: o.zone ?? t("anywhere"), item: o.template_code ?? "", profession: o.profession ?? "", action: o.action ? t(`action.${o.action}`) : "" });
  return (
    <li className={value >= target ? "text-good" : ""}>
      {what} — {Math.min(value, target)}/{target}
    </li>
  );
}

function QuestCard({ q, actions }: { q: QuestView; actions?: React.ReactNode }) {
  const t = useTranslations("goals");
  return (
    <li className="rounded border border-border p-2 text-sm" data-testid={`quest-${q.code}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{q.name}</span>
        <span className="text-xs text-muted">
          {t(`type.${q.type}`)} · Lv {q.min_level}
          {q.repeatable ? ` · ${t("repeatable")}` : ""}
        </span>
        <span className="ml-auto flex gap-2 text-xs">{actions}</span>
      </div>
      <ul className="text-xs">
        {q.objectives.map((o, i) => (
          <ObjectiveLine key={i} o={o} value={q.progress[i] ?? 0} />
        ))}
      </ul>
      <p className="text-xs text-muted">
        {t("rewards", { xp: String(q.rewards.xp ?? 0), gold: String(q.rewards.gold ?? 0) })}
        {q.rewards.title_code ? ` · ${t("rewardTitle")}` : ""}
      </p>
    </li>
  );
}

function Quests({ characterId }: { characterId: number }) {
  const t = useTranslations("goals");
  const tc = useTranslations("common");
  const q = useQuery({ queryKey: ["quests", characterId], queryFn: () => goalsApi.quests(characterId) });
  const run = useRun([["quests", characterId], ["progression", characterId], ["achievements", characterId]]);
  if (q.isLoading) return <p>{tc("loading")}</p>;
  if (!q.data) return <p role="alert">{tc("error")}</p>;
  const log = q.data;
  return (
    <div className="grid gap-3 @3xl:grid-cols-2">
      <section aria-label={t("active")}>
        <h2 className="font-semibold">{t("active")}</h2>
        <ul className="space-y-1">
          {log.active.map((x) => (
            <QuestCard
              key={x.code}
              q={x}
              actions={
                <>
                  <button type="button" data-testid={`claim-${x.code}`} className="rounded bg-accent px-2 font-semibold text-bg" onClick={() => run(() => goalsApi.claim(characterId, x.code), t("claimed"))}>
                    {t("claim")}
                  </button>
                  <button type="button" className="underline" onClick={() => run(() => goalsApi.abandon(characterId, x.code))}>
                    {t("abandon")}
                  </button>
                </>
              }
            />
          ))}
          {!log.active.length ? <li className="text-sm text-muted">{t("noActive")}</li> : null}
        </ul>
      </section>
      <section aria-label={t("available")}>
        <h2 className="font-semibold">{t("available")}</h2>
        <ul className="space-y-1">
          {log.available.map((x) => (
            <QuestCard
              key={x.code}
              q={x}
              actions={
                <button type="button" data-testid={`accept-${x.code}`} className="rounded bg-accent px-2 font-semibold text-bg" onClick={() => run(() => goalsApi.accept(characterId, x.code), t("accepted"))}>
                  {t("accept")}
                </button>
              }
            />
          ))}
        </ul>
        <details className="mt-2 text-sm">
          <summary>{t("lockedCount", { n: log.locked.length })}</summary>
          <ul className="space-y-1 opacity-70">
            {log.locked.map((x) => (
              <QuestCard key={x.code} q={x} />
            ))}
          </ul>
        </details>
        <p className="mt-2 text-xs text-muted">{t("completedCount", { n: log.completed.length })}</p>
      </section>
    </div>
  );
}

function Achievements({ characterId }: { characterId: number }) {
  const t = useTranslations("goals");
  const q = useQuery({ queryKey: ["achievements", characterId], queryFn: () => goalsApi.achievements(characterId) });
  if (!q.data) return null;
  const a = q.data;
  return (
    <section className="space-y-2" aria-label={t("tab.achievements")}>
      <p className="text-sm" data-testid="prestige">
        <span className={STATUS_RARITY_TEXT[a.prestige.rarity]}>{t(`rarity.${a.prestige.rarity}`)}</span> · {t("prestige", { points: String(a.prestige.points) })}
        {a.prestige.next ? ` · ${t("nextRank", { points: String(a.prestige.next.points) })}` : ""}
      </p>
      <ul className="grid gap-1 @xl:grid-cols-2">
        {a.achievements.map((x) => (
          <li key={x.code} className={`rounded border border-border p-2 text-sm ${x.unlocked_at ? "" : "opacity-60"}`} data-testid={`achievement-${x.code}`}>
            <span className={`font-semibold ${STATUS_RARITY_TEXT[x.rarity]}`}>{x.name}</span>
            <span className="ml-2 text-xs text-muted">
              {t(`rarity.${x.rarity}`)} · {x.points} pts
            </span>
            <div className="mt-1 h-1.5 rounded bg-border" role="progressbar" aria-valuemin={0} aria-valuemax={x.threshold} aria-valuenow={x.value}>
              <div className="h-1.5 rounded bg-accent" style={{ width: `${Math.round((100 * x.value) / x.threshold)}%` }} />
            </div>
            <p className="text-xs text-muted">
              {t(`counter.${x.counter}`)}: {x.value.toLocaleString()}/{x.threshold.toLocaleString()}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Titles({ characterId }: { characterId: number }) {
  const t = useTranslations("goals");
  const q = useQuery({ queryKey: ["titles", characterId], queryFn: () => goalsApi.titles(characterId) });
  const run = useRun([["titles", characterId]]);
  if (!q.data) return null;
  return (
    <fieldset className="space-y-1" data-testid="title-picker">
      <legend className="font-semibold">{t("chooseTitle")}</legend>
      <p className="text-xs text-muted">{t("rarityNote")}</p>
      {q.data.titles.map((x) => (
        <label key={x.ref} className="flex items-center gap-2 text-sm">
          <input type="radio" name="title" checked={q.data!.selected === x.ref} onChange={() => run(() => goalsApi.selectTitle(characterId, x.ref), t("titleSelected"))} />
          <span className={STATUS_RARITY_TEXT[x.rarity]}>{x.name}</span>
          <span className="text-xs text-muted">
            {t(`titleKind.${x.kind}`)} · {t(`rarity.${x.rarity}`)}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

function Collections({ characterId }: { characterId: number }) {
  const t = useTranslations("goals");
  const q = useQuery({ queryKey: ["collections", characterId], queryFn: () => goalsApi.collections(characterId) });
  if (!q.data) return null;
  return (
    <section className="space-y-2" aria-label={t("tab.collections")} data-testid="collections">
      <p className="text-sm">{t("collected", { owned: q.data.owned, total: q.data.total })}</p>
      {Object.entries(q.data.groups).map(([g, list]) => (
        <div key={g}>
          <h3 className="text-xs font-semibold uppercase text-muted">{g}</h3>
          <ul className="flex flex-wrap gap-1">
            {list.map((i) => (
              <li key={i.template_code} title={i.name} className={`rounded border px-1 text-xs ${i.owned ? "border-good" : "border-border opacity-50"}`}>
                {i.owned ? i.name : "???"}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
