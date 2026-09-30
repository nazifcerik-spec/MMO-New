import { getTranslations } from "next-intl/server";

import { HealthStatus } from "@/features/health/health-status";

export default async function HomePage() {
  const t = await getTranslations();
  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-mono text-2xl font-bold">{t("common.appName")}</h1>
        <p className="mt-2 text-muted">{t("home.tagline")}</p>
      </section>
      <HealthStatus />
    </div>
  );
}
