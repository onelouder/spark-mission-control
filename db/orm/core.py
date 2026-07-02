"""ORM models for schema `core`."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import SCHEMA_CORE, Base


class Context(Base):
    """Life domain (personal, venture, client, etc.)."""

    __tablename__ = "contexts"
    __table_args__ = {"schema": SCHEMA_CORE}

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(32))
    user_email: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    match_rules: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Account(Base):
    """Mail/calendar account registry."""

    __tablename__ = "accounts"
    __table_args__ = {"schema": SCHEMA_CORE}

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    icon: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(32))
    gateway_url: Mapped[str | None] = mapped_column(Text)
    tokens_path: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    contexts: Mapped[list["AccountContext"]] = relationship(back_populates="account")


class AccountContext(Base):
    """Many-to-many account ↔ context."""

    __tablename__ = "account_contexts"
    __table_args__ = (
        UniqueConstraint("account_id", "context_id"),
        {"schema": SCHEMA_CORE},
    )

    account_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA_CORE}.accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    context_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA_CORE}.contexts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    account: Mapped[Account] = relationship(back_populates="contexts")


class Contact(Base):
    """Normalized contact entry."""

    __tablename__ = "contacts"
    __table_args__ = {"schema": SCHEMA_CORE}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    interaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ContactDomain(Base):
    """Partner/blocked domain tier."""

    __tablename__ = "contact_domains"
    __table_args__ = {"schema": SCHEMA_CORE}

    domain: Mapped[str] = mapped_column(CITEXT, primary_key=True)
    tier: Mapped[str] = mapped_column(String(32), default="partner", nullable=False)


class AppSetting(Base):
    """Key/value application configuration."""

    __tablename__ = "app_settings"
    __table_args__ = {"schema": SCHEMA_CORE}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SnoozeItem(Base):
    """Briefing or task snooze."""

    __tablename__ = "snooze_items"
    __table_args__ = (
        UniqueConstraint("item_type", "source_id"),
        {"schema": SCHEMA_CORE},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    original_block: Mapped[str | None] = mapped_column(Text)
    wake_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailTriage(Base):
    """Email triage metadata (no raw message bodies)."""

    __tablename__ = "email_triage"
    __table_args__ = {"schema": SCHEMA_CORE}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA_CORE}.accounts.id"),
        nullable=False,
    )
    context_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA_CORE}.contexts.id"),
    )
    subject: Mapped[str | None] = mapped_column(Text)
    from_address: Mapped[str | None] = mapped_column(CITEXT)
    from_name: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contact_tier: Mapped[str | None] = mapped_column(String(32))
    final_decision: Mapped[str] = mapped_column(String(16), nullable=False)
    filter_reason: Mapped[str | None] = mapped_column(Text)
    briefing_handled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    converted_to_task: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    converted_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "kanban.tasks.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_email_triage_converted_task_id",
        ),
    )
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    pipeline_stages: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
