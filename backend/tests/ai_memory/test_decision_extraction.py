from app.ai_memory.decision_extraction import DECISION_SYSTEM_PROMPT


def test_decision_prompt_proposes_from_analysis_without_claiming_user_intent():
    assert "entire supplied sequence" in DECISION_SYSTEM_PROMPT
    assert "even when the user did not" in DECISION_SYSTEM_PROMPT
    assert "never claim the user already chose it" in DECISION_SYSTEM_PROMPT
    assert "never reject merely because" in DECISION_SYSTEM_PROMPT
