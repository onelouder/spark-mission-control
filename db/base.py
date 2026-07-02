"""SQLAlchemy declarative base and schema constants."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


SCHEMA_CORE = "core"
SCHEMA_KANBAN = "kanban"
SCHEMA_AGENTS = "agents"
