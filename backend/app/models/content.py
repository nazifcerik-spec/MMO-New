"""Content backbone: shared mixin, releases, immutable revisions, pending drafts (ADR-0008)."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base, TimestampMixin

CONTENT_STATUSES = ("draft", "published", "disabled", "archived")


class ContentMixin(TimestampMixin):
    """Common columns for every content entity. `code` is immutable once created."""

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    description_key: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column()
    deleted_at: Mapped[datetime | None] = mapped_column()

    @declared_attr
    def created_by(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    @declared_attr
    def updated_by(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}

    @classmethod
    def status_check(cls) -> CheckConstraint:
        return CheckConstraint("status IN ('draft','published','disabled','archived')", name="status_valid")


class ContentRelease(Base):
    """A published change-set (single entity or bundle). `version_no` is the global content version."""

    __tablename__ = "content_releases"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ContentRevision(Base):
    """Immutable snapshot of an entity as published. Replays/audits read these, never live rows."""

    __tablename__ = "content_revisions"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "revision_no"),
        Index("ix_content_revisions_type_code", "entity_type", "entity_code", "revision_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_code: Mapped[str] = mapped_column(String(96), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("content_releases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ContentDraft(Base):
    """Pending edits of an already-published entity; live rows stay untouched until publish."""

    __tablename__ = "content_drafts"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    base_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)

    __mapper_args__ = {"version_id_col": version}


class BalanceConfig(Base, ContentMixin):
    """Named, schema-validated balance configuration blobs (progression, afk, combat, ...)."""

    __tablename__ = "balance_configs"
    __table_args__ = (ContentMixin.status_check(),)

    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ContentReview(Base):
    """Review step of the publish workflow (Draft → Validation → Review → Published → Archived). A review is
    bound to one edit_version: any later edit makes it stale, so approvals always cover the exact data."""

    __tablename__ = "content_reviews"
    __table_args__ = (
        CheckConstraint("status IN ('requested','approved','changes_requested')", name="status_valid"),
        UniqueConstraint("entity_type", "entity_id", "base_revision_no", "edit_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    base_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    edit_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested")
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column()
