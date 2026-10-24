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
from typing import NamedTuple, Optional
from urllib.parse import urljoin, urlparse

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


def _is_private_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
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


def download_image(url: str) -> Optional[PreparedImage]:
    """Download and prepare ``url``. Returns ``None`` on any failure
    (unsafe host, network error, non-2xx, size cap, unsupported type).

    The caller owns the returned file and must ``os.unlink`` it after
    ``add_picture`` has read the bytes. ``add_picture`` reads eagerly, so
    the file can be removed before ``doc.save``.
    """
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

            with httpx.stream(
                "GET",
                current_url,
                timeout=_INLINE_IMAGE_TIMEOUT,
                follow_redirects=False,
                headers=headers,
            ) as resp:
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
                return _prepare_image(bytes(data))
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


def prepare_image_source(src: str) -> Optional[PreparedImage]:
    """Fetch and prepare an image reference from the Markdown.

    Only remote and ``data:`` images are embedded. Markdown comes from
    untrusted users, so a local path (e.g. `/dev/zero`, `/etc/...`) must
    never be read off the converter's own filesystem.
    """
    src = (src or "").strip()
    if src.startswith(("http://", "https://")):
        return download_image(src)
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
                with httpx.stream(
                    "GET",
                    current_url,
                    timeout=10,
                    follow_redirects=False,
                    headers=headers,
                ) as resp:
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

