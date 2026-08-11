"""Stable Chinese display labels for the canonical pulse taxonomy."""

from __future__ import annotations

import re


_EXACT = {
    "TECHNOLOGY": "信息技术", "COMMUNICATION SERVICES": "通信服务", "CONSUMER DISCRETIONARY": "可选消费",
    "CONSUMER STAPLES": "必需消费", "HEALTHCARE": "医疗保健", "FINANCIALS": "金融",
    "INDUSTRIALS": "工业", "ENERGY": "能源", "MATERIALS": "材料", "UTILITIES & POWER": "公用事业与电力",
    "REAL ESTATE": "房地产", "AI COMPUTE": "AI 算力", "AI INFRASTRUCTURE": "AI 基础设施",
    "AI POWER": "AI 电力", "AI SOFTWARE & DATA": "AI 软件与数据", "AI APPLICATIONS": "AI 应用",
    "Semiconductors": "半导体", "Technology Hardware": "科技硬件", "IT Services": "信息技术服务",
    "Internet Platforms": "互联网平台", "Media & Entertainment": "媒体与娱乐", "Telecommunications": "电信",
    "Consumer Products": "消费品", "Household & Personal": "家居与个人用品", "Staples Retail": "必需品零售",
    "Medical Technology": "医疗科技", "Life Science Tools": "生命科学工具", "Healthcare Services": "医疗服务",
    "Capital Markets": "资本市场", "Asset Management": "资产管理", "Payments & FinTech": "支付与金融科技",
    "Consumer Finance": "消费金融", "Aerospace & Defense": "航空航天与国防", "Electrical Equipment": "电气设备",
    "Construction & Infrastructure": "建筑与基础设施", "Commercial Services": "商业服务", "Oil & Gas": "石油与天然气",
    "Emerging Energy": "新兴能源", "Metals & Mining": "金属与采矿", "Electric Utilities": "电力公用事业",
    "Independent Power": "独立发电", "Nuclear Power": "核电", "Renewable Generation": "可再生能源发电",
    "Other Utilities": "其他公用事业", "Digital Infrastructure": "数字基础设施", "Commercial Real Estate": "商业地产",
    "Specialized Real Estate": "专业地产", "Semiconductor Production": "半导体制造", "Semiconductor Design Infrastructure": "半导体设计基础设施",
    "Data Centers": "数据中心", "Power Generation": "电力生产", "Nuclear Fuel Cycle": "核燃料循环",
    "Energy Storage": "储能", "AI Platforms": "AI 平台", "Enterprise AI": "企业级 AI", "Developer Ecosystem": "开发者生态",
    "Autonomous Systems": "自主系统", "Healthcare AI": "医疗 AI", "Financial AI": "金融 AI", "Defense AI": "国防 AI",
    "Consumer AI": "消费级 AI", "Foundation Model Ecosystem": "基础模型生态", "High-speed Interconnect": "高速互连",
    "Independent Power Producers": "独立发电商", "Traditional Asset Managers": "传统资产管理机构",
    "Alternative Asset Managers": "另类资产管理机构", "Defense Prime Contractors": "国防主承包商",
    "Building-related Consumer Products": "住宅建筑相关消费品", "Money Center Banks": "大型货币中心银行",
    "Market Data / Ratings": "市场数据与评级", "Property & Casualty": "财产与意外保险",
    "Integrated Device Manufacturers": "集成器件制造商", "Contract Electronics Manufacturing": "电子制造服务",
    "Artificial Intelligence": "人工智能", "Large-cap Biotech": "大型生物科技", "Advanced Nuclear / SMR": "先进核能 / SMR",
    "Industrial / Logistics REIT": "工业与物流 REIT", "Fiber / Digital Infrastructure": "光纤与数字基础设施",
    "Search / Assistants": "搜索与智能助手", "Risk / Data": "风险与数据", "Gene / Cell Therapy": "基因与细胞治疗",
    "RNA / Genetic Medicine": "RNA 与遗传医学", "Drones / Unmanned Systems": "无人机与无人系统",
    "AI Accelerators / GPU / High Performance Compute": "AI 加速器 / GPU / 高性能计算",
    "Memory / DRAM / NAND / HBM": "存储芯片 / DRAM / NAND / HBM", "EDA / Semiconductor IP": "EDA / 半导体 IP",
}

