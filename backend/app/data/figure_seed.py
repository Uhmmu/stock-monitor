"""三位种子人物的档案与持仓基线（用户提供的数据，2026 Q1/Q2 快照）。

金额取披露区间中点；木头姐（fund_manager）用 % 存 baseline，不叠加国会交易。
category: stock/etf/preferred/corp_bond/muni_bond/treasury/option/other
"""

FIGURES = [
    {
        "slug": "trump",
        "display_name": "Donald J. Trump",
        "kind": "politician",
        "kadoa_filer_id": "oge_donald_trump",
        "photo_url": None,
        "note": "行政部门（总统），OGE 披露。持仓为 2026 Q1 快照，金额取区间中点估算。",
        "is_seed": True,
        "baseline_date": "2026-03-31",
    },
    {
        "slug": "pelosi",
        "display_name": "Nancy Pelosi",
        "kind": "politician",
        "kadoa_filer_id": "house_nancy_pelosi",
        "photo_url": "https://unitedstates.github.io/images/congress/225x275/P000197.jpg",
        "note": "众议院。持仓为公开底仓（Genesis Block）估值，金额取区间中点估算。",
        "is_seed": True,
        "baseline_date": "2026-01-31",
    },
    {
        "slug": "cathie_wood",
        "display_name": "Cathie Wood (ARK)",
        "kind": "fund_manager",
        "kadoa_filer_id": None,
        "photo_url": None,
        "note": "ARKK 旗舰基金 2026-05-21 持仓占比（%），非个人交易，不叠加国会数据。",
        "is_seed": True,
        "baseline_date": None,
    },
]

_M1_5 = 3_000_000
_K500_1M = 750_000
_K50_100 = 75_000
_K100_250 = 175_000

# (ticker, asset_name, category, value, note)
TRUMP_POSITIONS = [
    ("DJT", "Trump Media & Technology Group", "stock", 588_000_000, "核心控股"),
    ("NVDA", "NVIDIA Corporation", "stock", _M1_5, None),
    ("DELL", "Dell Technologies Inc.", "stock", _M1_5, None),
    ("AVGO", "Broadcom Inc.", "stock", _M1_5, None),
    ("NOW", "ServiceNow Inc.", "stock", _M1_5, None),
    ("ADBE", "Adobe Inc.", "stock", _M1_5, None),
    ("WDAY", "Workday Inc.", "stock", _M1_5, None),
    ("ORCL", "Oracle Corporation", "stock", _M1_5, None),
    ("MSFT", "Microsoft Corporation", "stock", _M1_5, "净减仓"),
    ("SNPS", "Synopsys Inc.", "stock", _M1_5, None),
    ("CDNS", "Cadence Design Systems", "stock", _M1_5, None),
    ("AXON", "Axon Enterprise Inc.", "stock", _M1_5, None),
    ("TDG", "TransDigm Group Inc.", "stock", _M1_5, None),
    ("BA", "Boeing Company", "stock", _M1_5, None),
    ("CDW", "CDW Corporation", "stock", _M1_5, None),
    ("PG", "Procter & Gamble Co.", "stock", _M1_5, None),
    ("TXN", "Texas Instruments Inc.", "stock", _M1_5, None),
    ("FIS", "Fidelity National Info Services", "stock", _M1_5, None),
    ("MSI", "Motorola Solutions Inc.", "stock", _M1_5, None),
    ("ETN", "Eaton Corp PLC", "stock", _M1_5, None),
    ("TT", "Trane Technologies PLC", "stock", _M1_5, None),
    ("AMZN", "Amazon.com Inc.", "stock", _M1_5, "净减仓"),
    ("JBL", "Jabil Inc.", "stock", _M1_5, None),
    ("COST", "Costco Wholesale Corp", "stock", _M1_5, None),
    ("AAPL", "Apple Inc.", "stock", _M1_5, None),
    ("UBER", "Uber Technologies Inc.", "stock", _M1_5, None),
    ("KURA", "Kura Sushi USA Inc.", "stock", _M1_5, None),
    ("PLTR", "Palantir Technologies", "stock", 440_000, "净买入"),
    ("AMD", "Advanced Micro Devices", "stock", _K50_100, None),
    ("GOOGL", "Alphabet Inc.", "stock", _K500_1M, None),
    ("EQIX", "Equinix Inc.", "stock", _K500_1M, None),
    ("GS", "Goldman Sachs Group", "stock", _K500_1M, None),
    ("DDOG", "Datadog Inc.", "stock", _K500_1M, None),
    ("PM", "Philip Morris International", "stock", _K500_1M, None),
    ("AMAT", "Applied Materials", "stock", _K500_1M, None),
    ("INTC", "Intel Corporation", "stock", _K50_100, None),
    ("SNDK", "SanDisk Corp", "stock", _K50_100, None),
    ("MRVL", "Marvell Technology", "stock", _K50_100, None),
    ("MU", "Micron Technology", "stock", _K50_100, None),
    ("LMT", "Lockheed Martin", "stock", _K100_250, "国防"),
    ("NOC", "Northrop Grumman", "stock", _K100_250, "国防"),
    ("GD", "General Dynamics", "stock", _K100_250, "国防"),
    ("HOOD", "Robinhood Markets Inc.", "stock", _K100_250, None),
    ("COIN", "Coinbase Global Inc.", "stock", _K50_100, None),
    # ETF
    ("VOO", "Vanguard S&P 500 ETF", "etf", _M1_5, None),
    ("IWB", "iShares Russell 1000 ETF", "etf", _M1_5, None),
    ("RSP", "Invesco S&P 500 Equal Weight ETF", "etf", _M1_5, None),
    ("XLI", "Industrial SPDR ETF", "etf", _M1_5, None),
    ("COMT", "iShares Commodity Roll ETF", "etf", _M1_5, None),
    ("IEMG", "iShares Core MSCI Emerging ETF", "etf", _M1_5, None),
    ("SPMO", "Invesco S&P 500 Momentum ETF", "etf", _K500_1M, None),
    ("IAU", "iShares Gold Trust", "etf", _K500_1M, None),
    ("XLE", "Energy Select SPDR", "etf", _K500_1M, None),
    ("IJJ", "iShares Mid Cap Value ETF", "etf", _K500_1M, None),
    # 金融优先股/永续债（普通股 HOOD/COIN 已在上面）
    (None, "Goldman Sachs 7.500% Perp", "preferred", 150_000, None),
    (None, "JPMorgan Chase Perp 6.875%", "preferred", 150_000, None),
    (None, "Bank of America Preferred BACpI", "preferred", 32_500, None),
    (None, "Wells Fargo GG NT 6.125%", "corp_bond", 125_000, "新建仓"),
    (None, "Morgan Stanley Dep 6.625%", "preferred", 57_500, None),
    (None, "PNC Financial 6.250% Perp", "preferred", 75_000, None),
    (None, "Corebridge Financial 优先股", "preferred", 125_000, "新建仓"),
    # 债券桶（无 ticker，聚合估算）
    (None, "市政债组合（130+ 笔，遍布全美）", "muni_bond", 8_000_000, "代表性持仓聚合估算"),
    (None, "企业债核心篮子（Netflix/Sirius/Carnival/CoreWeave 等）", "corp_bond", 5_000_000, "反复建仓聚合"),
    (None, "CoreWeave 9.00% due 2031 / 9.25% due 2030", "corp_bond", 3_000_000, "特别关注"),
    (None, "美国国债 T-Bills（4/16、4/30 到期）", "treasury", 6_000_000, "现金管理"),
]

