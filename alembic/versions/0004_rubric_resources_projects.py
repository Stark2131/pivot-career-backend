"""evidence quotes on evaluations, curated resources on weekly tasks, template ids on projects

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("interview_evaluations", sa.Column("evidence", _JSON, nullable=False, server_default="{}"))
    op.add_column("weekly_tasks", sa.Column("resources", _JSON, nullable=False, server_default="[]"))
    op.add_column("project_recommendations", sa.Column("template_id", sa.String(length=60), nullable=True))
    op.add_column("project_recommendations", sa.Column("gaps_covered", _JSON, nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("project_recommendations", "gaps_covered")
    op.drop_column("project_recommendations", "template_id")
    op.drop_column("weekly_tasks", "resources")
    op.drop_column("interview_evaluations", "evidence")
