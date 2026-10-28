"""Cooperative termination: finish issued calls, forbid subsequent calls."""
import asyncio


class ResearchTerminated(BaseException):
    pass


class ToolDrain:
    def __init__(self, should_stop):
        self.should_stop = should_stop
        self.pending = set()
        self.stopped = False

    def check(self):
        self.stopped = self.stopped or self.should_stop()
        if self.stopped:
            raise ResearchTerminated()

    async def run(self, function, *args, **kwargs):
        self.check()
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)
        result = await asyncio.shield(task)
        self.check()
        return result

    async def drain(self):
        while self.pending:
            await asyncio.gather(*list(self.pending), return_exceptions=True)
