from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

STATS = ("str", "dex", "int", "vit", "wis", "spi", "luk")


class CharacterStatAllocation(Base, TimestampMixin):
    """Points the player allocated (manual or template). Base/race/class/equipment live elsewhere."""

    __tablename__ = "character_stat_allocations"
    __table_args__ = tuple(CheckConstraint(f"{s}_points >= 0", name=f"{s}_non_negative") for s in STATS)

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    str_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dex_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    int_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vit_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wis_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spi_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    luk_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_respec_at: Mapped[datetime | None] = mapped_column()

    def as_dict(self) -> dict[str, int]:
        return {s.upper(): getattr(self, f"{s}_points") for s in STATS}

    def set_from(self, alloc: dict[str, int]) -> None:
        for s in STATS:
            setattr(self, f"{s}_points", alloc.get(s.upper(), 0))


class ProgressionEvent(Base):
    """Append-only progression ledger (XP grants, level-ups, allocations, respecs). Idempotency key unique."""

    __tablename__ = "progression_events"
    __table_args__ = (
        UniqueConstraint("character_id", "idempotency_key"),
        Index("ix_progression_events_character_created", "character_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(48))
    source_id: Mapped[str | None] = mapped_column(String(128))
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    level_before: Mapped[int] = mapped_column(Integer, nullable=False)
    level_after: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Wallet(Base, TimestampMixin):
    """Character currency balances in integer minor units (copper). Economy phase extends currencies."""

    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("gold >= 0", name="gold_non_negative"),)

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    gold: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class EconomyLedger(Base):
    """Append-only currency ledger: every balance change has a source/sink, reason and idempotency key."""

    __tablename__ = "economy_ledger"
    __table_args__ = (
        UniqueConstraint("character_id", "currency", "idempotency_key"),
        Index("ix_economy_ledger_character_created", "character_id", "created_at"),
        Index("ix_economy_ledger_reason_created", "reason", "created_at"),
        CheckConstraint("balance_after >= 0", name="balance_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="gold")
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)  # e.g. afk_reward, respec, repair, vendor_sell
    ref_type: Mapped[str | None] = mapped_column(String(48))
    ref_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class MarketListing(Base):
    """Buyout market listing. The item is escrowed (location='market'); purchase is atomic and idempotent."""

    __tablename__ = "market_listings"
    __table_args__ = (
        CheckConstraint("status IN ('active','sold','cancelled','expired')", name="status_valid"),
        CheckConstraint("unit_price >= 1 AND total_price >= unit_price AND quantity >= 1", name="price_valid"),
        UniqueConstraint("seller_character_id", "listing_key"),
        UniqueConstraint("buyer_character_id", "purchase_key"),
        Index("ix_market_listings_active", "status", "template_code", "unit_price"),
        Index("ix_market_listings_expiry", "status", "expires_at"),
        Index(
            "uq_market_listings_active_instance", "instance_id", unique=True, postgresql_where=text("status = 'active'")
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    seller_character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instance_id: Mapped[int] = mapped_column(ForeignKey("item_instances.id", ondelete="RESTRICT"), nullable=False)
    template_code: Mapped[str] = mapped_column(String(96), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    rarity: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_pct: Mapped[float] = mapped_column(Float, nullable=False)
    fee_paid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    listing_key: Mapped[str] = mapped_column(String(128), nullable=False)
    buyer_character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    purchase_key: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}
