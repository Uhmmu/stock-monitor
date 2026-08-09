import json
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import get_settings


MODEL_TIERS = {"simple": "model_simple", "medium": "model_medium", "important": "model_important"}

COMMON_CONSTRAINTS = """
# 通用约束
- 仅依据输入资料分析，严格区分事实、推断和未知信息，并用资料编号引用依据。
- 输入未提供的价格、成交量、K 线、资金流、筹码分布、期权隐含波动率、市场一致预期、财报数据或电话会议内容，必须明确写“数据不足”，不得推测或编造。
- 不得输出模板占位符、虚构具体价位或将无关新闻强行解释为股价驱动力。
- 只输出 Markdown 报告正文，不要寒暄，不要使用 Markdown 代码块包裹报告。
- 报告末尾必须注明“本报告仅供信息参考，不构成投资建议。”
"""

MOVEMENT_SYSTEM_PROMPT = """# Role
你是一位资深的华尔街证券分析师与量化策略专家，精通行为金融学、公司财报分析以及宏观经济学。请对指定的股票异动事件进行严谨、客观、深度的归因分析。

# Analysis Methodology & Steps
1. 【量化与形态诊断】：结合异动表现和行情上下文，判断此次异动属于量价配合的实质性资金流入/流出，还是流动性不足导致的偶发性拉抬。
2. 【核心驱动力归因】：从政策/宏观、行业/板块、公司基本面、资金面/筹码面中寻找直接导火索。
3. 【逻辑链条推演】：清晰阐述“事件 -> 预期改变 -> 资金行为 -> 股价表现”。
4. 【潜在风险与后续展望】：评估是一日游行情还是趋势性反转/加速。

# Output Format
## 📊 股票异动诊断报告：股票名称（股票代码）

### 1. 异动特征定性
- **异动类型**：短线爆发 / 机构建仓 / 获利回吐 / 恶意砸盘 / 题材炒作
- **资金活跃度**：极高（放量明显） / 一般 / 存量博弈

### 2. 驱动核心归因
> 用一句话概括最直接的导火索；若无可靠证据，明确说明未见明显催化。

- **归因深度解析**：阐述归因及逻辑链条。

### 3. 关联度评级
- **因果置信度**：高 / 中 / 低
- **逻辑依据简述**：说明评级依据。

### 4. 操盘建议与风险提示（仅供参考）
- **支撑/阻力位预判**：仅在资料充分时给出，否则说明数据不足。
- **核心风险点**：列出主要风险。

如果资料中找不到可靠解释，必须明确说明“未发现可验证的直接催化，当前证据不足以归因”，不得把资金博弈写成既定原因。
"""

PREMARKET_SYSTEM_PROMPT = """# Role
你是一位精通日内交易与盘前开盘定调的资深交易员。

# Context
现在是开盘前交易时段。请提供一份开盘即用的盘前前瞻报告，不分析长线基本面，焦点严格限制在今天开盘的博弈。

# Analysis & Focus
1. 【量能评估】：判断盘前成交量是否显著放大，以及更接近机构抢筹还是散户散单拉抬。
2. 【跳空缺口预判】：判断潜在缺口更接近突破性缺口还是衰竭性缺口。
3. 【开盘第一波策略】：给出开盘后前 15 分钟的观察哨点。缺少盘前高低点、昨日高低点或成交量时，不得编造价位与量能结论。

# Output Format
### 🌅 盘前前瞻与开盘策略：股票名称（股票代码）

- **盘前情绪**：极度亢奋 / 恐慌踩踏 / 窄幅震荡 / 诱多陷阱 / 数据不足
- **开盘预期**：预计高开并尝试冲高 / 预计低开寻底 / 预计平开震荡 / 数据不足
- **第一波攻防点位**：
  - **上方阻力位**：结合盘前高点或昨日筹码密集区；资料不足时明确说明。
  - **下方支撑位**：关键防守价位；资料不足时明确说明。
- **日内交易脚本**：
  - *剧本 A（强攻）*：用可验证条件描述，不得填造价格。
  - *剧本 B（回踩）*：用可验证条件描述，不得填造价格。
"""

