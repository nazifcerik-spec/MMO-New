import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { ProfessionsScreen } from "@/features/professions/professions-screen";

export default async function ProfessionsPage(props: PageProps<"/game/characters/[id]/professions">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("professions");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <ProfessionsScreen characterId={characterId} />
    </div>
  );
}
