import { getTranslations } from "next-intl/server";

export default async function LoginPage() {
  const t = await getTranslations("auth");
  return (
    <section className="max-w-md">
      <h1 className="text-xl font-bold">{t("title")}</h1>
    </section>
  );
}
