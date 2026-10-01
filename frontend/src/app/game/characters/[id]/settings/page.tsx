import { getTranslations } from "next-intl/server";

import { SettingsScreen } from "@/features/shell/settings-screen";

export default async function SettingsPage() {
  const t = await getTranslations("shell");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("nav.settings")}</h1>
      <SettingsScreen />
    </div>
  );
}
