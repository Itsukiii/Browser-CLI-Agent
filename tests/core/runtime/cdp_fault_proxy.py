"""Test-only loopback relay: forward to real Edge, selectively discard actual replies."""

import asyncio
import json
from http import HTTPStatus

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from bca.core.browser.endpoint import discover_websocket


class ReplyLossProxy:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.method = None
        self.kind = None
        self.drop_release = False
        self.seen = asyncio.Event()
        self.requests = []
        self.dropped = []
        self.sockets = set()

    async def __aenter__(self):
        self.upstream = await discover_websocket(self.endpoint)
        self.server = await serve(
            self.handle, "127.0.0.1", 0, max_size=16 * 1024 * 1024, process_request=self.discovery
        )
        self.url = f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"
        return self

    async def discovery(self, connection, request):
        if request.path == "/json/version":
            return connection.respond(
                HTTPStatus.OK,
                json.dumps(
                    {
                        "webSocketDebuggerUrl": self.url.replace("http://", "ws://")
                        + "/devtools/browser/fault"
                    }
                ),
            )
        return None

    async def handle(self, client):
        async with connect(self.upstream, proxy=None, max_size=16 * 1024 * 1024) as upstream:
            self.sockets.update((client, upstream))
            requests = {}

            async def forward():
                async for wire in client:
                    request = json.loads(wire)
                    requests[request["id"]] = request
                    self.requests.append(request)
                    await upstream.send(wire)

            async def replies():
                async for wire in upstream:
                    response = json.loads(wire)
                    request = requests.pop(response.get("id"), {})
                    kind = request.get("params", {}).get("type")
                    if (
                        self.method is not None
                        and request.get("method") == self.method
                        and (self.kind is None or kind == self.kind)
                    ) or (self.drop_release and kind == "mouseReleased"):
                        self.dropped.append(request)
                        self.seen.set()  # Edge has already processed and replied to this command.
                        continue
                    await client.send(wire)

            tasks = [asyncio.create_task(forward()), asyncio.create_task(replies())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.sockets.difference_update((client, upstream))

    async def disconnect(self):
        await asyncio.gather(*(s.close() for s in tuple(self.sockets)), return_exceptions=True)

    async def __aexit__(self, *args):
        await self.disconnect()
        self.server.close()
        try:
            await self.server.wait_closed()
        except ConnectionClosed:
            pass
