import unittest
from io import BytesIO

from docx import Document

from app.converter import convert_md_to_docx


class HeadingStyleTests(unittest.TestCase):
    def test_mid_document_h1_uses_body_heading_style(self):
        docx_bytes = convert_md_to_docx(
            "\n".join(
                [
                    "# Document title",
                    "",
                    "Intro paragraph.",
                    "",
                    "## First subsection",
                    "",
                    "Subsection body.",
                    "",
                    "# Major body section",
                    "",
                    "## Nested subsection",
                    "",
                    "Nested body.",
                ]
            )
        )
        doc = Document(BytesIO(docx_bytes))

        title = self._paragraph_with_text(doc, "Document title")
        first_h2 = self._paragraph_with_text(doc, "First subsection")
        body_h1 = self._paragraph_with_text(doc, "Major body section")
        nested_h2 = self._paragraph_with_text(doc, "Nested subsection")

        self.assertEqual(title.style.name, "Title")
        self.assertEqual(first_h2.style.name, "Heading 2")
        self.assertEqual(body_h1.style.name, "Heading 1")
        self.assertEqual(nested_h2.style.name, "Heading 2")

        heading_1 = doc.styles["Heading 1"]
        heading_2 = doc.styles["Heading 2"]
        self.assertGreater(heading_1.font.size.pt, heading_2.font.size.pt)
        self.assertGreater(
            heading_1.paragraph_format.space_before.pt,
            heading_2.paragraph_format.space_before.pt,
        )

    @staticmethod
    def _paragraph_with_text(doc, text):
        for paragraph in doc.paragraphs:
            if paragraph.text == text:
                return paragraph
        raise AssertionError(f"Paragraph not found: {text}")


if __name__ == "__main__":
    unittest.main()
