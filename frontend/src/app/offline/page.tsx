import { getTranslations } from "next-intl/server";

export default async function OfflinePage() {
  const t = await getTranslations("shell");
  return (
    <section role="status" className="space-y-2">
      <h1 className="text-xl font-bold">{t("offlineTitle")}</h1>
      <p className="text-muted">{t("offline")}</p>
    </section>
  );
}
