from pydantic import TypeAdapter

from app.ai.conversations.schemas import PAGE_CONTEXTS as CONVERSATION_CONTEXTS
from app.ai.orchestrator import TOOL_DISPLAY_NAMES
from app.ai.schemas import PAGE_CONTEXTS
from app.ai.tool_selector import DOMAIN_RULES, PREFERRED, ToolSelector
from app.ai_tools import tool_registry
from app.api.mood_routes import Range
from app.main import app
from app.tasks.celery_app import celery_app


def test_mood_api_chat_and_scheduler_are_registered():
    assert TypeAdapter(Range).validate_python("20") == "20"
    paths = {route.path for route in app.routes}
    assert {"/api/mood/overview", "/api/mood/report", "/api/mood/history-health", "/api/mood/history-gaps",
            "/api/mood/history-recovery", "/api/mood/{scope_type}/{scope_key}",
            "/api/mood-lab/overview", "/api/mood-lab/runs", "/api/mood-lab/runs/{run_id}/results"} <= paths
    assert PAGE_CONTEXTS == CONVERSATION_CONTEXTS
    assert "mood" in PAGE_CONTEXTS
    assert "情绪台" in DOMAIN_RULES["mood"]
    assert PREFERRED["mood"] == ["get_mood_overview", "get_mood_history", "get_mood_validation"]
    assert {"get_mood_overview", "get_mood_history", "get_mood_validation"} <= {item.name for item in tool_registry.list()}
    assert {"get_mood_overview", "get_mood_validation"} <= TOOL_DISPLAY_NAMES.keys()
    assert celery_app.conf.beat_schedule["sync-mood-due"]["task"] == "app.tasks.celery_app.ensure_mood_fresh"
    assert celery_app.conf.beat_schedule["sync-mood-eod-due"]["task"] == "app.tasks.celery_app.ensure_mood_daily"
    assert "app.tasks.celery_app.sync_daily_mood" in celery_app.tasks
    assert "app.tasks.celery_app.run_mood_validation" in celery_app.tasks


def test_mood_page_context_selects_only_persisted_semantic_tools():
    selected = ToolSelector(tool_registry).select(
        message="哪些板块开始拥挤，哪里出现价格和广度分歧？",
        page_context="mood",
        active_symbol=None,
        allowed_tools=None,
        denied_tools=set(),
    )
    assert "get_mood_overview" in selected.tool_names
    assert "get_mood_history" in selected.tool_names
    assert "get_mood_validation" in selected.tool_names
    assert not any("search" in name for name in selected.tool_names)
