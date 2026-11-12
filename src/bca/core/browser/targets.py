"""Explicit page discovery and flattened Target attachment."""

import logging

from bca.core.protocol.validation import token

from .connection import CDPConnection
from .errors import CDPCommandError, CDPMessageError, TargetBindingError, TargetNotFoundError
from .models import BrowserTarget

logger = logging.getLogger(__name__)


class TargetManager:
    """Stateless CDP operations. BrowserSession owns single-target lifecycle policy."""

    def __init__(self, connection: CDPConnection) -> None:
        self._connection = connection

    async def _all_targets(self) -> tuple[BrowserTarget, ...]:
        result = await self._connection.send("Target.getTargets")
        infos = result.get("targetInfos")
        if not isinstance(infos, list) or any(not isinstance(info, dict) for info in infos):
            raise CDPMessageError("Target.getTargets returned invalid targetInfos")
        return tuple(BrowserTarget.from_cdp(info) for info in infos if isinstance(info, dict))

    async def list_targets(self) -> tuple[BrowserTarget, ...]:
        targets = tuple(target for target in await self._all_targets() if target.type == "page")
        logger.debug("CDP discovered pages count=%s", len(targets))
        return targets

    async def bind(self, target_id: str) -> tuple[BrowserTarget, str]:
        token(target_id, "target_id")
        target = next(
            (item for item in await self._all_targets() if item.target_id == target_id), None
        )
        if target is None:
            raise TargetNotFoundError(f"target does not exist: {target_id}")
        if target.type != "page":
            raise TargetBindingError(f"target is not a page: {target_id}")
        try:
            result = await self._connection.send(
                "Target.attachToTarget",
                {
                    "targetId": target_id,
                    "flatten": True,
                },
            )
        except CDPCommandError as exc:
            raise TargetBindingError(f"cannot attach target: {target_id}") from exc
        session_id = result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise CDPMessageError("attachToTarget returned invalid sessionId")
        logger.info("CDP attached target=%s session=%s", target_id, session_id)
        return target, session_id

    async def unbind(self, session_id: str) -> None:
        token(session_id, "session_id")
        try:
            await self._connection.send("Target.detachFromTarget", {"sessionId": session_id})
        except CDPCommandError as exc:
            raise TargetBindingError(f"cannot detach session: {session_id}") from exc
        logger.info("CDP detached session=%s", session_id)
