import json
from pathlib import Path

from app.services.industry_pulse.definitions import BASE_LEAVES


DATA = Path(__file__).parents[1] / "app/services/industry_pulse/data"


def test_canonical_seed_registry_and_lifecycle_invariants():
    registry = json.loads((DATA / "leaf_industry_seed_registry.v1.json").read_text())
    replacements = json.loads((DATA / "replacement_required.v1.json").read_text())
    leaves = registry["leaves"]
    memberships = [member for leaf in leaves for member in leaf["memberships"]]
    taxonomy = {row["code"]: row["id"] for row in BASE_LEAVES}

    assert len(taxonomy) == len(leaves) == 229
    assert {leaf["leaf_code"]: leaf["taxonomy_node_id"] for leaf in leaves} == taxonomy
    assert all(len(leaf["memberships"]) == 5 for leaf in leaves)
    assert all(len({member["ticker"] for member in leaf["memberships"]}) == 5 for leaf in leaves)
    assert len(memberships) == 1145
    assert all(member["source"] == "MANUAL_CURATED_SEED" for member in memberships)
    assert len(registry["unique_universe"]) == registry["statistics"]["unique_ticker_count"] == 861
    assert all({"previous_symbol", "current_symbol", "symbol_change_date", "change_reason"} <= row.keys() for row in registry["symbol_lifecycle"])
    assert len(replacements["items"]) == replacements["count"] == 21
    assert all(len(row["current_other_4_constituents"]) == 4 for row in replacements["items"])
