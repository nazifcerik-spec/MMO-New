# Phase 16 — Inventory, Equipment, Tooltip, Item Requirements

## Result
- Data-driven equipment slots (`balance/inventory.yaml`: 16 slots incl. ring_1/2, trinket_1/2, tool; off hand
  blocked by two-handed weapons), bag capacity (60 + provider hook), bounded overflow mailbox (200) and
  sell percentages. Migration 0013: one item per equipped slot (partial unique index) + slot/location CHECK.
- Stackables and unique instances share `item_instances` (quantity ≤ stack size); grants merge stacks →
  free bag slots → mailbox → auto-sell for gold (`overflow_autosell` ledger). Rewards are never lost and storage
  is never unbounded. All placements are idempotent on grant keys (replays return the same instances).
- Equip/unequip are atomic and server-authoritative (row locks on the item and loadout; displaced items return
  to the bag or the action fails with `inventory_full`). Validation: min level, stat requirements, class/race
  restrictions, weapon/armor proficiency (class families), slot compatibility, two-handed rules, binding
  (bind-on-equip records provenance).
- Anti-circular rule: requirements are checked against **gear-free** primary stats (base + allocation +
  race/class/talents), so neither the item itself nor any chain of equipped items can enable an item.
- Derived stats stay single-source: the stat sheet's equipment provider; equip previews run the same calculator
  on a hypothetical loadout (tests assert preview delta == live change).
- AFK integration: loot granter (item pools resolved deterministically to published templates, loot filter
  applied, keep → bag/mailbox, rejected → vendor gold `loot_filter_sell`), potion provider/consumer from potion
  stacks, idempotent durability loss on equipped gear. Loot filter contract: category/rarity/tier/class-tag,
  keep materials, `auto_salvage` accepted (sells until salvage exists; materials/quest items never filtered).
- API: inventory (bag/mailbox, capacity, labels), equipment view (slots + derived/primary stats), equip,
  unequip, equip preview, mailbox claim, destroy.
- Frontend `/game/characters/[id]/inventory`: equipment list + stats, bag with category filter, mailbox with
  overflow policy, localized tooltip (rarity/tier/slot/family, requirement pass/fail using gear-free stats,
  stats, affixes, unique, durability/broken, sockets, bind, marketability, sources, equip delta); AFK loot filter
  gains category/class-tag toggles; 4 locales.

## Tests
- `tests/test_inventory.py`: equip → stats (preview == live), unequip, ownership; gear-free requirement check
  (self and chained STR boosts rejected); proficiency, slot, two-handed displacement/blocking, ring slots,
  bind-on-equip; overflow bag→mailbox→autosell with idempotent replay; stack merging; AFK claim loot + filter
  sells + potion consumption; idempotent durability loss. AFK tests updated for granted loot.
- Frontend unit `item-tooltip.test.tsx`; E2E inventory equip/unequip flow.
- Gate: `scripts/check.sh` ALL CHECKS PASSED (pytest 220, vitest 36); `scripts/e2e.sh` 36 passed.

## Risks
- Repair, salvage/auto-salvage, gems and upgrades arrive with crafting (Phases 17–18) and economy (Phase 20).
