"""Parties: membership, invites and a minimal chat log. Group AFK sessions reference a party via group_id."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    leader_character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    max_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    disbanded_at: Mapped[datetime | None] = mapped_column()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class PartyMember(Base):
    __tablename__ = "party_members"
    __table_args__ = (
        CheckConstraint("role IN ('tank','healer','support','dps')", name="role_valid"),
        Index("ix_party_members_party", "party_id"),
    )

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class PartyInvite(Base):
    __tablename__ = "party_invites"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','expired','cancelled')", name="status_valid"),
        Index(
            "uq_party_invites_pending",
            "party_id",
            "character_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), nullable=False)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_by: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)


class PartyMessage(Base):
    __tablename__ = "party_messages"
    __table_args__ = (
        UniqueConstraint("character_id", "client_key"),
        Index("ix_party_messages_party", "party_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), nullable=False)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    client_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
