import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { PartyScreen } from "@/features/party/party-screen";

export default async function PartyPage(props: PageProps<"/game/characters/[id]/party">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("party");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <PartyScreen characterId={characterId} />
    </div>
  );
}
