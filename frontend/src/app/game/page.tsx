import { getTranslations } from "next-intl/server";

export default async function GamePage() {
  const t = await getTranslations("game");
  return (
    <section>
      <h1 className="text-xl font-bold">{t("title")}</h1>
    </section>
  );
}
