"""initial schema

Revision ID: 592a44c3fe57
Revises: 
Create Date: 2026-08-16 13:21:47.589533
"""

from __future__ import annotations

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '592a44c3fe57'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations'))
    )
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('chunk_params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents'))
    )
    op.create_table('eval_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('dataset_version', sa.String(length=120), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eval_runs'))
    )
    op.create_index('ix_eval_runs_created_at', 'eval_runs', ['created_at'], unique=False)
    op.create_table('llm_calls',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('operation', sa.String(length=16), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('fallback_used', sa.Boolean(), nullable=False),
    sa.Column('trace_id', sa.String(length=128), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_calls'))
    )
    op.create_index('ix_llm_calls_created_at', 'llm_calls', ['created_at'], unique=False)
    op.create_table('chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('heading_path', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
    sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', text)", persisted=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_chunks_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chunks')),
    sa.UniqueConstraint('document_id', 'seq', name=op.f('uq_chunks_document_id'))
    )
    op.create_index(op.f('ix_chunks_document_id'), 'chunks', ['document_id'], unique=False)
    op.create_index('ix_chunks_embedding_hnsw', 'chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_chunks_tsv_gin', 'chunks', ['tsv'], unique=False, postgresql_using='gin')
    op.create_table('document_blobs',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('content', postgresql.BYTEA(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_blobs_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('document_id', name=op.f('pk_document_blobs'))
    )
    op.create_table('messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('model', sa.String(length=255), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_table('citations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('marker', sa.Integer(), nullable=False),
    sa.Column('chunk_id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('heading_path', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('snippet', sa.Text(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_citations_message_id_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_citations'))
    )
    op.create_index(op.f('ix_citations_message_id'), 'citations', ['message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_citations_message_id'), table_name='citations')
    op.drop_table('citations')
    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_table('document_blobs')
    op.drop_index('ix_chunks_tsv_gin', table_name='chunks', postgresql_using='gin')
    op.drop_index('ix_chunks_embedding_hnsw', table_name='chunks', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_chunks_document_id'), table_name='chunks')
    op.drop_table('chunks')
    op.drop_index('ix_llm_calls_created_at', table_name='llm_calls')
    op.drop_table('llm_calls')
    op.drop_index('ix_eval_runs_created_at', table_name='eval_runs')
    op.drop_table('eval_runs')
    op.drop_table('documents')
    op.drop_table('conversations')
