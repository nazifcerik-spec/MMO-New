import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { AfkProfileEditor } from "@/features/afk/afk-profile-editor";

export default async function AfkProfilePage(props: PageProps<"/game/characters/[id]/afk">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("afk");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <p className="text-sm text-muted">{t("intro")}</p>
      <AfkProfileEditor characterId={characterId} />
    </div>
  );
}
