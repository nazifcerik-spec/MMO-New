import { getTranslations } from "next-intl/server";

import { CharacterList } from "@/features/characters/character-list";

export default async function GamePage() {
  const t = await getTranslations("game");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <CharacterList />
    </div>
  );
}
