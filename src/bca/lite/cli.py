"""Installable command dispatch; native imports only when explicitly needed."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Sequence

from .cli_config import load, parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    try:
        settings = load(args)
        logging.basicConfig(level=settings.log_level, format="%(levelname)s %(message)s")
        if args.list_targets:
            from .cli_session import list_targets

            asyncio.run(list_targets(settings))
        else:
            from .cli_session import UnreleasedNativeError, run

            async def execute() -> None:
                try:
                    await run(
                        settings,
                        check=args.check,
                        once=args.once,
                        create_fixture=args.create_fixture,
                    )
                except UnreleasedNativeError as exc:
                    print(
                        f"Fatal cleanup: {exc}; ending process without destructor retries.",
                        file=sys.stderr,
                        flush=True,
                    )
                    sys.stdout.flush()
                    os._exit(3)  # Before asyncio.run shuts down borrowed CDP loop.

            asyncio.run(execute())
        return 0
    except KeyboardInterrupt:
        print("Interrupted; shutdown completed.", file=sys.stderr)
        return 130
    except ImportError as exc:
        print(f"Missing CLI dependency: {exc}. Install browser-cli-agent[lite].", file=sys.stderr)
        return 2
    except Exception as exc:
        # Do not print untrusted TOML values, endpoint credentials or tracebacks.
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
