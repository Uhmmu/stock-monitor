"""Strategy-aware interpretation over an immutable objective health result.

Rules are small, deterministic plug-ins. Future analyzers can append a rule to
``INTERPRETATION_RULES`` without changing the health scoring pipeline or API.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from app.models import PortfolioStrategyProfile

from .strategy_profile import STRATEGY_CHOICES


@dataclass(frozen=True)
class RuleResult:
    item: dict
    recommendation: dict | None = None


RuleEvaluator = Callable[[dict, PortfolioStrategyProfile], RuleResult]


VALUATION_LIMITS = {"strict": 35.0, "balanced": 50.0, "flexible": 65.0}
SEC_LIMITS = {"conservative": 20.0, "balanced": 35.0, "aggressive": 50.0}
REGION_MIN_PREFERRED_WEIGHT = 60.0
REGION_COUNTRIES = {
    "north_america": {"us", "usa", "united states", "canada", "ca", "mexico"},
    "greater_china": {"china", "cn", "hong kong", "hk", "taiwan", "tw", "macau"},
    "europe": {"united kingdom", "uk", "gb", "germany", "france", "italy", "spain", "netherlands", "switzerland", "sweden", "norway", "denmark", "finland", "belgium", "austria", "ireland", "portugal"},
    "japan": {"japan", "jp"},
    "asia_pacific": {"australia", "au", "new zealand", "singapore", "sg", "south korea", "korea", "kr", "india", "in", "indonesia", "thailand", "malaysia", "philippines", "vietnam"},
    "emerging_markets": {"china", "cn", "india", "in", "brazil", "br", "south africa", "za", "indonesia", "mexico", "turkey", "saudi arabia", "uae", "vietnam", "thailand", "malaysia", "philippines"},
}


def _item(rule_id: str, dimension: str, status: str, title: str, message: str, evidence: dict) -> dict:
    return {
        "id": rule_id, "dimension": dimension, "status": status,
        "title": title, "message": message, "evidence": evidence,
    }


def _single_position(health: dict, profile: PortfolioStrategyProfile) -> RuleResult:
    actual = health["concentration"].get("largest_position_weight")
    target = profile.max_single_position
    if actual is None:
        return RuleResult(_item("single_position", "concentration", "unavailable", "单一持仓暂无法判断", "缺少可折算的持仓市值，未对单一持仓上限形成结论。", {"target": target}))
    aligned = actual <= target
    return RuleResult(
        _item(
            "single_position", "concentration", "aligned" if aligned else "caution",
            "单一持仓集中度符合策略" if aligned else "单一持仓超过策略上限",
            f"当前最大单一持仓为 {actual:.1f}%，你的偏好上限为 {target:.1f}%。",
            {"actual": actual, "target": target},
        ),
        None if aligned else {
            "id": "reduce_single_thesis_dependency", "title": "降低单一投资逻辑依赖",
            "reason": f"最大单一持仓高于偏好上限 {actual - target:.1f} 个百分点，单一判断偏差会更明显地影响组合。", "priority": 100,
        },
    )


def _theme_exposure(health: dict, profile: PortfolioStrategyProfile) -> RuleResult:
    sectors = [row for row in health["concentration"].get("sector_weights", []) if row.get("sector") != "未分类"]
    target = profile.max_theme_exposure
    if not sectors:
        return RuleResult(_item("theme_exposure", "theme", "unavailable", "主题暴露暂无法判断", "当前行业分类覆盖不足，未用未知分类推断投资主题。", {"target": target}))
    top = max(sectors, key=lambda row: row.get("weight", 0))
    actual = float(top.get("weight", 0))
    aligned = actual <= target
    return RuleResult(
        _item(
            "theme_exposure", "theme", "aligned" if aligned else "caution",
            "主要主题暴露符合策略" if aligned else "主要主题暴露高于偏好目标",
            f"当前最大已分类行业暴露为 {actual:.1f}%，你的主题上限为 {target:.1f}%。",
            {"actual": actual, "target": target, "classification": top.get("sector")},
        ),
        None if aligned else {
            "id": "diversify_earnings_drivers", "title": "增加盈利驱动因素的多样性",
            "reason": f"最大行业暴露超过偏好目标 {actual - target:.1f} 个百分点，行业共同因素可能同时影响多项持仓。", "priority": 95,
        },
    )


def _fundamental_quality(health: dict, profile: PortfolioStrategyProfile) -> RuleResult:
    component = health["fundamental_quality"]
    actual, target = component.get("score"), profile.minimum_quality_score
    if actual is None or component.get("coverage_weight", 0) < 60:
        return RuleResult(_item("fundamental_quality", "quality", "unavailable", "基本面门槛暂无法判断", "基本面覆盖不足 60%，避免用不完整数据判断是否达到策略门槛。", {"target": target, "coverage": component.get("coverage_weight", 0)}))
    aligned = actual >= target
    return RuleResult(
        _item(
            "fundamental_quality", "quality", "aligned" if aligned else "caution",
            "基本面质量达到策略门槛" if aligned else "基本面质量低于策略门槛",
            f"覆盖范围内的加权质量得分为 {actual:.0f}，你的最低要求为 {target:.0f}。",
            {"actual": actual, "target": target, "coverage": component.get("coverage_weight", 0)},
        ),
        None if aligned else {
            "id": "reduce_lower_quality_exposure", "title": "降低较低质量资产的组合暴露",
            "reason": f"加权基本面质量低于你的最低要求 {target - actual:.0f} 分，应优先检查质量较弱暴露对整体的拖累。", "priority": 90,
        },
    )


def _valuation(health: dict, profile: PortfolioStrategyProfile) -> RuleResult:
    component = health["valuation_risk"]
    actual = component.get("score")
    target = VALUATION_LIMITS[profile.valuation_preference]
    if actual is None or component.get("coverage_weight", 0) < 60:
        return RuleResult(_item("valuation", "valuation", "unavailable", "估值偏好暂无法判断", "估值覆盖不足 60%，暂不判断当前定价是否符合你的风格。", {"target": target, "coverage": component.get("coverage_weight", 0)}))
    aligned = actual <= target
    return RuleResult(
        _item(
            "valuation", "valuation", "aligned" if aligned else "caution",
            "组合估值符合当前风格" if aligned else "组合估值超出风格容忍度",
            f"组合估值风险为 {actual:.0f}，当前估值偏好的可接受上限为 {target:.0f}。",
            {"actual": actual, "target": target, "preference": profile.valuation_preference},
        ),
        None if aligned else {
            "id": "avoid_similar_valuation_exposure", "title": "避免继续增加相似估值特征的暴露",
            "reason": f"当前估值风险高于所选风格上限 {actual - target:.0f} 分，新增同类高估值暴露会进一步压缩容错空间。", "priority": 85,
        },
    )


def _sec_risk(health: dict, profile: PortfolioStrategyProfile) -> RuleResult:
    component = health["sec_risk"]
    actual = component.get("score")
    target = SEC_LIMITS[profile.risk_tolerance]
    if actual is None or component.get("coverage_weight", 0) < 60:
        return RuleResult(_item("sec_risk", "event_risk", "unavailable", "事件风险偏好暂无法判断", "SEC 覆盖不足 60%，暂不根据缺失数据推断风险容忍度匹配情况。", {"target": target, "coverage": component.get("coverage_weight", 0)}))
    aligned = actual <= target
    return RuleResult(
        _item(
            "sec_risk", "event_risk", "aligned" if aligned else "caution",
            "已披露事件风险符合风险偏好" if aligned else "已披露事件风险高于风险偏好",
            f"结构化 SEC 风险得分为 {actual:.0f}，当前风险偏好的参考上限为 {target:.0f}。",
            {"actual": actual, "target": target, "risk_tolerance": profile.risk_tolerance},
        ),
        None if aligned else {
            "id": "reduce_event_risk_budget", "title": "降低动态事件风险预算",
            "reason": "当前结构化披露风险高于你的风险容忍度，组合对突发公司事件的承受空间较小。", "priority": 80,
        },
    )


def _region_preference(health: dict, profile: PortfolioStrategyProfile) -> RuleResult:
    preferred = profile.preferred_regions or []
    if "global" in preferred:
        return RuleResult(_item("region_preference", "region", "aligned", "区域配置符合全球偏好", "你的策略允许全球配置，因此当前区域分布不受额外约束。", {"preferred_regions": preferred}))
    rows = [row for row in health["concentration"].get("country_weights", []) if row.get("country") != "未分类"]
    if not rows:
        return RuleResult(_item("region_preference", "region", "unavailable", "区域偏好暂无法判断", "当前国家或地区分类覆盖不足，未对区域偏好形成结论。", {"preferred_regions": preferred}))
    allowed = set().union(*(REGION_COUNTRIES.get(region, set()) for region in preferred))
    classified = sum(float(row.get("weight", 0)) for row in rows)
    matched = sum(float(row.get("weight", 0)) for row in rows if str(row.get("country", "")).strip().lower() in allowed)
    matched_ratio = matched / classified * 100 if classified else 0.0
    aligned = matched_ratio >= REGION_MIN_PREFERRED_WEIGHT
    return RuleResult(
        _item(
            "region_preference", "region", "aligned" if aligned else "caution",
            "区域配置符合偏好" if aligned else "区域配置与偏好存在偏离",
            f"已分类区域中有 {matched_ratio:.1f}% 位于你的偏好范围，参考目标为 {REGION_MIN_PREFERRED_WEIGHT:.0f}%。",
            {"actual": round(matched_ratio, 2), "target": REGION_MIN_PREFERRED_WEIGHT, "preferred_regions": preferred},
        ),
        None if aligned else {
            "id": "rebalance_region_exposure", "title": "重新审视区域风险分配",
            "reason": "当前已分类区域暴露与所选偏好偏离，宏观与汇率驱动可能不符合你的预期风险来源。", "priority": 60,
        },
    )


INTERPRETATION_RULES: tuple[RuleEvaluator, ...] = (
    _single_position,
    _theme_exposure,
    _fundamental_quality,
    _valuation,
    _sec_risk,
    _region_preference,
)


def _choice_label(field: str, value: str) -> str:
    return next((row["label"] for row in STRATEGY_CHOICES[field] if row["value"] == value), value)


def build_personalized_interpretation(health: dict, profile: PortfolioStrategyProfile) -> dict:
    results = [rule(health, profile) for rule in INTERPRETATION_RULES]
    items = [result.item for result in results]
    caution_count = sum(item["status"] == "caution" for item in items)
    aligned_count = sum(item["status"] == "aligned" for item in items)
    unavailable = [item["dimension"] for item in items if item["status"] == "unavailable"]
    unavailable.append("market_cap")  # Objective health v1 has no market-cap exposure dimension yet.
    if caution_count == 0 and aligned_count:
        summary = "当前有数据支持的组合特征总体符合你选择的投资策略。"
    elif aligned_count:
        summary = f"组合整体与所选策略部分一致，但仍有 {caution_count} 项偏好目标需要关注。"
    elif caution_count:
        summary = f"当前有 {caution_count} 项组合特征超出所选策略偏好，建议先调整风险预算方向。"
    else:
        summary = "当前数据不足以形成可靠的个性化总体判断。"
    recommendations = sorted(
        (result.recommendation for result in results if result.recommendation),
        key=lambda row: row["priority"], reverse=True,
    )
    if not recommendations and aligned_count:
        recommendations = [{
            "id": "maintain_current_alignment", "title": "维持当前策略匹配度",
            "reason": "当前有数据支持的集中度、质量与风险指标均未超过你设置的偏好边界。", "priority": 20,
        }]
    return {
        "strategy_type": profile.strategy_type,
        "strategy_label": _choice_label("strategy_type", profile.strategy_type),
        "evaluated_at": datetime.now(UTC),
        "items": items,
        "overall_summary": summary,
        "recommendations": recommendations[:4],
        "unavailable_dimensions": list(dict.fromkeys(unavailable)),
    }
