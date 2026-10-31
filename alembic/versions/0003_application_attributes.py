"""application role attributes (posting_url, role_family, industry, company_size, channel, resume_version, ...)

Revision ID: 0003
Revises: 0002
"""
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = [
    ("posting_url", sa.String(length=2048)),
    ("role_family", sa.String(length=40)),
    ("industry", sa.String(length=60)),
    ("company_size", sa.String(length=20)),
    ("channel", sa.String(length=20)),
    ("resume_version", sa.String(length=60)),
    ("work_mode", sa.String(length=20)),
    ("location", sa.String(length=120)),
]
# The first frontend stored the posting link inside notes as "Posting: <url>\n\n<notes>".
_LEGACY = re.compile(r"^Posting:\s*(\S+)(?:\n\n([\s\S]*))?$")


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("job_applications", sa.Column(name, type_, nullable=True))
    op.create_index(op.f("ix_job_applications_role_family"), "job_applications", ["role_family"])

    # Backfill: move legacy "Posting:" notes into posting_url.
    bind = op.get_bind()
    apps = sa.table("job_applications", sa.column("id", sa.Integer), sa.column("notes", sa.Text),
                    sa.column("posting_url", sa.String))
    for row in bind.execute(sa.select(apps.c.id, apps.c.notes).where(apps.c.notes.like("Posting:%"))):
        m = _LEGACY.match(row.notes or "")
        if m:
            bind.execute(apps.update().where(apps.c.id == row.id).values(posting_url=m.group(1)[:2048], notes=m.group(2) or None))


def downgrade() -> None:
    op.drop_index(op.f("ix_job_applications_role_family"), table_name="job_applications")
    for name, _ in reversed(_COLUMNS):
        op.drop_column("job_applications", name)