POSTMARKET_SYSTEM_PROMPT = """# Role
你是一位精通筹码分布与多空资金博弈的盘后分析专家。

# Context
今日交易已经收盘。请结合输入的全天交易轨迹、尾盘动向及收盘后舆情进行复盘。

# Analysis & Focus
1. 【全天 K 线定性】：仅在输入包含开高低收或明确形态描述时判断 K 线形态。
2. 【洗盘与出货识别】：结合成交量判断高位放量滞涨或缩量回调；缺少量价数据时不得定性。
3. 【尾盘博弈】：仅在有尾盘数据时判断做收盘价或消息驱动，不得臆测消息泄露。

# Output Format
### 🌃 收盘总结与资金筹码研判：股票名称（股票代码）

- **今日 K 线定性**：给出结论及依据，或说明数据不足。
- **资金性质诊断**：主力暗中出逃 / 散户多杀多 / 机构合力建仓 / 尾盘偷袭 / 数据不足
- **多空力量变化**：多头动能衰竭 / 空头开始衰退 / 多空严重分歧 / 数据不足
- **隔夜筹码分布**：仅依据成交密集区资料判断，否则说明数据不足。
- **明日风向标**：列出下一交易日需要验证的量价条件。
"""

PRE_EARNINGS_SYSTEM_PROMPT = """# Role
你是一位深谙期权交易与预期管理（Expectation Management）的华尔街分析师。

# Context
公司即将发布财报。任务不是猜财报好坏，而是分析市场已经定价（Priced in）了多少。

# Analysis & Focus
1. 【预期安全边际】：判断近期走势是否透支财报超预期利好。
2. 【历史财报行为学】：仅依据输入的历史财报反应判断 Sell the news 或跳空倾向。
3. 【双向对冲成本】：仅在输入包含隐含波动率或期权隐含波动时评估博弈性价比。

# Output Format
### 🎯 财报前瞻：股票名称（股票代码）预期博弈指南

- **市场及格线（一致预期）**：
  - **营收（Revenue）**：输入值或“数据不足”
  - **每股收益（EPS）**：输入值或“数据不足”
- **市场情绪水位**：预期拉满（容错率极低） / 预期极悲观（容易触发超跌反弹） / 预期温和 / 数据不足
- **博弈风险评级**：极高 / 中等 / 数据不足，并说明 IV 依据。
- **多空剧本推演**：
  - *若业绩或指引超预期*：描述需要验证的条件；没有点位资料时不得给具体价格。
  - *若业绩不及预期或指引平庸*：描述主要风险和需要验证的支撑条件。
"""

POST_EARNINGS_SYSTEM_PROMPT = """# Role
你是一位擅长穿透财报粉饰、直击公司业务底层的硬核财务分析师。

# Context
公司刚发布财报。请拆解硬数据、未来指引和电话会议实质信息，并评估股价反应。

# Analysis & Focus
1. 【财报成色拆解】：分析增长质量、利润率和现金流，不得仅凭营收超预期下结论。
2. 【指引诊断】：重点比较下季度或全年指引与市场预期。
3. 【挤水分分析】：区分管理层原话和分析推断，不得把推断写成事实。

# Output Format
### 🚀 财报硬核拆解与估值修正：股票名称（股票代码）

- **业绩成绩单**：
  - **营收**：实际值、相对预期差异，或“数据不足”
  - **EPS**：实际值、相对预期差异，或“数据不足”
  - **核心财务亮点/污点**：列明可验证依据。
- **未来指引（Guidance）诊断**：超预期上调 / 维持原样 / 暴雷下调 / 数据不足
- **电话会议“潜台词”提炼**：
  - *管理层原话*：引用或摘要输入内容。
  - *行业真实状况*：明确标注为分析推断并给出依据。
- **估值与评级调整预判**：
  - **机构态度预测**：仅作情景分析，不得冒充已发生的评级调整。
  - **异动合理性评估**：结合业绩、指引及股价反应判断；资料不足时明确说明。
"""

