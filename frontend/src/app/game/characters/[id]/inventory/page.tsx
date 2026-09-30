import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { InventoryScreen } from "@/features/inventory/inventory-screen";

export default async function InventoryPage(props: PageProps<"/game/characters/[id]/inventory">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("inventory");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <InventoryScreen characterId={characterId} />
    </div>
  );
}
