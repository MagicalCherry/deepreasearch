"""提供版本列表、单题实时事件展示及批量评测三个命令行入口。"""

import argparse
import asyncio
import json

from app.runner import research, run_eval
from app.trace import Trace
from app.versions import list_versions


async def ask(question: str, version: str) -> None:
    """同时运行研究与事件消费者，实时打印事件并在结束时清理订阅。"""
    trace = Trace()
    queue = trace.subscribe()

    async def display() -> None:
        while True:
            event = await queue.get()
            print(json.dumps(event, ensure_ascii=False), flush=True)
            if event["event"] in {"done", "error"}:
                return

    consumer = asyncio.create_task(display())
    try:
        response = await research(question, version, trace)
        await consumer
        print(response)
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        trace.unsubscribe(queue)


def main() -> None:
    """解析参数并调用对应入口，运行失败时返回非零退出码。"""
    parser = argparse.ArgumentParser(description="深度研究助手")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("versions", help="查看可用版本")
    single = commands.add_parser("ask", help="研究一道问题")
    single.add_argument("question")
    single.add_argument("--version", default="v0-closedbook")
    batch = commands.add_parser("run", help="批量评测或续跑")
    batch.add_argument("--dataset", choices=["smoke20", "dev100"], required=True)
    batch.add_argument("--version", default="v0-closedbook")
    batch.add_argument("--run-id", required=True)
    batch.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    try:
        if args.command == "versions":
            print(json.dumps(list_versions(), ensure_ascii=False, indent=2))
        elif args.command == "ask":
            asyncio.run(ask(args.question, args.version))
        else:
            status = asyncio.run(run_eval(args.dataset, args.version, args.concurrency, args.run_id))
            print(json.dumps(status, ensure_ascii=False, indent=2))
            if status["errors"]:
                raise SystemExit(1)
    except KeyboardInterrupt:
        parser.exit(130, "运行已中断，可使用相同命令续跑。\n")
    except Exception as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
