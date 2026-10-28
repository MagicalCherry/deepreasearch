import asyncio
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "app/service/deep_research_v2/background.py"
spec = importlib.util.spec_from_file_location("background", path)
background = importlib.util.module_from_spec(spec)
spec.loader.exec_module(background)


class BackgroundResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_does_not_cancel_or_pause_research(self):
        continue_work = asyncio.Event()
        completed = asyncio.Event()
        phases = []
        async def source():
            try:
                phases.append("planning")
                yield "plan"
                await continue_work.wait()
                phases.append("writing")
                yield "report"
                phases.append("completed")
            finally:
                completed.set()
        subscription = background.stream_in_background(source())
        self.assertEqual(await anext(subscription), "plan")
        await subscription.aclose()
        self.assertTrue(background.RUNNING_RESEARCH)
        continue_work.set()
        await asyncio.wait_for(completed.wait(), 1)
        await asyncio.sleep(0)
        self.assertEqual(phases, ["planning", "writing", "completed"])
        self.assertFalse(background.RUNNING_RESEARCH)

    async def test_slow_subscriber_cannot_stall_completion(self):
        start = asyncio.Event()
        done = asyncio.Event()
        async def source():
            yield "start"
            await start.wait()
            for i in range(1000):
                yield str(i)
            done.set()
        subscription = background.stream_in_background(source(), buffer_size=4)
        self.assertEqual(await anext(subscription), "start")
        start.set()
        await asyncio.wait_for(done.wait(), 1)
        tail = [event async for event in subscription]
        self.assertIn("999", tail)
        self.assertLessEqual(len(tail), 4)

    async def test_disconnected_failure_still_runs_finalizer(self):
        start = asyncio.Event()
        finalized = asyncio.Event()
        async def source():
            try:
                yield "start"
                await start.wait()
                raise RuntimeError("simulated model failure")
            finally:
                finalized.set()
        subscription = background.stream_in_background(source())
        await anext(subscription)
        await subscription.aclose()
        start.set()
        await asyncio.wait_for(finalized.wait(), 1)


if __name__ == "__main__":
    unittest.main()
