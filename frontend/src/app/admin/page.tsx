import { getTranslations } from "next-intl/server";

export default async function AdminPage() {
  const t = await getTranslations("admin");
  return (
    <section>
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <p className="text-muted">{t("restricted")}</p>
    </section>
  );
}
