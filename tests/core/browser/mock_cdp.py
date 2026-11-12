"""Local HTTP + WebSocket CDP peer; no browser or external network required."""

import asyncio
import json
from http import HTTPStatus

from websockets.asyncio.server import serve


async def eventually(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.001)


class MockCDP:
    def __init__(self):
        self.targets = {
            "page-a": {"targetId": "page-a", "title": "A", "url": "about:blank", "type": "page"},
            "page-b": {"targetId": "page-b", "title": "B", "url": "about:blank#b", "type": "page"},
            "worker": {"targetId": "worker", "title": "W", "url": "worker.js", "type": "worker"},
        }
        self.connections = set()
        self.tasks = set()
        self.requests = []
        self.sessions = {}
        self.next_session = 0
        self.release_wait = asyncio.Event()
        self.attach_gate = None
        self.attach_event = None
        self.fail_methods = set()
        self.version_document = None
        self.http_status = HTTPStatus.OK
        self.http_delay = 0
        self.discovery_paths = []
        self.websocket_redirect = None

    async def __aenter__(self):
        self.server = await serve(
            self._handle, "127.0.0.1", 0, process_request=self._http, close_timeout=0.2
        )
        self.port = self.server.sockets[0].getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self.ws_url = f"ws://127.0.0.1:{self.port}/devtools/browser/mock"
        return self

    async def __aexit__(self, *args):
        self.release_wait.set()
        if self.attach_gate is not None:
            self.attach_gate.set()
        self.server.close()
        await self.server.wait_closed()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _http(self, connection, request):
        if request.path == "/json/version":
            self.discovery_paths.append(request.path)
            await asyncio.sleep(self.http_delay)
            document = self.version_document
            if document is None:
                document = {"webSocketDebuggerUrl": self.ws_url}
            return connection.respond(self.http_status, json.dumps(document))
        if self.websocket_redirect is not None:
            response = connection.respond(HTTPStatus.FOUND, "redirect")
            response.headers["Location"] = self.websocket_redirect
            return response
        return None

    async def _handle(self, socket):
        self.connections.add(socket)
        try:
            async for text in socket:
                request = json.loads(text)
                self.requests.append(request)
                task = asyncio.create_task(self._reply(socket, request))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
        finally:
            self.connections.discard(socket)
            for sid, (owner, _) in tuple(self.sessions.items()):
                if owner is socket:
                    self.sessions.pop(sid)

    async def _reply(self, socket, request):
        method, params = request["method"], request.get("params", {})
        response = {"id": request["id"]}
        if "sessionId" in request:
            response["sessionId"] = request["sessionId"]
        if method in self.fail_methods or method == "Test.error":
            response["error"] = {"code": -32000, "message": "mock rejection"}
        elif method == "Target.getTargets":
            response["result"] = {"targetInfos": list(self.targets.values())}
        elif method == "Target.attachToTarget":
            assert params["flatten"] is True
            self.next_session += 1
            sid = f"session-{self.next_session}"
            self.sessions[sid] = (socket, params["targetId"])
            if self.attach_event:
                await self.emit(*self.attach_event)
            if self.attach_gate is not None:
                await self.attach_gate.wait()
            response["result"] = {"sessionId": sid}
        elif method == "Target.detachFromTarget":
            sid = params["sessionId"]
            self.sessions.pop(sid, None)
            await self.emit("Target.detachedFromTarget", {"sessionId": sid})
            response["result"] = {}
        elif method == "Test.disconnect":
            await socket.close()
            return
        elif method == "Test.malformed":
            await socket.send("not json")
            return
        else:
            if method == "Test.wait":
                await self.release_wait.wait()
            if method == "Test.echo":
                await asyncio.sleep(params.get("delay", 0))
            response["result"] = {"echo": params} if method.startswith("Test.") else {}
        try:
            await socket.send(json.dumps(response))
        except Exception:
            pass  # A test may have intentionally disconnected before its late response.

    async def emit(self, method, params, session_id=None):
        message = {"method": method, "params": params}
        if session_id is not None:
            message["sessionId"] = session_id
        for socket in tuple(self.connections):
            await socket.send(json.dumps(message))

    async def seen(self, method, count=1):
        await eventually(lambda: sum(item["method"] == method for item in self.requests) >= count)
