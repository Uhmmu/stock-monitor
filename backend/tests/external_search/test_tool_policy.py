from app.ai.tool_selector import ToolSelector
from app.ai_tools.adapters.external_search import build_external_search_adapters
from app.ai_tools.registry import ToolRegistry
from app.external_search.enums import WebAccessMode


def selector():
    registry = ToolRegistry()
    for adapter in build_external_search_adapters():
        registry.register(adapter)
    return ToolSelector(registry)


def selected(mode, message="请核实最新官网公告"):
    return selector().select(
        message=message, page_context=None, active_symbol="MSFT",
        allowed_tools=None, denied_tools=set(), web_access_mode=mode,
    ).tool_names


def test_off_strictly_exposes_no_external_tools():
    assert selected(WebAccessMode.off) == []


def test_normal_search_exposes_only_relevant_search_tools():
    tools = selected(WebAccessMode.search)
    assert 1 <= len(tools) <= 3
    assert "search_latest_news_web" in tools
    assert "search_official_company_sources" in tools
    assert "run_deep_web_research" not in tools


def test_each_deep_mode_exposes_exactly_one_server_controlled_agent_tool():
    for mode in (
        WebAccessMode.deep_minimal, WebAccessMode.deep_low, WebAccessMode.deep_medium,
        WebAccessMode.deep_high, WebAccessMode.deep_xhigh,
    ):
        tools = selected(mode)
        assert tools == ["run_deep_web_research"]
        schema = selector().registry.get("run_deep_web_research").arguments_model.model_json_schema()
        assert "effort" not in schema["properties"]
