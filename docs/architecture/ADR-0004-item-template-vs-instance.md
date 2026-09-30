# ADR-0004 — Item template vs item instance
Status: Accepted (Phase 00)

## Decision
- `item_templates`: content definition (code, category/family/slot, tier, rarity, requirements, base stats,
  fixed effects, affix pool rules, sockets, durability, bind/trade flags, set/unique links, sources, status,
  version). Each publish creates an immutable `item_template_revisions` row.
- `item_instances`: player-owned copy referencing `template_id` + `template_revision_id`, with rolled affixes
  and values, durability, sockets/gems, bind state, quality/upgrade, provenance id, created/source timestamps.
- Stackables (materials/consumables) are stack rows (`inventory_stacks`: owner, template, quantity).
- Rolls are deterministic from a recorded seed; provenance recorded (source type/id, seed).

## Consequences
Published template edits never reinterpret historical instances: instance stats are computed from the
referenced revision + rolled values. Template deletions are soft (archive).
