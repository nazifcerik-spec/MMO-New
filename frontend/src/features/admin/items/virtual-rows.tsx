"use client";

import { useState, type KeyboardEvent, type ReactNode } from "react";

/** Minimal fixed-height row virtualization (no dependency): renders only visible rows + overscan. */
export function VirtualRows<T>({
  rows,
  rowHeight,
  height,
  render,
  onEndReached,
  onKeyDown,
  label,
}: {
  rows: T[];
  rowHeight: number;
  height: number;
  render: (row: T, index: number) => ReactNode;
  onEndReached?: () => void;
  onKeyDown?: (e: KeyboardEvent<HTMLDivElement>) => void;
  label: string;
}) {
  const [top, setTop] = useState(0);
  const overscan = 8;
  const start = Math.max(0, Math.floor(top / rowHeight) - overscan);
  const end = Math.min(rows.length, Math.ceil((top + height) / rowHeight) + overscan);
  return (
    <div
      role="grid"
      aria-label={label}
      aria-rowcount={rows.length}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="overflow-y-auto rounded border border-border focus:outline-accent"
      style={{ height }}
      onScroll={(e) => {
        const el = e.currentTarget;
        setTop(el.scrollTop);
        if (onEndReached && el.scrollTop + el.clientHeight > el.scrollHeight - rowHeight * 10) onEndReached();
      }}
    >
      <div style={{ height: rows.length * rowHeight, position: "relative" }}>
        {rows.slice(start, end).map((r, i) => (
          <div key={start + i} role="row" aria-rowindex={start + i + 1} style={{ position: "absolute", top: (start + i) * rowHeight, height: rowHeight, left: 0, right: 0 }}>
            {render(r, start + i)}
          </div>
        ))}
      </div>
    </div>
  );
}
