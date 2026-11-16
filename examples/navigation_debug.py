"""Compare navigation evidence on new disposable data: and loopback HTTP test pages."""

import argparse
import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import quote

from bca.core.browser import BrowserSession, CDPEvent
from bca.core.errors import BCAError
from bca.core.protocol import JsonObject, JsonValue
from bca.core.protocol.validation import positive

INITIAL_TITLE = "BCA-01.1-A"
FINAL_TITLE = "BCA-01.1-Navigated"
EXPRESSION = "({title: document.title, href: location.href, readyState: document.readyState})"


def cache_snapshot(session: BrowserSession) -> JsonObject:
    target = session.bound_target
    return {
        "page_id": session.page_id,
        "session_id": session.session_id,
        "generation": session.generation,
        "is_ready": session.is_ready,
        "title": target.title if target else None,
        "url": target.url if target else None,
    }


async def probe(operation: Awaitable[JsonObject]) -> JsonObject:
    try:
        return {"response": await operation}
    except BCAError as exc:
        return {"exception": {"type": type(exc).__name__, "code": exc.code, "message": str(exc)}}


async def snapshot(session: BrowserSession, target_id: str, started: float) -> JsonObject:
    # These are sequential observations, not an atomic snapshot. Keep both cache readings.
    before = cache_snapshot(session)
    runtime = await probe(
        session.send(
            "Runtime.evaluate",
            {
                "expression": EXPRESSION,
                "returnByValue": True,
            },
            timeout=2,
        )
    )
    info = await probe(
        session.connection.send("Target.getTargetInfo", {"targetId": target_id}, timeout=2)
    )
    return {
        "elapsed": monotonic() - started,
        "cache_before_queries": before,
        "runtime": runtime,
        "target_info": info,
        "cache": cache_snapshot(session),
    }


def nested(value: JsonValue, *keys: str) -> JsonValue:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def classify(case: JsonObject) -> str:
    """Classify observed evidence only; do not claim a browser root cause."""
    if case.get("setup_error"):
        return "setup_failed"
    navigation = case.get("navigation")
    if nested(navigation, "exception") is not None:
        return "navigation_command_failed"
    navigation_result = nested(navigation, "response")
    if isinstance(navigation_result, dict) and "errorText" in navigation_result:
        return "navigation_reported_error"
    if nested(navigation, "response", "isDownload") is True:
        return "navigation_became_download"
    samples = case.get("samples")
    if not isinstance(samples, list) or not samples:
        return "no_post_navigation_evidence"
    last = samples[-1]
    before = nested(case, "before", "cache")
    cache = nested(last, "cache")
    if nested(cache, "is_ready") is not True or any(
        nested(before, key) != nested(cache, key) for key in ("page_id", "session_id", "generation")
    ):
        return "binding_identity_changed"
    runtime = nested(last, "runtime", "response", "result", "value")
    if not isinstance(runtime, dict):
        return "runtime_probe_failed"
    expected_url = case.get("destination")
    if runtime.get("title") != FINAL_TITLE or runtime.get("href") != expected_url:
        return "document_navigation_not_confirmed"
    info = nested(last, "target_info", "response", "targetInfo")
    if not isinstance(info, dict):
        return "target_info_probe_failed"
    if info.get("title") != FINAL_TITLE or info.get("url") != expected_url:
        return "target_metadata_not_updated"
    if nested(cache, "title") == FINAL_TITLE and nested(cache, "url") == expected_url:
        return "ok"
    events = case.get("events")
    navigation_started = case.get("navigation_started_at")
    sampled_at = nested(last, "elapsed")
    matching = (
        [
            event
            for event in events
            if isinstance(event, dict)
            and isinstance(event_time := event.get("elapsed"), (int, float))
            and isinstance(navigation_started, (int, float))
            and isinstance(sampled_at, (int, float))
            and navigation_started <= event_time <= sampled_at
            and nested(event, "target_info", "title") == FINAL_TITLE
            and nested(event, "target_info", "url") == expected_url
        ]
        if isinstance(events, list)
        else []
    )
    if any(event.get("top_level_session_id") is None for event in matching):
        return "cache_stale_despite_browser_event"
    if matching:
        return "cache_stale_with_session_scoped_event"
    return "cache_stale_without_matching_event"


