"""SSRF-safe HTTP URL fetcher with strict DNS, IP, and network limits."""

import asyncio
import ipaddress
import logging
import socket
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import httpcore
import httpcore._backends.auto
import httpx

logger = logging.getLogger(__name__)

# Constants & Defaults
DEFAULT_MAX_RESPONSE_SIZE = 2 * 1024 * 1024  # 2 MB
DEFAULT_CONNECT_TIMEOUT = 5.0  # seconds
DEFAULT_READ_TIMEOUT = 10.0  # seconds
DEFAULT_TOTAL_TIMEOUT = 15.0  # seconds
DEFAULT_MAX_REDIRECTS = 5
LENS_USER_AGENT = "LENS/1.0 (Personal Information Capture; +https://github.com/hardikkaurani/Lens)"

SUPPORTED_SCHEMES = ("http", "https")
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


class FetchError(Exception):
    """Base exception for all fetch-related failures."""


class SSRFBlockedError(FetchError):
    """Raised when a request target violates SSRF security boundaries."""


class FetchTimeoutError(FetchError):
    """Raised when connection or read timeout expires."""


class ResponseSizeLimitExceededError(FetchError):
    """Raised when the remote response exceeds the maximum permitted byte size."""


class InvalidContentTypeError(FetchError):
    """Raised when the remote response is not an accepted readable HTML content type."""


@dataclass
class FetchedPage:
    """Encapsulates a successfully fetched and validated HTML webpage."""

    url: str
    status_code: int
    content_type: str
    html: str


def is_prohibited_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allow_localhost: bool = False,
) -> bool:
    """Return True if the IP address belongs to loopback, private, or non-public ranges."""
    if allow_localhost and (ip.is_loopback or str(ip) in ("127.0.0.1", "::1")):
        return False

    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True

    # IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1, ::ffff:10.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return is_prohibited_ip(ip.ipv4_mapped, allow_localhost=allow_localhost)

    # Site-local IPv6 (deprecated)
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return True

    # IPv4 specific prohibited ranges
    if isinstance(ip, ipaddress.IPv4Address):
        # Carrier-grade NAT (RFC 6598: 100.64.0.0/10)
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
        # Documentation & benchmark ranges (RFC 5737 / RFC 2544)
        if (
            ip in ipaddress.ip_network("198.18.0.0/15")
            or ip in ipaddress.ip_network("192.0.2.0/24")
            or ip in ipaddress.ip_network("198.51.100.0/24")
            or ip in ipaddress.ip_network("203.0.113.0/24")
        ):
            return True

    return False


def validate_url_syntax(url_str: str, allow_localhost: bool = False) -> urllib.parse.SplitResult:
    """Validate URL format, scheme, ports, and embedded credentials."""
    try:
        parsed = urllib.parse.urlsplit(url_str)
    except Exception as e:
        raise SSRFBlockedError(f"Malformed URL: {e}") from e

    if not parsed.scheme or parsed.scheme.lower() not in SUPPORTED_SCHEMES:
        raise SSRFBlockedError(
            f"Unsupported scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted."
        )

    if parsed.username or parsed.password:
        raise SSRFBlockedError("URLs with embedded credentials are not permitted.")

    if not parsed.hostname:
        raise SSRFBlockedError("URL must contain a valid host.")

    # Port restriction: only standard HTTP/HTTPS ports (or custom ports for local test servers if allowed)
    port = parsed.port
    if port is not None and not allow_localhost:
        if port not in (80, 443, 8080, 8443):
            raise SSRFBlockedError(f"Prohibited destination port '{port}'.")

    return parsed


