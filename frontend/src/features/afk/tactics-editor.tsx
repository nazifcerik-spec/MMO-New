"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import {
  afkApi,
  cleanRule,
  CODE_KINDS,
  defaultCondition,
  NO_VALUE_KINDS,
  PRESENCE_KINDS,
  type TacticCondition,
  type TacticRule,
  type TacticsOptions,
} from "@/lib/api/afk-profile";
import { useErrorMessage } from "@/lib/api/errors";

const sel = "rounded border border-border bg-bg px-1 py-0.5 text-xs";

interface Props {
  characterId: number;
  options: TacticsOptions;
  saved: TacticRule[];
  saving: boolean;
  onSave: (rules: TacticRule[]) => void;
}

/** Priority rule editor for Active Tactics (1–6 ordered rules, closed condition registry, no free-form code). */
export function TacticsEditor({ characterId, options, saved, saving, onSave }: Props) {
  const t = useTranslations("tactics");
  const errorMessage = useErrorMessage();
  const [rules, setRules] = useState<TacticRule[]>(saved);
  const [scenario, setScenario] = useState<"pack" | "boss">("pack");
  const [enemies, setEnemies] = useState(3);
  const preview = useMutation({
    mutationFn: () =>
      afkApi.preview(characterId, {
        fights: 5,
        boss: scenario === "boss",
        enemies: scenario === "pack" ? enemies : undefined,
        tactics: rules.map(cleanRule),
      }),
  });
  const update = (i: number, rule: TacticRule) => setRules(rules.map((r, j) => (j === i ? rule : r)));
  const move = (i: number, d: -1 | 1) => {
    const next = [...rules];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    setRules(next);
  };
  const setCond = (i: number, k: number, c: TacticCondition) =>
    update(i, { ...rules[i], when: rules[i].when.map((x, j) => (j === k ? c : x)) });
  const ruleKey = (r: TacticRule) => (r.use.ability ? `ability:${r.use.ability}` : `tag:${r.use.tag}`);
  const nameOf = (r: TacticRule) =>
    r.use.ability ? (options.abilities.find((a) => a.code === r.use.ability)?.name ?? r.use.ability) : t("tagLabel", { tag: r.use.tag ?? "" });
  const dirty = JSON.stringify(rules.map(cleanRule)) !== JSON.stringify(saved.map(cleanRule));

  return (
    <section aria-labelledby="tactics-title" className="space-y-3 rounded border border-border bg-panel p-3" data-testid="tactics-editor">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="tactics-title" className="font-semibold">
          {t("title")}
        </h2>
        <span className="text-xs text-muted">
          {t("limits", { rules: options.max_rules, actives: options.max_core_actives, ultimates: options.max_ultimates })}
        </span>
      </div>
      <p className="text-xs text-muted">{t("hint", { encounters: options.decision_encounters.map((e) => t(`encounter.${e}`)).join(", ") })}</p>
      <ol className="space-y-2">
        {rules.map((rule, i) => (
          <li key={i} className="rounded border border-border p-2 text-xs" data-testid={`tactic-rule-${i}`}>
            <div className="flex flex-wrap items-center gap-1">
              <span className="font-mono font-semibold">{i + 1}.</span>
              <label className="sr-only" htmlFor={`tactic-use-${i}`}>
                {t("use", { n: i + 1 })}
              </label>
              <select
                id={`tactic-use-${i}`}
                className={sel}
                value={ruleKey(rule)}
                onChange={(e) => {
                  const [kind, code] = e.target.value.split(":");
                  update(i, { ...rule, use: kind === "ability" ? { ability: code } : { tag: code } });
                }}
              >
                <optgroup label={t("abilities")}>
                  {options.abilities.map((a) => (
                    <option key={a.code} value={`ability:${a.code}`}>
                      {a.name}
                      {a.type === "ULTIMATE" ? ` (${t("ultimate")})` : ""}
                    </option>
                  ))}
                </optgroup>
                <optgroup label={t("tags")}>
                  {options.tags.map((tag) => (
                    <option key={tag} value={`tag:${tag}`}>
                      {t("tagLabel", { tag })}
                    </option>
                  ))}
                </optgroup>
              </select>
              <span className="ml-auto flex gap-1">
                <button type="button" className={sel} disabled={i === 0} aria-label={t("moveUp", { n: i + 1 })} onClick={() => move(i, -1)}>
                  ↑
                </button>
                <button
                  type="button"
                  className={sel}
                  disabled={i === rules.length - 1}
                  aria-label={t("moveDown", { n: i + 1 })}
                  onClick={() => move(i, 1)}
                >
                  ↓
                </button>
                <button type="button" className={sel} aria-label={t("remove", { n: i + 1 })} onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                  ✕
                </button>
              </span>
            </div>
            <ul className="mt-1 space-y-1 pl-4">
              {rule.when.map((c, k) => (
                <li key={k} className="flex flex-wrap items-center gap-1">
                  <span className="text-muted">{k === 0 ? t("when") : t("and")}</span>
                  <select
                    aria-label={t("conditionKind", { n: i + 1 })}
                    className={sel}
                    value={c.kind}
                    onChange={(e) => setCond(i, k, defaultCondition(e.target.value))}
                  >
                    {options.condition_kinds.map((kind) => (
                      <option key={kind} value={kind}>
                        {t(`kind.${kind}`)}
                      </option>
                    ))}
                  </select>
                  {c.kind === "TARGET_TYPE" ? (
                    <select
                      aria-label={t("targetType")}
                      className={sel}
                      value={c.target_type}
                      onChange={(e) => setCond(i, k, { ...c, target_type: e.target.value as TacticCondition["target_type"] })}
                    >
                      {(["boss", "elite", "normal"] as const).map((x) => (
                        <option key={x} value={x}>
                          {t(`encounter.${x}`)}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  {PRESENCE_KINDS.has(c.kind) ? (
                    <select
                      aria-label={t("presence")}
                      className={sel}
                      value={c.value ? "1" : "0"}
                      onChange={(e) => setCond(i, k, { ...c, op: "eq", value: Number(e.target.value) })}
                    >
                      <option value="0">{t("absent")}</option>
                      <option value="1">{t("present")}</option>
                    </select>
                  ) : null}
                  {!NO_VALUE_KINDS.has(c.kind) && !PRESENCE_KINDS.has(c.kind) && c.kind !== "EVERY_N_ACTIONS" ? (
                    <select aria-label={t("operator")} className={sel} value={c.op ?? "gte"} onChange={(e) => setCond(i, k, { ...c, op: e.target.value })}>
                      {options.ops.map((op) => (
                        <option key={op} value={op}>
                          {t(`op.${op}`)}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  {!NO_VALUE_KINDS.has(c.kind) && !PRESENCE_KINDS.has(c.kind) ? (
                    <input
                      aria-label={t("value")}
                      type="number"
                      min={0}
                      max={100000}
                      className={`${sel} w-16`}
                      value={c.value ?? 0}
                      onChange={(e) => setCond(i, k, { ...c, value: Math.max(0, Number(e.target.value) || 0) })}
                    />
                  ) : null}
                  {CODE_KINDS.has(c.kind) ? (
                    <input
                      aria-label={t("code")}
                      className={`${sel} w-24`}
                      placeholder={t("codePlaceholder")}
                      value={c.code ?? ""}
                      pattern="[a-z0-9_]*"
                      onChange={(e) => setCond(i, k, { ...c, code: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") || undefined })}
                    />
                  ) : null}
                  <button
                    type="button"
                    className={sel}
                    aria-label={t("removeCondition")}
                    onClick={() => update(i, { ...rule, when: rule.when.filter((_, j) => j !== k) })}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
            {rule.when.length < options.max_conditions ? (
              <button
                type="button"
                className="mt-1 pl-4 text-xs underline"
                onClick={() => update(i, { ...rule, when: [...rule.when, defaultCondition("HP_PERCENT")] })}
              >
                {t("addCondition")}
              </button>
            ) : null}
            {!rule.when.length ? <p className="pl-4 text-muted">{t("always", { name: nameOf(rule) })}</p> : null}
          </li>
        ))}
        <li className="list-none text-xs text-muted">{t("fallback")}</li>
      </ol>
      <div className="flex flex-wrap gap-2 text-sm">
        <button
          type="button"
          className="underline disabled:opacity-50"
          disabled={rules.length >= options.max_rules || !options.abilities.length}
          onClick={() => setRules([...rules, { use: { ability: options.abilities[0].code }, when: [] }])}
        >
          {t("addRule")}
        </button>
        <button type="button" className="underline" data-testid="tactics-template" onClick={() => setRules(options.template)}>
          {t("loadTemplate")}
        </button>
        <button
          type="button"
          data-testid="tactics-save"
          disabled={!dirty || saving}
          onClick={() => onSave(rules.map(cleanRule))}
          className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50"
        >
          {t("save")}
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2 text-sm">
        <label className="flex items-center gap-1">
          {t("scenario")}
          <select aria-label={t("scenario")} className={sel} value={scenario} onChange={(e) => setScenario(e.target.value as "pack" | "boss")}>
            <option value="pack">{t("scenarioPack")}</option>
            <option value="boss">{t("scenarioBoss")}</option>
          </select>
        </label>
        {scenario === "pack" ? (
          <label className="flex items-center gap-1">
            {t("enemies")}
            <input
              type="number"
              min={1}
              max={5}
              className={`${sel} w-12`}
              value={enemies}
              onChange={(e) => setEnemies(Math.max(1, Math.min(5, Number(e.target.value) || 1)))}
            />
          </label>
        ) : null}
        <button
          type="button"
          data-testid="tactics-preview"
          disabled={!rules.length || preview.isPending}
          onClick={() => preview.mutate()}
          className="rounded border border-border px-3 py-1 disabled:opacity-50"
        >
          {t("simulate")}
        </button>
      </div>
      {preview.error ? (
        <p role="alert" className="text-sm text-bad" data-testid="tactics-error">
          {errorMessage(preview.error)}
        </p>
      ) : null}
      {preview.data ? (
        <table className="w-full text-xs" data-testid="tactics-preview-result">
          <caption className="text-left text-muted">
            {t("result", { win: Math.round(preview.data.win_rate * 100), s: preview.data.avg_duration_s })}
          </caption>
          <tbody>
            {preview.data.rules.map((r) => (
              <tr key={r.index} data-testid={`tactic-uses-${r.index}`}>
                <td className="pr-2 font-mono">{r.index + 1}.</td>
                <td>{r.name ?? r.ability ?? r.tag}</td>
                <td className="text-right font-mono">{r.uses}</td>
              </tr>
            ))}
            <tr>
              <td />
              <td className="text-muted">{t("fallbackShort")}</td>
              <td className="text-right font-mono">{preview.data.fallback_basic_attacks}</td>
            </tr>
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
