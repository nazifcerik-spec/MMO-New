import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { ZoneBrowser } from "@/features/world/zone-browser";

export default async function ZonesPage(props: PageProps<"/game/characters/[id]/zones">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("zones");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <ZoneBrowser characterId={characterId} />
    </div>
  );
}
