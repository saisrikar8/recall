"""Store document token vectors separately from single-vector text embeddings."""
from alembic import op
import sqlalchemy as sa
revision = 'c41e7ab20316'
down_revision = '8f3a2c7d910b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('visual_embeddings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chunk_id', sa.Integer(), sa.ForeignKey('chunks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model_key', sa.String(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('model_revision', sa.String(), nullable=False),
        sa.Column('configuration', sa.JSON(), nullable=False),
        sa.Column('dimensions', sa.Integer(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('vectors', sa.LargeBinary(), nullable=False),
        sa.Column('input_hash', sa.String(), nullable=False),
        sa.UniqueConstraint('chunk_id', 'model_key', name='uq_visual_chunk_model'),
        sa.CheckConstraint('dimensions > 0 AND token_count > 0', name='ck_visual_shape'),
        sa.CheckConstraint('length(vectors) = token_count * dimensions * 2', name='ck_visual_bytes'))
    op.create_index('ix_visual_embeddings_chunk_id', 'visual_embeddings', ['chunk_id'])


def downgrade():
    op.drop_table('visual_embeddings')
