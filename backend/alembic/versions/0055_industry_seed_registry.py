"""persist versioned industry seed memberships and replacement reviews

Revision ID: 0055_industry_seed_registry
Revises: 0054_security_symbol_aliases
"""

from alembic import op
import sqlalchemy as sa


revision = "0055_industry_seed_registry"
down_revision = "0054_security_symbol_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("industry_pulse_instruments", sa.Column("seed_version", sa.Integer(), nullable=True))
    op.add_column("industry_pulse_instruments", sa.Column("slot", sa.Integer(), nullable=True))
    op.add_column("industry_pulse_instruments", sa.Column("basket_quality", sa.String(16), nullable=True))
    op.create_index("ix_industry_pulse_instruments_seed_version", "industry_pulse_instruments", ["seed_version"])
    op.create_table(
        "industry_seed_replacement_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("seed_version", sa.Integer(), nullable=False),
        sa.Column("leaf_code", sa.String(16), nullable=False),
        sa.Column("leaf_name", sa.String(256), nullable=False),
        sa.Column("old_symbol", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("last_valid_date", sa.Date(), nullable=True),
        sa.Column("remaining_constituents", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("suggested_candidates", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("suggestion_reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("seed_version", "leaf_code", "old_symbol", name="uq_industry_seed_replacement_review"),
    )
    for column in ("seed_version", "leaf_code", "old_symbol", "status"):
        op.create_index(f"ix_industry_seed_replacement_reviews_{column}", "industry_seed_replacement_reviews", [column])


def downgrade() -> None:
    for column in ("status", "old_symbol", "leaf_code", "seed_version"):
        op.drop_index(f"ix_industry_seed_replacement_reviews_{column}", table_name="industry_seed_replacement_reviews")
    op.drop_table("industry_seed_replacement_reviews")
    op.drop_index("ix_industry_pulse_instruments_seed_version", table_name="industry_pulse_instruments")
    for column in ("basket_quality", "slot", "seed_version"):
        op.drop_column("industry_pulse_instruments", column)
