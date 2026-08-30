import io
import os
import tempfile
import unittest
import zipfile

from core.infrastructure.converter import (
    convert_bytes,
    convert_file,
    is_convertible,
)
from core.infrastructure.converter.csv_tsv import csv_to_markdown
from core.infrastructure.converter.docx import docx_to_markdown
from core.infrastructure.converter.epub import epub_to_markdown
from core.infrastructure.converter.html import html_to_markdown
from core.infrastructure.converter.ipynb import ipynb_to_markdown
from core.infrastructure.converter.pdf import pdf_to_markdown
from core.infrastructure.converter.pptx import pptx_to_markdown
from core.infrastructure.converter.xlsx import xlsx_to_markdown


class TestHTMLToMarkdown(unittest.TestCase):
    def test_basic_formatting(self):
        html = """
        <html>
        <head><title>Test Page</title><style>body { color: red; }</style></head>
        <body>
            <h1>Title Header</h1>
            <p>This is <b>bold</b> and <i>italic</i> and <code>inline code</code>.</p>
            <p>Here is a <a href="https://example.com" title="Example">link</a>.</p>
            <script>console.log('strip me');</script>
        </body>
        </html>
        """
        md = html_to_markdown(html)
        self.assertIn("# Title Header", md)
        self.assertIn("**bold**", md)
        self.assertIn("*italic*", md)
        self.assertIn("`inline code`", md)
        self.assertIn("[link](https://example.com \"Example\")", md)
        self.assertNotIn("console.log", md)
        self.assertNotIn("color: red", md)

    def test_lists(self):
        html = """
        <ul>
            <li>Item 1</li>
            <li>Item 2
                <ul>
                    <li>Subitem A</li>
                </ul>
            </li>
        </ul>
        <ol start="5">
            <li>Numbered 5</li>
            <li>Numbered 6</li>
        </ol>
        """
        md = html_to_markdown(html)
        self.assertIn("- Item 1", md)
        self.assertIn("  - Subitem A", md)
        self.assertIn("5. Numbered 5", md)
        self.assertIn("6. Numbered 6", md)

    def test_tables(self):
        html = """
        <table>
            <tr><th>Header 1</th><th>Header 2</th></tr>
            <tr><td>Cell 1|with pipe</td><td>Cell 2</td></tr>
        </table>
        """
        md = html_to_markdown(html)
        self.assertIn("| Header 1 | Header 2 |", md)
        self.assertIn("| --- | --- |", md)
        self.assertIn("Cell 1\\|with pipe", md)

    def test_code_block_and_images(self):
        html = """
        <pre><code>def hello():\n    return 42</code></pre>
        <img src="https://example.com/pic.png" alt="Pic" title="Caption" />
        <img src="data:image/png;base64,xxxx" alt="Inline" />
        """
        md = html_to_markdown(html)
        self.assertIn("```\ndef hello():\n    return 42\n```", md)
        self.assertIn("![Pic](https://example.com/pic.png \"Caption\")", md)
        self.assertIn("![Inline](data:...)", md)


class TestCSVAndTSVToMarkdown(unittest.TestCase):
    def test_csv_table(self):
        data = "Name,Age,Role\nAlice,30,Engineer\nBob,25,Designer\n"
        md = csv_to_markdown(data)
        self.assertIn("| Name | Age | Role |", md)
        self.assertIn("| --- | --- | --- |", md)
        self.assertIn("| Alice | 30 | Engineer |", md)

    def test_tsv_table(self):
        data = "A\tB\tC\n1\t2\t3\n"
        md = csv_to_markdown(data, delimiter="\t")
        self.assertIn("| A | B | C |", md)
        self.assertIn("| 1 | 2 | 3 |", md)


class TestIPYNBToMarkdown(unittest.TestCase):
    def test_notebook_conversion(self):
        nb = {
            "cells": [
                {"cell_type": "markdown", "source": ["# Notebook Title\n", "Description"]},
                {
                    "cell_type": "code",
                    "source": ["x = 10\n", "print(x)"],
                    "outputs": [{"output_type": "stream", "text": ["10\n"]}],
                },
            ]
        }
        md = ipynb_to_markdown(nb)
        self.assertIn("# Notebook Title", md)
        self.assertIn("```python\nx = 10\nprint(x)\n```", md)
        self.assertIn("```output\n10\n```", md)


class TestDOCXToMarkdown(unittest.TestCase):
    def _create_mock_docx(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "word/_rels/document.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.org" TargetMode="External"/>
                </Relationships>""",
            )
            zf.writestr(
                "word/document.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <w:body>
                        <w:p>
                            <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
                            <w:r><w:t>DOCX Document Title</w:t></w:r>
                        </w:p>
                        <w:p>
                            <w:r><w:rPr><w:b/></w:rPr><w:t>Bold statement</w:t></w:r>
                        </w:p>
                        <w:p>
                            <w:hyperlink r:id="rId1">
                                <w:r><w:t>External Link</w:t></w:r>
                            </w:hyperlink>
                        </w:p>
                        <w:tbl>
                            <w:tr>
                                <w:tc><w:p><w:r><w:t>Col1</w:t></w:r></w:p></w:tc>
                                <w:tc><w:p><w:r><w:t>Col2</w:t></w:r></w:p></w:tc>
                            </w:tr>
                            <w:tr>
                                <w:tc><w:p><w:r><w:t>Val1</w:t></w:r></w:p></w:tc>
                                <w:tc><w:p><w:r><w:t>Val2</w:t></w:r></w:p></w:tc>
                            </w:tr>
                        </w:tbl>
                    </w:body>
                </w:document>""",
            )
        return buf.getvalue()

    def test_docx_conversion(self):
        data = self._create_mock_docx()
        md = docx_to_markdown(data)
        self.assertIn("# DOCX Document Title", md)
        self.assertIn("**Bold statement**", md)
        self.assertIn("[External Link](https://example.org)", md)
        self.assertIn("| Col1 | Col2 |", md)
        self.assertIn("| Val1 | Val2 |", md)


