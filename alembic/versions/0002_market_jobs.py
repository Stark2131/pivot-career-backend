"""job role families, market postings cache, evidence snapshot on skill-gap analyses

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("job_descriptions", sa.Column("role_family", sa.String(length=40), nullable=True))
    op.add_column("job_descriptions", sa.Column("source_provider", sa.String(length=20), nullable=True))
    op.create_index(op.f("ix_job_descriptions_role_family"), "job_descriptions", ["role_family"])
    op.add_column("skill_gap_analyses", sa.Column("job_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("skill_gap_analyses", sa.Column("role_family", sa.String(length=40), nullable=True))
    op.add_column("skill_gap_analyses", sa.Column("job_sources", _JSON, nullable=False, server_default="{}"))
    op.create_table(
        "market_job_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("cache_key", sa.String(length=300), nullable=False),
        sa.Column("payload", _JSON, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_job_cache")),
    )
    op.create_index(op.f("ix_market_job_cache_cache_key"), "market_job_cache", ["cache_key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_market_job_cache_cache_key"), table_name="market_job_cache")
    op.drop_table("market_job_cache")
    op.drop_column("skill_gap_analyses", "job_sources")
    op.drop_column("skill_gap_analyses", "role_family")
    op.drop_column("skill_gap_analyses", "job_count")
    op.drop_index(op.f("ix_job_descriptions_role_family"), table_name="job_descriptions")
    op.drop_column("job_descriptions", "source_provider")
    op.drop_column("job_descriptions", "role_family")
