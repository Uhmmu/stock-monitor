from __future__ import annotations

import math


def build_trade_plan(positions: list[dict], target_weights: dict[str, float], total_value: float, *, fractional_shares: bool, minimum_trade_amount: float) -> tuple[list[dict], float]:
    rows=[]; rounding_cash=0.0
    for position in positions:
        symbol=position["symbol"]; current_value=float(position["market_value"]); target_value=total_value*target_weights.get(symbol,0.0); theoretical=target_value-current_value; actual=theoretical; rounding_error=0.0; shares=None
        price=position.get("current_price")
        if not fractional_shares:
            if not price or price<=0:
                actual=0.0; rounding_error=theoretical; rounding_cash+=theoretical
            else:
                shares=math.floor(abs(theoretical)/price+1e-12)*(1 if theoretical>=0 else -1)
                actual=shares*price; rounding_error=theoretical-actual; rounding_cash+=rounding_error
        if abs(actual)<minimum_trade_amount:
            rounding_cash+=actual; actual=0.0; shares=0 if shares is not None else None
        action="increase" if actual>1e-8 else "reduce" if actual<-1e-8 else "hold"
        change=target_weights.get(symbol,0)-float(position["market_value"])/total_value
        reasons=[]
        if change<-.02: reasons.append("single_position_concentration")
        if change<0 and position.get("sector") not in (None,"未分类"): reasons.append("sector_concentration")
        if abs(change)>.02: reasons.append("risk_adjusted_reallocation")
        rows.append({"symbol":symbol,"current_weight":float(position["market_value"])/total_value,"target_weight":target_weights.get(symbol,0.0),"weight_change":change,"current_value":current_value,"target_value":target_value,"trade_amount":actual,"fractional_share_change":actual/price if fractional_shares and price else shares,"rounding_error":rounding_error,"action":action,"reason_codes":reasons})
    return rows,rounding_cash
