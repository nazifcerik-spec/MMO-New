import { getTranslations } from "next-intl/server";

import Link from "next/link";

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
      {me?.permissions.includes("content.read_drafts") ? (
        <Link href="/admin/items" className="underline" data-testid="open-item-studio">
          {t("itemStudio.title")}
        </Link>
      ) : null}
      {me?.permissions.includes("content.read_drafts") ? (
        <Link href="/admin/content" className="ml-3 underline" data-testid="open-content-studio">
          {t("contentStudio.title")}
        </Link>
      ) : null}
      {me?.permissions.includes("localization.edit") ? (
        <Link href="/admin/localization" className="ml-3 underline" data-testid="open-localization">
          {t("contentStudio.localization")}
        </Link>
      ) : null}
      {me?.permissions.includes("economy.view") || me?.permissions.includes("*") ? (
        <Link href="/admin/economy" className="ml-3 underline" data-testid="open-economy">
          {t("economyAdmin.title")}
        </Link>
      ) : null}
    </section>
  );
}