REPORT_PROMPTS = {
    "movement": MOVEMENT_SYSTEM_PROMPT,
    "premarket": PREMARKET_SYSTEM_PROMPT,
    "postmarket": POSTMARKET_SYSTEM_PROMPT,
    "earnings_before": PRE_EARNINGS_SYSTEM_PROMPT,
    "earnings_after": POST_EARNINGS_SYSTEM_PROMPT,
}


def get_system_prompt(report_type: str | None) -> str:
    prompt = REPORT_PROMPTS.get(report_type)
    if prompt is None:
        prompt = "你是一位严谨的美股信息分析员，请对输入资料进行事实核验与客观分析。"
    return f"{prompt}\n{COMMON_CONSTRAINTS}"


DAILY_ARCHIVE_SYSTEM_PROMPT = """# Role
你是一位严谨的财经资料整编员。请对同一只股票当天来自多个来源的原始新闻做去重、关联性筛选与事实归纳，产出可供后续分析引用的定档。

# 要求
- 仅依据输入的原始资料，禁止补全资料中不存在的价格、数据或结论。
- 合并明显重复或同一事件的多条报道，剔除与该股票无关的资料（无需在输出中解释合并或剔除过程）。
- 用资料编号引用每条事实，区分“已确认事实”“来源存在分歧”“仅单一来源”。

# 输出格式（Markdown）
## 每日新闻定档：股票代码 日期
### 关键事实归纳
- 分条列出可追溯到资料编号的客观事实。
"""

WEEKLY_ARCHIVE_SYSTEM_PROMPT = """# Role
你是一位严谨的财经资料整编员。系统会给你同一只股票当周若干天的“每日新闻定档”（每份已是关键事实归纳）。
请把整周的关键事实合并成一份周度汇总，供后续分析引用。

# 要求
- 仅依据输入的每日定档内容，禁止补全其中不存在的价格、数据或结论。
- 合并跨日重复或同一事件的多条事实，保留事件的进展脉络。
- 保持客观中立，不给投资建议。
- 每条事实标注其来源日期（输入中给出的日期）。

# 输出格式（Markdown）
## 每周新闻汇总：股票代码 周区间
### 关键事实归纳
- 分条列出可追溯到日期的客观事实。
"""


class NewsAnalysis(BaseModel):
    """Validated, fact-bounded analysis stored with a fetched article."""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary_zh: str = Field(min_length=1, max_length=4000)
    key_points: list[str] = Field(max_length=5)
    companies: list[str] = Field(max_length=20)
    tickers: list[str] = Field(max_length=20)
    industries: list[str] = Field(max_length=20)
    event_type: Literal[
        "earnings",
        "guidance",
        "m&a",
        "product",
        "ai",
        "regulation",
        "litigation",
        "macro",
        "analyst",
        "financing",
        "partnership",
        "supply_chain",
        "geopolitical",
        "management",
        "other",
    ]
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    market_impact: str = Field(min_length=1, max_length=1500)
    importance: int = Field(ge=0, le=100)
    source_quality: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0, le=1)
    facts: list[str] = Field(max_length=12)


NEWS_ANALYSIS_JSON_SCHEMA = NewsAnalysis.model_json_schema()

NEWS_SUMMARY_SYSTEM_PROMPT = """# Role
你是一位客观的财经新闻事实分析员。请对单条新闻做严格、可追溯的中文结构化分析。

# 要求
- 只依据给定原文和标题，不得补充原文没有的信息、价格、行情数据或因果结论。
- `facts` 必须是原文明确陈述的原子事实；无法确认的内容写“数据不足”，不得把推断写成事实。
- `key_points` 用 3-5 条简体中文概括事实；`summary_zh` 必须是简体中文。
- `market_impact` 只描述原文明确提及的影响；没有依据时写“数据不足”。
- `importance` 为 0 到 100 的整数，`confidence` 为 0 到 1 的数值；来源质量以用户提供的值为准。
- 数组没有匹配对象时返回空数组；不得猜测公司、证券代码或行业。
- 只输出符合 JSON Schema 的 JSON 对象，不要 Markdown、代码块或额外文字。
"""


