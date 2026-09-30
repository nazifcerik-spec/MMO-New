# Item Studio (`/admin/items`)

Content tool for managing 1,520+ item templates without code changes. All authorization is server-side;
UI hiding is cosmetic only.

## Roles (RBAC)
| Permission | Grants | Default roles |
|---|---|---|
| `content.read_drafts` | list, inspector, export, preview, compare, meta | translator, item_editor, game_designer, admin |
| `item.edit` | create/edit drafts, clone, import, bulk edit, generator | item_editor, game_designer, admin |
| `item.publish` | publish, archive/disable/restore, rollback | game_designer, admin |
| `localization.edit` / `.review` | item texts, bulk translation status (review needs `.review`) | translator, item_editor*, game_designer, admin |

## Screens
- **List** (three panes): left filters + category→slot tree + saved filters (per-browser localStorage);
  center virtualized table (fixed-row windowing, 100-row server pages, sortable columns, keyboard `/` search,
  ↑/↓ or j/k, Enter opens editor, row checkboxes for bulk actions); right quick inspector (key fields,
  validation summary, per-locale status, open/clone).
- Toolbar: New, Generator, Export CSV/JSON (current filters), Import (file/paste → dry-run report →
  atomic commit, downloadable validation report), bulk translation status, bulk vendor value / untradeable.
- **Editor** `/admin/items/{code}`: tabs General · Localization · Requirements · Stats & Effects · Affixes ·
  Unique/Set · Sockets/Upgrade · Sources · Craft/Salvage · Preview · History. Ctrl/Cmd+S saves, unsaved-changes
  guard, destructive confirmations, toasts, optimistic concurrency with a field-level conflict view.
- **Generator** `/admin/items/generator`: category/slot/family, tier range, rarity weights, requirement profile,
  code + per-locale name patterns, material theme, affix pool, class tags, salvage material, count.

## Field schema (template data)
`category, subcategory, family, slot, weapon_family, armor_family, tier, min_level, rarity, stack_size,
bind_policy, tradeable, sellable, vendor_value, durability{max}, sockets{min,max}, class_tags,
allowed/blocked_classes, allowed/blocked_races, requirement_profile, requirements{stats{STR..LUK}, profession},
base_stats[{stat,amount}], effects[registry effects], affix_rules{pool (codes or group:x), min, max, fixed},
unique_effect{key, effects, mastery_scaling}, set_code, salvage[{template_code,min_qty,max_qty,chance_pct}],
icon, sources[{kind,ref}], short_description_key, lore_key` (validated by `ItemTemplateData`).
Texts live in localization keys `item.{code}.{name|description|short_description|lore}` (EN/TR/ZH-CN/ES,
fallback selected → en → internal label).

## Effects editor
Forms are generated from the effect registry JSON schemas (`/admin/content/effects/registry`): enums →
selects, numbers with bounds, booleans, nested objects (conditions), nested effect lists (max depth 3),
stat/damage-type pickers. Raw JSON is an explicit advanced mode, parsed client-side and validated by the
server on save; nothing is executed.

## Admin API (`/api/v1/admin/items`, separate from public `/items`)
`GET ""` (server-side filters: q code/localized name, category, tier, rarity, slot, family, class_tag, status,
translation, missing_locale; sort/order; offset/limit ≤200) · `GET /meta` · `GET /preview-profiles` ·
`GET /export?format=csv|json` · `POST /import {format, content, dry_run}` · `POST /generator {params, commit}` ·
`POST /bulk-edit {codes, patch(safe fields), expected_versions}` · `POST /bulk-translation-status` ·
`GET /compare?a&b` · `GET /{code}` (inspector: working data, texts, validation, budgets, reverse references) ·
`PUT /{code}/texts/{field}/{locale}` · `POST /{code}/clone` · `POST /{code}/preview {profile}`.
Lifecycle (create/update/validate/publish/status/history/diff/rollback) uses the generic content API
(`/admin/content/item_template…`, ADR-0008).

## Safety rules
- Generator and import are **dry-run first**; commit is all-or-nothing and only when every row validates
  (schema, publish validators, duplicate codes, edit versions). Generated items are **drafts**; publishing still
  runs validators. In `prod` the generator additionally requires explicit confirmation.
- Bulk edit is limited to safe fields (vendor value, trade/sell flags, bind policy, class tags, icon, sources,
  durability) with per-item optimistic versions.
- Every action is audited (create/update/clone/import/generator/bulk/translation).
