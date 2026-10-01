import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { MarketScreen } from "@/features/economy/market-screen";

export default async function MarketPage(props: PageProps<"/game/characters/[id]/market">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("market");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <MarketScreen characterId={characterId} />
    </div>
  );
}