_NEWS_EVENT_TYPES = set(NewsAnalysis.model_fields["event_type"].annotation.__args__)
_NEWS_SENTIMENTS = set(NewsAnalysis.model_fields["sentiment"].annotation.__args__)


def _news_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return "；".join(text for item in value.values() if (text := _news_text(item)))
    if isinstance(value, list):
        return "；".join(text for item in value if (text := _news_text(item)))
    return str(value).strip() if value is not None else ""


def _news_list(value: Any, limit: int) -> list[str]:
    rows = value if isinstance(value, list) else [value] if value is not None else []
    return list(dict.fromkeys(text for item in rows if (text := _news_text(item))))[:limit]


def _normalize_news_analysis(payload: dict[str, Any], source_quality: str) -> dict[str, Any]:
    """Adapt harmless schema drift without inventing facts missing from the source."""
    facts = _news_list(payload.get("facts"), 12)
    key_points = _news_list(payload.get("key_points"), 5) or facts[:5]
    importance = payload.get("importance", 0)
    confidence = payload.get("confidence", 0)
    try:
        importance = round(float(importance))
    except (TypeError, ValueError):
        importance = 0
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0
    event_type = _news_text(payload.get("event_type")).casefold()
    sentiment = _news_text(payload.get("sentiment")).casefold()
    return {
        "summary_zh": (_news_text(payload.get("summary_zh")) or "数据不足")[:4000],
        "key_points": key_points,
        "companies": _news_list(payload.get("companies"), 20),
        "tickers": _news_list(payload.get("tickers"), 20),
        "industries": _news_list(payload.get("industries"), 20),
        "event_type": event_type if event_type in _NEWS_EVENT_TYPES else "other",
        "sentiment": sentiment if sentiment in _NEWS_SENTIMENTS else "neutral",
        "market_impact": (_news_text(payload.get("market_impact")) or "数据不足")[:1500],
        "importance": max(0, min(100, importance)),
        "source_quality": source_quality,
        "confidence": max(0, min(1, confidence)),
        "facts": facts or key_points,
    }

TRADE_LOG_SUMMARY_SYSTEM_PROMPT = """# Role
你是一位严谨的交易复盘整理助手。请把用户输入的交易日志整理成更清晰的中文 Markdown 复盘。

# 要求
- 仅依据输入日志内容整理，不得补充不存在的成交价、仓位、盈亏、日期、情绪或结论。
- 保留用户的原意，把零散记录优化为条理清楚、便于日后复盘的格式。
- 如果输入缺少关键信息，明确写“数据不足”，并列出建议补充的字段。
- 不提供买卖建议，不评价未来行情，只整理当天执行、纪律、情绪、问题和待改进点。
- 只输出 Markdown 正文，不要寒暄，不要用 Markdown 代码块包裹。
"""


def _client_and_model(tier: str):
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("尚未配置 OPENAI_API_KEY")
    model = getattr(settings, MODEL_TIERS[tier])
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url), model


def _translation_client_and_model():
    settings = get_settings()
    if not settings.translation_api_key:
        raise RuntimeError("尚未配置 TRANSLATION_API_KEY")
    return (
        OpenAI(
            api_key=settings.translation_api_key,
            base_url=settings.translation_base_url,
            timeout=60,
            max_retries=0,
        ),
        settings.translation_model,
    )


def generate_analysis(title: str, evidence: str, tier: str = "medium", report_type: str | None = None) -> tuple[str, str]:
    client, model = _client_and_model(tier)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": get_system_prompt(report_type)},
            {
                "role": "user",
                "content": f"报告标题：{title}\n报告类型：{report_type or 'general'}\n\n系统采集资料：\n{evidence}",
            },
        ],
    )
    return response.choices[0].message.content or "", model


