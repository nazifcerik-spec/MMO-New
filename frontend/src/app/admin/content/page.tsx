import { getTranslations } from "next-intl/server";

import { ContentHome } from "@/features/admin/content/content-home";

export default async function ContentStudioPage() {
  const t = await getTranslations("contentStudio");
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <ContentHome />
    </div>
  );
}
