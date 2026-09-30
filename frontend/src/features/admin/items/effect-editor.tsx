"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { EffectDef, Json, JsonSchema, Meta, RegistryEntry } from "@/lib/api/admin-items";

const input = "rounded border border-border bg-bg px-1 py-0.5 text-xs";
const MAX_DEPTH = 3;

function resolve(schema: JsonSchema, root: JsonSchema): JsonSchema {
  if (schema.$ref) {
    const name = schema.$ref.split("/").pop() ?? "";
    return root.$defs?.[name] ?? {};
  }
  return schema;
}

/** Default params for an effect type: schema defaults, else first enum value / min / empty. */
export function defaultParams(entry: RegistryEntry): Record<string, Json> {
  const root = entry.params_schema;
  const out: Record<string, Json> = {};
  for (const name of root.required ?? []) {
    const s = resolve(root.properties?.[name] ?? {}, root);
    if (s.default !== undefined) out[name] = s.default;
    else if (s.enum) out[name] = s.enum[0];
    else if (s.type === "number" || s.type === "integer") out[name] = s.minimum ?? (s.exclusiveMinimum !== undefined ? s.exclusiveMinimum + 1 : 1);
    else if (s.type === "boolean") out[name] = false;
    else if (s.type === "array") out[name] = [];
    else if (s.type === "object" || s.properties) out[name] = {};
    else out[name] = "";
  }
  return out;
}

interface FieldProps {
  name: string;
  schema: JsonSchema;
  root: JsonSchema;
  value: Json | undefined;
  onChange: (v: Json | undefined) => void;
  registry: RegistryEntry[];
  meta: Meta;
  depth: number;
  idPrefix: string;
}

function Field({ name, schema: raw, root, value, onChange, registry, meta, depth, idPrefix }: FieldProps) {
  const t = useTranslations("itemStudio");
  const id = `${idPrefix}-${name}`;
  const optional = raw.anyOf?.some((s) => s.type === "null");
  const schema = resolve(optional ? (raw.anyOf?.find((s) => s.type !== "null") ?? {}) : raw, root);
  const label = (
    <label htmlFor={id} className="text-[11px] text-muted">
      {schema.title ?? raw.title ?? name}
    </label>
  );
  const clear = (v: string) => (optional && v === "" ? undefined : v);
  if (schema.enum) {
    return (
      <div className="flex flex-col">
        {label}
        <select id={id} className={input} value={value === undefined || value === null ? "" : String(value)} onChange={(e) => onChange(clear(e.target.value))}>
          {optional ? <option value="">—</option> : null}
          {schema.enum.map((o) => (
            <option key={String(o)} value={String(o)}>
              {String(o)}
            </option>
          ))}
        </select>
      </div>
    );
  }
  if (schema.type === "number" || schema.type === "integer") {
    return (
      <div className="flex flex-col">
        {label}
        <input
          id={id}
          type="number"
          className={`${input} w-24`}
          min={schema.minimum}
          max={schema.maximum}
          step={schema.type === "integer" ? 1 : "any"}
          value={typeof value === "number" ? value : ""}
          onChange={(e) => onChange(e.target.value === "" ? (optional ? undefined : 0) : Number(e.target.value))}
        />
      </div>
    );
  }
  if (schema.type === "boolean") {
    return (
      <label className="flex items-center gap-1 text-xs">
        <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        {schema.title ?? name}
      </label>
    );
  }
  if (schema.type === "array") {
    const items = resolve(schema.items ?? {}, root);
    if (items.properties?.effect_type) {
      if (depth >= MAX_DEPTH) return <p className="text-xs text-bad">{t("maxDepth")}</p>;
      return (
        <fieldset className="col-span-full rounded border border-border p-1">
          <legend className="text-[11px] text-muted">{schema.title ?? name}</legend>
          <EffectListEditor value={(value as unknown as EffectDef[]) ?? []} onChange={(v) => onChange(v as unknown as Json)} registry={registry} meta={meta} depth={depth + 1} />
        </fieldset>
      );
    }
    return (
      <div className="flex flex-col">
        {label}
        <input
          id={id}
          className={input}
          value={Array.isArray(value) ? value.join(", ") : ""}
          onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
        />
      </div>
    );
  }
  if (schema.properties) {
    const obj = (value as Record<string, Json> | null | undefined) ?? undefined;
    return (
      <fieldset className="col-span-full rounded border border-border p-1">
        <legend className="text-[11px] text-muted">
          {schema.title ?? name}
          {optional ? (
            <button type="button" className="ml-2 underline" onClick={() => onChange(obj ? undefined : {})}>
              {obj ? t("remove") : t("add")}
            </button>
          ) : null}
        </legend>
        {obj || !optional ? (
          <ObjectFields schema={schema} root={root} value={obj ?? {}} onChange={(v) => onChange(v)} registry={registry} meta={meta} depth={depth} idPrefix={id} />
        ) : null}
      </fieldset>
    );
  }
  if (name === "stat" || name === "damage_type" || name === "applies_to_stat") {
    const options = name === "damage_type" ? meta.damage_types : [...meta.primary_stats, ...meta.derived_stats];
    return (
      <div className="flex flex-col">
        {label}
        <select id={id} className={input} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(clear(e.target.value))}>
          <option value="">—</option>
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>
    );
  }
  return (
    <div className="flex flex-col">
      {label}
      <input id={id} className={input} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(clear(e.target.value))} />
    </div>
  );
}

