import asyncio
import io
import threading
import time
import unittest
from io import BytesIO
from unittest import mock

from docx import Document
from docx.oxml.ns import qn
from PIL import Image

import app.images as images
import app.libreoffice as libreoffice
from app.converter import _image_urls, convert_md_to_docx
from app.markdown_parser import make_parser, preprocess


def _png(width=40, height=20) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "purple").save(buf, format="PNG")
    return buf.getvalue()


class ImageUrlTests(unittest.TestCase):
    def test_collects_markdown_and_html_images(self):
        md = "\n".join([
            "# Doc",
            "",
            "![a](https://example.com/a.png) and inline <img src='https://example.com/b.png'>",
            "",
            '<img src="https://example.com/c.png" width="160">',
            "",
            "[not an image](https://example.com/page)",
        ])
        urls = _image_urls(make_parser().parse(preprocess(md)))
        self.assertEqual(urls, ["https://example.com/a.png", "https://example.com/b.png",
                                "https://example.com/c.png"])


class PrefetchTests(unittest.TestCase):
    def setUp(self):
        images._cache.clear()
        images._cache_bytes = 0

    def test_downloads_in_parallel_once_per_url(self):
        calls, active, peak = [], [0], [0]
        lock = threading.Lock()

        def fake_download(url):
            with lock:
                calls.append(url)
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return _png()

        urls = [f"https://example.com/{n}.png" for n in range(6)]
        with mock.patch.object(images, "_download", fake_download):
            fetched = images.prefetch_images(urls + urls[:2])
            self.assertEqual(sorted(calls), sorted(urls))
            self.assertGreater(peak[0], 1)
            self.assertTrue(all(fetched[u] for u in urls))
            # A second document with the same images is served from the cache.
            images.prefetch_images(urls)
            self.assertEqual(len(calls), len(urls))

    def test_failed_downloads_are_not_cached(self):
        with mock.patch.object(images, "_download", return_value=None) as download:
            self.assertIsNone(images.fetch_image_bytes("https://example.com/missing.png"))
            self.assertIsNone(images.fetch_image_bytes("https://example.com/missing.png"))
            self.assertEqual(download.call_count, 2)

    def test_document_embeds_prefetched_images(self):
        md = "\n".join(["# Doc", "", "![x](https://example.com/x.png)", "",
                        "Again: ![x](https://example.com/x.png)"])
        with mock.patch.object(images, "_download", return_value=_png()) as download:
            doc = Document(BytesIO(convert_md_to_docx(md)))
        self.assertEqual(download.call_count, 1)
        self.assertEqual(len(doc.inline_shapes), 2)


class StyleTests(unittest.TestCase):
    def test_paragraph_styles(self):
        doc = Document(BytesIO(convert_md_to_docx("# Title\n\n## Section\n\nBody text.")))
        styles = {}
        for p in doc.element.body.iter(qn("w:p")):
            text = "".join(t.text for t in p.iter(qn("w:t")))
            style = p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
            styles[text] = style.get(qn("w:val")) if style is not None else None
        self.assertEqual(styles["Title"], "Title")
        self.assertEqual(styles["Section"], "Heading2")
        # The default style is implied, not written out.
        self.assertIsNone(styles["Body text."])


class LibreOfficePoolTests(unittest.TestCase):
    def test_without_unoserver_each_conversion_starts_libreoffice(self):
        async def run():
            with mock.patch.object(libreoffice, "unoserver_available", return_value=False), \
                    mock.patch.object(libreoffice, "convert_oneshot", return_value=b"%PDF-1.7 x") as oneshot:
                pool = libreoffice.LibreOfficePool(2)
                await pool.start()
                pdf = await pool.convert(b"docx")
                await pool.stop()
            return pdf, oneshot.call_count

        pdf, calls = asyncio.run(run())
        self.assertEqual(pdf, b"%PDF-1.7 x")
        self.assertEqual(calls, 1)

    def test_failed_worker_is_restarted_and_the_document_still_converts(self):
        class FlakyWorker:
            index, conversions = 0, 0
            starts = 0

            def start(self):
                FlakyWorker.starts += 1

            def convert(self, docx):
                raise OSError("LibreOffice went away")

            def stop(self):
                pass

        async def run():
            with mock.patch.object(libreoffice, "unoserver_available", return_value=True), \
                    mock.patch.object(libreoffice, "convert_oneshot", return_value=b"%PDF-1.7 y"):
                pool = libreoffice.LibreOfficePool(1)
                pool.workers = [FlakyWorker()]
                await pool.start()
                pdf = await pool.convert(b"docx")
                await asyncio.sleep(0.05)  # let the restart run
                ready = pool.ready
                await pool.stop()
            return pdf, ready

        pdf, ready = asyncio.run(run())
        self.assertEqual(pdf, b"%PDF-1.7 y")
        self.assertEqual(FlakyWorker.starts, 2)
        self.assertEqual(ready, 1)

    def test_busy_workers_are_waited_for(self):
        class Slow:
            index, conversions = 0, 0

            def start(self):
                pass

            def convert(self, docx):
                time.sleep(0.05)
                return b"%PDF-1.7"

            def stop(self):
                pass

        async def run():
            with mock.patch.object(libreoffice, "unoserver_available", return_value=True), \
                    mock.patch.object(libreoffice, "convert_oneshot") as oneshot:
                pool = libreoffice.LibreOfficePool(1, conversion_timeout=0.5)
                pool.workers = [Slow()]
                await pool.start()
                await asyncio.sleep(0.01)
                results = await asyncio.gather(*(pool.convert(b"docx") for _ in range(4)))
                await pool.stop()
            return results, oneshot.call_count

        results, oneshots = asyncio.run(run())
        # Four conversions queue for the one worker; none starts its own
        # LibreOffice while it's busy.
        self.assertEqual(results, [b"%PDF-1.7"] * 4)
        self.assertEqual(oneshots, 0)

    def test_worker_restarts_after_its_quota(self):
        class Counting:
            index, conversions, starts = 0, 0, 0

            def start(self):
                Counting.starts += 1
                self.conversions = 0

            def convert(self, docx):
                self.conversions += 1
                return b"%PDF-1.7"

            def stop(self):
                pass

        async def run():
            with mock.patch.object(libreoffice, "unoserver_available", return_value=True):
                pool = libreoffice.LibreOfficePool(1, restart_after=3)
                pool.workers = [Counting()]
                await pool.start()
                for _ in range(7):
                    await pool.convert(b"docx")
                await pool.stop()

        asyncio.run(run())
        # Started once, then restarted after conversions 3 and 6.
        self.assertEqual(Counting.starts, 3)


if __name__ == "__main__":
    unittest.main()
