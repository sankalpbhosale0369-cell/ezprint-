"""
Lightweight fallback implementation of the `netifaces` API for Windows-only CI/dev
environments where compiling the official package is not possible.

This module implements just enough of the API used by the codebase:
- `AF_INET` constant
- `interfaces()` -> list[str]
- `ifaddresses(interface)` -> dict mapping AF_INET to list of dicts with 'addr'

It attempts to determine the primary local IPv4 address without requiring any
native extensions. If detection fails, it returns an empty IPv4 list, which
results in callers gracefully scanning zero dynamic ranges (tests should still
proceed using fallbacks).
"""

from __future__ import annotations

from typing import Dict, List
import socket

# Minimal compatibility constant
AF_INET = 2


def _get_primary_ipv4_address() -> str | None:
    """Best-effort detection of the primary local IPv4 address.

    Tries a UDP socket connect trick to a public IP (no packets sent) to learn
    the chosen outbound interface address. Falls back to hostname lookup.
    Returns None if a non-loopback IPv4 cannot be determined.
    """
    # Try UDP connect trick (no external traffic is actually sent)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    # Fallback to hostname resolution
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    return None


def interfaces() -> List[str]:
    """Return a synthetic list of interfaces.

    We expose a minimal, stable name for the detected primary adapter, plus a
    loopback entry to mimic real environments.
    """
    return ["primary", "lo"]


def ifaddresses(interface: str) -> Dict[int, List[Dict[str, str]]]:
    """Return IPv4 addresses for the given interface in `netifaces`-like shape.

    Shape: { AF_INET: [ { 'addr': 'x.x.x.x' } ] }
    If we cannot determine a non-loopback address, we return an empty mapping
    (callers generally treat missing AF_INET as no dynamic ranges).
    """
    ipv4 = _get_primary_ipv4_address()
    result: Dict[int, List[Dict[str, str]]] = {}

    if interface == "primary" and ipv4:
        result[AF_INET] = [{"addr": ipv4}]
        return result

    if interface == "lo":
        # Provide a loopback entry for compatibility
        result[AF_INET] = [{"addr": "127.0.0.1"}]
        return result

    # Unknown interface: return empty mapping to match netifaces behavior when
    # an interface has no IPv4 addresses of interest.
    return result


