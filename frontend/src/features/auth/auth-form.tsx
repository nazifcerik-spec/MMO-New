"use client";

import { useMutation } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { authApi } from "@/lib/api/auth";
import { useErrorMessage } from "@/lib/api/errors";

export function AuthForm() {
  const t = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const errorMessage = useErrorMessage();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const mutation = useMutation({
    mutationFn: () => (mode === "login" ? authApi.login(email, password) : authApi.register(email, password, locale)),
    onSuccess: () => {
      router.push("/game");
      router.refresh();
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  return (
    <div className="max-w-md space-y-4">
      <div role="tablist" className="flex gap-2">
        {(["login", "register"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => {
              setMode(m);
              mutation.reset();
            }}
            className={`rounded px-3 py-1 text-sm ${mode === m ? "bg-accent text-bg" : "border border-border"}`}
          >
            {t(m === "login" ? "loginTab" : "registerTab")}
          </button>
        ))}
      </div>
      <form onSubmit={onSubmit} className="space-y-3 rounded border border-border bg-panel p-4" noValidate>
        <div className="space-y-1">
          <label htmlFor="email" className="block text-sm">
            {t("email")}
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded border border-border bg-bg p-2"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="password" className="block text-sm">
            {t("password")}
          </label>
          <input
            id="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "register" ? 10 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby={mode === "register" ? "pw-hint" : undefined}
            className="w-full rounded border border-border bg-bg p-2"
          />
          {mode === "register" ? (
            <p id="pw-hint" className="text-xs text-muted">
              {t("passwordHint")}
            </p>
          ) : null}
        </div>
        {mutation.isError ? (
          <p role="alert" className="text-sm text-bad" data-testid="auth-error">
            {errorMessage(mutation.error)}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={mutation.isPending}
          className="w-full rounded bg-accent px-3 py-2 font-semibold text-bg disabled:opacity-60"
        >
          {t(mode === "login" ? "submitLogin" : "submitRegister")}
        </button>
      </form>
    </div>
  );
}
