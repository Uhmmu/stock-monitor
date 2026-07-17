"""add users and trade_logs tables

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('username', sa.String(64), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('role', sa.String(16), nullable=False, server_default='user'),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_status', 'users', ['status'])
    op.create_table(
        'trade_logs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('ticker', sa.String(16), nullable=False),
        sa.Column('direction', sa.String(8), nullable=False),
        sa.Column('quantity', sa.Float, nullable=False),
        sa.Column('price', sa.Float, nullable=False),
        sa.Column('trade_date', sa.Date, nullable=False),
        sa.Column('note', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_trade_logs_user_id', 'trade_logs', ['user_id'])
    op.create_index('ix_trade_logs_ticker', 'trade_logs', ['ticker'])

def downgrade():
    op.drop_table('trade_logs')
    op.drop_table('users')