# 佩洛西 Genesis Block
PELOSI_POSITIONS = [
    ("AAPL", "Apple Inc.", "stock", 5_250_000, "12月卖出后剩余底仓"),
    ("MSFT", "Microsoft Corporation", "stock", 5_000_000, "重仓"),
    ("NVDA", "NVIDIA Corporation", "stock", 5_500_000, "行权补回"),
    ("AMZN", "Amazon.com Inc.", "stock", 5_500_000, "行权补回"),
    ("AB", "AllianceBernstein", "stock", 2_000_000, "1月购入"),
    ("VST", "Vistra Corp.", "stock", 100_000, "1月买入"),
    ("TEM", "Tempus AI", "stock", 50_000, "AI医疗"),
    ("UBER", "UBER Call Option（行权价$50）", "option", 500_000, "5月购入，折算持仓"),
    ("INTC", "INTC Call Option（行权价$50）", "option", 200_000, "5月购入，折算持仓"),
]

# 木头姐 ARKK 持仓占比（%），is_percent=True，不叠加交易
CATHIE_POSITIONS = [
    ("TSLA", "Tesla", "stock", 10.61, None),
    ("COIN", "Coinbase", "stock", 8.19, None),
    ("TEM", "Tempus AI", "stock", 6.27, None),
    ("PLTR", "Palantir", "stock", 5.94, None),
    ("AMD", "Advanced Micro Devices", "stock", 5.09, None),
    ("META", "Meta Platforms", "stock", 4.94, None),
    ("AMZN", "Amazon", "stock", 4.81, None),
    ("CRCL", "Circle", "stock", 4.38, None),
    ("HOOD", "Robinhood", "stock", 4.16, None),
    ("CRSP", "CRISPR Therapeutics", "stock", 3.36, None),
    ("ROKU", "Roku", "stock", 3.27, None),
    ("TWST", "Twist Bioscience", "stock", 2.85, None),
    (None, "其他持仓合计", "other", 35.63, "ARKK 剩余仓位"),
]

# 木头姐近30天调仓（异动看板，纯展示）
CATHIE_MOVES = {
    "buys": ["CBRS (Cerebras Systems) 新建仓", "TEM (Tempus AI)", "COIN (Coinbase)", "META (Meta)", "RKLB (Rocket Lab)"],
    "sells": ["ROKU (Roku)", "ZM (Zoom)", "PATH (UiPath)", "TDOC (Teladoc)", "DNA (Ginkgo Bioworks)"],
}


def all_positions():
    """返回 {slug: (positions_list, is_percent)}。"""
    return {
        "trump": (TRUMP_POSITIONS, False),
        "pelosi": (PELOSI_POSITIONS, False),
        "cathie_wood": (CATHIE_POSITIONS, True),
    }
