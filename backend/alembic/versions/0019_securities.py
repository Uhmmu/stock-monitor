"""canonical securities and provider symbols

Revision ID: 0019_securities
Revises: 0018_temporary_snapshots
"""

from alembic import op
import sqlalchemy as sa

revision = "0019_securities"
down_revision = "0018_temporary_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_symbol", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(256)), sa.Column("local_symbol", sa.String(32)),
        sa.Column("exchange_code", sa.String(32)), sa.Column("exchange_name", sa.String(128)),
        sa.Column("mic_code", sa.String(16)), sa.Column("market", sa.String(32)),
        sa.Column("country_code", sa.String(2)), sa.Column("currency", sa.String(8)),
        sa.Column("instrument_type", sa.String(32)), sa.Column("isin", sa.String(32)),
        sa.Column("yahoo_symbol", sa.String(32)), sa.Column("finnhub_symbol", sa.String(32)),
        sa.Column("yahoo_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("finnhub_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("mapping_confidence", sa.Float()),
        sa.Column("mapping_method", sa.String(32), nullable=False, server_default="unresolved"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("yahoo_symbol", name="uq_securities_yahoo_symbol"),
        sa.UniqueConstraint("finnhub_symbol", name="uq_securities_finnhub_symbol"),
        sa.CheckConstraint("yahoo_symbol IS NOT NULL OR finnhub_symbol IS NOT NULL", name="ck_securities_provider_symbol"),
    )
    for column in ("display_symbol", "display_name", "local_symbol", "exchange_code", "market", "country_code", "instrument_type", "isin", "yahoo_symbol", "finnhub_symbol"):
        op.create_index(f"ix_securities_{column}", "securities", [column])
    # Preserve every existing ticker as a Yahoo-backed compatibility security.
    op.execute(sa.text("""
        INSERT INTO securities (display_symbol, display_name, local_symbol, yahoo_symbol, yahoo_status, finnhub_status, mapping_method)
        SELECT ticker, COALESCE(MAX(company_name), ticker), split_part(ticker, '.', 1), ticker, 'available', 'unknown', 'unresolved'
        FROM (
          SELECT ticker, NULL::varchar AS company_name FROM watchlist_items
          UNION ALL SELECT ticker, NULL::varchar FROM temporary_snapshots
          UNION ALL SELECT base_ticker, NULL::varchar FROM peer_relations
          UNION ALL SELECT peer_ticker, NULL::varchar FROM peer_relations
          UNION ALL SELECT ticker, company_name FROM stock_profiles
        ) legacy GROUP BY ticker ON CONFLICT (yahoo_symbol) DO NOTHING
    """))
    op.add_column("watchlist_items", sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL")))
    op.add_column("temporary_snapshots", sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL")))
    op.add_column("peer_relations", sa.Column("peer_security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL")))
    for table, column, symbol_column in (("watchlist_items", "security_id", "ticker"), ("temporary_snapshots", "security_id", "ticker"), ("peer_relations", "peer_security_id", "peer_ticker")):
        op.create_index(f"ix_{table}_{column}", table, [column])
        op.execute(sa.text(f"UPDATE {table} SET {column}=securities.id FROM securities WHERE {table}.{symbol_column}=securities.yahoo_symbol"))


def downgrade():
    for table, column in (("peer_relations", "peer_security_id"), ("temporary_snapshots", "security_id"), ("watchlist_items", "security_id")):
        op.drop_column(table, column)
    op.drop_table("securities")
