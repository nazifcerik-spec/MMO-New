import { notFound } from "next/navigation";

import { GameShell } from "@/features/shell/game-shell";

export default async function CharacterLayout(props: LayoutProps<"/game/characters/[id]">) {
  const { id } = await props.params;
  const characterId = Number(id);
  if (!Number.isInteger(characterId) || characterId <= 0) notFound();
  return <GameShell characterId={characterId}>{props.children}</GameShell>;
}
