"use client";

import { useQuery } from "@tanstack/react-query";

import { overviewApi } from "@/lib/api/overview";

import { NextGoals } from "./next-goals";

/** On small screens the goals column is hidden; show the card inline on the character page. */
export function MobileGoals({ characterId }: { characterId: number }) {
  const s = useQuery({ queryKey: ["summary", characterId], queryFn: () => overviewApi.summary(characterId) });
  if (!s.data) return null;
  return (
    <div className="lg:hidden">
      <NextGoals characterId={characterId} goals={s.data.next_goals} />
    </div>
  );
}
