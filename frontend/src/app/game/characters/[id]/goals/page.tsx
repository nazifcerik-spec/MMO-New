import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { GoalsScreen } from "@/features/goals/goals-screen";

export default async function GoalsPage(props: PageProps<"/game/characters/[id]/goals">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("goals");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <GoalsScreen characterId={characterId} />
    </div>
  );
}
