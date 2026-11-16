"""测试答案解析与格式规范化：字段提取、引用编号、置信度和缺失字段处理。"""

from app.answer import normalize, parse


def test_parse_standard_answer():
    """正常答案应提取最终答案、整数置信度和解释中的引用编号。"""
    text = (
        "Explanation: 根据文档[12]和[34]得到结论。\n"
        "Exact Answer: 示例答案\n"
        "Confidence: 80%"
    )

    result = parse(text)

    assert result["exact_answer"] == "示例答案"
    assert result["confidence"] == 80
    assert isinstance(result["confidence"], int)
    assert result["cited_docids"] == ["12", "34"]


def test_normalize_missing_confidence():
    """有答案但没有置信度时，按课程规则补为50%。"""
    text = (
        "Explanation: 这是一段示例解释。\n"
        "Exact Answer: 示例答案"
    )

    normalized = normalize(text)

    assert "Confidence: 50%" in normalized
    assert parse(normalized)["confidence"] == 50


def test_normalize_confidence_above_100():
    """置信度超过100时，应截断为100%。"""
    text = (
        "Explanation: 这是一段示例解释。\n"
        "Exact Answer: 示例答案\n"
        "Confidence: 120%"
    )

    normalized = normalize(text)

    assert "Confidence: 100%" in normalized
    assert parse(normalized)["confidence"] == 100


def test_normalize_without_exact_answer():
    """没有答案标签时，保留原文作为解释，答案留空且置信度为0。"""
    text = "目前只有分析，还没有明确答案。"

    result = parse(normalize(text))

    assert result["explanation"] == text
    assert result["exact_answer"] == ""
    assert result["confidence"] == 0
    assert result["cited_docids"] == []
