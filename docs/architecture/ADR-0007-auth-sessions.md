# ADR-0007 — Authentication: server-side cookie sessions
Status: Accepted (Phase 03)

## Decision
- Browser auth uses an opaque random session token (256-bit) in an `HttpOnly`, `SameSite=Lax`,
  `Secure` (prod) cookie `session`. Only its SHA-256 hash is stored (`auth_sessions`), enabling instant
  revocation (logout, role change, compromise) — no JWT.
- CSRF: double-submit token. Cookie `csrf_token` (JS-readable) must be echoed in `X-CSRF-Token` on every
  non-GET request; the server compares against the hash bound to the session. `Origin` is checked against
  the configured origins. The frontend proxies `/api/*` so cookies stay first-party.
- Passwords: argon2id (argon2-cffi defaults), rehash on login when parameters change; dummy verify on unknown
  email to equalize timing; generic error message.
- Brute force: Redis fixed-window limits per IP and per email (config), plus temporary account lock after N
  consecutive failures. Rate limiting fails open if Redis is down (DB state remains authoritative).
- RBAC: roles → permissions from `content/data/system/rbac.yaml`, deny by default, enforced by
  `require(<permission>)` dependencies. Role grants limited to roles below the actor's rank.
- No default credentials: staff accounts are bootstrapped with `scripts.create_admin`.
- `auth_sessions.step_up_at` + `users.mfa_secret_enc` are the extension point for admin 2FA/step-up (Phase 26).