_WORDS = {
    "Accelerators": "加速器", "Accelerator": "加速器", "Advanced": "先进", "Advertising": "广告", "Agricultural": "农业",
    "Airlines": "航空公司", "Alcoholic": "酒精", "Alternative": "替代", "Aluminum": "铝", "Analog": "模拟",
    "Analytics": "分析", "Applications": "应用", "Application": "应用", "Apparel": "服装", "Appliances": "家电",
    "Apartment": "公寓", "Automakers": "汽车制造商", "Automation": "自动化", "Automotive": "汽车",
    "Autonomous": "自动驾驶", "Banks": "银行", "Bank": "银行", "Battery": "电池", "Beauty": "美容",
    "Beverage": "饮品", "Beverages": "饮品", "Biotech": "生物科技", "Biotechnology": "生物技术", "Broadband": "宽带",
    "Brokers": "经纪商", "Building": "建筑", "Care": "护理", "Card": "银行卡", "Cards": "信用卡",
    "Casinos": "赌场", "Center": "中心", "Centers": "中心", "Chemicals": "化学品", "Chips": "芯片",
    "Cloud": "云", "Clinics": "诊所", "Clubs": "会员店", "Coal": "煤炭", "Coffee": "咖啡",
    "Commodity": "大宗商品", "Communications": "通信", "Components": "组件", "Computing": "计算", "Connectors": "连接器",
    "Construction": "建筑", "Consulting": "咨询", "Consumer": "消费", "Cooling": "冷却", "Copper": "铜",
    "Creator": "创作者", "Credit": "信贷", "Cybersecurity": "网络安全", "Data": "数据", "Database": "数据库",
    "Defense": "国防", "Delivery": "配送", "Design": "设计", "Developer": "开发者", "Development": "开发",
    "Devices": "设备", "Device": "器械", "Diagnostics": "诊断", "Diabetes": "糖尿病", "Digital": "数字化",
    "Distribution": "分销", "Diversified": "多元化", "Drinks": "饮料", "Driving": "驾驶", "Drugs": "药品",
    "Earths": "稀土", "Economy": "经济", "Electric": "电力", "Electrical": "电气", "Electronics": "电子",
    "Electronic": "电子", "Endpoint": "终端", "Energy": "能源", "Engineering": "工程", "Enrichment": "浓缩",
    "Enterprise": "企业", "Entertainment": "娱乐", "Environmental": "环保", "Equipment": "设备", "Equity": "股权投资",
    "Exchanges": "交易所", "Exploration": "勘探", "Factory": "工厂", "Fiber": "光纤", "Film": "电影",
    "Finance": "金融", "Financial": "金融", "Fixed": "固定", "Food": "食品", "Footwear": "鞋履",
    "Forest": "林产品", "Foundry": "晶圆代工", "Fuels": "燃料", "Furniture": "家具", "Gaming": "游戏",
    "Gas": "天然气", "Generation": "发电", "Generic": "仿制", "Genetic": "遗传", "Genomics": "基因组学",
    "Gold": "黄金", "Goods": "商品", "Grid": "电网", "Grocery": "食品杂货", "Hardware": "硬件",
    "Health": "健康", "Healthcare": "医疗保健", "Heavy": "重型", "Home": "家居", "Homebuilders": "住宅建筑商",
    "Hospitals": "医院", "Hotel": "酒店", "Hotels": "酒店", "Housing": "住房", "Humanoid": "人形",
    "Hydrogen": "氢能", "Hydro": "水电", "Hyperscalers": "超大规模云厂商", "Identity": "身份安全",
    "Imaging": "影像", "Improvement": "家装", "Industrial": "工业", "Industrials": "工业", "Infrastructure": "基础设施",
    "Ingredients": "食品配料", "Insurance": "保险", "Integrated": "综合", "Interconnect": "互连", "Internet": "互联网",
    "Investment": "投资", "Iron": "铁", "Laboratory": "实验室", "Lake": "湖仓", "Large": "大型",
    "Leisure": "休闲", "Lending": "借贷", "Life": "人寿", "Liquid": "液冷", "Lithium": "锂",
    "Logistics": "物流", "Luxury": "奢侈品", "Machinery": "机械", "Managed": "管理式", "Management": "管理",
    "Manufactured": "预制式", "Manufacturers": "制造商", "Manufacturing": "制造", "Materials": "材料", "Meat": "肉类",
    "Media": "媒体", "Medical": "医疗", "Medicine": "医学", "Memory": "存储", "Merchant": "市场化",
    "Metallurgical": "冶金", "Metals": "金属", "Midstream": "中游", "Mining": "采矿", "Mixed": "混合信号",
    "Mobile": "移动", "Mortgage": "抵押贷款", "Music": "音乐", "Natural": "天然", "Network": "网络",
    "Networking": "网络", "Nickel": "镍", "Nicotine": "尼古丁", "Nuclear": "核能", "Observability": "可观测性",
    "Office": "办公", "Oilfield": "油田", "Oil": "石油", "Online": "在线", "Operators": "运营商",
    "Optical": "光通信", "Other": "其他", "Outsourcing": "外包", "Packaging": "包装", "Packaged": "包装",
    "Paper": "纸业", "Parts": "零部件", "Payment": "支付", "Payments": "支付", "Personal": "个人护理",
    "Pharma": "制药", "Pharmaceuticals": "制药", "Pharmacy": "药房", "Pipelines": "管道", "Platforms": "平台",
    "Platform": "平台", "Power": "电力", "Precision": "精密", "Private": "私募", "Processors": "处理商",
    "Products": "产品", "Producers": "生产商", "Production": "生产", "Professional": "专业", "Protein": "蛋白",
    "Publishing": "出版", "Railroads": "铁路", "Rare": "稀有", "Ratings": "评级", "Recreation": "休闲娱乐",
    "Refining": "炼化", "Regional": "区域", "Regulated": "受监管", "Reinsurance": "再保险", "Renewable": "可再生能源",
    "Rental": "租赁", "Research": "研发服务", "Residential": "住宅", "Resorts": "度假村", "Restaurants": "餐饮",
    "Retail": "零售", "Robotics": "机器人", "Satellite": "卫星", "Science": "科学", "Security": "安防",
    "Semiconductor": "半导体", "Sequencing": "测序", "Servers": "服务器", "Server": "服务器", "Services": "服务",
    "Shipping": "航运", "Silver": "白银", "Smartphones": "智能手机", "Social": "社交", "Soft": "软性",
    "Software": "软件", "Solar": "太阳能", "Space": "航天", "Specialty": "专业", "Specialized": "专业",
    "Sports": "体育", "Staffing": "人力资源", "Staples": "必需品", "Steel": "钢铁", "Storage": "存储",
    "Streaming": "流媒体", "Surgical": "手术", "Switches": "交换机", "Switchgear": "开关设备", "Systems": "系统",
    "Technology": "科技", "Telecom": "电信", "Television": "电视", "Testing": "测试", "Thermal": "动力",
    "Therapy": "治疗", "Tobacco": "烟草", "Tools": "工具", "Tower": "铁塔", "Trading": "交易",
    "Traditional": "传统", "Transformation": "转型", "Transformers": "变压器", "Transmission": "输电", "Transportation": "交通运输",
    "Travel": "旅游", "Trucking": "公路货运", "Uranium": "铀", "Utilities": "公用事业", "Vehicles": "汽车",
    "Vertical": "垂直行业", "Wafer": "晶圆", "Warehouse": "仓储", "Warehouses": "仓储", "Waste": "废弃物",
    "Water": "水务", "Wealth": "财富", "Wind": "风电", "Wireless": "无线", "Workflow": "工作流",
}
_WORDS.update({
    "Aerospace": "航空航天", "Auto": "汽车", "Benefit": "福利", "Booking": "预订", "Cardiovascular": "心血管",
    "Contractors": "承包商", "Custom": "定制", "Discovery": "发现", "Display": "显示", "Drones": "无人机",
    "Drug": "药物", "E-commerce": "电商", "Edge": "边缘", "Emerging": "新兴", "Ethernet": "以太网",
    "Fabless": "无晶圆厂", "Fuel": "燃料", "Gases": "气体", "General": "综合", "Household": "家居",
    "Live": "现场", "Networks": "网络", "Operations": "运营", "Ore": "矿石", "Productivity": "生产力",
    "Rack": "机架", "Search": "搜索", "Sensors": "传感器", "Signal": "信号", "Single-family": "独栋住宅",
})

_ACRONYMS = {"AI", "GPU", "ASIC", "CPU", "HBM", "DRAM", "NAND", "EDA", "IP", "PC", "SaaS", "IT", "ERP", "CRM", "RNA", "CRO", "LNG", "HVAC", "REIT", "SMR", "IPP", "IaaS", "PaaS", "CI", "CD", "ADAS", "FinTech", "DevTools"}


def chinese_name(name: str) -> str:
    if name in _EXACT:
        return _EXACT[name]

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return _WORDS.get(token, token if token in _ACRONYMS else token)

    translated = re.sub(r"[A-Za-z][A-Za-z-]*", replace, name).replace(" & ", "与").replace(" / ", " / ")
    translated = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", translated)
    return translated


__all__ = ["chinese_name"]
