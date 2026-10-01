import { getTranslations } from "next-intl/server";

import { BundlePublisher } from "@/features/admin/content/bundle-publisher";

export default async function BundlePage() {
  const t = await getTranslations("contentStudio");
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">{t("bundle")}</h1>
      <BundlePublisher />
    </div>
  );
}
