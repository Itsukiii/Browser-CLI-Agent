"""List local CDP pages; bind only the target explicitly supplied by the caller."""

import argparse
import asyncio

from bca.core.browser import BrowserSession


async def run(endpoint: str, target_id: str | None) -> None:
    session = BrowserSession(endpoint)
    try:
        await session.connect()
        for target in await session.list_targets():
            print(f"{target.target_id}\t{target.title}\t{target.url}")
        if target_id is not None:
            await session.bind(target_id)
            print(
                f"bound page_id={session.page_id} session_id={session.session_id} "
                f"generation={session.generation}"
            )
        else:
            print("No page selected. Run again with --target-id <ID> to bind explicitly.")
    finally:
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--target-id")
    args = parser.parse_args()
    asyncio.run(run(args.endpoint, args.target_id))


if __name__ == "__main__":
    main()
