"""解析和规范化官方答案格式，提取解释、最终答案、置信度及引用文档编号。"""

import re
from typing import TypedDict


class ParsedAnswer(TypedDict):
    """供研究事件与页面展示使用的答案字段。"""

    explanation: str
    exact_answer: str
    confidence: int
    cited_docids: list[str]


_LABEL = re.compile(
    r"^[ \t]*(Explanation|Exact Answer|Confidence):[ \t]*",
    re.MULTILINE,
)


def parse(text: str) -> ParsedAnswer:
    """按标签拆分字段；缺少答案标签时保留原文，并将置信度设为0。"""
    matches = list(_LABEL.finditer(text))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fields[match.group(1)] = text[match.end():end].strip()

    if "Exact Answer" not in fields:
        explanation = text.strip()
        exact_answer = ""
        confidence = 0
    else:
        explanation = fields.get("Explanation", text[:matches[0].start()].strip())
        exact_answer = fields["Exact Answer"]
        number = re.fullmatch(r"([+-]?\d+)(?:\.\d+)?[ \t]*%?", fields.get("Confidence", ""))
        confidence = max(0, min(100, int(number.group(1)))) if number else 50

    # 引用仅从解释中提取，按出现顺序去重；编号始终使用字符串。
    cited_docids = list(dict.fromkeys(re.findall(r"\[(\d+)\]", explanation)))
    return {
        "explanation": explanation,
        "exact_answer": exact_answer,
        "confidence": confidence,
        "cited_docids": cited_docids,
    }


def normalize(text: str) -> str:
    """补齐字段并限制置信度范围，输出统一的三字段文字格式。"""
    answer = parse(text)
    return (
        f"Explanation: {answer['explanation']}\n"
        f"Exact Answer: {answer['exact_answer']}\n"
        f"Confidence: {answer['confidence']}%"
    )
