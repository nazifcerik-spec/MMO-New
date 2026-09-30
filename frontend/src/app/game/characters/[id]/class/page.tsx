import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { ClassTree } from "@/features/classes/class-tree";

export default async function CharacterClassPage(props: PageProps<"/game/characters/[id]/class">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("classes");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <ClassTree characterId={characterId} />
    </div>
  );
}