class SSRFSafeNetworkBackend(httpcore._backends.auto.AutoBackend):
    """Network backend resolving hostnames and validating IP addresses before connection.

    Connects directly to the validated IP to eliminate DNS rebinding vulnerabilities.
    """

    def __init__(self, allow_localhost: bool = False):
        super().__init__()
        self.allow_localhost = allow_localhost

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options=None,
    ):
        loop = asyncio.get_running_loop()
        try:
            addr_info = await loop.getaddrinfo(
                host,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as e:
            raise SSRFBlockedError(f"Could not resolve host '{host}': {e}") from e

        if not addr_info:
            raise SSRFBlockedError(f"No address records found for '{host}'")

        validated_ip: Optional[str] = None
        for family, socktype, proto, canonname, sockaddr in addr_info:
            ip_str = str(sockaddr[0])
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                raise SSRFBlockedError(f"Invalid IP address format '{ip_str}'")

            if is_prohibited_ip(ip_obj, allow_localhost=self.allow_localhost):
                raise SSRFBlockedError(
                    f"Host '{host}' resolved to prohibited destination IP {ip_str}"
                )

            if validated_ip is None:
                validated_ip = ip_str

        if not validated_ip:
            raise SSRFBlockedError(f"No safe IP address resolved for '{host}'")

        # Establish TCP connection directly to the pre-validated IP address
        return await super().connect_tcp(
            validated_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class SSRFSafeTransport(httpx.AsyncHTTPTransport):
    """Async transport utilizing the SSRFSafeNetworkBackend."""

    def __init__(self, *args, allow_localhost: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=getattr(self._pool, "_ssl_context", None),
            network_backend=SSRFSafeNetworkBackend(allow_localhost=allow_localhost),
            http1=True,
            http2=False,
            retries=0,
        )


async def safe_fetch_url(
    url: str,
    max_response_size: int = DEFAULT_MAX_RESPONSE_SIZE,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_localhost: bool = False,
) -> FetchedPage:
    """Fetch an external URL with strict SSRF validation, timeouts, and streaming size limits.

    Follows HTTP redirects manually, re-validating every redirect target for SSRF safety.
    """
    transport = SSRFSafeTransport(allow_localhost=allow_localhost)
    timeout = httpx.Timeout(
        timeout=total_timeout,
        connect=connect_timeout,
        read=read_timeout,
    )
    headers = {
        "User-Agent": LENS_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        "Accept-Language": "en-US,en;q=0.8",
    }

    current_url = url
    redirect_count = 0

    async with httpx.AsyncClient(transport=transport, verify=True) as client:
        while True:
            # 1. Validate URL syntax and protocol
            validate_url_syntax(current_url, allow_localhost=allow_localhost)

            try:
                # 2. Open streaming connection without automatic redirect following
                async with client.stream(
                    "GET",
                    current_url,
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=False,
                ) as response:
                    # 3. Handle HTTP redirects manually with SSRF re-validation
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise FetchError(
                                f"HTTP {response.status_code} redirect missing 'Location' header."
                            )

                        redirect_count += 1
                        if redirect_count > max_redirects:
                            raise FetchError(
                                f"Exceeded maximum redirect limit of {max_redirects} hops."
                            )

                        # Resolve relative redirect URLs against the current URL
                        next_url = urllib.parse.urljoin(current_url, location)
                        logger.debug("Following redirect %d: %s -> %s", redirect_count, current_url, next_url)
                        current_url = next_url
                        continue

                    # 4. Check HTTP status code
                    if response.status_code < 200 or response.status_code >= 300:
                        raise FetchError(
                            f"Remote server responded with unsuccessful HTTP status {response.status_code}."
                        )

                    # 5. Check Content-Type (HTML only)
                    content_type = response.headers.get("Content-Type", "").lower()
                    if not any(t in content_type for t in ALLOWED_CONTENT_TYPES):
                        raise InvalidContentTypeError(
                            f"Unsupported content type '{content_type}'. Only HTML documents are processed."
                        )

                    # 6. Stream and buffer response body enforcing maximum byte limit
                    chunks: list[bytes] = []
                    total_bytes = 0

                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > max_response_size:
                            raise ResponseSizeLimitExceededError(
                                f"Response size exceeded limit of {max_response_size} bytes."
                            )
                        chunks.append(chunk)

                    encoding = response.encoding or "utf-8"
                    html_text = b"".join(chunks).decode(encoding, errors="replace")

                    return FetchedPage(
                        url=current_url,
                        status_code=response.status_code,
                        content_type=content_type,
                        html=html_text,
                    )

            except httpx.ConnectTimeout as e:
                raise FetchTimeoutError(f"Connection timeout to '{current_url}': {e}") from e
            except httpx.ReadTimeout as e:
                raise FetchTimeoutError(f"Read timeout from '{current_url}': {e}") from e
            except httpx.TimeoutException as e:
                raise FetchTimeoutError(f"Request timeout for '{current_url}': {e}") from e
            except (SSRFBlockedError, InvalidContentTypeError, ResponseSizeLimitExceededError, FetchTimeoutError):
                raise
            except Exception as e:
                # Wrap any unexpected network/httpcore exceptions
                logger.warning("Error fetching '%s': %s", current_url, e)
                raise FetchError(f"Failed to fetch URL: {e}") from e
