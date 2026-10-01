import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { AfkSessionPanel } from "@/features/afk/afk-session-panel";
import { ProgressionPanel } from "@/features/progression/progression-panel";

export default async function CharacterPage(props: PageProps<"/game/characters/[id]">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  const t = await getTranslations("progression");
  const tc = await getTranslations("classes");
  const tt = await getTranslations("talents");
  const ta = await getTranslations("afk");
  const tz = await getTranslations("zones");
  const ti = await getTranslations("inventory");
  const tp = await getTranslations("professions");
  const tm = await getTranslations("market");
  const tpa = await getTranslations("party");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold">{t("title")}</h1>
        <Link href={`/game/characters/${characterId}/class`} className="text-sm underline" data-testid="open-class">
          {tc("openClass")}
        </Link>
        <Link href={`/game/characters/${characterId}/talents`} className="text-sm underline" data-testid="open-talents">
          {tt("open")}
        </Link>
        <Link href={`/game/characters/${characterId}/afk`} className="text-sm underline" data-testid="open-afk">
          {ta("open")}
        </Link>
        <Link href={`/game/characters/${characterId}/zones`} className="text-sm underline" data-testid="open-zones">
          {tz("open")}
        </Link>
        <Link href={`/game/characters/${characterId}/inventory`} className="text-sm underline" data-testid="open-inventory">
          {ti("open")}
        </Link>
        <Link href={`/game/characters/${characterId}/professions`} className="text-sm underline" data-testid="open-professions">
          {tp("open")}
        </Link>
        <Link href={`/game/characters/${characterId}/market`} className="text-sm underline" data-testid="open-market">
          {tm("open")}
        </Link>
        <Link href={`/game/characters/${characterId}/party`} className="text-sm underline" data-testid="open-party">
          {tpa("open")}
        </Link>
      </div>
      <AfkSessionPanel characterId={characterId} />
      <ProgressionPanel characterId={characterId} />
    </div>
  );
}
