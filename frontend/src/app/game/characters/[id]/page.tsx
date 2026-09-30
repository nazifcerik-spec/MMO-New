import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { ProgressionPanel } from "@/features/progression/progression-panel";

export default async function CharacterPage(props: PageProps<"/game/characters/[id]">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("progression");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <ProgressionPanel characterId={characterId} />
    </div>
  );
}
