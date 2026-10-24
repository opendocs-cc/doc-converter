import base64
import io
import unittest
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from app.converter import convert_md_to_docx

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="100" viewBox="0 0 320 100">'
    '<rect width="320" height="100" fill="#6B3FC9"/></svg>'
)


def data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def webp_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (15, 76, 92)).save(buf, format="WEBP")
    return buf.getvalue()


def convert(md: str) -> Document:
    return Document(BytesIO(convert_md_to_docx(md)))


def body_text(doc: Document) -> list[str]:
    return [p.text for p in doc.paragraphs]


class MarkdownCoverageTests(unittest.TestCase):
    def test_svg_and_webp_images_are_embedded(self):
        doc = convert(
            f"# T\n\n![svg]({data_uri('image/svg+xml', SVG.encode())})\n\n"
            f"![webp]({data_uri('image/webp', webp_bytes())})\n"
        )
        self.assertEqual(len(doc.inline_shapes), 2)
        # The SVG keeps its CSS size: 320px at 96 per inch.
        self.assertAlmostEqual(doc.inline_shapes[0].width.inches, 320 / 96, places=1)

    def test_svg_cannot_read_local_files(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'width="10" height="10"><image xlink:href="file:///etc/passwd" width="10" height="10"/></svg>'
        )
        doc = convert(f"![x]({data_uri('image/svg+xml', svg.encode())})\n")
        # Renders (the reference is ignored) without touching the file.
        self.assertEqual(len(doc.inline_shapes), 1)

    def test_strikethrough_and_escapes(self):
        doc = convert("# T\n\n~~gone~~ and \\*literal\\* stars\n")
        p = doc.paragraphs[1]
        self.assertEqual(p.text, "gone and *literal* stars")
        self.assertTrue(p.runs[0].font.strike)
        self.assertFalse(any(run.italic for run in p.runs))

    def test_blockquote_has_left_bar(self):
        doc = convert("# T\n\n> Quoted\n\nAfter\n")
        quoted, after = doc.paragraphs[1], doc.paragraphs[2]
        self.assertIsNotNone(quoted._p.pPr.find(qn("w:pBdr")))
        self.assertIsNone(after._p.pPr.find(qn("w:pBdr")) if after._p.pPr is not None else None)

    def test_horizontal_rule_is_drawn(self):
        doc = convert("# T\n\nAbove\n\n---\n\nBelow\n")
        rule = doc.paragraphs[2]
        self.assertEqual(rule.text, "")
        self.assertIsNotNone(rule._p.pPr.find(qn("w:pBdr")))

    def test_task_list_uses_check_boxes(self):
        doc = convert("# T\n\n- [x] Done\n- [ ] Open\n")
        self.assertEqual(body_text(doc)[1:3], ["☑\tDone", "☐\tOpen"])

    def test_adjacent_code_blocks_stay_separate(self):
        doc = convert("# T\n\n```\none\n```\n\n```\ntwo\n```\n")
        texts = body_text(doc)
        one, two = texts.index("one"), texts.index("two")
        self.assertEqual(two - one, 2)  # a spacer paragraph sits between them

    def test_footnotes_and_inline_html(self):
        doc = convert("# T\n\nNote.[^1] H<sub>2</sub>O\n\n[^1]: The note.\n")
        p = doc.paragraphs[1]
        sup = [run for run in p.runs if run.font.superscript]
        sub = [run for run in p.runs if run.font.subscript]
        self.assertEqual([run.text for run in sup], ["1"])
        self.assertEqual([run.text for run in sub], ["2"])
        self.assertIn("1\tThe note.", body_text(doc))

    def test_ordered_list_keeps_its_start_number(self):
        md = "# T\n\nIntro\n\n5. Five\n6. Six\n"
        xml = convert_md_to_docx(md)
        doc = Document(BytesIO(xml))
        numbering = doc.part.numbering_part.element
        starts = {el.get(qn("w:val")) for el in numbering.iter(qn("w:start"))}
        self.assertIn("5", starts)

    def test_list_item_code_block_and_second_paragraph(self):
        doc = convert("# T\n\n1. Install:\n\n   ```\n   npm i\n   ```\n\n   Then run it.\n")
        self.assertEqual(body_text(doc)[1:4], ["Install:", "npm i", "Then run it."])

    def test_html_comments_are_dropped(self):
        doc = convert("# T\n\n<!-- internal note -->\n\nVisible\n")
        self.assertNotIn("internal note", " ".join(body_text(doc)))


if __name__ == "__main__":
    unittest.main()
