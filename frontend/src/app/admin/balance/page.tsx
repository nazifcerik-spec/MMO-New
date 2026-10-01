import { getTranslations } from "next-intl/server";

import { BalanceLab } from "@/features/admin/balance/balance-lab";

export default async function BalancePage() {
  const t = await getTranslations("balanceLab");
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <BalanceLab />
    </div>
  );
}
