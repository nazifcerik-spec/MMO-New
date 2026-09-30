import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { ProgressionPanel } from "@/features/progression/progression-panel";

export default async function CharacterPage(props: PageProps<"/game/characters/[id]">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("progression");
  const tc = await getTranslations("classes");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold">{t("title")}</h1>
        <Link href={`/game/characters/${characterId}/class`} className="text-sm underline" data-testid="open-class">
          {tc("openClass")}
        </Link>
      </div>
      <ProgressionPanel characterId={characterId} />
    </div>
  );
}
