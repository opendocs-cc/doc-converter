"""Remote image downloads only ever connect to public addresses.

DNS is mocked, and so is the TCP connection: nothing here touches the
network. ``FakeStream`` plays the server's side of one HTTP exchange.
"""

import io
import socket
import unittest
from unittest import mock

import httpcore
from PIL import Image

import app.images as images
from app.branding import BrandingConfig

PUBLIC_IP = "93.184.216.34"
PUBLIC_IP_2 = "93.184.216.35"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "purple").save(buf, format="PNG")
    return buf.getvalue()


def _response(status: str, headers: dict, body: bytes = b"") -> bytes:
    lines = [f"HTTP/1.1 {status}"] + [f"{k}: {v}" for k, v in headers.items()]
    lines.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


class FakeStream(httpcore.NetworkStream):
    def __init__(self, response: bytes):
        self._response = response
        self.written = b""
        self.server_hostname = None

    def read(self, max_bytes, timeout=None):
        chunk, self._response = self._response[:max_bytes], self._response[max_bytes:]
        return chunk

    def write(self, buffer, timeout=None):
        self.written += buffer

    def close(self):
        pass

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.server_hostname = server_hostname
        return self

    def get_extra_info(self, info):
        return None


class FakeNetwork:
    """Mocked DNS and TCP. ``dns`` maps a host to the list of answers it
    gives, one per lookup (the last answer repeats). ``servers`` maps an IP
    to the raw HTTP response it sends."""

    def __init__(self, dns: dict, servers: dict):
        self.dns = {host: list(answers) for host, answers in dns.items()}
        self.servers = servers
        self.lookups: list[str] = []
        self.connections: list[tuple[str, int]] = []
        self.streams: list[FakeStream] = []

    def getaddrinfo(self, host, port, *args, **kwargs):
        self.lookups.append(host)
        answers = self.dns.get(host)
        if not answers:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        ips = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(ips, str):
            ips = [ips]
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (ip, port or 0)) for ip in ips]

    def connect_tcp(self, backend, host, port, timeout=None, local_address=None, socket_options=None):
        self.connections.append((host, port))
        if host not in self.servers:
            raise httpcore.ConnectError(f"no route to {host}")
        stream = FakeStream(self.servers[host])
        self.streams.append(stream)
        return stream

    def __enter__(self):
        net = self
        self._patches = [
            mock.patch.object(images.socket, "getaddrinfo", self.getaddrinfo),
            # The real TCP connect, which _PublicOnlyBackend calls once it has
            # checked the address.
            mock.patch.object(httpcore.SyncBackend, "connect_tcp",
                              lambda backend, *a, **kw: net.connect_tcp(backend, *a, **kw)),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def png_server() -> bytes:
    return _response("200 OK", {"Content-Type": "image/png"}, _png())


class PrivateAddressTests(unittest.TestCase):
    def test_host_resolving_to_private_address_is_refused(self):
        for ip in ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1", "::1",
                   "fd00::1", "::ffff:10.0.0.5", "64:ff9b::a00:5"]:
            with self.subTest(ip=ip), FakeNetwork({"evil.example": [ip]}, {ip: png_server()}) as net:
                self.assertIsNone(images._download("http://evil.example/x.png"))
                self.assertEqual(net.connections, [])

    def test_any_private_answer_refuses_the_host(self):
        with FakeNetwork({"evil.example": [[PUBLIC_IP, "10.0.0.5"]]},
                         {PUBLIC_IP: png_server(), "10.0.0.5": png_server()}) as net:
            self.assertIsNone(images._download("http://evil.example/x.png"))
            self.assertEqual(net.connections, [])

    def test_dns_rebinding_after_the_check_is_refused(self):
        # Public for the first lookup (the URL check), private afterwards.
        with FakeNetwork({"rebind.example": [PUBLIC_IP, "169.254.169.254"]},
                         {PUBLIC_IP: png_server(), "169.254.169.254": png_server()}) as net:
            self.assertIsNone(images._download("http://rebind.example/x.png"))
            self.assertGreaterEqual(len(net.lookups), 2)
            self.assertEqual(net.connections, [])

    def test_connection_is_checked_without_the_url_check(self):
        with FakeNetwork({"evil.example": ["10.0.0.5"]}, {"10.0.0.5": png_server()}) as net:
            with self.assertRaises(httpcore.ConnectError):
                images._PublicOnlyBackend().connect_tcp("evil.example", 80)
            with self.assertRaises(httpcore.ConnectError):
                images._PublicOnlyBackend().connect_tcp("10.0.0.5", 80)
            self.assertEqual(net.connections, [])

    def test_redirect_to_private_address_is_refused(self):
        redirect = _response("302 Found", {"Location": "http://internal.example/secret.png"})
        with FakeNetwork({"images.example": [PUBLIC_IP], "internal.example": ["10.1.2.3"]},
                         {PUBLIC_IP: redirect, "10.1.2.3": png_server()}) as net:
            self.assertIsNone(images._download("http://images.example/x.png"))
            self.assertEqual(net.connections, [(PUBLIC_IP, 80)])

    def test_redirect_that_rebinds_is_refused(self):
        redirect = _response("302 Found", {"Location": "http://rebind.example/x.png"})
        with FakeNetwork({"images.example": [PUBLIC_IP], "rebind.example": [PUBLIC_IP_2, "10.1.2.3"]},
                         {PUBLIC_IP: redirect, PUBLIC_IP_2: png_server(), "10.1.2.3": png_server()}) as net:
            self.assertIsNone(images._download("http://images.example/x.png"))
            self.assertEqual(net.connections, [(PUBLIC_IP, 80)])

    def test_logo_on_private_address_is_refused(self):
        brand = BrandingConfig(logo_url="http://rebind.example/logo.png")
        with FakeNetwork({"rebind.example": [PUBLIC_IP, "10.0.0.5"]},
                         {PUBLIC_IP: png_server(), "10.0.0.5": png_server()}) as net:
            self.assertEqual(images.resolve_logo(brand), (None, False))
            self.assertEqual(net.connections, [])


