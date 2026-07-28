from sqlalchemy.orm import Session

from app.models import Portfolio

from .scenario_presets import PRESET_MAP
from .schemas import ScenarioAnalysisRequest, StressTestRequest
from .stress_test import calculate_stress_test


def calculate_scenario_analysis(db: Session, portfolio: Portfolio, request: ScenarioAnalysisRequest, *, positions_override: list[dict] | None = None) -> dict:
    preset = PRESET_MAP.get(request.scenario_code)
    if preset is None:
        return {"status": "invalid_input", "message": "未知情景预设", "scenario_mode": "proxy_scenario", "confidence": "low"}
    stress = StressTestRequest(
        portfolio_id=request.portfolio_id, scenario_code=preset.code, mode=preset.mode,
        start_date=preset.start_date, end_date=preset.end_date,
        use_fundamental_modifiers=request.use_fundamental_modifiers,
    )
    return calculate_stress_test(db, portfolio, stress, positions_override=positions_override)
