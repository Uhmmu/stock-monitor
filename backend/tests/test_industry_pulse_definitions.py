from app.services.industry_pulse.definitions import (
    AI_CATEGORIES,
    AI_GROUPS,
    AI_NODES,
    AI_RELATIONS,
    AI_TAXONOMY,
    AI_TAXONOMY_BY_ID,
    BASE_GROUPS,
    BASE_LEAVES,
    BASE_SECTORS,
    BASE_TAXONOMY,
    BASE_TAXONOMY_BY_ID,
    CLASSIFICATION_SEEDS,
    ETF_MAPPINGS,
    ETF_REGISTRY,
    PULSE_ROLES,
    REGISTRY_ROLES,
    THEME_INCLUSION_THRESHOLD,
    is_exposure_included,
    pulse_mappings,
)


def test_base_taxonomy_counts_ids_and_parent_refs():
    assert (len(BASE_SECTORS), len(BASE_GROUPS), len(BASE_LEAVES)) == (11, 50, 229)
    assert len(BASE_TAXONOMY) == 290
    assert len({row["id"] for row in BASE_TAXONOMY}) == len(BASE_TAXONOMY)
    for row in BASE_TAXONOMY:
        if row["parent_id"]:
            assert row["parent_id"] in BASE_TAXONOMY_BY_ID
    assert all(row["level"] == 1 for row in BASE_SECTORS)
    assert all(row["level"] == 2 for row in BASE_GROUPS)
    assert all(row["level"] == 3 for row in BASE_LEAVES)


def test_ai_taxonomy_counts_ids_and_relation_refs():
    assert (len(AI_CATEGORIES), len(AI_GROUPS), len(AI_NODES)) == (5, 25, 92)
    assert len(AI_TAXONOMY) == 122
    assert len({row["id"] for row in AI_TAXONOMY}) == len(AI_TAXONOMY)
    for row in AI_TAXONOMY:
        if row["parent_id"]:
            assert row["parent_id"] in AI_TAXONOMY_BY_ID
    for relation in AI_RELATIONS:
        assert relation["source_id"] in AI_TAXONOMY_BY_ID or relation["source_id"].startswith("base.")
        assert relation["target_id"] in AI_TAXONOMY_BY_ID or relation["target_id"].startswith("base.")
        assert relation["relation"] in {"parent", "downstream", "upstream", "child", "related"}


def test_every_taxonomy_node_has_a_chinese_display_name():
    allowed_acronyms = {"AI", "GPU", "ASIC", "CPU", "HBM", "DRAM", "NAND", "EDA", "IP", "PC", "SaaS", "IT", "ERP", "CRM", "RNA", "CRO", "LNG", "HVAC", "REIT", "SMR", "IPP", "IaaS", "PaaS", "CI", "CD", "ADAS", "FinTech", "DevTools"}
    for row in BASE_TAXONOMY + AI_TAXONOMY:
        tokens = set(re.findall(r"[A-Za-z][A-Za-z-]*", row["name_zh"]))
        assert row["name_zh"]
        assert row["name_zh"] != row["name"] or tokens <= allowed_acronyms
        assert tokens <= allowed_acronyms


def test_etf_registry_is_deduplicated_and_mappings_are_bounded():
    assert len(ETF_REGISTRY) == 64
    assert set(ETF_REGISTRY) == {row["ticker"] for row in ETF_REGISTRY.values()}
    for ticker, row in ETF_REGISTRY.items():
        assert ticker == ticker.upper() and row["instrument_class"] == "equity_etf"
        assert row["provider_priority"][:2] == ("yfinance", "finnhub")
        assert row["role"] in REGISTRY_ROLES or row["role"] is None
        for mapping in row["mappings"]:
            assert mapping["role"] in REGISTRY_ROLES
            assert 0 <= mapping["purity"] <= 1
            assert 0 <= mapping["exposure_weight"] <= 1
            assert 0 <= mapping["confidence"] <= 1
            assert mapping["coverage_quality"] in {"high", "medium", "low", "unavailable"}
    assert all(
        mapping["role"] not in PULSE_ROLES
        for row in ETF_REGISTRY.values()
        for mapping in row["mappings"]
        if mapping["role"] in {"benchmark", "reference"}
    )
    level_one = {row["id"] for row in BASE_SECTORS}
    primary_level_one = {
        mapping["node_id"]
        for mapping in ETF_MAPPINGS
        if mapping["role"] == "primary" and mapping["node_id"] in level_one
    }
    assert primary_level_one == level_one


def test_exposure_threshold_and_msft_identity():
    assert is_exposure_included(THEME_INCLUSION_THRESHOLD)
    assert not is_exposure_included(THEME_INCLUSION_THRESHOLD - 0.01)
    assert not is_exposure_included(None)
    for seed in CLASSIFICATION_SEEDS.values():
        assert set(seed["theme_exposures"]) <= set(AI_TAXONOMY_BY_ID)
        assert all(
            key in AI_TAXONOMY_BY_ID
            for key, weight in seed["theme_exposures"].items()
            if is_exposure_included(weight)
        )
    msft = CLASSIFICATION_SEEDS["MSFT"]
    assert msft["primary_industry"] == "base.technology.software.enterprise_software"
    assert "semiconductors" not in msft["primary_industry"]
    assert not is_exposure_included(msft["theme_exposures"]["ai.compute"])


def test_smr_uranium_nuclear_and_utilities_boundaries():
    assert CLASSIFICATION_SEEDS["SMR"]["primary_industry"].endswith("advanced_nuclear_smr")
    assert "uranium_mining" not in CLASSIFICATION_SEEDS["SMR"]["primary_industry"]
    assert any("uranium_mining" in mapping["node_id"] for mapping in ETF_REGISTRY["URA"]["mappings"])
    assert all("uranium_mining" not in mapping["node_id"] for mapping in ETF_REGISTRY["NLR"]["mappings"])
    assert ETF_REGISTRY["XLU"]["role"] == "benchmark"
    assert all("advanced_nuclear" not in mapping["node_id"] for mapping in ETF_REGISTRY["XLU"]["mappings"])
import re
