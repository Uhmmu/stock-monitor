"""add traceable investment decision lineage

Revision ID: 0043_decision_lineage
Revises: 0042_price_market_snapshots
Create Date: 2026-08-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043_decision_lineage"
down_revision = "0042_price_market_snapshots"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("ai_investment_decisions", sa.Column("decision_number", sa.Integer(), nullable=True))
    op.add_column("ai_investment_decisions", sa.Column("structured_conditions", JSON_VALUE, nullable=False, server_default=sa.text("'[]'")))
    op.add_column("ai_investment_decisions", sa.Column("supersedes_decision_id", sa.Integer(), nullable=True))
    op.add_column("ai_investment_decisions", sa.Column("merged_from_ids", JSON_VALUE, nullable=False, server_default=sa.text("'[]'")))
    op.add_column("ai_investment_decisions", sa.Column("resolution_type", sa.String(24), nullable=False, server_default="standalone"))
    op.execute(sa.text("""
        UPDATE ai_investment_decisions AS target
        SET decision_number = ranked.sequence
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id) AS sequence
            FROM ai_investment_decisions
        ) AS ranked
        WHERE target.id = ranked.id
    """))
    with op.batch_alter_table("ai_investment_decisions") as batch_op:
        batch_op.alter_column("decision_number", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint("uq_ai_decisions_user_number", ["user_id", "decision_number"])
        batch_op.create_foreign_key("fk_ai_decisions_supersedes", "ai_investment_decisions", ["supersedes_decision_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_ai_investment_decisions_supersedes_decision_id", "ai_investment_decisions", ["supersedes_decision_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_investment_decisions_supersedes_decision_id", table_name="ai_investment_decisions")
    with op.batch_alter_table("ai_investment_decisions") as batch_op:
        batch_op.drop_constraint("fk_ai_decisions_supersedes", type_="foreignkey")
        batch_op.drop_constraint("uq_ai_decisions_user_number", type_="unique")
    for name in ("resolution_type", "merged_from_ids", "supersedes_decision_id", "structured_conditions", "decision_number"):
        op.drop_column("ai_investment_decisions", name)
