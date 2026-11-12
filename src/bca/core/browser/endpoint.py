"""Bounded asynchronous HTTP discovery pinned to a verified loopback address."""

import asyncio
import ipaddress
import json
import socket
from contextlib import suppress
from urllib.parse import SplitResult, urlsplit

from .errors import CDPConnectionError, EndpointError

_MAX_BODY = 1024 * 1024


def _url(value: str, scheme: str) -> SplitResult:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != scheme
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or any(c.isspace() for c in value)
        ):
            raise ValueError("invalid URL")
        return parsed
    except (ValueError, TypeError) as exc:
        raise EndpointError(
            f"expected a local {scheme} endpoint without credentials/query"
        ) from exc


async def _addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        address = ipaddress.ip_address(host)
        if not address.is_loopback:
            raise EndpointError("only loopback addresses are allowed")
        return (str(address),)
    except ValueError:
        if host.lower() != "localhost":
            raise EndpointError(
                "only localhost or literal loopback addresses are allowed"
            ) from None
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = tuple(dict.fromkeys(str(record[4][0]) for record in records))
    if not addresses or any(not ipaddress.ip_address(item).is_loopback for item in addresses):
        raise EndpointError("localhost resolved to a non-loopback address")
    return addresses


async def discover_websocket(endpoint: str) -> str:
    """Called inside the connection's timeout; no proxies, redirects or remote DNS."""
    parsed = _url(endpoint, "http")
    if parsed.path not in ("", "/"):
        raise EndpointError("HTTP endpoint must be an origin, without a path")
    assert parsed.hostname is not None
    port = parsed.port or 80
    addresses = await _addresses(parsed.hostname, port)
    writer: asyncio.StreamWriter | None = None
    last_error: OSError | None = None
    for address in addresses:
        try:
            reader, writer = await asyncio.open_connection(address, port, limit=32768)
            break
        except OSError as exc:
            last_error = exc
    if writer is None:
        raise CDPConnectionError("cannot connect to local discovery endpoint") from last_error
    try:
        peer = writer.get_extra_info("peername")
        if peer is None or peer[0] not in addresses:
            raise EndpointError("discovery peer differs from validated loopback address")
        host = f"[{peer[0]}]" if ":" in peer[0] else peer[0]
        writer.write(
            (
                f"GET /json/version HTTP/1.1\r\nHost: {host}:{port}\r\n"
                "Connection: close\r\nAccept: application/json\r\n\r\n"
            ).encode("ascii")
        )
        await writer.drain()
        header = (await reader.readuntil(b"\r\n\r\n")).decode("iso-8859-1")
        lines = header.split("\r\n")
        if lines[0].split()[1] != "200":
            raise EndpointError("discovery requires HTTP 200; redirects are not followed")
        headers = dict(line.lower().split(":", 1) for line in lines[1:] if ":" in line)
        if "transfer-encoding" in headers:
            raise EndpointError("chunked discovery responses are not supported")
        if "content-length" in headers:
            length = int(headers["content-length"])
            if not 0 < length <= _MAX_BODY:
                raise EndpointError("invalid discovery Content-Length")
            body = await reader.readexactly(length)
        else:
            body = await reader.read(_MAX_BODY + 1)
            # Read to EOF for close-delimited HTTP, including fragmented bodies.
            while len(body) <= _MAX_BODY:
                chunk = await reader.read(_MAX_BODY + 1 - len(body))
                if not chunk:
                    break
                body += chunk
            if len(body) > _MAX_BODY:
                raise EndpointError("discovery response too large")
        document = json.loads(body)
        if not isinstance(document, dict) or not isinstance(
            document.get("webSocketDebuggerUrl"), str
        ):
            raise EndpointError("missing browser webSocketDebuggerUrl")
        websocket = _url(document["webSocketDebuggerUrl"], "ws")
        assert websocket.hostname is not None
        ws_port = websocket.port or 80
        ws_addresses = await _addresses(websocket.hostname, ws_port)
        if ws_port != port or peer[0] not in ws_addresses:
            raise EndpointError("WebSocket must use the same validated discovery peer and port")
        if not websocket.path.startswith("/devtools/browser/"):
            raise EndpointError("expected browser-level WebSocket URL")
        return f"ws://{host}:{port}{websocket.path}"
    except (ValueError, IndexError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
        raise EndpointError("invalid discovery response") from exc
    finally:
        writer.close()
        # A peer reset during TCP teardown must not replace a completed response
        # or mask the original discovery error (notably on Windows Proactor).
        with suppress(OSError):
            await writer.wait_closed()
