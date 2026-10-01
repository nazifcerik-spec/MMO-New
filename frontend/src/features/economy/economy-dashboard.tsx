"use client";

import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { economyApi } from "@/lib/api/economy";

/** Admin economy dashboard: gold sources/sinks by reason, item creation/destruction, market volume. */
export function EconomyDashboard() {
  const t = useTranslations("economyAdmin");
  const tc = useTranslations("common");
  const f = useFormatter();
  const [days, setDays] = useState(7);
  const q = useQuery({ queryKey: ["economy-summary", days], queryFn: () => economyApi.summary(days) });
  const n = (v: number) => f.number(v);
  return (
    <div className="space-y-3">
      <label className="text-sm">
        {t("window")}{" "}
        <select className="rounded border border-border bg-bg px-1" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[1, 7, 30, 90].map((d) => (
            <option key={d} value={d}>
              {t("days", { d })}
            </option>
          ))}
        </select>
      </label>
      {q.isLoading ? <p>{tc("loading")}</p> : null}
      {q.data ? (
        <>
          <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4" data-testid="economy-totals">
            {(["sources", "sinks", "transfers", "net_created"] as const).map((k) => (
              <div key={k} className="rounded border border-border bg-panel p-2">
                <dt className="text-xs text-muted">{t(`gold.${k}`)}</dt>
                <dd className="font-semibold">{n(q.data.gold[k])}</dd>
              </div>
            ))}
          </dl>
          <table className="w-full text-sm">
            <caption className="text-left font-semibold">{t("byReason")}</caption>
            <thead>
              <tr className="text-left text-xs text-muted">
                <th>{t("reason")}</th>
                <th>{t("kind")}</th>
                <th className="text-right">{t("entries")}</th>
                <th className="text-right">{t("in")}</th>
                <th className="text-right">{t("out")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.gold.by_reason.map((r) => (
                <tr key={r.reason} className="border-t border-border">
                  <td>{r.reason}</td>
                  <td className={r.kind === "sink" ? "text-bad" : r.kind === "source" ? "text-good" : ""}>{t(`kindName.${r.kind}`)}</td>
                  <td className="text-right">{n(r.entries)}</td>
                  <td className="text-right">{n(r.gold_in)}</td>
                  <td className="text-right">{n(r.gold_out)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="grid gap-3 md:grid-cols-2">
            <section className="rounded border border-border bg-panel p-2 text-sm">
              <h2 className="font-semibold">{t("items")}</h2>
              <ul>
                {Object.entries(q.data.items).map(([e, c]) => (
                  <li key={e}>
                    {e}: {n(c)}
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded border border-border bg-panel p-2 text-sm" data-testid="economy-market">
              <h2 className="font-semibold">{t("market")}</h2>
              <p>{t("marketLine", { sales: q.data.market.sales, volume: q.data.market.volume, tax: q.data.market.tax, active: q.data.market.active_listings })}</p>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