function ObjectFields({
  schema,
  root,
  value,
  onChange,
  registry,
  meta,
  depth,
  idPrefix,
}: {
  schema: JsonSchema;
  root: JsonSchema;
  value: Record<string, Json>;
  onChange: (v: Record<string, Json>) => void;
  registry: RegistryEntry[];
  meta: Meta;
  depth: number;
  idPrefix: string;
}) {
  return (
    <div className="grid grid-cols-2 gap-1 sm:grid-cols-4">
      {Object.entries(schema.properties ?? {}).map(([name, s]) => (
        <Field
          key={name}
          name={name}
          schema={s}
          root={root}
          value={value[name]}
          registry={registry}
          meta={meta}
          depth={depth}
          idPrefix={idPrefix}
          onChange={(v) => {
            const next = { ...value };
            if (v === undefined) delete next[name];
            else next[name] = v;
            onChange(next);
          }}
        />
      ))}
    </div>
  );
}

export function EffectListEditor({
  value,
  onChange,
  registry,
  meta,
  depth = 0,
  testId,
}: {
  value: EffectDef[];
  onChange: (v: EffectDef[]) => void;
  registry: RegistryEntry[];
  meta: Meta;
  depth?: number;
  testId?: string;
}) {
  const t = useTranslations("itemStudio");
  const [raw, setRaw] = useState<string | null>(null);
  const [rawError, setRawError] = useState(false);
  const byType = Object.fromEntries(registry.map((r) => [r.effect_type, r]));
  const categories = [...new Set(registry.map((r) => r.category))];
  const set = (i: number, e: EffectDef) => onChange(value.map((x, j) => (j === i ? e : x)));
  return (
    <div className="space-y-1" data-testid={testId}>
      {depth === 0 ? (
        <button
          type="button"
          className="text-xs underline"
          onClick={() => {
            setRaw(raw === null ? JSON.stringify(value, null, 2) : null);
            setRawError(false);
          }}
        >
          {raw === null ? t("advancedJson") : t("formMode")}
        </button>
      ) : null}
      {raw !== null ? (
        <div>
          <textarea
            aria-label={t("advancedJson")}
            className={`${input} h-40 w-full font-mono`}
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            onBlur={() => {
              try {
                const parsed = JSON.parse(raw);
                if (!Array.isArray(parsed)) throw new Error("not a list");
                setRawError(false);
                onChange(parsed as EffectDef[]);
              } catch {
                setRawError(true);
              }
            }}
          />
          {rawError ? <p role="alert" className="text-xs text-bad">{t("invalidJson")}</p> : <p className="text-[11px] text-muted">{t("jsonHint")}</p>}
        </div>
      ) : (
        <>
          {value.map((e, i) => {
            const entry = byType[e.effect_type];
            return (
              <div key={i} className="rounded border border-border p-1" data-testid="effect-row">
                <div className="mb-1 flex items-center gap-1">
                  <select
                    aria-label={t("effectType")}
                    className={input}
                    value={e.effect_type}
                    onChange={(ev) => {
                      const next = byType[ev.target.value];
                      set(i, { effect_type: ev.target.value, params: next ? defaultParams(next) : {} });
                    }}
                  >
                    {categories.map((c) => (
                      <optgroup key={c} label={c}>
                        {registry
                          .filter((r) => r.category === c)
                          .map((r) => (
                            <option key={r.effect_type} value={r.effect_type} title={r.description}>
                              {r.effect_type}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                  <span className="truncate text-[11px] text-muted">{entry?.description}</span>
                  <button type="button" aria-label={t("removeEffect")} className="ml-auto text-xs" onClick={() => onChange(value.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </div>
                {entry ? (
                  <ObjectFields
                    schema={entry.params_schema}
                    root={entry.params_schema}
                    value={e.params}
                    onChange={(params) => set(i, { ...e, params })}
                    registry={registry}
                    meta={meta}
                    depth={depth}
                    idPrefix={`eff-${depth}-${i}`}
                  />
                ) : (
                  <p className="text-xs text-bad">{t("unknownEffect")}</p>
                )}
              </div>
            );
          })}
          <button
            type="button"
            className="text-xs underline"
            data-testid={depth === 0 ? "add-effect" : undefined}
            onClick={() => {
              const first = byType.STAT_FLAT ?? registry[0];
              onChange([...value, { effect_type: first.effect_type, params: defaultParams(first) }]);
            }}
          >
            {t("addEffect")}
          </button>
        </>
      )}
    </div>
  );
}
