# ADR-0006 — Server-authoritative economy
Status: Accepted (Phase 00)

## Decision
- The server computes all XP, levels, combat, loot, currency, crafting, profession gains, market results.
  Clients send intents only (e.g. "start AFK in zone X with profile Y", "buy listing Z").
- Currency is integer minor units (`BIGINT`, gold copper-equivalent); no floats in money/XP/quantity math.
- Every currency/item movement writes an append-only `economy_ledger` entry (source/sink, amounts,
  correlation id, idempotency key). Balances are updated in the same transaction with non-negative
  CHECK constraints and row locks.
- Critical mutations (AFK claim, reward claim, craft claim, market purchase, item grant, currency transfer)
  require idempotency: unique idempotency keys per actor+action and DB unique constraints.
- Timers use server UTC time only.

## Consequences
Retries are safe; duplication exploits must defeat DB constraints, not just Redis locks.