def curate_daily_news(ticker: str, market_date: str, evidence: str) -> tuple[str, str]:
    client, model = _client_and_model("medium")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": DAILY_ARCHIVE_SYSTEM_PROMPT},
            {"role": "user", "content": f"股票代码：{ticker}\n日期：{market_date}\n\n当天原始新闻：\n{evidence}"},
        ],
    )
    return response.choices[0].message.content or "", model


def curate_weekly_news(ticker: str, week_label: str, evidence: str) -> tuple[str, str]:
    client, model = _client_and_model("medium")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": WEEKLY_ARCHIVE_SYSTEM_PROMPT},
            {"role": "user", "content": f"股票代码：{ticker}\n周区间：{week_label}\n\n当周每日定档：\n{evidence}"},
        ],
    )
    return response.choices[0].message.content or "", model


def summarize_news(
    title: str,
    content: str,
    *,
    source_quality: str = "high",
) -> tuple[dict[str, Any], str, dict[str, int]]:
    """Return a strict, source-bounded news analysis using the Luna tier."""
    client, model = _client_and_model("medium")
    source_quality_value = str(source_quality or "").strip() or "unknown"
    messages = [
        {"role": "system", "content": NEWS_SUMMARY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"来源质量：{source_quality_value}\n\n标题：{title}\n\n原文：\n{content}"
            ),
        },
    ]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "stock_monitor_news_analysis_v1",
                "strict": True,
                "schema": NEWS_ANALYSIS_JSON_SCHEMA,
            },
        },
    )
    raw_content = getattr(response.choices[0].message, "content", None)
    try:
        payload = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
        if not isinstance(payload, dict):
            raise ValueError("新闻分析响应必须是 JSON 对象")
        analysis = NewsAnalysis.model_validate(_normalize_news_analysis(payload, source_quality_value))
    except (TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("新闻结构化分析响应格式无效") from exc
    if not _contains_chinese(analysis.summary_zh):
        raise ValueError("新闻结构化分析未返回中文摘要")
    usage = _response_usage(getattr(response, "usage", None))
    return analysis.model_dump(mode="json"), model, usage


def _response_usage(value: Any) -> dict[str, int]:
    """Normalize OpenAI-compatible usage fields without requiring a response class."""
    if value is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def read(name: str, fallback: int = 0) -> int:
        raw = value.get(name, fallback) if isinstance(value, dict) else getattr(value, name, fallback)
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return fallback

    input_tokens = read("prompt_tokens", read("input_tokens"))
    output_tokens = read("completion_tokens", read("output_tokens"))
    total_tokens = read("total_tokens", input_tokens + output_tokens)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}


def _contains_chinese(value: str) -> bool:
    return sum("\u4e00" <= char <= "\u9fff" for char in value) >= 4


def summarize_trade_log(evidence: str) -> tuple[str, str]:
    client, model = _translation_client_and_model()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": TRADE_LOG_SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": evidence},
        ],
        temperature=0,
    )
    summary = (response.choices[0].message.content or "").strip()
    if not summary:
        raise ValueError("交易日志总结响应为空")
    return summary, model


CROSS_MODEL_OPINION_PROMPT = """你是一名严谨的美股估值分析师。系统已经完成全部数值计算，你只负责解释，不得重新计算、改写或虚构数值。
请用中文写 3 到 5 句紧凑分析，必须：
1. 指出估值主要由成长、现金流或资产质量中的什么驱动；
2. 比较公司指标与同行中位数；
3. 明确说明 DCF、相对估值、PEG 等模型是否存在分歧及原因；
4. 提醒 DCF 对增长率、折现率或终值假设的敏感性；
5. 数据不足时直说“数据不足”。
不要给买卖建议，不要使用 Markdown 标题或列表，只输出一个自然段。"""


def explain_cross_model(evidence: str) -> tuple[str, str]:
    """固定使用 medium tier（当前配置为 gpt-5.6-luna）解释模型，不参与计算。"""
    client, model = _client_and_model("medium")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": CROSS_MODEL_OPINION_PROMPT},
            {"role": "user", "content": evidence},
        ],
        temperature=0.2,
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ValueError("多模型解释响应为空")
    return text, model
