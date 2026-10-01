"use client";

import { useTranslations } from "next-intl";
import { useSyncExternalStore } from "react";

import { LanguageSwitcher } from "@/components/i18n/language-switcher";
import { LogoutButton } from "@/features/auth/logout-button";

const KEY = "mmo.reduceMotion";

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener("mmo-reduce-motion", cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener("mmo-reduce-motion", cb);
  };
}

export function applyReducedMotion(on: boolean) {
  document.documentElement.toggleAttribute("data-reduce-motion", on);
}

/** Player settings: language, reduced motion (in addition to the OS preference), sign out. */
export function SettingsScreen() {
  const t = useTranslations("shell");
  const reduce = useSyncExternalStore(subscribe, read, () => false);
  const toggle = (on: boolean) => {
    try {
      localStorage.setItem(KEY, on ? "1" : "0");
    } catch {
      /* storage unavailable: still apply for this page */
    }
    applyReducedMotion(on);
    window.dispatchEvent(new Event("mmo-reduce-motion"));
  };
  return (
    <div className="space-y-4 text-sm">
      <section className="space-y-1">
        <h2 className="font-semibold">{t("language")}</h2>
        <LanguageSwitcher />
      </section>
      <section>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={reduce} onChange={(e) => toggle(e.target.checked)} data-testid="reduce-motion" />
          {t("reduceMotion")}
        </label>
        <p className="text-xs text-muted">{t("reduceMotionHint")}</p>
      </section>
      <section>
        <p className="text-xs text-muted">{t("offlineNote")}</p>
      </section>
      <LogoutButton />
    </div>
  );
}
