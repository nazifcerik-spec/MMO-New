import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import es from "../../messages/es.json";
import tr from "../../messages/tr.json";
import zh from "../../messages/zh-CN.json";
import { LOCALES, resolveLocale } from "@/lib/i18n/config";

type Tree = { [k: string]: string | Tree };
const flatten = (t: Tree, prefix = ""): string[] =>
  Object.entries(t).flatMap(([k, v]) => (typeof v === "string" ? [`${prefix}${k}`] : flatten(v, `${prefix}${k}.`)));

describe("locale resolution", () => {
  it("supports exactly the four canonical locales", () => {
    expect([...LOCALES]).toEqual(["en", "tr", "zh-CN", "es"]);
  });
  it("prefers explicit valid locale", () => {
    expect(resolveLocale("tr", "es")).toBe("tr");
  });
  it("ignores invalid explicit locale and uses Accept-Language", () => {
    expect(resolveLocale("fr", "es-ES,es;q=0.9")).toBe("es");
    expect(resolveLocale(undefined, "zh-TW,zh;q=0.8")).toBe("zh-CN");
  });
  it("falls back to en", () => {
    expect(resolveLocale("xx", "de-DE")).toBe("en");
    expect(resolveLocale(null, null)).toBe("en");
  });
});

describe("message catalogs", () => {
  const base = flatten(en as Tree).sort();
  it.each([
    ["tr", tr],
    ["zh-CN", zh],
    ["es", es],
  ])("%s has the same keys as en", (_l, cat) => {
    expect(flatten(cat as Tree).sort()).toEqual(base);
  });
  it("has at least 30 static UI keys", () => {
    expect(base.length).toBeGreaterThanOrEqual(30);
  });
});
