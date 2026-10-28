"""Offline regression tests for tool draining and the streaming orchestrator."""
import ast
import asyncio
import importlib.util
import logging
from pathlib import Path
import runpy
import threading
import types
import unittest
from typing import AsyncGenerator, Dict, Any

ROOT = Path(__file__).resolve().parents[1] / "app/service/deep_research_v2"
spec = importlib.util.spec_from_file_location("termination", ROOT / "termination.py")
termination = importlib.util.module_from_spec(spec)
spec.loader.exec_module(termination)


class TerminationTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_tool_finishes_but_next_tool_cannot_start(self):
        stop = threading.Event()
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        drain = termination.ToolDrain(stop.is_set)

        def tool():
            started.set()
            release.wait(3)
            finished.set()

        task = asyncio.create_task(drain.run(tool))
        while not started.is_set():
            await asyncio.sleep(0.01)
        stop.set()
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(termination.ResearchTerminated):
            await task
        self.assertTrue(finished.is_set())
        # A new question may clear Redis's session flag; the old run stays dead.
        stop.clear()
        called = []
        with self.assertRaises(termination.ResearchTerminated):
            await drain.run(lambda: called.append(True))
        self.assertEqual(called, [])
        await drain.drain()

    async def test_graph_waits_for_all_parallel_calls_and_never_runs_next_agent(self):
        # Extract the actual orchestrator without importing database/model clients.
        tree = ast.parse((ROOT / "graph.py").read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_simplified")
        state_module = runpy.run_path(str(ROOT / "state.py"))
        stop = threading.Event()
        scope = dict(asyncio=asyncio, logger=logging.getLogger("test"),
                     Dict=Dict, Any=Any, AsyncGenerator=AsyncGenerator,
                     ResearchState=dict, ResearchPhase=state_module["ResearchPhase"],
                     ToolDrain=termination.ToolDrain, ResearchTerminated=termination.ResearchTerminated,
                     is_research_cancelled=lambda _: stop.is_set())
        exec(compile(ast.Module(body=[method], type_ignores=[]), "graph.py", "exec"), scope)
        releases = [threading.Event(), threading.Event()]
        starts = [threading.Event(), threading.Event()]
        next_agents = []

        class Architect:
            name = "architect"
            async def process(self, state):
                def tool(index):
                    starts[index].set()
                    releases[index].wait(4)
                await asyncio.gather(*(self.tool_drain.run(tool, i) for i in range(2)))
                await self.tool_drain.run(lambda: next_agents.append("extra tool"))

        class Other:
            name = "other"
            async def process(self, state):
                next_agents.append("next agent")

        statuses = []
        graph = types.SimpleNamespace(architect=Architect(), scout=Other(), data_analyst=Other(),
                                      wizard=Other(), writer=Other(), critic=Other(),
                                      checkpoint_service=types.SimpleNamespace(update_status=lambda *args: statuses.append(args[1])),
                                      _save_checkpoint=lambda *args: True)
        state = state_module["create_initial_state"]("test", "test-session")
        async def consume():
            return [event async for event in scope["_run_simplified"](graph, state)]
        task = asyncio.create_task(consume())
        while not all(event.is_set() for event in starts):
            await asyncio.sleep(0.01)
        stop.set()
        releases[0].set()
        await asyncio.sleep(0.1)
        self.assertFalse(task.done(), "must wait for the second issued call")
        releases[1].set()
        events = await asyncio.wait_for(task, timeout=3)
        self.assertEqual(next_agents, [])
        self.assertIn("cancelled", statuses)
        self.assertTrue(any(e["type"] == "research_cancelled" for e in events))


if __name__ == "__main__":
    unittest.main()
