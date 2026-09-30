import { getTranslations } from "next-intl/server";

import { ItemStudio } from "@/features/admin/items/item-studio";

export default async function ItemStudioPage() {
  const t = await getTranslations("itemStudio");
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <ItemStudio />
    </div>
  );
}
