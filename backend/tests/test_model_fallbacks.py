from app.model_fallbacks import fallback_model, model_candidates, model_matches


def test_gpt_56_models_have_claude_fallbacks():
    assert fallback_model("gpt-5.6-luna") == "claude-haiku-4-5-20251001"
    assert fallback_model("gpt-5.6-sol") == "claude-opus-5"
    assert fallback_model("gpt-5.6-terra") == "claude-sonnet-4-6"
    assert fallback_model("gpt-5.4-mini") is None
    assert model_candidates("gpt-5.6-luna") == ("gpt-5.6-luna", "claude-haiku-4-5-20251001")
    assert model_matches("gpt-5.6-luna", "claude-haiku-4-5-20251001")
