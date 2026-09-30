"""AFK sessions (immutable snapshot + deterministic result), per-player-day AFK usage and per-character AFK stats."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

SESSION_STATUSES = ("running", "resolved", "claimed", "cancelled")


class AfkSession(Base, TimestampMixin):
    __tablename__ = "afk_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('running','resolved','claimed','cancelled')", name="status_valid"),
        CheckConstraint("ends_at > started_at", name="ends_after_start"),
        CheckConstraint("ends_at <= started_at + interval '3 hours'", name="max_three_hours"),
        # at most one unclaimed session per character
        Index(
            "uq_afk_sessions_one_active",
            "character_id",
            unique=True,
            postgresql_where=text("status IN ('running','resolved')"),
        ),
        Index("ix_afk_sessions_character_created", "character_id", "created_at"),
        Index("ix_afk_sessions_sweep", "status", "ends_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    zone_code: Mapped[str] = mapped_column(String(96), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column()
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column()
    claimed_at: Mapped[datetime | None] = mapped_column()
    claim_idempotency_key: Mapped[str | None] = mapped_column(String(128))
    claim_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class AfkDailyUsage(Base):
    """AFK seconds per account per player-day (efficiency bands). Reserved at start, trued-up at claim."""

    __tablename__ = "afk_daily_usage"
    __table_args__ = (CheckConstraint("seconds >= 0", name="seconds_non_negative"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CharacterAfkStats(Base, TimestampMixin):
    __tablename__ = "character_afk_stats"

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    pity_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_claimed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_claimed_at: Mapped[datetime | None] = mapped_column()
