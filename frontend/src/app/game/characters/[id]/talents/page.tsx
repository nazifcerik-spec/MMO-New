import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { TalentTrees } from "@/features/talents/talent-trees";

export default async function TalentsPage(props: PageProps<"/game/characters/[id]/talents">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("talents");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <TalentTrees characterId={characterId} />
    </div>
  );
}
