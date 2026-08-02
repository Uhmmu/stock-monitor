from datetime import UTC
from decimal import Decimal
from pathlib import Path

from app.integrations.ibkr.flex_parser import parse_flex_report


FIXTURE = Path(__file__).parent / "fixtures" / "ibkr_flex_structure.xml"


def test_typed_flex_parser_preserves_decimal_dates_unknown_and_sections():
    report = parse_flex_report(FIXTURE.read_text())
    assert report.metadata.account_id == "DU000000"
    assert report.metadata.generated_at.tzinfo == UTC
    assert report.records["positions"][0].quantity == Decimal("12.5")
    assert report.records["positions"][0].values["costBasisPrice"] == Decimal("10.125")
    assert report.records["fx_rates"][0].values["rate"] == Decimal("0.006712345678")
    assert report.records["trades"][0].occurred_at.tzinfo == UTC
    assert report.records["orders"][0].source_id != report.records["trades"][0].source_id
    assert report.unknown_sections == {"UnexpectedRecord": 1}


def test_same_report_has_stable_hash_and_source_ids():
    first = parse_flex_report(FIXTURE.read_text())
    second = parse_flex_report(FIXTURE.read_text())
    assert first.source_hash == second.source_hash
    assert first.records["trades"][0].source_id == second.records["trades"][0].source_id
