import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";

import { Providers } from "@/components/providers";
import { SiteHeader } from "@/components/site-header";

import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("common");
  return {
    title: t("appName"),
    description: "Oldschool AFK text MMORPG",
    applicationName: t("appName"),
    appleWebApp: { capable: true, title: t("appName"), statusBarStyle: "black-translucent" },
    icons: { icon: "/icons/icon-192.png", apple: "/icons/apple-touch-icon.png" },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f1110",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const t = await getTranslations("common");
  return (
    <html lang={locale}>
      <body className="min-h-dvh antialiased">
        <NextIntlClientProvider>
          <Providers>
            <a href="#main" className="skip-link">
              {t("skipToContent")}
            </a>
            <SiteHeader />
            <main id="main" className="mx-auto w-full max-w-6xl px-4 py-6">
              {children}
            </main>
          </Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
