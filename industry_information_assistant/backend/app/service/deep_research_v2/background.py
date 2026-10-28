"""Run research independently of its transient SSE subscriber."""
import asyncio

RUNNING_RESEARCH = set()


async def stream_in_background(source, buffer_size=256):
    queue = asyncio.Queue(maxsize=buffer_size)
    attached = True
    done = object()

    def publish(item):
        if not attached:
            return
        # Snapshots remain authoritative; a slow client cannot stall the producer.
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(item)

    async def produce():
        try:
            async for item in source:
                publish(item)
        except Exception as error:
            publish(error)
        finally:
            try:
                await source.aclose()
            finally:
                publish(done)

    task = asyncio.create_task(produce(), name="background-research")
    RUNNING_RESEARCH.add(task)
    task.add_done_callback(RUNNING_RESEARCH.discard)
    try:
        while True:
            item = await queue.get()
            if item is done:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        attached = False
        # Do not cancel the producer when the page disconnects.
