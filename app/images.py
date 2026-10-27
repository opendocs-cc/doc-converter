"""
Images for exports: fetching, decoding and sizing.

Inline body images (Markdown ``![alt](url)``) are downloaded at conversion
time and embedded into the DOCX. Downloads are hard-capped on size, time,
and format so a single bad URL can never take a worker down. Any failure
returns ``None`` and the caller shows the image's alt text instead, so
exports always complete.

Every prepared image comes with its CSS width: the width in pixels it is
drawn at on the web (an SVG's declared size, a bitmap's pixel width). The
converter sizes pictures from that, so an image takes the same share of
the page as it takes of the web column.
"""

from __future__ import annotations

import base64
import binascii
import io
import ipaddress
import os
import re
import socket
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Iterable, Iterator, NamedTuple, Optional
from urllib.parse import urljoin, urlparse

import httpcore
import httpx
from lxml import etree

from .branding import BrandingConfig


class PreparedImage(NamedTuple):
    path: str          # temp file python-docx can embed; the caller unlinks it
    css_width: float   # width in CSS pixels on the web
    css_height: float

_INLINE_IMAGE_TIMEOUT = 15.0
_INLINE_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_REMOTE_FETCH_MAX_REDIRECTS = 3
_REMOTE_LOGO_MAX_BYTES = 5 * 1024 * 1024
_BLOCKED_HOSTS = {
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
    "0.0.0.0",
    "broadcasthost",
    "metadata.google.internal",
    "metadata",
}


_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")


def _is_private_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    # An IPv6 address can carry an IPv4 one (``::ffff:10.0.0.1``, or NAT64's
    # ``64:ff9b::10.0.0.1``); judge the IPv4 address it reaches.
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64_PREFIX:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return not ip.is_global


def _is_blocked_host(host: str) -> bool:
    lower = host.lower().strip("[]")
    return (
        lower in _BLOCKED_HOSTS
        or lower.endswith(".local")
        or lower.endswith(".internal")
        or lower.endswith(".localhost")
    )