class TestXLSXToMarkdown(unittest.TestCase):
    def _create_mock_xlsx(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "xl/sharedStrings.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">
                    <si><t>Header A</t></si>
                    <si><t>Header B</t></si>
                </sst>""",
            )
            zf.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <sheets>
                        <sheet name="Sales" sheetId="1" r:id="rId1"/>
                    </sheets>
                </workbook>""",
            )
            zf.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
                </Relationships>""",
            )
            zf.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <sheetData>
                        <row r="1">
                            <c r="A1" t="s"><v>0</v></c>
                            <c r="B1" t="s"><v>1</v></c>
                        </row>
                        <row r="2">
                            <c r="A2"><v>100</v></c>
                            <c r="B2"><v>200</v></c>
                        </row>
                    </sheetData>
                </worksheet>""",
            )
        return buf.getvalue()

    def test_xlsx_conversion(self):
        data = self._create_mock_xlsx()
        md = xlsx_to_markdown(data)
        self.assertIn("## Sales", md)
        self.assertIn("| Header A | Header B |", md)
        self.assertIn("| 100 | 200 |", md)


class TestPPTXToMarkdown(unittest.TestCase):
    def _create_mock_pptx(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "ppt/presentation.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <p:sldIdLst>
                        <p:sldId id="256" r:id="rId1"/>
                    </p:sldIdLst>
                </p:presentation>""",
            )
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
                </Relationships>""",
            )
            zf.writestr(
                "ppt/slides/slide1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <p:cSld>
                        <p:spTree>
                            <p:sp>
                                <p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
                                <p:txBody>
                                    <a:p><a:r><a:t>Slide One Title</a:t></a:r></a:p>
                                </p:txBody>
                            </p:sp>
                            <p:sp>
                                <p:txBody>
                                    <a:p><a:r><a:t>Bullet Point One</a:t></a:r></a:p>
                                </p:txBody>
                            </p:sp>
                        </p:spTree>
                    </p:cSld>
                </p:sld>""",
            )
        return buf.getvalue()

    def test_pptx_conversion(self):
        data = self._create_mock_pptx()
        md = pptx_to_markdown(data)
        self.assertIn("## Slide 1", md)
        self.assertIn("# Slide One Title", md)
        self.assertIn("Bullet Point One", md)


class TestEPUBToMarkdown(unittest.TestCase):
    def _create_mock_epub(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0"?>
                <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                    <rootfiles>
                        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
                    </rootfiles>
                </container>""",
            )
            zf.writestr(
                "OEBPS/content.opf",
                """<?xml version="1.0" encoding="UTF-8"?>
                <package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookID" version="2.0">
                    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                        <dc:title>Sample eBook</dc:title>
                        <dc:creator>Johnston Author</dc:creator>
                    </metadata>
                    <manifest>
                        <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
                    </manifest>
                    <spine>
                        <itemref idref="chap1"/>
                    </spine>
                </package>""",
            )
            zf.writestr(
                "OEBPS/chap1.xhtml",
                """<html xmlns="http://www.w3.org/1999/xhtml">
                <body>
                    <h2>Chapter 1</h2>
                    <p>It was a dark and stormy night.</p>
                </body>
                </html>""",
            )
        return buf.getvalue()

    def test_epub_conversion(self):
        data = self._create_mock_epub()
        md = epub_to_markdown(data)
        self.assertIn("# Sample eBook", md)
        self.assertIn("**Author:** Johnston Author", md)
        self.assertIn("## Chapter 1", md)
        self.assertIn("It was a dark and stormy night.", md)


class TestPDFToMarkdown(unittest.TestCase):
    def test_pdf_conversion(self):
        # Create a simple valid PDF using pypdf writer
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        data = buf.getvalue()

        md = pdf_to_markdown(data)
        self.assertIsInstance(md, str)


class TestConverterEngine(unittest.TestCase):
    def test_is_convertible(self):
        self.assertTrue(is_convertible("doc.pdf"))
        self.assertTrue(is_convertible("sheet.xlsx"))
        self.assertTrue(is_convertible("page.html"))
        self.assertFalse(is_convertible("binary.exe"))

    def test_convert_bytes_and_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write('{"key": "value"}')
            temp_path = f.name

        try:
            res_file = convert_file(temp_path)
            self.assertIn('"key": "value"', res_file)
            self.assertIn("```json", res_file)

            res_bytes = convert_bytes(b'{"key": "value"}', ".json")
            self.assertIn('"key": "value"', res_bytes)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_convert_zip_archive(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("test.csv", "a,b\n1,2\n")
            zf.writestr("notes.html", "<h1>Notes</h1>")

        md = convert_bytes(buf.getvalue(), ".zip")
        self.assertIn("## File: notes.html", md)
        self.assertIn("# Notes", md)
        self.assertIn("## File: test.csv", md)
        self.assertIn("| a | b |", md)


if __name__ == "__main__":
    unittest.main()
