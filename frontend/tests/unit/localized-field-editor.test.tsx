import { fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  LocalizedFieldEditor,
  emptyLocalizedValues,
  fallbackPreview,
  type LocalizedValues,
} from "@/components/i18n/localized-field-editor";

import { renderIntl } from "./render";

function Harness({ initial }: { initial: LocalizedValues }) {
  const [values, setValues] = useState(initial);
  return (
    <LocalizedFieldEditor label="Name" values={values} onChange={(l, v) => setValues({ ...values, [l]: v })} />
  );
}

describe("fallbackPreview", () => {
  it("uses own locale, then English, then null", () => {
    const v = emptyLocalizedValues();
    expect(fallbackPreview(v, "tr")).toEqual({ text: null, from: null });
    v.en = { value: "Sword", status: "published" };
    expect(fallbackPreview(v, "tr")).toEqual({ text: "Sword", from: "en" });
    v.tr = { value: "Kılıç", status: "draft" };
    expect(fallbackPreview(v, "tr")).toEqual({ text: "Kılıç", from: "tr" });
  });
});

describe("LocalizedFieldEditor", () => {
  it("shows four locale tabs with missing badges", () => {
    const v = emptyLocalizedValues();
    v.en = { value: "Sword", status: "published" };
    renderIntl(<Harness initial={v} />);
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    expect(screen.queryByTestId("missing-en")).toBeNull();
    expect(screen.getByTestId("missing-tr")).toBeInTheDocument();
    expect(screen.getByTestId("missing-zh-CN")).toBeInTheDocument();
  });

  it("shows English fallback preview and NFC-normalizes input", () => {
    const v = emptyLocalizedValues();
    v.en = { value: "Sword", status: "published" };
    renderIntl(<Harness initial={v} />);
    fireEvent.click(screen.getByRole("tab", { name: /^ES/ }));
    expect(screen.getByTestId("fallback-preview")).toHaveTextContent("Sword");
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Espadé" } });
    expect((input as HTMLInputElement).value).toBe("Espadé");
    expect(screen.queryByTestId("missing-es")).toBeNull();
  });

  it("supports arrow-key tab navigation", () => {
    renderIntl(<Harness initial={emptyLocalizedValues()} />);
    const en = screen.getByRole("tab", { name: /^EN/ });
    fireEvent.keyDown(en, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: /^TR/ })).toHaveAttribute("aria-selected", "true");
  });

  it("renders in zh-CN UI locale", () => {
    renderIntl(<Harness initial={emptyLocalizedValues()} />, "zh-CN");
    expect(screen.getAllByText("缺失").length).toBeGreaterThan(0);
  });
});
