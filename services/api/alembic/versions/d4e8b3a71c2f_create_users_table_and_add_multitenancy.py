"""create_users_table_and_add_multitenancy

Revision ID: d4e8b3a71c2f
Revises: c741e98d24b6
Create Date: 2026-11-07 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e8b3a71c2f'
down_revision: Union[str, Sequence[str], None] = 'c741e98d24b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema with users table and multi-tenant user ownership on captures and integrations."""
    # 1. Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_created_at'), 'users', ['created_at'], unique=False)

    # 2. Add user_id to captures table
    op.add_column(
        'captures',
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index(op.f('ix_captures_user_id'), 'captures', ['user_id'], unique=False)

    # 3. Add user_id and update unique constraints on github_connections table
    op.add_column(
        'github_connections',
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index(op.f('ix_github_connections_user_id'), 'github_connections', ['user_id'], unique=False)

    # Reconfigure GitHub uniqueness: drop singleton constraint, re-index github_user_id non-unique, add tenant-scoped unique
    op.drop_constraint('uq_github_connections_provider_user', 'github_connections', type_='unique')
    op.drop_index('ix_github_connections_github_user_id', table_name='github_connections')
    op.create_index(op.f('ix_github_connections_github_user_id'), 'github_connections', ['github_user_id'], unique=False)
    op.create_unique_constraint('uq_github_connections_user_provider', 'github_connections', ['user_id', 'provider'])


def downgrade() -> None:
    """Downgrade schema."""
    # Revert github_connections constraints
    op.drop_constraint('uq_github_connections_user_provider', 'github_connections', type_='unique')
    op.drop_index(op.f('ix_github_connections_github_user_id'), table_name='github_connections')
    op.create_index('ix_github_connections_github_user_id', 'github_connections', ['github_user_id'], unique=True)
    op.create_unique_constraint('uq_github_connections_provider_user', 'github_connections', ['provider', 'github_user_id'])

    op.drop_index(op.f('ix_github_connections_user_id'), table_name='github_connections')
    op.drop_column('github_connections', 'user_id')

    # Revert captures
    op.drop_index(op.f('ix_captures_user_id'), table_name='captures')
    op.drop_column('captures', 'user_id')

    # Drop users table
    op.drop_index(op.f('ix_users_created_at'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')

