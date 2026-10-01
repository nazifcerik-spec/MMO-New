"use client";

import { useFormatter } from "next-intl";
import { useState } from "react";

export interface Bar {
  label: string;
  value: number;
  note?: string;
}

/** Single-series horizontal bar chart: one hue, recessive axis, per-bar hover tooltip, optional reference band,
 *  and an always-available table view (identity never relies on color). */
export function BarChart({ title, bars, unit = "", band, tableLabel }: { title: string; bars: Bar[]; unit?: string; band?: [number, number]; tableLabel: string }) {
  const f = useFormatter();
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const max = Math.max(1, ...bars.map((b) => b.value), band ? band[1] : 0);
  const pct = (v: number) => `${(100 * Math.max(0, v)) / max}%`;
  return (
    <figure className="space-y-1" data-testid={`chart-${title}`}>
      <figcaption className="flex items-center text-xs font-semibold">
        {title}
        <button type="button" className="ml-auto font-normal underline" aria-pressed={table} onClick={() => setTable((v) => !v)}>
          {tableLabel}
        </button>
      </figcaption>
      {table ? (
        <table className="w-full text-xs">
          <tbody>
            {bars.map((b) => (
              <tr key={b.label} className="border-t border-border">
                <th scope="row" className="text-left font-normal">
                  {b.label}
                </th>
                <td className="text-right">
                  {f.number(b.value)}
                  {unit}
                </td>
                <td className="text-muted">{b.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <ul className="relative space-y-[2px]" role="list">
          {bars.map((b, i) => (
            <li key={b.label} className="relative flex items-center gap-2 text-xs" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={0} aria-label={`${b.label}: ${f.number(b.value)}${unit}${b.note ? ` (${b.note})` : ""}`}>
              <span className="w-28 shrink-0 truncate text-fg">{b.label}</span>
              <span className="relative h-3 flex-1">
                {band ? <span aria-hidden className="absolute inset-y-0 bg-border" style={{ left: pct(band[0]), width: `${(100 * (band[1] - band[0])) / max}%` }} /> : null}
                <span className="absolute inset-y-[2px] left-0 rounded-r bg-accent" style={{ width: pct(b.value) }} />
              </span>
              {hover === i ? (
                <span role="tooltip" className="absolute right-0 -top-6 z-10 rounded border border-border bg-panel px-1 text-fg shadow">
                  {f.number(b.value)}
                  {unit}
                  {b.note ? ` · ${b.note}` : ""}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}
