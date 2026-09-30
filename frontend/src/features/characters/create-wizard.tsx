"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { EffectList, type EffectData } from "@/components/effects/effect-text";
import { characterApi, type OptionCard } from "@/lib/api/auth";
import type { ClassCard } from "@/lib/api/classes";
import { useErrorMessage } from "@/lib/api/errors";

const STEPS = ["stepName", "stepRace", "stepClass", "stepConfirm"] as const;

function ClassDetails({ option }: { option: OptionCard }) {
  const t = useTranslations("classes");
  const card = option as unknown as Partial<ClassCard>;
  if (!card.branches) return null;
  return (
    <span className="block space-y-0.5 text-xs text-muted">
      <span className="block text-sm text-fg">
        {card.category_name} · {card.role}
      </span>
      {card.stat_weights ? <span className="block">{t("stats", card.stat_weights)}</span> : null}
      <span className="block">{t("resources", { list: (card.resources ?? []).join(", ") })}</span>
      <span className="block">{t("weapons", { list: (card.weapons ?? []).join(", ") })}</span>
      <span className="block">{t("paths", { list: card.branches.map((b) => b.name).join(" / ") })}</span>
      {card.solo_accord ? (
        <span className="block">{t("soloAccord", { percent: card.solo_accord.conversion_percent })}</span>
      ) : null}
    </span>
  );
}

function OptionDetails({ option }: { option: OptionCard }) {
  const t = useTranslations("races");
  const labels = (option.labels as Record<string, string>) ?? {};
  const effects = (option.effects as EffectData[]) ?? [];
  const affinity = (option.affinity as string[]) ?? [];
  return (
    <span className="mt-2 block space-y-1">
      {option.trait_name ? (
        <span className="block text-sm">
          <span className="text-accent">{String(option.trait_name)}</span>
          {option.title ? <span className="text-muted"> · {t("raceTitle", { title: String(option.title) })}</span> : null}
        </span>
      ) : null}
      {effects.length ? <EffectList effects={effects} labels={labels} /> : null}
      <ClassDetails option={option} />
      {affinity.length ? (
        <span className="block text-xs text-muted">
          {t("affinity", { classes: affinity.map((c) => labels[`class.${c}.name`] ?? c).join(", ") })}
        </span>
      ) : null}
    </span>
  );
}

function OptionGrid({
  items,
  selected,
  onSelect,
  label,
}: {
  items: OptionCard[];
  selected: number | null;
  onSelect: (id: number) => void;
  label: string;
}) {
  const t = useTranslations("wizard");
  if (items.length === 0)
    return (
      <p className="text-muted" data-testid="no-options">
        {t("noOptions")}
      </p>
    );
  return (
    <div role="radiogroup" aria-label={label} className="grid gap-2 sm:grid-cols-2">
      {items.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={selected === o.id}
          data-testid={`option-${o.code}`}
          onClick={() => onSelect(o.id)}
          className={`rounded border p-3 text-left ${selected === o.id ? "border-accent" : "border-border"} bg-panel`}
        >
          <span className="font-semibold">{o.name}</span>
          {o.description ? <span className="mt-1 block text-sm text-muted">{o.description}</span> : null}
          <OptionDetails option={o} />
        </button>
      ))}
    </div>
  );
}

export function CreateCharacterWizard() {
  const t = useTranslations("wizard");
  const tr = useTranslations("races");
  const tc = useTranslations("common");
  const router = useRouter();
  const qc = useQueryClient();
  const errorMessage = useErrorMessage();
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [raceId, setRaceId] = useState<number | null>(null);
  const [classId, setClassId] = useState<number | null>(null);

  const options = useQuery({ queryKey: ["character-options"], queryFn: characterApi.options });
  const nameCheck = useMutation({ mutationFn: characterApi.nameCheck });
  const create = useMutation({
    mutationFn: characterApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["characters"] });
      router.push("/game");
    },
  });

  const races = options.data?.races ?? [];
  const classes = options.data?.base_classes ?? [];
  const canNext =
    (step === 0 && nameCheck.data?.valid && nameCheck.data.available && nameCheck.data.name === name.trim()) ||
    (step === 1 && raceId !== null) ||
    (step === 2 && classId !== null);

  return (
    <section className="max-w-2xl space-y-4" aria-labelledby="wizard-title">
      <h1 id="wizard-title" className="text-xl font-bold">
        {t("title")}
      </h1>
      <ol className="flex flex-wrap gap-2 text-xs" aria-label={t("stepOf", { current: step + 1, total: STEPS.length })}>
        {STEPS.map((s, i) => (
          <li
            key={s}
            aria-current={i === step ? "step" : undefined}
            className={`rounded px-2 py-1 ${i === step ? "bg-accent text-bg" : "border border-border"}`}
          >
            {t(s)}
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <div className="space-y-2">
          <label htmlFor="char-name" className="block text-sm">
            {t("nameLabel")}
          </label>
          <input
            id="char-name"
            value={name}
            maxLength={32}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name.trim() && nameCheck.mutate(name.trim())}
            className="w-full rounded border border-border bg-bg p-2"
          />
          {nameCheck.data && !nameCheck.data.valid ? (
            <p role="alert" className="text-sm text-bad" data-testid="name-error">
              {errorMessage({ code: nameCheck.data.error_code })}
            </p>
          ) : null}
          {nameCheck.data?.valid && !nameCheck.data.available ? (
            <p role="alert" className="text-sm text-bad" data-testid="name-error">
              {errorMessage({ code: "name_taken" })}
            </p>
          ) : null}
          {nameCheck.data?.valid && nameCheck.data.available ? (
            <p className="text-sm text-good">{t("nameAvailable")}</p>
          ) : null}
        </div>
      ) : null}
      {step === 1 ? (
        <div className="space-y-2">
          <p className="text-sm text-muted">{tr("noLock")}</p>
          <OptionGrid items={races} selected={raceId} onSelect={setRaceId} label={t("stepRace")} />
        </div>
      ) : null}
      {step === 2 ? (
        <OptionGrid items={classes} selected={classId} onSelect={setClassId} label={t("stepClass")} />
      ) : null}
      {step === 3 ? (
        <p className="font-mono" data-testid="wizard-summary">
          {t("summary", {
            name: name.trim(),
            race: races.find((r) => r.id === raceId)?.name ?? "",
            cls: classes.find((c) => c.id === classId)?.name ?? "",
          })}
        </p>
      ) : null}

      {create.isError ? (
        <p role="alert" className="text-sm text-bad">
          {errorMessage(create.error)}
        </p>
      ) : null}

      <div className="flex gap-2">
        {step > 0 ? (
          <button type="button" onClick={() => setStep(step - 1)} className="rounded border border-border px-3 py-1">
            {tc("back")}
          </button>
        ) : null}
        {step < 3 ? (
          <button
            type="button"
            onClick={() => (step === 0 && !canNext ? nameCheck.mutate(name.trim()) : setStep(step + 1))}
            disabled={step > 0 && !canNext}
            className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50"
          >
            {tc("next")}
          </button>
        ) : (
          <button
            type="button"
            disabled={create.isPending || raceId === null || classId === null}
            onClick={() => raceId && classId && create.mutate({ name: name.trim(), race_id: raceId, base_class_id: classId })}
            className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50"
          >
            {t("create")}
          </button>
        )}
      </div>
    </section>
  );
}
