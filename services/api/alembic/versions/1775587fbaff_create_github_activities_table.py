"""create_github_activities_table

Revision ID: 1775587fbaff
Revises: a91f3e72b0c1
Create Date: 2026-10-18 01:23:49.561205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1775587fbaff'
down_revision: Union[str, Sequence[str], None] = 'a91f3e72b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Native enum for GitHub activity type
activity_type_enum = postgresql.ENUM(
    'pull_request',
    'issue',
    'commit',
    'review',
    name='github_activity_type',
    create_type=False,
)


def upgrade() -> None:
    """Upgrade database schema."""
    # 1. Create native enum type if it does not exist
    activity_type_enum.create(op.get_bind(), checkfirst=True)

    # 2. Create github_activities table
    op.create_table(
        'github_activities',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('activity_type', activity_type_enum, nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('html_url', sa.String(length=1024), nullable=True),
        sa.Column('author_login', sa.String(length=255), nullable=True),
        sa.Column('state', sa.String(length=64), nullable=True),
        sa.Column('source_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['github_repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repository_id', 'activity_type', 'external_id', name='uq_github_activities_repo_type_ext'),
    )

    op.create_index(op.f('ix_github_activities_repository_id'), 'github_activities', ['repository_id'], unique=False)
    op.create_index(op.f('ix_github_activities_activity_type'), 'github_activities', ['activity_type'], unique=False)
    op.create_index(op.f('ix_github_activities_external_id'), 'github_activities', ['external_id'], unique=False)
    op.create_index(op.f('ix_github_activities_source_created_at'), 'github_activities', ['source_created_at'], unique=False)
    op.create_index('ix_github_activities_repo_type', 'github_activities', ['repository_id', 'activity_type'], unique=False)
    op.create_index('ix_github_activities_repo_created', 'github_activities', ['repository_id', 'source_created_at'], unique=False)

    # 3. Add activity sync status tracking columns to github_repositories
    op.add_column(
        'github_repositories',
        sa.Column('activity_sync_status', sa.String(length=32), server_default=sa.text("'idle'"), nullable=False),
    )
    op.add_column(
        'github_repositories',
        sa.Column('activity_sync_error', sa.Text(), nullable=True),
    )
    op.add_column(
        'github_repositories',
        sa.Column('activity_sync_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
    )
    op.add_column(
        'github_repositories',
        sa.Column('activity_last_synced_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_github_repositories_activity_sync_status'), 'github_repositories', ['activity_sync_status'], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    # 1. Remove columns from github_repositories
    op.drop_index(op.f('ix_github_repositories_activity_sync_status'), table_name='github_repositories')
    op.drop_column('github_repositories', 'activity_last_synced_at')
    op.drop_column('github_repositories', 'activity_sync_metadata')
    op.drop_column('github_repositories', 'activity_sync_error')
    op.drop_column('github_repositories', 'activity_sync_status')

    # 2. Drop github_activities table and indexes
    op.drop_index('ix_github_activities_repo_created', table_name='github_activities')
    op.drop_index('ix_github_activities_repo_type', table_name='github_activities')
    op.drop_index(op.f('ix_github_activities_source_created_at'), table_name='github_activities')
    op.drop_index(op.f('ix_github_activities_external_id'), table_name='github_activities')
    op.drop_index(op.f('ix_github_activities_activity_type'), table_name='github_activities')
    op.drop_index(op.f('ix_github_activities_repository_id'), table_name='github_activities')
    op.drop_table('github_activities')

    # 3. Drop native enum type
    activity_type_enum.drop(op.get_bind(), checkfirst=True)
