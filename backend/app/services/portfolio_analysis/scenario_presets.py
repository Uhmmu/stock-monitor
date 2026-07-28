from __future__ import annotations

from .schemas import ScenarioDefinition


PRESETS = [
    ScenarioDefinition(code="tech_bear_2022", name="2022 科技股熊市", description="本地覆盖区间内的科技股下跌回放。", mode="historical_replay", start_date="2022-01-03", end_date="2022-10-14"),
    ScenarioDefinition(code="rapid_hikes_2022", name="2022 快速加息", description="快速加息主要阶段真实区间回放。", mode="historical_replay", start_date="2022-03-16", end_date="2022-12-14"),
    ScenarioDefinition(code="ukraine_2022", name="2022 俄乌冲突初期", description="冲突初期市场区间回放。", mode="historical_replay", start_date="2022-02-18", end_date="2022-03-08"),
    ScenarioDefinition(code="regional_banks_2023", name="2023 地区银行危机", description="美国地区银行压力阶段回放。", mode="historical_replay", start_date="2023-03-08", end_date="2023-05-04"),
    ScenarioDefinition(code="financial_crisis_like", name="2008 类金融危机", description="信用收缩、股市下跌和波动上升的代理估算，并非真实持仓回测。", mode="proxy_scenario", market_shock=-.38, sector_shocks={"Financial Services": -.20, "Financials": -.20}, style_shocks={"value": -.05}, interest_rate_change_bp=-150, volatility_change=1.2),
    ScenarioDefinition(code="liquidity_shock_like", name="2020 类流动性冲击", description="短期流动性枯竭代理估算，并非真实持仓回测。", mode="proxy_scenario", market_shock=-.30, volatility_change=1.5),
    ScenarioDefinition(code="growth_repricing", name="科技泡沫破裂", description="成长股估值快速压缩。", mode="proxy_scenario", market_shock=-.22, sector_shocks={"Technology": -.18}, style_shocks={"growth": -.20}, interest_rate_change_bp=100, volatility_change=.8),
    ScenarioDefinition(code="soft_landing", name="软着陆", description="通胀回落且增长保持韧性。", mode="proxy_scenario", market_shock=.08, style_shocks={"growth": .03, "value": .02}, interest_rate_change_bp=-50, volatility_change=-.15),
    ScenarioDefinition(code="recession", name="经济衰退", description="盈利收缩和风险偏好下降。", mode="proxy_scenario", market_shock=-.25, sector_shocks={"Consumer Cyclical": -.10, "Financial Services": -.08}, interest_rate_change_bp=-100, volatility_change=.7),
    ScenarioDefinition(code="inflation_rebound", name="通胀反弹", description="通胀再度上行并推高利率。", mode="proxy_scenario", market_shock=-.12, style_shocks={"growth": -.08, "value": .03}, interest_rate_change_bp=150, currency_shocks={"USD": .05}, volatility_change=.35),
    ScenarioDefinition(code="rapid_cuts", name="快速降息", description="增长走弱背景下的快速降息。", mode="proxy_scenario", market_shock=-.05, style_shocks={"growth": .08}, interest_rate_change_bp=-200, volatility_change=.2),
    ScenarioDefinition(code="ai_continues", name="AI 景气延续", description="AI 投资继续扩张。", mode="proxy_scenario", market_shock=.08, sector_shocks={"Technology": .12, "Semiconductors": .18}, style_shocks={"growth": .06}),
    ScenarioDefinition(code="ai_capex_cools", name="AI 资本开支降温", description="AI 资本开支预期下修。", mode="proxy_scenario", market_shock=-.10, sector_shocks={"Technology": -.12, "Semiconductors": -.22}, style_shocks={"growth": -.08}, volatility_change=.4),
    ScenarioDefinition(code="usd_strength", name="美元走强", description="美元指数快速上升。", mode="proxy_scenario", market_shock=-.04, currency_shocks={"USD": .12}, volatility_change=.15),
    ScenarioDefinition(code="yen_reversal", name="日元反转", description="日元快速升值。", mode="proxy_scenario", currency_shocks={"JPY": .15}, market_shock=-.03, volatility_change=.1),
    ScenarioDefinition(code="semiconductor_drop", name="半导体行业下跌", description="半导体行业独立下跌冲击。", mode="proxy_scenario", market_shock=-.08, sector_shocks={"Semiconductors": -.35, "Technology": -.12}, volatility_change=.5),
]
PRESET_MAP = {preset.code: preset for preset in PRESETS}


def preset_catalog() -> list[dict]:
    return [preset.model_dump(mode="json") for preset in PRESETS]
