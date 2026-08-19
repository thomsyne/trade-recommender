import hashlib
import ipaddress
import socket
import zlib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from django.utils import timezone

USER_AGENT = "FXForecastLab/0.1 (private point-in-time research)"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class FetchRejected(ValueError):
    pass


@dataclass(frozen=True)
class FetchResult:
    url: str
    fetched_at: object
    status_code: int
    content_type: str
    body: bytes
    etag: str
    last_modified: str

    @property
    def body_sha256(self):
        return hashlib.sha256(self.body).hexdigest()


def resolve_host(host):
    return {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}


def validate_url(url, policy, resolver=resolve_host):
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise FetchRejected("only HTTPS sources are allowed")
    if parsed.username or parsed.password:
        raise FetchRejected("credentials in source URLs are forbidden")
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {value.lower().rstrip(".") for value in policy.allowed_hosts}
    if not host or host not in allowed:
        raise FetchRejected(f"host is not allowed for {policy.slug}")
    try:
        addresses = resolver(host)
    except OSError as error:
        raise FetchRejected("source host could not be resolved") from error
    if not addresses:
        raise FetchRejected("source host did not resolve")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise FetchRejected("source resolved to a non-public address")
    return parsed


def fetch(policy, url, *, transport=None, resolver=resolve_host, now=None):
    if policy.state != policy.State.ENABLED:
        raise FetchRejected(f"source policy is {policy.state}")
    current = url
    with httpx.Client(
        transport=transport,
        follow_redirects=False,
        timeout=httpx.Timeout(20, connect=10),
        trust_env=False,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
    ) as client:
        for redirect_count in range(4):
            validate_url(current, policy, resolver)
            with client.stream("GET", current) as response:
                _validate_connected_peer(response)
                if response.status_code in REDIRECT_STATUSES:
                    if redirect_count == 3:
                        raise FetchRejected("source exceeded three redirects")
                    location = response.headers.get("location")
                    if not location:
                        raise FetchRejected("redirect did not include a location")
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    raise FetchRejected(f"source returned HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in policy.allowed_content_types:
                    raise FetchRejected(f"content type {content_type or 'missing'} is not allowed")
                declared_size = response.headers.get("content-length")
                if declared_size:
                    try:
                        too_large = int(declared_size) > policy.max_response_bytes
                    except ValueError as error:
                        raise FetchRejected("declared response size is invalid") from error
                    if too_large:
                        raise FetchRejected("declared response size exceeds source policy")
                raw_chunks = []
                compressed_bytes = 0
                chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
                for chunk in chunks:
                    compressed_bytes += len(chunk)
                    if compressed_bytes > policy.max_response_bytes:
                        raise FetchRejected("compressed response size exceeds source policy")
                    raw_chunks.append(chunk)
                body = _decode_bounded(
                    raw_chunks,
                    response.headers.get("content-encoding", "identity").lower(),
                    policy.max_response_bytes,
                )
                return FetchResult(
                    url=str(response.url),
                    fetched_at=now or timezone.now(),
                    status_code=response.status_code,
                    content_type=content_type,
                    body=body,
                    etag=response.headers.get("etag", "")[:500],
                    last_modified=response.headers.get("last-modified", "")[:200],
                )
    raise FetchRejected("source could not be retrieved")


def _decode_bounded(chunks, encoding, limit):
    if encoding in {"", "identity"}:
        body = b"".join(chunks)
        if len(body) > limit:
            raise FetchRejected("decoded response size exceeds source policy")
        return body
    if encoding == "gzip":
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decoder = zlib.decompressobj()
    else:
        raise FetchRejected(f"content encoding {encoding} is not allowed")
    output = []
    decoded_bytes = 0
    try:
        for chunk in chunks:
            value = decoder.decompress(chunk, limit - decoded_bytes + 1)
            decoded_bytes += len(value)
            if decoded_bytes > limit or decoder.unconsumed_tail:
                raise FetchRejected("decoded response size exceeds source policy")
            output.append(value)
        value = decoder.flush(limit - decoded_bytes + 1)
    except zlib.error as error:
        raise FetchRejected("response compression is invalid") from error
    decoded_bytes += len(value)
    if decoded_bytes > limit:
        raise FetchRejected("decoded response size exceeds source policy")
    output.append(value)
    return b"".join(output)


def _validate_connected_peer(response):
    stream = response.extensions.get("network_stream")
    if not stream:
        return
    peer = stream.get_extra_info("server_addr") or stream.get_extra_info("peername")
    if not peer:
        raise FetchRejected("connected source address could not be verified")
    value = peer[0] if isinstance(peer, tuple) else peer
    if not ipaddress.ip_address(value).is_global:
        raise FetchRejected("connected source address is non-public")
