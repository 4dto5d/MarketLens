from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
import urllib3
from requests.structures import CaseInsensitiveDict

MAX_REDIRECTS = 5
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
STYLESHEET_MAX_RESPONSE_BYTES = 1024 * 1024
STREAM_CHUNK_BYTES = 64 * 1024
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".test", ".example", ".invalid")
BLOCKED_IPV6_TRANSLATION = tuple(ipaddress.ip_network(value) for value in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"))


class Resolver(Protocol):
    def __call__(self, host: str, port: int) -> tuple[str, ...]: ...


class UnsafePublicUrlError(requests.RequestException):
    """The target cannot safely be used for a public-network fetch."""


class PublicResponseTooLargeError(UnsafePublicUrlError):
    """The decoded public response exceeded the bounded download size."""


@dataclass(frozen=True)
class ValidatedPublicUrl:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


class PublicTransport(Protocol):
    def request(self, method: str, target: ValidatedPublicUrl, *, timeout: float, headers: dict[str, str]) -> requests.Response: ...


def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafePublicUrlError(f"Public hostname could not be resolved: {host}") from exc
    return tuple(dict.fromkeys(str(record[4][0]) for record in records))


def _public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.scope_id or any(ip in network for network in BLOCKED_IPV6_TRANSLATION):
            return False
        if ip.ipv4_mapped is not None:
            return _public_address(str(ip.ipv4_mapped))
    return True


def validate_public_url(url: str, *, resolver: Resolver = resolve_public_addresses) -> ValidatedPublicUrl:
    cleaned = (url or "").strip()
    if "\\" in cleaned or any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise UnsafePublicUrlError("URL contains unsafe control characters or backslashes.")
    try:
        parsed = urlsplit(cleaned)
        host = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    except ValueError as exc:
        raise UnsafePublicUrlError("URL could not be parsed safely.") from exc
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise UnsafePublicUrlError("Only public HTTP and HTTPS URLs may be fetched.")
    if not host or parsed.username is not None or parsed.password is not None:
        raise UnsafePublicUrlError("URL must contain a public hostname and no embedded credentials.")
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafePublicUrlError(f"Local or special-use hostname is blocked: {host}")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
            addresses = resolver(host, port)
        except (UnicodeError, OSError) as exc:
            raise UnsafePublicUrlError(f"Public hostname could not be resolved safely: {host}") from exc
    else:
        addresses = (str(literal),)
    if not addresses or any(not _public_address(address) for address in addresses):
        raise UnsafePublicUrlError(f"Non-public, special-use, or unresolved network destination is blocked for {host}.")
    authority = f"[{host}]" if ":" in host else host
    if parsed.port is not None:
        authority += f":{port}"
    normalized = urlunsplit((parsed.scheme.casefold(), authority, parsed.path, parsed.query, ""))
    return ValidatedPublicUrl(normalized, host, port, tuple(addresses))


class PinnedPublicTransport:
    """Connect only to a validated numeric IP while preserving TLS hostname verification.

    No environment proxy, automatic redirect, or second hostname resolution is used.
    urllib3 is already a required dependency of the project's requests dependency.
    """

    def __init__(self, max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES) -> None:
        if max_response_bytes < 0:
            raise ValueError("max_response_bytes must be non-negative")
        self.max_response_bytes = max_response_bytes

    def request(self, method: str, target: ValidatedPublicUrl, *, timeout: float, headers: dict[str, str]) -> requests.Response:
        # Keep direct transport callers fail-closed too; never trust a constructed token.
        validated = validate_public_url(target.url, resolver=lambda _host, _port: target.addresses)
        if validated != target:
            raise UnsafePublicUrlError("Transport destination does not match its validated URL.")
        parsed = urlsplit(target.url)
        pool: Any
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(
                target.addresses[0], target.port,
                cert_reqs="CERT_REQUIRED", ca_certs=requests.certs.where(),
                assert_hostname=target.host, server_hostname=target.host,
            )
        else:
            pool = urllib3.HTTPConnectionPool(target.addresses[0], target.port)
        request_headers = dict(headers)
        request_headers["Host"] = parsed.netloc
        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        try:
            raw = pool.urlopen(
                method, path, headers=request_headers, redirect=False, retries=False,
                timeout=urllib3.Timeout(connect=timeout, read=timeout), preload_content=False,
            )
            content_length = raw.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > self.max_response_bytes:
                        raise PublicResponseTooLargeError(
                            f"Public response exceeds the {self.max_response_bytes}-byte limit."
                        )
                except ValueError:
                    pass
            if hasattr(raw, "stream"):
                chunks: list[bytes] = []
                total = 0
                for chunk in raw.stream(amt=STREAM_CHUNK_BYTES, decode_content=True):
                    total += len(chunk)
                    if total > self.max_response_bytes:
                        raise PublicResponseTooLargeError(
                            f"Decoded public response exceeds the {self.max_response_bytes}-byte limit."
                        )
                    chunks.append(chunk)
                content = b"".join(chunks)
            else:
                # Compatibility for bounded fixture transports used by the test suite.
                content = bytes(raw.data)
                if len(content) > self.max_response_bytes:
                    raise PublicResponseTooLargeError(
                        f"Public response exceeds the {self.max_response_bytes}-byte limit."
                    )
            response = requests.Response()
            response.status_code = raw.status
            response.headers = CaseInsensitiveDict(raw.headers)
            response.url = target.url
            response._content = content
            response.encoding = requests.utils.get_encoding_from_headers(response.headers)
            return response
        except PublicResponseTooLargeError:
            raise
        except (urllib3.exceptions.HTTPError, OSError) as exc:
            raise requests.ConnectionError(f"Public website connection failed: {exc.__class__.__name__}") from exc
        finally:
            if "raw" in locals() and hasattr(raw, "release_conn"):
                raw.release_conn()
            pool.close()


def safe_request(
    requester: Any,
    method: str,
    url: str,
    *,
    resolver: Resolver = resolve_public_addresses,
    transport: PublicTransport | None = None,
    max_redirects: int = MAX_REDIRECTS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    timeout: float = 12,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """Validate and pin every hop BEFORE sending any traffic to that destination."""
    current = url
    request_method = method.upper()
    request_headers = dict(getattr(requester, "headers", {}) or {})
    request_headers.update(headers or {})
    network = transport or PinnedPublicTransport(max_response_bytes)
    for redirect_count in range(max_redirects + 1):
        target = validate_public_url(current, resolver=resolver)
        response = network.request(request_method, target, timeout=timeout, headers=request_headers)
        response_content = getattr(response, "content", None)
        response_size = (
            len(response_content)
            if response_content is not None
            else len(str(getattr(response, "text", "")).encode("utf-8"))
        )
        if response_size > max_response_bytes:
            response.close()
            raise PublicResponseTooLargeError(
                f"Public response exceeds the {max_response_bytes}-byte limit."
            )
        location = response.headers.get("Location")
        if response.status_code not in {301, 302, 303, 307, 308} or not location:
            return response
        try:
            if redirect_count >= max_redirects:
                raise UnsafePublicUrlError(f"Redirect limit exceeded ({max_redirects}).")
            current = validate_public_url(urljoin(target.url, location), resolver=resolver).url
        finally:
            response.close()
        if response.status_code == 303 and request_method != "HEAD":
            request_method = "GET"
    raise UnsafePublicUrlError("Redirect validation failed closed.")
