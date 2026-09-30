import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import type { Me } from "@/lib/api/auth";
import { serverApi } from "@/lib/api/server";

/** UI guard only; every admin API enforces permissions server-side. */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const me = await serverApi<Me>("/auth/me");
  if (!me) redirect("/login");
  if (!me.is_staff || !me.permissions.includes("admin.access")) {
    const t = await getTranslations("adminShell");
    return (
      <section role="alert" data-testid="admin-forbidden">
        <h1 className="text-xl font-bold">403</h1>
        <p className="text-muted">{t("forbidden")}</p>
      </section>
    );
  }
  return <>{children}</>;
}
