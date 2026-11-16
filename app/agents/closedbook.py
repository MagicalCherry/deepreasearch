"""闭卷基线的提示词与运行函数：只凭模型记忆回答，不提供检索工具。"""

from typing import Any

from app.llm import LLM
from app.trace import Trace


SYSTEM_PROMPT = """Answer the question using only your existing knowledge.
You must give your best guess, even if uncertain. State uncertainty honestly.
Do not claim to have searched or read sources, and do not invent document citations.
Use this output format, ending with the Exact Answer and Confidence lines:
Explanation: {brief explanation}
Exact Answer: {short final answer}
Confidence: {integer from 0 to 100}%"""


async def run(question: str, trace: Trace, opts: dict[str, Any]) -> str:
    """记录启动事件，进行一次对话调用，并在成功或失败后关闭客户端。"""
    trace.emit("agent_start", role="作答", task=question)
    llm = LLM(trace=trace)
    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=opts.get("temperature", 0),
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise ValueError("闭卷模型返回了空答案")
        return content
    finally:
        await llm.close()
