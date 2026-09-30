"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Kind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: Kind;
  text: string;
}

const ToastContext = createContext<(kind: Kind, text: string) => void>(() => {});

/** Accessible toasts: polite live region for success/info, assertive for errors. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Kind, text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, kind, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 8000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2">
        <div aria-live="polite" className="contents">
          {toasts
            .filter((t) => t.kind !== "error")
            .map((t) => (
              <p key={t.id} data-testid="toast" className="pointer-events-auto rounded border border-good bg-panel px-3 py-2 text-sm shadow">
                {t.text}
              </p>
            ))}
        </div>
        <div aria-live="assertive" className="contents">
          {toasts
            .filter((t) => t.kind === "error")
            .map((t) => (
              <p key={t.id} role="alert" data-testid="toast-error" className="pointer-events-auto rounded border border-bad bg-panel px-3 py-2 text-sm shadow">
                {t.text}
              </p>
            ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
