"""create_github_repositories_table

Revision ID: a91f3e72b0c1
Revises: 626cc9fe4322
Create Date: 2026-10-09 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a91f3e72b0c1'
down_revision: Union[str, Sequence[str], None] = '626cc9fe4322'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Native enum for sync status
repo_sync_enum = postgresql.ENUM(
    'discovered',
    'syncing',
    'synced',
    'failed',
    name='repository_sync_status',
    create_type=False,
)


def upgrade() -> None:
    """Upgrade database schema."""
    # Create enum type if it does not exist
    repo_sync_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'github_repositories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('connection_id', sa.UUID(), nullable=False),
        sa.Column('github_repository_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('owner_login', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.String(length=64), nullable=True),
        sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_fork', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_disabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_selected', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('html_url', sa.String(length=512), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('default_branch', sa.String(length=128), nullable=True),
        sa.Column('language', sa.String(length=64), nullable=True),
        sa.Column('visibility', sa.String(length=32), nullable=True),
        sa.Column('license_name', sa.String(length=128), nullable=True),
        sa.Column(
            'sync_status',
            repo_sync_enum,
            nullable=False,
            server_default='discovered',
        ),
        sa.Column('sync_error', sa.Text(), nullable=True),
        sa.Column('github_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('github_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('github_pushed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['github_connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id', 'github_repository_id', name='uq_github_repositories_conn_repo'),
    )

    op.create_index(op.f('ix_github_repositories_connection_id'), 'github_repositories', ['connection_id'], unique=False)
    op.create_index(op.f('ix_github_repositories_github_repository_id'), 'github_repositories', ['github_repository_id'], unique=False)
    op.create_index(op.f('ix_github_repositories_full_name'), 'github_repositories', ['full_name'], unique=False)
    op.create_index(op.f('ix_github_repositories_is_selected'), 'github_repositories', ['is_selected'], unique=False)
    op.create_index(op.f('ix_github_repositories_sync_status'), 'github_repositories', ['sync_status'], unique=False)
    op.create_index('ix_github_repositories_conn_sync', 'github_repositories', ['connection_id', 'sync_status'], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index('ix_github_repositories_conn_sync', table_name='github_repositories')
    op.drop_index(op.f('ix_github_repositories_sync_status'), table_name='github_repositories')
    op.drop_index(op.f('ix_github_repositories_is_selected'), table_name='github_repositories')
    op.drop_index(op.f('ix_github_repositories_full_name'), table_name='github_repositories')
    op.drop_index(op.f('ix_github_repositories_github_repository_id'), table_name='github_repositories')
    op.drop_index(op.f('ix_github_repositories_connection_id'), table_name='github_repositories')
    op.drop_table('github_repositories')

    # Drop enum type
    repo_sync_enum.drop(op.get_bind(), checkfirst=True)
