import { getTranslations } from "next-intl/server";

import { EconomyDashboard } from "@/features/economy/economy-dashboard";

export default async function EconomyPage() {
  const t = await getTranslations("economyAdmin");
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <EconomyDashboard />
    </div>
  );
}