class PublicAddressTests(unittest.TestCase):
    def test_public_image_is_fetched_from_the_checked_address(self):
        with FakeNetwork({"images.example": [PUBLIC_IP]}, {PUBLIC_IP: png_server()}) as net:
            self.assertEqual(images._download("http://images.example/x.png"), _png())
        self.assertEqual(net.connections, [(PUBLIC_IP, 80)])
        request = net.streams[0].written.decode()
        self.assertTrue(request.startswith("GET /x.png HTTP/1.1\r\n"))
        self.assertIn("\r\nHost: images.example\r\n", request)
        self.assertIn("\r\nUser-Agent: OpenDocs-Converter/0.1 (+https://opendocs.cc)\r\n", request)

    def test_https_keeps_the_hostname_for_tls(self):
        with FakeNetwork({"images.example": [PUBLIC_IP]}, {PUBLIC_IP: png_server()}) as net:
            self.assertEqual(images._download("https://images.example/x.png"), _png())
        self.assertEqual(net.connections, [(PUBLIC_IP, 443)])
        self.assertEqual(net.streams[0].server_hostname, "images.example")
        self.assertIn("\r\nHost: images.example\r\n", net.streams[0].written.decode())

    def test_public_redirect_is_followed(self):
        redirect = _response("301 Moved Permanently", {"Location": "https://cdn.example/x.png"})
        with FakeNetwork({"images.example": [PUBLIC_IP], "cdn.example": [PUBLIC_IP_2]},
                         {PUBLIC_IP: redirect, PUBLIC_IP_2: png_server()}) as net:
            self.assertEqual(images._download("http://images.example/x.png"), _png())
        self.assertEqual(net.connections, [(PUBLIC_IP, 80), (PUBLIC_IP_2, 443)])

    def test_next_address_is_tried_when_one_is_down(self):
        with FakeNetwork({"images.example": [["93.184.216.99", PUBLIC_IP]]},
                         {PUBLIC_IP: png_server()}) as net:
            self.assertEqual(images._download("http://images.example/x.png"), _png())
        self.assertEqual(net.connections, [("93.184.216.99", 80), (PUBLIC_IP, 80)])

    def test_public_logo_is_downloaded(self):
        brand = BrandingConfig(logo_url="https://images.example/logo.png")
        with FakeNetwork({"images.example": [PUBLIC_IP]}, {PUBLIC_IP: png_server()}):
            path, is_temp = images.resolve_logo(brand)
        try:
            self.assertTrue(is_temp)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), _png())
        finally:
            images.os.unlink(path)


if __name__ == "__main__":
    unittest.main()
