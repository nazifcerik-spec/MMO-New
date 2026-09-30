from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

LOCALE_CHECK = "locale IN ('en','tr','zh-CN','es')"
STATUS_CHECK = "status IN ('missing','draft','reviewed','published')"


class LocalizationKey(Base, TimestampMixin):
    __tablename__ = "localization_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    context: Mapped[str | None] = mapped_column(Text)
    max_length: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column()

    values: Mapped[list["LocalizationValue"]] = relationship(back_populates="key_ref", lazy="raise")


class LocalizationValue(Base, TimestampMixin):
    __tablename__ = "localization_values"
    __table_args__ = (
        UniqueConstraint("key_id", "locale"),
        CheckConstraint(LOCALE_CHECK, name="locale_supported"),
        CheckConstraint(STATUS_CHECK, name="status_valid"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_localization_values_locale_status", "locale", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key_id: Mapped[int] = mapped_column(ForeignKey("localization_keys.id", ondelete="CASCADE"), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    key_ref: Mapped[LocalizationKey] = relationship(back_populates="values", lazy="raise")

    __mapper_args__ = {"version_id_col": version}
