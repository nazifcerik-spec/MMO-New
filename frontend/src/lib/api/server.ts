import "server-only";

import { cookies } from "next/headers";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

/** Server-component fetch to the backend forwarding the user's cookies. Returns null on 401. */
export async function serverApi<T>(path: string): Promise<T | null> {
  const cookieHeader = (await cookies()).toString();
  const res = await fetch(`${BACKEND}/api/v1${path}`, { headers: { cookie: cookieHeader }, cache: "no-store" });
  if (res.status === 401 || res.status === 403) return null;
  if (!res.ok) throw new Error(`backend ${res.status} for ${path}`);
  return (await res.json()) as T;
}
