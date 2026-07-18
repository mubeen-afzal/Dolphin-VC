"""Initial VC Brain schema.

Revision ID: 0001_initial
Revises:
"""
from collections.abc import Sequence

from alembic import op

from app.db.base import Base
from app.db import models  # noqa: F401

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for extension in ("vector", "pg_trgm", "unaccent", "btree_gin", "citext", "pgcrypto"):
            op.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)

