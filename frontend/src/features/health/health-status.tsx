"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getHealth, type HealthCheck } from "@/lib/api/health";

function Row({ label, check }: { label: string; check?: HealthCheck }) {
  const t = useTranslations("home");
  const ok = check?.status === "ok";
  return (
    <li className="flex items-center justify-between gap-4 font-mono text-sm">
      <span>{label}</span>
      <span data-testid={`health-${label}`} className={ok ? "text-good" : "text-bad"}>
        {ok ? t("statusOk") : t("statusDown")}
      </span>
    </li>
  );
}

export function HealthStatus() {
  const t = useTranslations("home");
  const { data, isError, isLoading } = useQuery({ queryKey: ["health"], queryFn: getHealth, retry: 0 });
  return (
    <section aria-labelledby="health-title" className="rounded border border-border bg-panel p-4">
      <h2 id="health-title" className="mb-2 font-semibold">
        {t("systemStatus")}
      </h2>
      {isLoading ? null : (
        <ul className="space-y-1" data-testid="health-status" data-state={isError ? "error" : data?.status}>
          <Row label={t("database")} check={data?.checks.database} />
          <Row label={t("cache")} check={data?.checks.redis} />
        </ul>
      )}
    </section>
  );
}
