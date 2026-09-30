"""Integer currency movements with an append-only ledger (ADR-0006). Idempotent per (character, key)."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_correlation_id
from app.core.errors import ConflictError, ValidationFailedError
from app.models.progression import EconomyLedger, Wallet

MAX_BALANCE = 10**15


async def get_wallet(db: AsyncSession, character_id: int, *, for_update: bool = False) -> Wallet:
    await db.execute(insert(Wallet).values(character_id=character_id, gold=0).on_conflict_do_nothing())
    stmt = select(Wallet).where(Wallet.character_id == character_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one()


async def find_entry(db: AsyncSession, character_id: int, key: str, currency: str = "gold") -> EconomyLedger | None:
    return (
        await db.execute(
            select(EconomyLedger).where(
                EconomyLedger.character_id == character_id,
                EconomyLedger.currency == currency,
                EconomyLedger.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()


async def change_gold(
    db: AsyncSession,
    *,
    character_id: int,
    delta: int,
    reason: str,
    idempotency_key: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> EconomyLedger:
    """Apply a signed gold delta. Replays with the same key return the original entry without re-applying."""
    if not isinstance(delta, int) or abs(delta) > MAX_BALANCE:
        raise ValidationFailedError("Invalid amount", code="invalid_amount")
    existing = await find_entry(db, character_id, idempotency_key)
    if existing is not None:
        return existing
    wallet = await get_wallet(db, character_id, for_update=True)
    new_balance = wallet.gold + delta
    if new_balance < 0:
        raise ConflictError(
            "Not enough gold", code="insufficient_funds", details={"balance": wallet.gold, "required": -delta}
        )
    if new_balance > MAX_BALANCE:
        raise ValidationFailedError("Balance overflow", code="balance_overflow")
    wallet.gold = new_balance
    entry = EconomyLedger(
        character_id=character_id,
        currency="gold",
        delta=delta,
        balance_after=new_balance,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        idempotency_key=idempotency_key,
        correlation_id=get_correlation_id(),
    )
    db.add(entry)
    await db.flush()
    return entry
