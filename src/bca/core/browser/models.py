"""Browser-local models; these do not change Protocol 2 wire models."""

from dataclasses import dataclass
from enum import StrEnum

from bca.core.protocol import JsonObject

from .errors import CDPMessageError


class SessionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    BOUND = "bound"
    CLOSED = "closed"


@dataclass(frozen=True, kw_only=True)
class BrowserTarget:
    target_id: str
    title: str
    url: str
    type: str

    @classmethod
    def from_cdp(cls, info: JsonObject) -> "BrowserTarget":
        values = [info.get(key) for key in ("targetId", "title", "url", "type")]
        if not all(isinstance(value, str) for value in values) or not values[0] or not values[3]:
            raise CDPMessageError("invalid TargetInfo fields")
        target_id, title, url, kind = values
        assert isinstance(target_id, str) and isinstance(title, str)
        assert isinstance(url, str) and isinstance(kind, str)
        return cls(target_id=target_id, title=title, url=url, type=kind)


@dataclass(frozen=True, kw_only=True)
class CDPEvent:
    method: str
    params: JsonObject
    session_id: str | None = None
