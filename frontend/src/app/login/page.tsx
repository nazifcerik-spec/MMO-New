import { getTranslations } from "next-intl/server";

import { AuthForm } from "@/features/auth/auth-form";

export default async function LoginPage() {
  const t = await getTranslations("auth");
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-bold">{t("title")}</h1>
      <AuthForm />
    </section>
  );
}
