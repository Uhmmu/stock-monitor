"""add Industry Pulse constituent membership fields

Revision ID: 0052_industry_pulse_constituents
Revises: 0051_industry_pulse
"""

from alembic import op
import sqlalchemy as sa

revision = "0052_industry_pulse_constituents"
down_revision = "0051_industry_pulse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("industry_pulse_instruments", sa.Column("classification_source", sa.String(24), nullable=False, server_default="PROVIDER"))
    op.add_column("industry_pulse_instruments", sa.Column("source_etf", sa.String(32), nullable=True))
    op.add_column("industry_pulse_instruments", sa.Column("constituent_role", sa.String(24), nullable=True))
    op.add_column("industry_pulse_instruments", sa.Column("enabled_for_pulse", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("industry_pulse_instruments", sa.Column("valid_from", sa.Date(), nullable=True))
    op.add_column("industry_pulse_instruments", sa.Column("valid_to", sa.Date(), nullable=True))
    if op.get_bind().dialect.name != "sqlite":
        op.create_check_constraint("ck_industry_pulse_instruments_classification_source", "industry_pulse_instruments", "classification_source IN ('MANUAL', 'ETF_HOLDING', 'AI_CLASSIFIED', 'PROVIDER', 'INHERITED')")
    op.create_index("ix_industry_pulse_instruments_classification_source", "industry_pulse_instruments", ["classification_source"])
    op.create_index("ix_industry_pulse_instruments_enabled_for_pulse", "industry_pulse_instruments", ["enabled_for_pulse"])
    op.create_index("ix_industry_pulse_instruments_node_pulse", "industry_pulse_instruments", ["node_id", "enabled_for_pulse"])
    op.execute("""
        UPDATE industry_pulse_instruments
        SET classification_source = CASE WHEN mapping_type = 'etf_proxy' THEN 'MANUAL' ELSE 'PROVIDER' END,
            constituent_role = CASE WHEN mapping_type = 'etf_proxy' THEN 'PROXY' WHEN mapping_type = 'theme_exposure' THEN 'SECONDARY' ELSE NULL END,
            enabled_for_pulse = CASE WHEN mapping_type = 'etf_proxy' AND role IN ('primary', 'secondary') THEN enabled ELSE false END
    """)
    op.create_table(
        "industry_pulse_classification_cache",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("metadata_hash", sa.String(64), nullable=False),
        sa.Column("taxonomy_version", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_industry_pulse_classification_cache_metadata_hash", "industry_pulse_classification_cache", ["metadata_hash"])
    op.create_index("ix_industry_pulse_classification_cache_status", "industry_pulse_classification_cache", ["status"])


def downgrade() -> None:
    op.drop_index("ix_industry_pulse_classification_cache_status", table_name="industry_pulse_classification_cache")
    op.drop_index("ix_industry_pulse_classification_cache_metadata_hash", table_name="industry_pulse_classification_cache")
    op.drop_table("industry_pulse_classification_cache")
    op.drop_index("ix_industry_pulse_instruments_node_pulse", table_name="industry_pulse_instruments")
    op.drop_index("ix_industry_pulse_instruments_enabled_for_pulse", table_name="industry_pulse_instruments")
    op.drop_index("ix_industry_pulse_instruments_classification_source", table_name="industry_pulse_instruments")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("ck_industry_pulse_instruments_classification_source", "industry_pulse_instruments", type_="check")
    for name in ("valid_to", "valid_from", "enabled_for_pulse", "constituent_role", "source_etf", "classification_source"):
        op.drop_column("industry_pulse_instruments", name)
