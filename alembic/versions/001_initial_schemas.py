"""Initial PostgreSQL schemas and tables.

Revision ID: 001
Revises:
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op

from db.base import Base

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create schemas and all ORM tables."""
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS kanban")
    op.execute("CREATE SCHEMA IF NOT EXISTS agents")
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop all tables and schemas."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP SCHEMA IF EXISTS agents CASCADE")
    op.execute("DROP SCHEMA IF EXISTS kanban CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
