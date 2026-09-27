"""Outbound destination guard: no requests to private, loopback or metadata addresses.

Webhook URLs are tenant supplied. Without this check an administrator of one tenant could
point the worker at the database, the object store, or a cloud metadata service. The host
is resolved and every address it maps to must be publicly routable. Development allows
private destinations so the compose stack can post to local receivers.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from app.config import get_settings

# Beyond ipaddress' own private/loopback/link-local classification.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6, checked as IPv4 below
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64
)


class DestinationBlocked(ValueError):
    pass


def private_destinations_allowed() -> bool:
    return get_settings().environment == "development"


def address_is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or getattr(address, "is_site_local", False)
    ):
        return False
    return not any(address in network for network in _BLOCKED_NETWORKS)


def resolve_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        return [literal]
    try:
        records = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise DestinationBlocked(f"Destination host could not be resolved: {host}") from exc
    addresses = []
    for record in records:
        try:
            addresses.append(ipaddress.ip_address(str(record[4][0]).split("%")[0]))
        except ValueError:
            continue
    if not addresses:
        raise DestinationBlocked(f"Destination host could not be resolved: {host}")
    return addresses


def check_destination(url: str, *, allow_private: bool | None = None) -> None:
    """Raise :class:`DestinationBlocked` unless ``url`` points at a public HTTPS endpoint.

    ``allow_private`` defaults to the environment rule (development only). When private
    destinations are allowed the scheme may also be plain HTTP.
    """
    permissive = private_destinations_allowed() if allow_private is None else allow_private
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise DestinationBlocked("Destination must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise DestinationBlocked("Destination URL must not embed credentials")
    if parsed.scheme != "https" and not permissive:
        raise DestinationBlocked("Destination must use https")
    if permissive:
        return
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".internal", ".local")):
        raise DestinationBlocked("Destination host is not publicly routable")
    for address in resolve_addresses(host):
        if not address_is_public(address):
            raise DestinationBlocked("Destination resolves to a private or reserved address")
