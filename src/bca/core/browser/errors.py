"""Browser errors preserve Core's operational and validation classifications."""

from bca.core.errors import CapabilityUnavailableError, ProviderError, ValidationError


class BrowserError(ProviderError):
    code = "browser.error"


class EndpointError(ValidationError):
    code = "browser.endpoint"


class CDPConnectionError(BrowserError):
    code = "browser.connection"


class CDPDisconnectedError(BrowserError, CapabilityUnavailableError):
    code = "browser.disconnected"


class CDPTimeoutError(BrowserError, TimeoutError):
    code = "browser.timeout"


class CDPMessageError(BrowserError):
    code = "browser.message"


class CDPCommandError(BrowserError):
    code = "browser.command"

    def __init__(self, method: str, cdp_code: int, message: str) -> None:
        self.method = method
        self.cdp_code = cdp_code
        self.message = message
        super().__init__(f"{method}: CDP {cdp_code}: {message}")


class TargetNotFoundError(BrowserError):
    code = "browser.target_not_found"


class TargetBindingError(BrowserError):
    code = "browser.target_binding"


class TargetLostError(BrowserError, CapabilityUnavailableError):
    code = "browser.target_lost"
