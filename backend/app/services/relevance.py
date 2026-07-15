import json
import re

from openai import OpenAI

from app.config import get_settings

_SYSTEM_PROMPT = """你是财经新闻筛选助手。用户会给出一批带序号的新闻（标题+摘要）。
请对每条新闻，仅依据其与所属股票的基本面/股价的相关程度和情绪倾向打分。

输出严格的 JSON 数组，每个元素形如 {"i": 序号, "rel": 相关性, "sent": 情绪}：
- i：新闻序号，与输入一致。
- rel：相关性，0 到 1。0=与该股票无关或纯营销/水文，1=直接影响该股票基本面或股价的硬新闻。
- sent：情绪，-1 到 1。-1=极度利空，0=中性，1=极度利好。
只输出 JSON 数组本身，不要解释、不要 Markdown 代码块。"""

_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parse(content: str) -> dict[int, tuple[float, float]]:
    match = _JSON_RE.search(content or "")
    if not match:
        raise ValueError("相关性打分响应格式无效")
    scores: dict[int, tuple[float, float]] = {}
    for row in json.loads(match.group(0)):
        idx = int(row["i"])
        rel = max(0.0, min(1.0, float(row["rel"])))
        sent = max(-1.0, min(1.0, float(row["sent"])))
        scores[idx] = (rel, sent)
    return scores


def score_news(ticker: str, items: list[tuple[str, str]]) -> dict[int, tuple[float, float]]:
    """对一批新闻打分。items 为 [(title, summary), ...]，按位置返回 {index: (rel, sent)}。
    多条合并进一个带序号文本，一次请求；超过批大小才分多次。绝不逐条发。"""
    settings = get_settings()
    if not settings.openai_api_key or not items:
        return {}
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url, timeout=60)
    batch = max(1, settings.translation_batch_size)
    result: dict[int, tuple[float, float]] = {}
    for start in range(0, len(items), batch):
        chunk = items[start : start + batch]
        lines = []
        for offset, (title, summary) in enumerate(chunk):
            idx = start + offset
            body = (summary or "").strip().replace("\n", " ")[:400]
            lines.append(f"[{idx}] 标题：{title}\n摘要：{body or '（无摘要）'}")
        payload = f"股票代码：{ticker}\n\n新闻列表：\n" + "\n\n".join(lines)
        response = client.chat.completions.create(
            model=settings.model_simple,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ],
            temperature=0,
        )
        try:
            result.update(_parse(response.choices[0].message.content or ""))
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
    return result
