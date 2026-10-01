# Phase 20 — Economy: Gold, Vendor, Repair, Market

## Delivered
- `balance/economy.yaml` + `app/game_engine/economy.py`: static integer vendor prices (buy 400% / sell 25% of
  vendor value), repair cost per missing durability point (tier + quality), market fee 1% / tax 5%, durations
  12–72 h, active-listing cap, min/max price (1e12 overflow guard), ledger reason → source/sink/transfer map.
- Migration `0016_market`: `market_listings` (escrow instance, price checks, unique listing/purchase keys,
  partial unique index on active instance, optimistic version).
- `app/services/economy.py` + `app/api/economy.py`:
  - vendor stock (paginated, `vendor` sources ≤ fine), vendor buy/sell — ledgered, idempotent;
  - repair quote/repair-all (gold sink);
  - market: list (tradeable/bound/location checks, fee sink, escrow `location='market'`), browse (price
    cursor pagination), my listings, cancel, atomic buy (row lock serializes buyers, buyer debit → seller
    proceeds → tax sink, item transfer + provenance, idempotent per buyer key, same-account block), expiry
    sweep (also in `scripts/afk_sweeper.py`);
  - admin: `GET /admin/economy/summary` (economy.view): gold sources/sinks/transfers by reason, item events,
    market volume/tax; `POST /admin/characters/{id}/gold` (economy.grant, audited, idempotent).
- Every gold change keeps ledger + correlation id; items keep provenance (`listed`, `traded`, `sold`, …).
- Frontend: Market & Vendor screen (browse/buy, my listings/cancel, vendor), inventory sell/list actions and
  repair panel, admin economy dashboard; 4-locale strings.

## Tests
- `tests/test_economy.py` (10): price overflow/negative, vendor idempotency/insufficient funds, repair,
  listing guards (dup escrow, bound, overflow, duration), atomic taxed purchase + replay + own-listing,
  4 concurrent buyers → exactly one wins, cancel/expiry return, browse ordering, dashboard + RBAC, admin grant.
- Unit `market-screen.test.tsx`; E2E market list/cancel.
- Gate: pytest 253, vitest 41, build green; E2E 42 passed.

## Notes / risks
- Auctions (bids) are an extension point; buyout only by design.
- Listing whole stacks only (no partial-stack split) in v1.
