from app.api.routes import _extract_confidence


def test_extract_confidence_standard():
    content = "### 3. 关联度评级\n- **因果置信度**：高\n- **逻辑依据简述**：xxx"
    assert _extract_confidence(content) == "高"


def test_extract_confidence_colon_variants():
    assert _extract_confidence("- **因果置信度**: 中") == "中"
    assert _extract_confidence("因果置信度 低") == "低"


def test_extract_confidence_takes_first_filled_value():
    # 模板占位（高 / 中 / 低）应取到首个字符
    assert _extract_confidence("- **因果置信度**：中 / 低") == "中"


def test_extract_confidence_missing():
    assert _extract_confidence("正文没有该字段") is None
    assert _extract_confidence(None) is None
    assert _extract_confidence("") is None
