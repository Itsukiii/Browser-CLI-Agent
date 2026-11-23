"""BCA-lite adapters. Install [lite] before importing MaaCDPController."""

from .bridge import BridgeError, CDPBridge, ObservationRef, run_native

__all__ = ["BridgeError", "CDPBridge", "ObservationRef", "run_native"]