@asynccontextmanager
async def local_pages() -> AsyncIterator[str]:
    """No external network or disk assets; a temporary 127.0.0.1 HTTP origin."""
    tasks: set[asyncio.Task[None]] = set()

    async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(3):
                header = await reader.readuntil(b"\r\n\r\n")
                first = header.split(b"\r\n", 1)[0].split()
                path = first[1] if len(first) == 3 and first[0] == b"GET" else b""
                title = {b"/start": INITIAL_TITLE, b"/navigated": FINAL_TITLE}.get(path)
                body = (
                    (
                        f"<!doctype html><meta charset=utf-8><title>{title}</title><p>{title}</p>"
                    ).encode()
                    if title
                    else b"Not found"
                )
                status = "200 OK" if title else "404 Not Found"
                writer.write(
                    (
                        f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n"
                        "Content-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    + body
                )
                await writer.drain()
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(respond(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server = await asyncio.start_server(accept, "127.0.0.1", 0, limit=32768)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    finally:
        server.close()
        await server.wait_closed()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_case(endpoint: str, mode: str, origin: str, wait: float) -> JsonObject:
    if mode == "data":
        start_url = "data:text/html," + quote(
            f"<title>{INITIAL_TITLE}</title><p>{INITIAL_TITLE}</p>"
        )
        destination = "data:text/html," + quote(f"<title>{FINAL_TITLE}</title>")
    else:
        start_url, destination = origin + "/start", origin + "/navigated"
    events: list[JsonValue] = []
    initial_samples: list[JsonValue] = []
    samples: list[JsonValue] = []
    case: JsonObject = {
        "mode": mode,
        "start_url": start_url,
        "destination": destination,
        "events": events,
        "initial_samples": initial_samples,
        "samples": samples,
        "dropped_events": 0,
    }
    session = BrowserSession(endpoint, request_timeout=3)
    created: str | None = None
    started = monotonic()
    dropped = 0

    def observe(event: CDPEvent) -> None:
        nonlocal dropped
        info = event.params.get("targetInfo")
        if not isinstance(info, dict) or info.get("targetId") != created:
            return
        if len(events) >= 200:
            dropped += 1
            return
        events.append(
            {
                "elapsed": monotonic() - started,
                "top_level_session_id": event.session_id,
                "target_info": dict(info),
                "cache_at_callback": cache_snapshot(session),
            }
        )

    try:
        await session.connect()
        case["browser_version"] = await session.connection.send("Browser.getVersion")
        session.connection.subscribe("Target.targetInfoChanged", observe, session_id="*")
        result = await session.connection.send("Target.createTarget", {"url": start_url})
        target_id = result.get("targetId")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("Target.createTarget did not return a targetId")
        created = target_id
        await session.bind(created)
        await session.send("Page.enable")
        # Cache freshness is evidence to preserve, not a navigation prerequisite.
        deadline = monotonic() + wait
        while True:
            before = await snapshot(session, created, started)
            initial_samples.append(before)
            case["before"] = before
            document_ready = (
                nested(before, "runtime", "response", "result", "value", "title") == INITIAL_TITLE
                and nested(before, "runtime", "response", "result", "value", "href") == start_url
            )
            target_ready = (
                nested(before, "target_info", "response", "targetInfo", "title") == INITIAL_TITLE
                and nested(before, "target_info", "response", "targetInfo", "url") == start_url
                and nested(before, "target_info", "response", "targetInfo", "targetId") == created
            )
            if document_ready and target_ready:
                case["initial_cache_stale"] = (
                    nested(before, "cache", "title") != INITIAL_TITLE
                    or nested(before, "cache", "url") != start_url
                )
                case["initial_status"] = "ready"
                break
            if monotonic() >= deadline:
                case["initial_status"] = (
                    "initial_document_not_ready"
                    if not document_ready
                    else "initial_target_not_ready"
                )
                raise TimeoutError(
                    f"{case['initial_status']}: expected title={INITIAL_TITLE!r}, "
                    f"url={start_url!r}; see initial_samples and before"
                )
            await asyncio.sleep(0.1)
        case["navigation_started_at"] = monotonic() - started
        case["navigation"] = await probe(session.send("Page.navigate", {"url": destination}))
        deadline = monotonic() + wait
        while True:
            samples.append(await snapshot(session, created, started))
            outcome = classify(case)
            if len(samples) >= 2 and outcome in (
                "ok",
                "navigation_command_failed",
                "navigation_reported_error",
                "navigation_became_download",
                "binding_identity_changed",
            ):
                break
            if len(samples) >= 2 and monotonic() >= deadline:
                break
            await asyncio.sleep(0.2)
    except (BCAError, ValueError, TimeoutError, OSError) as exc:
        case["setup_error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if created is not None and session.connected:
            case["cleanup_target"] = await probe(
                session.connection.send("Target.closeTarget", {"targetId": created}, timeout=2)
            )
        await session.close()
        case["cleanup_connection"] = {
            "connected": session.connected,
            "pending_count": session.connection.pending_count,
            "reader_running": session.connection.reader_running,
        }
    case["dropped_events"] = dropped
    case["classification"] = classify(case)
    return case


async def run(endpoint: str, mode: str, wait: float) -> JsonObject:
    positive(wait, "wait")
    cases: list[JsonValue] = []
    async with local_pages() as origin:
        for selected in ("data", "http") if mode == "both" else (mode,):
            cases.append(await run_case(endpoint, selected, origin, wait))
    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "endpoint": endpoint,
        "note": "Sequential diagnostic samples, not an atomic snapshot or full acceptance.",
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("BCA_CDP_ENDPOINT"))
    parser.add_argument("--mode", choices=("both", "data", "http"), default="both")
    parser.add_argument("--wait", type=float, default=10)
    parser.add_argument("--output", type=Path, default=Path("navigation-debug-2.json"))
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("pass --endpoint or set BCA_CDP_ENDPOINT; no browser is started automatically")
    positive(args.wait, "wait")
    report = asyncio.run(run(args.endpoint, args.mode, args.wait))
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    cases = report["cases"]
    assert isinstance(cases, list)
    raise SystemExit(0 if all(nested(case, "classification") == "ok" for case in cases) else 1)


if __name__ == "__main__":
    main()
