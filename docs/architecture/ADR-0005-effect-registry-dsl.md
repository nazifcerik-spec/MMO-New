# ADR-0005 — Effect registry / safe DSL
Status: Accepted (Phase 00)

## Decision
Every gameplay effect in content data is `{effect_type, schema_version, params}`. `effect_type` must exist in a
code-side registry mapping (type, version) → Pydantic params model + engine handler. Params are validated on
import/save/publish; unknown types/versions/extra keys are rejected. Conditions/triggers (e.g. `hp_below`,
`every_n_hits`) and Active-Tactics rule conditions use the same registry pattern with enumerated operators.
Content can never carry executable code, expressions evaluated by `eval`, SQL, or scripts.

## Consequences
New mechanics require a registered type (code review) but no content-specific if/else. Engine dispatch is a
dict lookup. Admin UI builds param forms from the registry's JSON schema.
