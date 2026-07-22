"""Cached Claude Haiku translation for changed FMP company descriptions."""

from openai import OpenAI

from app.config import get_settings

SYSTEM = """将公司英文简介翻译为自然、简洁的简体中文。
保留公司名、产品名、股票代码、商标和技术术语；不得添加原文没有的事实、观点或投资建议。
只输出译文，不要 Markdown、解释或标题。"""


def translate_description(text: str) -> tuple[str, str]:
    settings = get_settings()
    if not settings.fmp_translation_enabled or not settings.translation_api_key:
        raise RuntimeError(
            "company profile translation is disabled or TRANSLATION_API_KEY is missing"
        )
    response = OpenAI(
        api_key=settings.translation_api_key,
        base_url=settings.translation_base_url,
        timeout=45,
        max_retries=0,
    ).chat.completions.create(
        model=settings.translation_model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
        temperature=0,
    )
    value = (response.choices[0].message.content or "").strip()
    if not value:
        raise ValueError("empty company-description translation")
    return value, settings.translation_model
