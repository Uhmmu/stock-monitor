"""Reviewed bootstrap candidates for canonical AI group classification.

Candidates are discovery input, never memberships by themselves.
"""

AI_NODE_SEED_CANDIDATES: dict[str, tuple[str, ...]] = {
    "ai.compute.accelerators": ("NVDA", "AMD", "AVGO", "MRVL", "INTC", "QCOM", "ARM"),
    "ai.compute.semiconductor_production": ("TSM", "ASML", "AMAT", "LRCX", "KLAC", "TER", "ACLS", "ENTG", "MKSI"),
    "ai.compute.memory": ("MU", "SNDK", "WDC", "STX", "SIMO", "RMBS"),
    "ai.compute.semiconductor_design_infrastructure": ("SNPS", "CDNS", "ARM", "RMBS", "CEVA", "LSCC"),
    "ai.infrastructure.servers": ("DELL", "SMCI", "HPE", "IBM", "NTAP", "PSTG", "VRT"),
    "ai.infrastructure.networking": ("ANET", "CSCO", "AVGO", "MRVL", "ALAB", "CRDO", "NOK", "CMBM"),
    "ai.infrastructure.optical": ("COHR", "LITE", "CIEN", "AAOI", "CALX", "GLW", "FN"),
    "ai.infrastructure.data_centers": ("EQIX", "DLR", "IRM", "APLD", "NBIS"),
    "ai.infrastructure.cooling": ("VRT", "TT", "CARR", "JCI", "MOD", "AAON", "FIX"),
    "ai.infrastructure.cloud": ("MSFT", "AMZN", "GOOGL", "ORCL", "IBM", "NET", "NBIS"),
    "ai.power.power_generation": ("CEG", "VST", "NRG", "TLN", "AES", "D"),
    "ai.power.nuclear_fuel_cycle": ("CCJ", "LEU", "UEC", "UUUU", "NXE", "DNN", "URG", "BWXT"),
    "ai.power.grid": ("ETN", "GEV", "HUBB", "PWR", "NVT", "MYRG", "POWL"),
    "ai.power.energy_storage": ("FLNC", "EOSE", "STEM", "TSLA", "ALB", "AES", "ENVX", "QS"),
    "ai.software_and_data.ai_platforms": ("MSFT", "GOOGL", "AMZN", "META", "ORCL", "IBM", "PLTR"),
    "ai.software_and_data.enterprise_ai": ("MSFT", "CRM", "NOW", "ORCL", "SAP", "IBM", "PLTR", "ADBE"),
    "ai.software_and_data.data": ("SNOW", "DDOG", "MDB", "ESTC", "CFLT", "ORCL", "PLTR", "TDC"),
    "ai.software_and_data.cybersecurity": ("PANW", "CRWD", "FTNT", "ZS", "OKTA", "CYBR", "S"),
    "ai.software_and_data.developer_ecosystem": ("MSFT", "GTLB", "NET", "DDOG", "CFLT", "ESTC", "MDB", "DOCN", "TWLO"),
    "ai.applications.robotics": ("ROK", "TER", "ISRG", "SYM", "PATH", "ABB"),
    "ai.applications.autonomous_systems": ("TSLA", "MBLY", "AUR", "QCOM", "NVDA", "AVAV", "KTOS"),
    "ai.applications.healthcare_ai": ("TEM", "RXRX", "SDGR", "GH", "GEHC", "BFLY", "ISRG"),
    "ai.applications.financial_ai": ("SPGI", "ICE", "CME", "IBKR", "HOOD", "SOFI", "XYZ", "PYPL"),
    "ai.applications.defense_ai": ("PLTR", "AVAV", "KTOS", "LHX", "RTX", "NOC", "GD", "LDOS", "BAH"),
    "ai.applications.consumer_ai": ("AAPL", "GOOGL", "META", "AMZN", "MSFT", "ADBE", "DUOL", "SNAP"),
}


def candidates_by_symbol() -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for node, symbols in AI_NODE_SEED_CANDIDATES.items():
        for symbol in symbols:
            result.setdefault(symbol, []).append(node)
    return {symbol: tuple(nodes) for symbol, nodes in result.items()}


__all__ = ["AI_NODE_SEED_CANDIDATES", "candidates_by_symbol"]
