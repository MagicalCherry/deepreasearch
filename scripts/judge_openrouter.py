"""适配只读课程判分器：使用OpenRouter独立凭证，离线预估输入，限制输出并保存实际费用。"""

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys

# 在导入项目配置前选择平台，不输出或持久化凭证。
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LLM_PROVIDER"] = "openrouter"
from app.config import settings

COURSE = ROOT.parent / "MAS实操课程" / "04-评测工具"
sys.path.insert(0, str(COURSE))
spec = importlib.util.spec_from_file_location("course_judge", COURSE / "judge.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def main():
    """默认仅统计待判输入；--execute才调用模型，标注只进入评测提示词。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--dataset", default="dev100")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    directory = Path(args.run).resolve()
    if ROOT / "runs" not in directory.parents:
        parser.error("run必须位于本项目runs目录")
    questions = judge.load_dataset(args.dataset)
    records = judge.load_jsonl(directory / "results.jsonl")
    cache = judge.load_jsonl(directory / "judged.jsonl")
    pending = [r for key, r in records.items() if key in questions and (
        key not in cache or cache[key].get("response") != r.get("response")
        or bool(cache[key].get("error")) != bool(r.get("error")))]
    import tiktoken
    encoding = tiktoken.get_encoding("cl100k_base")
    prompts = [judge.GRADER_TEMPLATE.format(question=questions[r["query_id"]]["query"],
               response=r["response"], correct_answer=questions[r["query_id"]]["answer"])
               for r in pending if not r.get("error") and r.get("response", "").strip()]
    print(json.dumps({"pending_calls": len(prompts),
        "estimated_prompt_tokens_cl100k": sum(len(encoding.encode(p, disallowed_special=())) for p in prompts),
        "max_output_tokens_per_call": 1024, "reasoning_enabled": False,
        "execute": args.execute}, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        return
    if not settings.api_key:
        parser.error("请在.env.openrouter本地填写OPENROUTER_API_KEY")
    original = judge.AsyncOpenAI
    clients = []

    def client_factory(**kwargs):
        client = original(api_key=settings.api_key, base_url=settings.base_url,
                          timeout=120, max_retries=0)
        clients.append(client)
        create = client.chat.completions.create

        async def bounded_create(**request):
            response = await create(**request, max_tokens=1024,
                                    extra_body={"reasoning": {"enabled": False}})
            usage = response.usage.model_dump() if response.usage else {}
            with (directory / "judge_usage.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"id": response.id, "usage": usage}, ensure_ascii=False) + "\n")
            if response.choices[0].finish_reason == "length":
                raise ValueError("判分输出截断，不把不完整判分当作正式结果")
            return response

        client.chat.completions.create = bounded_create
        return client

    judge.AsyncOpenAI = client_factory
    os.environ["OPENROUTER_API_KEY"] = settings.api_key
    sys.argv = [str(COURSE / "judge.py"), "--run", str(directory), "--dataset", args.dataset,
                "--judge-model", settings.model, "--base-url", settings.base_url,
                "--api-key-env", "OPENROUTER_API_KEY", "--concurrency", "2"]

    async def execute():
        try:
            await judge.main()
        finally:
            for client in clients:
                await client.close()
    asyncio.run(execute())


if __name__ == "__main__":
    main()
