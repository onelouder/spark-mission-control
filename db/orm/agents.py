"""ORM models for schema `agents`."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import SCHEMA_AGENTS, Base


class AgentProject(Base):
    """Agent queue project grouping."""

    __tablename__ = "agent_projects"
    __table_args__ = {"schema": SCHEMA_AGENTS}

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class QueueItem(Base):
    """Agent work queue card."""

    __tablename__ = "queue_items"
    __table_args__ = {"schema": SCHEMA_AGENTS}

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    column: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA_AGENTS}.agent_projects.id", ondelete="SET NULL"),
    )
    complexity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(64))
    doc_path: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[str | None] = mapped_column(Text)
    session_status: Mapped[str | None] = mapped_column(String(16))
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DispatchJob(Base):
    """OpenClaw dispatch job."""

    __tablename__ = "dispatch_jobs"
    __table_args__ = {"schema": SCHEMA_AGENTS}

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    queue_item_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA_AGENTS}.queue_items.id"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    task_prompt: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    run_id: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
