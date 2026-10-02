"""create_initial_domain_tables

Revision ID: e8721daf2b54
Revises: 
Create Date: 2026-10-02 15:51:14.756918

"""
from typing import Sequence, Union

from alembic import op
import pgvector
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e8721daf2b54'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Define PostgreSQL enum values for source_type
source_type_enum = postgresql.ENUM(
    'url', 'text', 'image', 'pdf', 'file', 'github',
    name='source_type',
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema to include core domain tables."""
    # 1. Ensure pgvector extension is enabled in PostgreSQL
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Create source_type enum
    sa_source_type = postgresql.ENUM(
        'url', 'text', 'image', 'pdf', 'file', 'github',
        name='source_type',
    )
    sa_source_type.create(op.get_bind(), checkfirst=True)

    # 3. Create captures table
    op.create_table(
        'captures',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'source_type',
            source_type_enum,
            nullable=False,
        ),
        sa.Column('title', sa.String(length=512), nullable=True),
        sa.Column('original_url', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('mime_type', sa.String(length=128), nullable=True),
        sa.Column('source_id', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_captures_created_at'), 'captures', ['created_at'], unique=False)
    op.create_index(op.f('ix_captures_source_id'), 'captures', ['source_id'], unique=False)
    op.create_index(op.f('ix_captures_source_type'), 'captures', ['source_type'], unique=False)

    # 4. Create content_chunks table
    op.create_table(
        'content_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('capture_id', sa.UUID(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['capture_id'], ['captures.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('capture_id', 'chunk_index', name='uq_content_chunks_capture_chunk'),
    )
    op.create_index(op.f('ix_content_chunks_capture_id'), 'content_chunks', ['capture_id'], unique=False)

    # 5. Create source_metadata table
    op.create_table(
        'source_metadata',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('capture_id', sa.UUID(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['capture_id'], ['captures.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('capture_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('source_metadata')
    op.drop_index(op.f('ix_content_chunks_capture_id'), table_name='content_chunks')
    op.drop_table('content_chunks')
    op.drop_index(op.f('ix_captures_source_type'), table_name='captures')
    op.drop_index(op.f('ix_captures_source_id'), table_name='captures')
    op.drop_index(op.f('ix_captures_created_at'), table_name='captures')
    op.drop_table('captures')

    # Drop source_type enum
    sa_source_type = postgresql.ENUM(
        'url', 'text', 'image', 'pdf', 'file', 'github',
        name='source_type',
    )
    sa_source_type.drop(op.get_bind(), checkfirst=True)
