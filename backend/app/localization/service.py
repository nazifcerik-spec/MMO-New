"""DB-backed dynamic localization: bulk resolution with fallback, admin edits, seeding, completeness."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.localization.locales import (
    DEFAULT_LOCALE,
    PLAYER_VISIBLE_STATUSES,
    SUPPORTED_LOCALES,
    TRANSLATION_STATUSES,
    is_supported,
    is_valid_key,
    normalize_text,
    safe_label,
)
from app.models.localization import LocalizationKey, LocalizationValue


@dataclass(frozen=True, slots=True)
class ResolvedText:
    key: str
    value: str
    locale: str | None  # locale actually used; None => safe internal label
    fallback: bool


def pick(key: str, locale: str, rows: dict[str, tuple[str, str]]) -> ResolvedText:
    """Pure fallback rule. rows: locale -> (value, status)."""
    for loc in (locale, DEFAULT_LOCALE):
        hit = rows.get(loc)
        if hit and hit[0] and hit[1] in PLAYER_VISIBLE_STATUSES:
            return ResolvedText(key, hit[0], loc, loc != locale)
    return ResolvedText(key, safe_label(key), None, True)


async def resolve_many(session: AsyncSession, keys: list[str], locale: str) -> dict[str, ResolvedText]:
    """Resolve many keys in one query (no N+1). Unknown keys resolve to a safe label."""
    if not is_supported(locale):
        raise ValidationFailedError(f"Unsupported locale: {locale}", code="invalid_locale")
    unique = list(dict.fromkeys(k for k in keys if k))
    if not unique:
        return {}
    wanted = {locale, DEFAULT_LOCALE}
    stmt = (
        select(LocalizationKey.key, LocalizationValue.locale, LocalizationValue.value, LocalizationValue.status)
        .join(LocalizationValue, LocalizationValue.key_id == LocalizationKey.id)
        .where(
            LocalizationKey.key.in_(unique),
            LocalizationValue.locale.in_(wanted),
            LocalizationKey.deleted_at.is_(None),
        )
    )
    by_key: dict[str, dict[str, tuple[str, str]]] = {}
    for k, loc, val, status in (await session.execute(stmt)).all():
        by_key.setdefault(k, {})[loc] = (val, status)
    return {k: pick(k, locale, by_key.get(k, {})) for k in unique}


async def resolve_text_map(session: AsyncSession, keys: list[str], locale: str) -> dict[str, str]:
    return {k: r.value for k, r in (await resolve_many(session, keys, locale)).items()}


async def get_all_locales(session: AsyncSession, keys: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """Admin view: key -> locale -> {value, status, version}. Missing locales are reported as status=missing."""
    stmt = (
        select(
            LocalizationKey.key,
            LocalizationValue.locale,
            LocalizationValue.value,
            LocalizationValue.status,
            LocalizationValue.version,
        )
        .join(LocalizationValue, LocalizationValue.key_id == LocalizationKey.id, isouter=True)
        .where(LocalizationKey.key.in_(keys))
    )
    out: dict[str, dict[str, dict[str, Any]]] = {
        k: {loc: {"value": "", "status": "missing", "version": 0} for loc in SUPPORTED_LOCALES} for k in keys
    }
    for k, loc, val, status, version in (await session.execute(stmt)).all():
        if loc is not None:
            out[k][loc] = {"value": val, "status": status if val else "missing", "version": version}
    return out


async def ensure_key(
    session: AsyncSession, key: str, namespace: str | None = None, context: str | None = None
) -> LocalizationKey:
    if not is_valid_key(key):
        raise ValidationFailedError(f"Invalid localization key: {key}", code="invalid_key")
    ns = namespace or key.split(".")[0]
    stmt = (
        insert(LocalizationKey)
        .values(key=key, namespace=ns, context=context)
        .on_conflict_do_nothing(index_elements=["key"])
    )
    await session.execute(stmt)
    row = (await session.execute(select(LocalizationKey).where(LocalizationKey.key == key))).scalar_one()
    return row


async def set_value(
    session: AsyncSession,
    *,
    key: str,
    locale: str,
    value: str,
    status: str,
    expected_version: int | None,
    actor_id: int | None,
) -> LocalizationValue:
    """Admin edit with optimistic concurrency. expected_version=0/None creates a new value."""
    if not is_supported(locale):
        raise ValidationFailedError(f"Unsupported locale: {locale}", code="invalid_locale")
    if status not in TRANSLATION_STATUSES:
        raise ValidationFailedError(f"Invalid status: {status}", code="invalid_status")
    text = normalize_text(value)
    key_row = (
        await session.execute(
            select(LocalizationKey).where(LocalizationKey.key == key, LocalizationKey.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if key_row is None:
        raise NotFoundError(f"Localization key not found: {key}")
    if key_row.max_length and len(text) > key_row.max_length:
        raise ValidationFailedError(
            "Translation exceeds max length", code="too_long", details={"max_length": key_row.max_length}
        )
    if status in ("reviewed", "published") and not text:
        raise ValidationFailedError("Empty text cannot be reviewed/published", code="empty_translation")
    row = (
        await session.execute(
            select(LocalizationValue).where(LocalizationValue.key_id == key_row.id, LocalizationValue.locale == locale)
        )
    ).scalar_one_or_none()
    if row is None:
        if expected_version not in (None, 0):
            raise ConflictError(
                "Translation was deleted or never existed",
                code="version_conflict",
                details={"current_version": 0},
            )
        row = LocalizationValue(key_id=key_row.id, locale=locale, value=text, status=status, updated_by=actor_id)
        session.add(row)
    else:
        if expected_version is not None and row.version != expected_version:
            raise ConflictError(
                "Translation was modified by someone else",
                code="version_conflict",
                details={
                    "current_version": row.version,
                    "current_value": row.value,
                    "current_status": row.status,
                },
            )
        row.value, row.status, row.updated_by = text, status, actor_id
    try:
        await session.flush()
    except StaleDataError as exc:
        raise ConflictError("Translation was modified concurrently", code="version_conflict") from exc
    return row


async def seed_values(
    session: AsyncSession,
    key: str,
    values: dict[str, str],
    *,
    namespace: str | None = None,
    en_status: str = "published",
    other_status: str = "draft",
    force: bool = False,
) -> int:
    """Idempotent seed. Never overwrites reviewed/published text unless force=True. Returns rows written."""
    key_row = await ensure_key(session, key, namespace)
    existing = {
        v.locale: v
        for v in (
            await session.execute(select(LocalizationValue).where(LocalizationValue.key_id == key_row.id))
        ).scalars()
    }
    written = 0
    for locale, raw in values.items():
        if not is_supported(locale):
            raise ValidationFailedError(f"Unsupported locale in seed: {locale}", code="invalid_locale")
        text = normalize_text(raw)
        status = en_status if locale == DEFAULT_LOCALE else other_status
        cur = existing.get(locale)
        if cur is None:
            session.add(LocalizationValue(key_id=key_row.id, locale=locale, value=text, status=status))
            written += 1
        elif cur.value != text and (
            force or cur.status not in ("reviewed", "published") or (locale == DEFAULT_LOCALE and cur.status == status)
        ):
            cur.value, cur.status = text, status
            written += 1
    return written


async def completeness(session: AsyncSession, namespace: str | None = None) -> dict[str, dict[str, int]]:
    """Per-locale counts of statuses across all live keys; absent rows count as missing."""
    key_filter: list[ColumnElement[bool]] = [LocalizationKey.deleted_at.is_(None)]
    if namespace:
        key_filter.append(LocalizationKey.namespace == namespace)
    total = (await session.execute(select(func.count()).select_from(LocalizationKey).where(*key_filter))).scalar_one()
    stmt = (
        select(LocalizationValue.locale, LocalizationValue.status, func.count())
        .join(LocalizationKey, LocalizationKey.id == LocalizationValue.key_id)
        .where(*key_filter, LocalizationValue.value != "")
        .group_by(LocalizationValue.locale, LocalizationValue.status)
    )
    out = {loc: {s: 0 for s in TRANSLATION_STATUSES} | {"total": total} for loc in SUPPORTED_LOCALES}
    for loc, status, count in (await session.execute(stmt)).all():
        out[loc][status] += count
    for loc in SUPPORTED_LOCALES:
        present = sum(out[loc][s] for s in ("draft", "reviewed", "published"))
        out[loc]["missing"] = total - present
    return out
