import os
import unittest
from io import BytesIO

from docx import Document

from app.converter import convert_md_to_docx

# A real image that exists on the converter's filesystem.
LOCAL_IMAGE = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets", "logo.png"))


class LocalImagePathTests(unittest.TestCase):
    def test_absolute_local_path_is_not_embedded(self):
        self.assertTrue(os.path.exists(LOCAL_IMAGE))

        docx_bytes = convert_md_to_docx(
            "\n".join(["# Doc", "", f"![Secret]({LOCAL_IMAGE})", "", "After."])
        )
        doc = Document(BytesIO(docx_bytes))

        self.assertEqual(len(doc.inline_shapes), 0)
        self.assertIn("[Secret]", [p.text for p in doc.paragraphs])

    def test_file_url_is_not_embedded(self):
        docx_bytes = convert_md_to_docx(
            "\n".join(["# Doc", "", f"![Secret](file://{LOCAL_IMAGE})"])
        )
        doc = Document(BytesIO(docx_bytes))

        self.assertEqual(len(doc.inline_shapes), 0)


if __name__ == "__main__":
    unittest.main()
