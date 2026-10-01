import { getTranslations } from "next-intl/server";

import { LocalizationDashboard } from "@/features/admin/content/localization-dashboard";

export default async function LocalizationAdminPage() {
  const t = await getTranslations("contentStudio");
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">{t("localization")}</h1>
      <LocalizationDashboard />
    </div>
  );
}
