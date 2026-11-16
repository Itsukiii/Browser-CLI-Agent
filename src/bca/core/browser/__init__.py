"""Local CDP transport and explicitly bound browser sessions."""

from .capture import BrowserCaptureProvider, CaptureError
from .connection import CDPConnection, DisconnectHandler, EventHandler
from .errors import (
    BrowserError,
    CDPCommandError,
    CDPConnectionError,
    CDPDisconnectedError,
    CDPMessageError,
    CDPTimeoutError,
    EndpointError,
    TargetBindingError,
    TargetLostError,
    TargetNotFoundError,
)
from .input import BrowserInputProvider
from .models import BrowserTarget, CDPEvent, SessionState
from .session import BrowserSession
from .targets import TargetManager

__all__ = [
    "BrowserCaptureProvider",
    "BrowserInputProvider",
    "CaptureError",
    "BrowserError",
    "BrowserSession",
    "BrowserTarget",
    "CDPCommandError",
    "CDPConnection",
    "CDPConnectionError",
    "CDPDisconnectedError",
    "CDPEvent",
    "CDPMessageError",
    "CDPTimeoutError",
    "DisconnectHandler",
    "EndpointError",
    "EventHandler",
    "SessionState",
    "TargetBindingError",
    "TargetLostError",
    "TargetManager",
    "TargetNotFoundError",
]
