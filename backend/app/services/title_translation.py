import hashlib
import re

from openai import OpenAI

from app.config import get_settings


_SYSTEM_PROMPT = """你是财经新闻标题翻译器。将输入标题翻译为简体中文。
只输出翻译后的标题，不要解释、总结、补充事实、添加引号或使用 Markdown。
保留股票代码、公司名、产品名、数字及必要专有名词。"""
_CHINESE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_WRAPPERS = (("**", "**"), ("__", "__"), ("`", "`"), ('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"))


def title_input_hash(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()


def is_chinese_title(title: str) -> bool:
    return bool(_CHINESE_RE.search(title))


def _clean_translation(value: str) -> str:
    result = value.strip()
    for prefix, suffix in _WRAPPERS:
        if result.startswith(prefix) and result.endswith(suffix) and len(result) > len(prefix) + len(suffix):
            result = result[len(prefix) : -len(suffix)].strip()
    if not result or "\n" in result:
        raise ValueError("标题翻译响应格式无效")
    return result[:512]


def translate_title(title: str) -> tuple[str, str | None]:
    if is_chinese_title(title):
        return title, None

    settings = get_settings()
    if not settings.translation_api_key:
        raise RuntimeError("尚未配置 TRANSLATION_API_KEY")
    client = OpenAI(
        api_key=settings.translation_api_key,
        base_url=settings.translation_base_url,
        timeout=30,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=settings.translation_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": title},
        ],
        temperature=0,
    )
    translated = _clean_translation(response.choices[0].message.content or "")
    return translated, settings.translation_model
