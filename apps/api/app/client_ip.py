"""Resolve the real client address behind the private web proxy.

Only a loopback or private-network peer is trusted to forward X-Forwarded-For.
Within that header the rightmost entry is the one appended by the trusted edge
(Caddy or the hosting platform); anything further left was supplied by the
browser and could be spoofed to dodge per-address limits.
"""

import ipaddress

from fastapi import Request

TRUSTED_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)


def is_trusted_peer(host: str) -> bool:
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in TRUSTED_NETWORKS)


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