def _is_safe_remote_url(url: str) -> bool:
    """Early check of a URL before it's requested: http(s), not a blocked
    name, and resolving only to public addresses. The connection itself is
    checked again (``_PublicOnlyBackend``), against the address it uses."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname
    if _is_blocked_host(host):
        return False
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(not _is_private_ip(addr) for addr in addresses)


def _public_addresses(host: str, port: int) -> list[str]:
    """The addresses ``host`` resolves to, if every one of them is public.
    Raises ``httpcore.ConnectError`` otherwise."""
    if _is_blocked_host(host):
        raise httpcore.ConnectError(f"refusing to connect to {host!r}")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise httpcore.ConnectError(f"could not resolve {host!r}: {exc}") from exc
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses or any(_is_private_ip(addr) for addr in addresses):
        raise httpcore.ConnectError(f"refusing to connect to {host!r}: not a public address")
    return addresses


class _PublicOnlyBackend(httpcore.SyncBackend):
    """Opens TCP connections only to public addresses.

    The host is resolved here, once, and the socket connects to the address
    that was checked. Checking the URL first and letting the HTTP client
    resolve the name again would leave a DNS-rebinding window: a name can
    answer with a public address for the check and a private one (the
    metadata server, a service on the private network) for the connection.

    Only the TCP connection uses the address. The request's Host header and
    TLS (SNI and certificate checks) still use the hostname from the URL,
    because httpcore takes those from the request, not from this call.
    """

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        last_error: Optional[Exception] = None
        for address in _public_addresses(host, port):
            try:
                return super().connect_tcp(address, port, timeout=timeout,
                                           local_address=local_address,
                                           socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore.ConnectError(f"could not connect to {host!r}")


class _PublicOnlyTransport(httpx.HTTPTransport):
    """``httpx.HTTPTransport`` whose connections go through
    ``_PublicOnlyBackend``. No proxy: a proxy would make the connection for
    us, to whatever the name resolves to on its side."""

    def __init__(self) -> None:
        super().__init__()
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            network_backend=_PublicOnlyBackend(),
        )


@contextmanager
def _stream_public(url: str, *, timeout: float, headers: dict) -> Iterator[httpx.Response]:
    """``httpx.stream("GET", url)`` that only ever connects to public
    addresses (see ``_PublicOnlyBackend``). Redirects are not followed: the
    caller checks each ``Location`` and makes a new request, which is
    checked again when it connects."""
    with httpx.Client(
        transport=_PublicOnlyTransport(),
        trust_env=False,  # no proxies from the environment
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
    ) as client:
        with client.stream("GET", url) as resp:
            yield resp


# Recently downloaded images, per process. Images on OpenDocs' own storage
# never change (every upload gets a new name); other URLs are kept briefly.
_CACHE_MAX_BYTES = int(os.getenv("IMAGE_CACHE_MB", "64")) * 1024 * 1024
_CACHE_TTL = 600.0
_cache: "OrderedDict[str, tuple[float, bytes]]" = OrderedDict()
_cache_bytes = 0
_cache_lock = threading.Lock()
# Parallel downloads per document.
_PREFETCH_WORKERS = 8


def _cache_get(url: str) -> Optional[bytes]:
    with _cache_lock:
        hit = _cache.get(url)
        if hit is None:
            return None
        stored, data = hit
        if time.monotonic() - stored > _CACHE_TTL:
            _cache_drop(url)
            return None
        _cache.move_to_end(url)
        return data


def _cache_drop(url: str) -> None:
    global _cache_bytes
    _, data = _cache.pop(url)
    _cache_bytes -= len(data)


def _cache_put(url: str, data: bytes) -> None:
    global _cache_bytes
    if len(data) > _CACHE_MAX_BYTES // 4:
        return
    with _cache_lock:
        if url in _cache:
            _cache_drop(url)
        _cache[url] = (time.monotonic(), data)
        _cache_bytes += len(data)
        while _cache_bytes > _CACHE_MAX_BYTES and _cache:
            _cache_drop(next(iter(_cache)))


def download_image(url: str) -> Optional[PreparedImage]:
    """Download and prepare ``url``. Returns ``None`` on any failure
    (unsafe host, network error, non-2xx, size cap, unsupported type).

    The caller owns the returned file and must ``os.unlink`` it after
    ``add_picture`` has read the bytes. ``add_picture`` reads eagerly, so
    the file can be removed before ``doc.save``.
    """
    data = fetch_image_bytes(url)
    return _prepare_image(data) if data is not None else None


def prefetch_images(urls: Iterable[str]) -> dict[str, Optional[bytes]]:
    """Download ``urls`` in parallel: ``{url: bytes or None}``."""
    remote = list(dict.fromkeys(u.strip() for u in urls if u.strip().startswith(("http://", "https://"))))
    if not remote:
        return {}
    if len(remote) == 1:
        return {remote[0]: fetch_image_bytes(remote[0])}
    with ThreadPoolExecutor(max_workers=min(_PREFETCH_WORKERS, len(remote))) as pool:
        return dict(zip(remote, pool.map(fetch_image_bytes, remote)))


def fetch_image_bytes(url: str) -> Optional[bytes]:
    """The bytes at ``url`` (cached), or ``None`` on any failure."""
    cached = _cache_get(url)
    if cached is not None:
        return cached
    data = _download(url)
    if data is not None:
        _cache_put(url, data)
    return data


def _download(url: str) -> Optional[bytes]:
    try:
        headers = {
            # Some CDNs (Wikimedia in particular) reject the default httpx
            # UA with a 403. Identify ourselves politely.
            "User-Agent": "OpenDocs-Converter/0.1 (+https://opendocs.cc)",
            "Accept": "image/*",
        }
        current_url = url
        for _hop in range(_REMOTE_FETCH_MAX_REDIRECTS + 1):
            if not _is_safe_remote_url(current_url):
                return None

            with _stream_public(current_url, timeout=_INLINE_IMAGE_TIMEOUT, headers=headers) as resp:
                if 300 <= resp.status_code < 400:
                    location = resp.headers.get("location")
                    if not location:
                        return None
                    current_url = urljoin(current_url, location)
                    continue

                if resp.status_code >= 400:
                    return None

                # The format is sniffed from the bytes afterwards
                # (`_prepare_image`), so the content type only screens out
                # obvious non-images; some origins serve images as
                # `application/octet-stream`.
                ctype = (resp.headers.get("content-type") or "").lower().split(";")[0].strip()
                if ctype.startswith(("text/html", "application/json", "video/", "audio/")):
                    return None

                data = bytearray()
                for chunk in resp.iter_bytes():
                    data.extend(chunk)
                    if len(data) > _INLINE_IMAGE_MAX_BYTES:
                        return None
                return bytes(data)
        return None
    except Exception:
        return None


def data_uri_image(uri: str) -> Optional[PreparedImage]:
    """Decode a ``data:image/...;base64,...`` URI and prepare it."""
    m = re.match(r"data:image/[a-z0-9.+-]+;base64,(.*)$", uri.strip(), re.I | re.S)
    if not m or len(m.group(1)) > _INLINE_IMAGE_MAX_BYTES * 4 // 3 + 4:
        return None
    try:
        data = base64.b64decode(re.sub(r"\s+", "", m.group(1)), validate=True)
    except (binascii.Error, ValueError):
        return None
    return _prepare_image(data)


# Formats python-docx embeds as-is, by magic bytes.
_NATIVE_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)
_SVG_UNITS_PX = {"": 1.0, "px": 1.0, "pt": 4 / 3, "pc": 16.0,
                 "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0}
# Rasterized images: at most this many pixels wide or tall.
_RASTER_MAX_SIDE = 2400
_RASTER_MAX_PIXELS = 40_000_000


def _write_temp(data: bytes, suffix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    with tmp:
        tmp.write(data)
    return tmp.name


def _looks_like_svg(data: bytes) -> bool:
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<svg", b"<?xml", b"<!--", b"<!doctype svg")) and b"<svg" in data[:4096].lower()


def _svg_length_px(value: Optional[str]) -> Optional[float]:
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([a-z%]*)\s*", value or "")
    if not m or m.group(2) not in _SVG_UNITS_PX:
        return None
    return float(m.group(1)) * _SVG_UNITS_PX[m.group(2)]


def _rasterize_svg(data: bytes) -> Optional[tuple[bytes, float, float]]:
    """Render an SVG to PNG, sized from its own width/height/viewBox.
    Returns the PNG and the SVG's CSS width and height.

    CairoSVG runs in its default safe mode: no XML entities, no external
    files and no network, only ``data:`` URLs inside the SVG. The output
    size is fixed up front so an SVG that declares a huge canvas can't
    exhaust memory. It's drawn at up to 3x its CSS size so it stays sharp
    in print.
    """
    try:
        root = etree.fromstring(
            data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        )
    except etree.XMLSyntaxError:
        return None
    if etree.QName(root).localname != "svg":
        return None
    width = _svg_length_px(root.get("width"))
    height = _svg_length_px(root.get("height"))
    viewbox = [float(v) for v in re.split(r"[\s,]+", (root.get("viewBox") or "").strip()) if v]
    if len(viewbox) == 4 and viewbox[2] > 0 and viewbox[3] > 0:
        aspect = viewbox[2] / viewbox[3]
        if width is None and height is None:
            width, height = viewbox[2], viewbox[3]
        elif width is None:
            width = height * aspect
        elif height is None:
            height = width / aspect
    if not width or not height:
        width, height = 600.0, 400.0
    scale = min(3.0, _RASTER_MAX_SIDE / width, _RASTER_MAX_SIDE / height)
    out_w, out_h = max(1, round(width * scale)), max(1, round(height * scale))
    try:
        import cairosvg

        png = cairosvg.svg2png(bytestring=data, output_width=out_w, output_height=out_h)
        return png, width, height
    except Exception:
        return None


def _prepare_image(data: bytes) -> Optional[PreparedImage]:
    """Write ``data`` to a temp file python-docx can embed.

    PNG, JPEG, GIF and BMP are kept as they are. SVG is rasterized and
    anything else Pillow can read (WebP, TIFF, AVIF, ICO...) becomes a PNG.
    The caller owns the returned file.
    """
    from PIL import Image

    if _looks_like_svg(data):
        rendered = _rasterize_svg(data)
        if rendered is None:
            return None
        png, width, height = rendered
        return PreparedImage(_write_temp(png, ".png"), width, height)
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > _RASTER_MAX_PIXELS:
                return None
            # Browsers ignore DPI metadata and draw a bitmap at one CSS
            # pixel per image pixel, so that's its CSS size here too.
            size = (float(img.width), float(img.height))
            for signature, suffix in _NATIVE_IMAGE_SIGNATURES:
                if data.startswith(signature):
                    return PreparedImage(_write_temp(data, suffix), *size)
            img.seek(0)
            converted = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
            buf = io.BytesIO()
            converted.save(buf, format="PNG")
            return PreparedImage(_write_temp(buf.getvalue(), ".png"), *size)
    except Exception:
        return None


def prepare_image_source(src: str, prefetched: Optional[dict] = None) -> Optional[PreparedImage]:
    """Fetch and prepare an image reference from the Markdown.
    ``prefetched`` holds images already downloaded (``prefetch_images``).

    Only remote and ``data:`` images are embedded. Markdown comes from
    untrusted users, so a local path (e.g. `/dev/zero`, `/etc/...`) must
    never be read off the converter's own filesystem.
    """
    src = (src or "").strip()
    if src.startswith(("http://", "https://")):
        data = prefetched[src] if prefetched is not None and src in prefetched else fetch_image_bytes(src)
        return _prepare_image(data) if data is not None else None
    if src.lower().startswith("data:image/"):
        return data_uri_image(src)
    return None


BUNDLED_LOGO_SENTINEL = "bundled:opendocs"


def resolve_logo(brand: BrandingConfig) -> tuple[Optional[str], bool]:
    """Resolve brand.logo_url into a local file path.

    Three modes:
        * ``None``                     → no logo (return ``(None, False)``)
        * ``"bundled:opendocs"``       → use the packaged OpenDocs logo
          (Free plan branding).
        * ``"https://..."`` / ``"http://..."``
                                       → download to a temp file and return
          its path.

    Returns
    -------
    (path, is_temp) : tuple[str | None, bool]
        ``path``   : filesystem path to the logo image, or ``None``.
        ``is_temp``: ``True`` if the file was downloaded and the caller
                     should unlink it after use; ``False`` for the bundled
                     logo (never delete it).
    """
    if not brand.logo_url:
        return None, False

    # Bundled OpenDocs logo — used for the Free plan
    if brand.logo_url == BUNDLED_LOGO_SENTINEL:
        bundled = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.png")
        if os.path.exists(bundled):
            return os.path.abspath(bundled), False
        return None, False

    # External URL — download into a temp file
    if brand.logo_url.startswith(("http://", "https://")):
        try:
            # Polite User-Agent — some CDNs (and Wikipedia) reject the
            # default httpx UA with a 403.
            headers = {
                "User-Agent": "OpenDocs-Converter/0.1 (+https://opendocs.cc)",
            }
            current_url = brand.logo_url
            for _hop in range(_REMOTE_FETCH_MAX_REDIRECTS + 1):
                if not _is_safe_remote_url(current_url):
                    return None, False
                with _stream_public(current_url, timeout=10, headers=headers) as resp:
                    if 300 <= resp.status_code < 400:
                        location = resp.headers.get("location")
                        if not location:
                            return None, False
                        current_url = urljoin(current_url, location)
                        continue
                    resp.raise_for_status()
                    ctype = resp.headers.get("content-type", "").lower()
                    suffix = ".png"
                    if "jpeg" in ctype or "jpg" in ctype or current_url.lower().endswith((".jpg", ".jpeg")):
                        suffix = ".jpg"
                    elif "gif" in ctype or current_url.lower().endswith(".gif"):
                        suffix = ".gif"
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    total = 0
                    try:
                        for chunk in resp.iter_bytes():
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > _REMOTE_LOGO_MAX_BYTES:
                                raise ValueError("logo exceeds size cap")
                            tmp.write(chunk)
                        tmp.close()
                        return tmp.name, True
                    except Exception:
                        tmp.close()
                        try:
                            os.unlink(tmp.name)
                        except OSError:
                            pass
                        return None, False
            return None, False
        except Exception:
            return None, False

    # Unrecognized value — treat as "no logo" rather than crash
    return None, False

