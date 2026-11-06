"""add_github_activities_tsv_column

Revision ID: c741e98d24b6
Revises: 1775587fbaff
Create Date: 2026-10-18 22:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c741e98d24b6'
down_revision: Union[str, Sequence[str], None] = '1775587fbaff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema with full-text search tsvector computed column on github_activities."""
    op.add_column(
        'github_activities',
        sa.Column(
            'tsv',
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, ''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index('ix_github_activities_tsv', 'github_activities', ['tsv'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    """Downgrade schema by removing full-text search index and computed column."""
    op.drop_index('ix_github_activities_tsv', table_name='github_activities', postgresql_using='gin')
    op.drop_column('github_activities', 'tsv')
