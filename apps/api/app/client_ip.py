"""Resolve the real client address behind the private web proxy.

Only a peer inside ``TRUSTED_PROXY_CIDRS`` (loopback and private networks by
default) is trusted to forward X-Forwarded-For. Within that header the rightmost
entry is the one appended by the trusted edge (Caddy or the hosting platform);
anything further left was supplied by the browser and could be spoofed to dodge
per-address limits.
"""

import ipaddress
from functools import lru_cache

from fastapi import Request

from app.config import get_settings

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def trusted_networks(spec: str) -> tuple[Network, ...]:
    return tuple(
        ipaddress.ip_network(entry.strip(), strict=False)
        for entry in spec.split(",")
        if entry.strip()
    )


def is_trusted_peer(host: str, networks: tuple[Network, ...] | None = None) -> bool:
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if networks is None:
        networks = trusted_networks(get_settings().trusted_proxy_cidrs)
    return any(address in network for network in networks)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client is not None else ""
    if not peer:
        return "unknown"
    if is_trusted_peer(peer):
        forwarded = request.headers.get("x-forwarded-for", "")
        entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
        if entries:
            return entries[-1]
    return peer


def describe_strategy() -> str:
    """One line for the startup log; contains configuration only, never request data."""
    cidrs = get_settings().trusted_proxy_cidrs or "(none)"
    return (
        f"rightmost X-Forwarded-For entry from peers in {cidrs}; "
        "other peers use their socket address"
    )
