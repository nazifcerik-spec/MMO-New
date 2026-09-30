import { getTranslations } from "next-intl/server";

import type { Me } from "@/lib/api/auth";
import { serverApi } from "@/lib/api/server";

export default async function AdminPage() {
  const t = await getTranslations();
  const me = await serverApi<Me>("/auth/me");
  return (
    <section>
      <h1 className="text-xl font-bold">{t("admin.title")}</h1>
      <p className="text-muted" data-testid="admin-roles">
        {t("adminShell.roles", { roles: me?.roles.join(", ") ?? "" })}
      </p>
    </section>
  );
}
