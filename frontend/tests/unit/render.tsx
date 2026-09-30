import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";

import en from "../../messages/en.json";
import es from "../../messages/es.json";
import tr from "../../messages/tr.json";
import zh from "../../messages/zh-CN.json";

const catalogs = { en, tr, "zh-CN": zh, es } as const;

export function renderIntl(ui: ReactElement, locale: keyof typeof catalogs = "en") {
  return render(
    <NextIntlClientProvider locale={locale} messages={catalogs[locale]} timeZone="UTC">
      {ui}
    </NextIntlClientProvider>,
  );
}
