from typing import Any

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.content import ContentMixin


class Race(Base, ContentMixin):
    __tablename__ = "races"
    __table_args__ = (ContentMixin.status_check(), CheckConstraint("sort_order >= 0", name="sort_order_valid"))

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    identity: Mapped[str] = mapped_column(String(32), nullable=False)
    trait_name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    trait_description_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title_key: Mapped[str] = mapped_column(String(200), nullable=False)
    affinity: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)  # informational only
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
