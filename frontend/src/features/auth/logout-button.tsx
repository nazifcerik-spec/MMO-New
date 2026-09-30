"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import { authApi } from "@/lib/api/auth";

export function LogoutButton() {
  const t = useTranslations("nav");
  const router = useRouter();
  const qc = useQueryClient();
  return (
    <button
      type="button"
      data-testid="logout"
      className="hover:underline"
      onClick={async () => {
        await authApi.logout().catch(() => undefined);
        qc.clear();
        router.push("/login");
        router.refresh();
      }}
    >
      {t("logout")}
    </button>
  );
}
