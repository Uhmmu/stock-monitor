from app.services.llm import (
    MOVEMENT_SYSTEM_PROMPT,
    POST_EARNINGS_SYSTEM_PROMPT,
    POSTMARKET_SYSTEM_PROMPT,
    PRE_EARNINGS_SYSTEM_PROMPT,
    PREMARKET_SYSTEM_PROMPT,
    get_system_prompt,
)


def test_report_type_prompt_routing():
    expected = {
        "movement": MOVEMENT_SYSTEM_PROMPT,
        "premarket": PREMARKET_SYSTEM_PROMPT,
        "postmarket": POSTMARKET_SYSTEM_PROMPT,
        "earnings_before": PRE_EARNINGS_SYSTEM_PROMPT,
        "earnings_after": POST_EARNINGS_SYSTEM_PROMPT,
    }
    for report_type, prompt in expected.items():
        routed = get_system_prompt(report_type)
        assert routed.startswith(prompt)
        assert "不得输出模板占位符" in routed
        assert "不构成投资建议" in routed


def test_unknown_report_type_uses_safe_default():
    prompt = get_system_prompt("unknown")
    assert "严谨的美股信息分析员" in prompt
    assert "输入未提供" in prompt
