import { getTranslations } from "next-intl/server";

import { GeneratorWizard } from "@/features/admin/items/generator-wizard";

export default async function GeneratorPage() {
  const t = await getTranslations("itemStudio");
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">{t("generator")}</h1>
      <GeneratorWizard />
    </div>
  );
}
