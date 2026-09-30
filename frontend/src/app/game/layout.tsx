import { redirect } from "next/navigation";

import type { Me } from "@/lib/api/auth";
import { serverApi } from "@/lib/api/server";

export default async function GameLayout({ children }: { children: React.ReactNode }) {
  const me = await serverApi<Me>("/auth/me");
  if (!me) redirect("/login");
  return <>{children}</>;
}
