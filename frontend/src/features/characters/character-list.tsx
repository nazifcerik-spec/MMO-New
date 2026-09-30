"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { characterApi } from "@/lib/api/auth";

export function CharacterList() {
  const t = useTranslations("characters");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["characters"], queryFn: characterApi.list });
  const remove = useMutation({
    mutationFn: characterApi.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["characters"] }),
  });

  if (isLoading) return <p>{tc("loading")}</p>;
  if (isError)
    return (
      <p role="alert">
        {tc("error")}{" "}
        <button type="button" onClick={() => refetch()} className="underline">
          {tc("retry")}
        </button>
      </p>
    );

  return (
    <section className="space-y-3" aria-labelledby="chars-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="chars-title" className="text-lg font-semibold">
          {t("title")}
        </h2>
        <Link href="/game/characters/new" className="rounded bg-accent px-3 py-1 text-sm font-semibold text-bg">
          {t("create")}
        </Link>
      </div>
      {data && data.length === 0 ? <p className="text-muted">{t("empty")}</p> : null}
      <ul className="grid gap-2 sm:grid-cols-2" data-testid="character-list">
        {data?.map((c) => (
          <li key={c.id} className="flex items-center justify-between rounded border border-border bg-panel p-3">
            <Link href={`/game/characters/${c.id}`} className="font-mono hover:underline">
              {c.name} · {t("levelShort", { level: c.level })}
            </Link>
            <button
              type="button"
              className="text-xs text-bad underline"
              onClick={() => window.confirm(t("deleteConfirm", { name: c.name })) && remove.mutate(c.id)}
            >
              {t("delete")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
