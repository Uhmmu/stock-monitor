"""Persistent user strategy preferences and built-in editable presets.

This module owns preference configuration only. It deliberately knows nothing
about health scoring so objective analysis stays independent.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PortfolioStrategyProfile

from .schemas import PortfolioStrategyProfileUpdate


STRATEGY_CHOICES = {
    "strategy_type": [
        {"value": "quality_growth", "label": "质量成长"},
        {"value": "growth", "label": "成长"},
        {"value": "value", "label": "价值"},
        {"value": "income", "label": "收益"},
        {"value": "index", "label": "指数"},
        {"value": "custom", "label": "自定义"},
    ],
    "risk_tolerance": [
        {"value": "conservative", "label": "稳健"},
        {"value": "balanced", "label": "平衡"},
        {"value": "aggressive", "label": "进取"},
    ],
    "investment_horizon": [
        {"value": "short_term", "label": "短期（1 年以内）"},
        {"value": "medium_term", "label": "中期（1–3 年）"},
        {"value": "long_term", "label": "长期（3 年以上）"},
    ],
    "valuation_preference": [
        {"value": "strict", "label": "估值纪律优先"},
        {"value": "balanced", "label": "质量与估值平衡"},
        {"value": "flexible", "label": "可接受成长溢价"},
    ],
    "preferred_regions": [
        {"value": "global", "label": "全球"},
        {"value": "north_america", "label": "北美"},
        {"value": "greater_china", "label": "大中华区"},
        {"value": "europe", "label": "欧洲"},
        {"value": "japan", "label": "日本"},
        {"value": "asia_pacific", "label": "亚太（不含大中华区与日本）"},
        {"value": "emerging_markets", "label": "新兴市场"},
    ],
    "preferred_market_caps": [
        {"value": "mega", "label": "超大盘"},
        {"value": "large", "label": "大盘"},
        {"value": "mid", "label": "中盘"},
        {"value": "small", "label": "小盘"},
        {"value": "micro", "label": "微盘"},
    ],
}


STRATEGY_PRESETS = {
    "quality_growth": {
        "strategy_type": "quality_growth", "investment_horizon": "long_term",
        "risk_tolerance": "balanced", "max_single_position": 25.0,
        "max_theme_exposure": 40.0, "valuation_preference": "balanced",
        "minimum_quality_score": 70.0, "preferred_regions": ["north_america"],
        "preferred_market_caps": ["large", "mid"],
    },
    "growth": {
        "strategy_type": "growth", "investment_horizon": "long_term",
        "risk_tolerance": "aggressive", "max_single_position": 25.0,
        "max_theme_exposure": 45.0, "valuation_preference": "flexible",
        "minimum_quality_score": 60.0, "preferred_regions": ["global"],
        "preferred_market_caps": ["large", "mid", "small"],
    },
    "value": {
        "strategy_type": "value", "investment_horizon": "long_term",
        "risk_tolerance": "balanced", "max_single_position": 20.0,
        "max_theme_exposure": 35.0, "valuation_preference": "strict",
        "minimum_quality_score": 65.0, "preferred_regions": ["global"],
        "preferred_market_caps": ["large", "mid", "small"],
    },
    "income": {
        "strategy_type": "income", "investment_horizon": "long_term",
        "risk_tolerance": "conservative", "max_single_position": 15.0,
        "max_theme_exposure": 30.0, "valuation_preference": "strict",
        "minimum_quality_score": 65.0, "preferred_regions": ["north_america"],
        "preferred_market_caps": ["large", "mid"],
    },
    "index": {
        "strategy_type": "index", "investment_horizon": "long_term",
        "risk_tolerance": "balanced", "max_single_position": 10.0,
        "max_theme_exposure": 25.0, "valuation_preference": "balanced",
        "minimum_quality_score": 55.0, "preferred_regions": ["global"],
        "preferred_market_caps": ["mega", "large", "mid", "small"],
    },
    "custom": {
        "strategy_type": "custom", "investment_horizon": "long_term",
        "risk_tolerance": "balanced", "max_single_position": 20.0,
        "max_theme_exposure": 35.0, "valuation_preference": "balanced",
        "minimum_quality_score": 65.0, "preferred_regions": ["global"],
        "preferred_market_caps": ["large", "mid"],
    },
}


PROFILE_FIELDS = tuple(STRATEGY_PRESETS["custom"])


def profile_catalog() -> dict:
    return {"presets": deepcopy(STRATEGY_PRESETS), "choices": deepcopy(STRATEGY_CHOICES)}


def get_or_create_strategy_profile(db: Session, user_id: int) -> PortfolioStrategyProfile:
    profile = db.scalar(select(PortfolioStrategyProfile).where(PortfolioStrategyProfile.user_id == user_id))
    if profile is None:
        profile = PortfolioStrategyProfile(user_id=user_id, **deepcopy(STRATEGY_PRESETS["quality_growth"]))
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _allowed(field: str) -> set[str]:
    return {row["value"] for row in STRATEGY_CHOICES[field]}


def _validate(values: dict) -> None:
    for field in ("strategy_type", "investment_horizon", "risk_tolerance", "valuation_preference"):
        if field in values and values[field] not in _allowed(field):
            raise ValueError(f"不支持的策略选项：{values[field]}")
    for field in ("preferred_regions", "preferred_market_caps"):
        if field not in values:
            continue
        if not values[field]:
            raise ValueError("偏好范围至少选择一项")
        if any(value not in _allowed(field) for value in values[field]):
            raise ValueError("偏好范围包含不支持的选项")
        values[field] = list(dict.fromkeys(values[field]))


def update_strategy_profile(
    db: Session, user_id: int, payload: PortfolioStrategyProfileUpdate
) -> PortfolioStrategyProfile:
    profile = get_or_create_strategy_profile(db, user_id)
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    _validate(values)
    for field, value in values.items():
        setattr(profile, field, value)
    profile.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(profile)
    return profile


def reset_strategy_profile(db: Session, user_id: int) -> PortfolioStrategyProfile:
    profile = get_or_create_strategy_profile(db, user_id)
    preset = deepcopy(STRATEGY_PRESETS.get(profile.strategy_type, STRATEGY_PRESETS["custom"]))
    for field, value in preset.items():
        setattr(profile, field, value)
    profile.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(profile)
    return profile
