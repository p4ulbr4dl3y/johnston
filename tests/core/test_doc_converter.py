import io
import json
import os
import re
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from pypdf import PdfWriter

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
        self.assertIn('[link](https://example.com "Example")', md)
        self.assertNotIn("console.log", md)
        self.assertNotIn("color: red", md)

    def test_headings_and_decorations(self):
        html = """
        <h2>H2</h2>
        <h3>H3</h3>
        <h4>H4</h4>
        <h5>H5</h5>
        <h6>H6</h6>
        <s>strikethrough</s>
        <strike>strike2</strike>
        <del>del text</del>
        <blockquote>Quote line 1</blockquote>
        <hr/>
        <p>Line with<br/>break</p>
        """
        md = html_to_markdown(html)
        self.assertIn("## H2", md)
        self.assertIn("### H3", md)
        self.assertIn("#### H4", md)
        self.assertIn("##### H5", md)
        self.assertIn("###### H6", md)
        self.assertIn("~~strikethrough~~", md)
        self.assertIn("~~strike2~~", md)
        self.assertIn("~~del text~~", md)
        self.assertIn("> Quote line 1", md)
        self.assertIn("---", md)

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
        <ol start="invalid">
            <li>Fallback 1</li>
        </ol>
        """
        md = html_to_markdown(html)
        self.assertIn("- Item 1", md)
        self.assertIn("  - Subitem A", md)
        self.assertIn("5. Numbered 5", md)
        self.assertIn("6. Numbered 6", md)
        self.assertIn("1. Fallback 1", md)

    def test_tables(self):
        html = """
        <table>
            <tr><th>Header 1</th><th>Header 2</th></tr>
            <tr><td>Cell 1|with pipe</td><td>Cell 2<br/>extra</td></tr>
            <tr><td>Only one col</td></tr>
        </table>
        <table></table>
        """
        md = html_to_markdown(html)
        self.assertIn("| Header 1 | Header 2 |", md)
        self.assertIn("| --- | --- |", md)
        self.assertIn("Cell 1\\|with pipe", md)
        self.assertIn("Cell 2 extra", md)

    def test_code_block_and_images(self):
        html = """
        <pre><code>def hello():\n    return 42</code></pre>
        <img src="https://example.com/pic.png" alt="Pic" title="Caption" />
        <img src="data:image/png;base64,xxxx" alt="Inline" />
        <img src="" alt="Empty" />
        <a href="javascript:void(0)">No link</a>
        <a href="https://example.com"></a>
        """
        md = html_to_markdown(html)
        self.assertIn("```\ndef hello():\n    return 42\n```", md)
        self.assertIn('![Pic](https://example.com/pic.png "Caption")', md)
        self.assertIn("![Inline](data:...)", md)
        self.assertNotIn("javascript:", md)
        self.assertIn("[https://example.com](https://example.com)", md)

    def test_void_tags_and_semantic_header(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="stylesheet" href="style.css">
            <title>Title</title>
        </head>
        <body>
            <article>
                <header><h1>Header Article</h1></header>
                <p>Paragraph content</p>
            </article>
        </body>
        </html>
        """
        md = html_to_markdown(html)
        self.assertIn("# Header Article", md)
        self.assertIn("Paragraph content", md)

    def test_nested_formatting_inside_links_and_cells(self):
        html = """
        <p><a href="https://example.com"><b>Bold</b> and <i>italic</i> link</a></p>
        <table>
            <tr><th>Header</th></tr>
            <tr><td><b>Bold Cell</b></td></tr>
        </table>
        """
        md = html_to_markdown(html)
        self.assertIn("[**Bold** and *italic* link](https://example.com)", md)
        self.assertIn("| **Bold Cell** |", md)
        # Verify formatting does not leak before table
        self.assertFalse(md.startswith("**|"))

    def test_bytes_and_encoding(self):
        html_bytes = "<h1>Заголовок</h1><p>Текст</p>".encode("utf-8")
        md = html_to_markdown(html_bytes)
        self.assertIn("# Заголовок", md)

        latin_bytes = b"<h1>Header</h1><p>\xe9\xe0\xfc</p>"
        md_latin = html_to_markdown(latin_bytes)
        self.assertIn("# Header", md_latin)


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

    def test_semicolon_and_sniffer(self):
        data = "Col1;Col2;Col3\nVal1;Val2;Val3\n"
        md = csv_to_markdown(data)
        self.assertIn("| Col1 | Col2 | Col3 |", md)
        self.assertIn("| Val1 | Val2 | Val3 |", md)

    def test_stream_and_bytes_inputs(self):
        buf = io.BytesIO(b"X,Y\n10,20\n")
        md = csv_to_markdown(buf)
        self.assertIn("| X | Y |", md)
        self.assertIn("| 10 | 20 |", md)

        sbuf = io.StringIO("M,N\n1,2\n")
        md_str = csv_to_markdown(sbuf)
        self.assertIn("| M | N |", md_str)

        self.assertEqual(csv_to_markdown("   \n\n  "), "")

    def test_latin1_bytes(self):
        raw = "Name,City\nRen\xe9,Montr\xe9al\n".encode("latin-1")
        md = csv_to_markdown(raw)
        self.assertIn("Ren\xe9", md)

        # Stream with non-utf8 bytes
        stream = io.BytesIO(raw)
        md_stream = csv_to_markdown(stream)
        self.assertIn("Montr\xe9al", md_stream)

        # Empty lines only
        self.assertEqual(csv_to_markdown(",,\n  ,  ,\n"), "")

    def test_nul_byte(self):
        raw = "Name,Age\x00,City\nAlice\x00,30,NYC\n"
        md = csv_to_markdown(raw)
        self.assertIn("| Name | Age | City |", md)
        self.assertIn("| Alice | 30 | NYC |", md)


class TestIPYNBToMarkdown(unittest.TestCase):
    def test_notebook_conversion(self):
        nb = {
            "cells": [
                {"cell_type": "markdown", "source": ["# Notebook Title\n", "Description"]},
                {
                    "cell_type": "code",
                    "source": ["x = 10\n", "print(x)"],
                    "outputs": [
                        {"output_type": "stream", "text": ["10\n"]},
                        {"output_type": "execute_result", "data": {"text/plain": ["'result'"]}},
                    ],
                },
                {"cell_type": "raw", "source": "Raw cell content"},
            ]
        }
        md = ipynb_to_markdown(nb)
        self.assertIn("# Notebook Title", md)
        self.assertIn("```python\nx = 10\nprint(x)\n```", md)
        self.assertIn("```output\n10\n```", md)
        self.assertIn("```output\n'result'\n```", md)
        self.assertIn("```\nRaw cell content\n```", md)

    def test_notebook_error_output(self):
        nb = {
            "cells": [
                {
                    "cell_type": "code",
                    "source": "1 / 0",
                    "outputs": [
                        {
                            "output_type": "error",
                            "ename": "ZeroDivisionError",
                            "evalue": "division by zero",
                            "traceback": ["\x1b[0;31mZeroDivisionError: division by zero\x1b[0m"],
                        },
                        {
                            "output_type": "error",
                            "ename": "ValueError",
                            "evalue": "bad val",
                            "traceback": [],
                        },
                    ],
                }
            ]
        }
        md = ipynb_to_markdown(json.dumps(nb).encode("utf-8"))
        self.assertIn("ZeroDivisionError: division by zero", md)
        self.assertIn("ValueError: bad val", md)

    def test_corrupted_or_non_dict_ipynb(self):
        # Malformed notebooks raise instead of silently converting to "".
        with self.assertRaises(ValueError):
            ipynb_to_markdown(b"not json at all")
        with self.assertRaises(ValueError):
            ipynb_to_markdown(json.dumps([1, 2, 3]))
        with self.assertRaises(ValueError):
            ipynb_to_markdown({"cells": "not a list"})


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
                            <w:pPr><w:pStyle w:val="Heading2"/></w:pPr>
                            <w:r><w:t>Subheading</w:t></w:r>
                        </w:p>
                        <w:p>
                            <w:pPr>
                                <w:numPr><w:ilvl w:val="1"/></w:numPr>
                            </w:pPr>
                            <w:r><w:t>Nested list item</w:t></w:r>
                        </w:p>
                        <w:p>
                            <w:r>
                                <w:rPr>
                                    <w:b w:val="true"/>
                                    <w:i/>
                                    <w:strike/>
                                </w:rPr>
                                <w:t>Bold statement</w:t>
                                <w:tab/>
                                <w:br/>
                            </w:r>
                            <w:r>
                                <w:rPr>
                                    <w:b w:val="0"/>
                                </w:rPr>
                                <w:t>Not bold</w:t>
                            </w:r>
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
        self.assertIn("## Subheading", md)
        self.assertIn("  - Nested list item", md)
        self.assertIn("~~***Bold statement", md)
        self.assertIn("Not bold", md)
        self.assertIn("[External Link](https://example.org)", md)
        self.assertIn("| Col1 | Col2 |", md)
        self.assertIn("| Val1 | Val2 |", md)

    def test_docx_invalid(self):
        with self.assertRaises(ValueError):
            docx_to_markdown(b"not a zip file")

        # Missing document.xml
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("something_else.xml", "<root/>")
        self.assertEqual(docx_to_markdown(buf.getvalue()), "")

    def test_docx_more_headings_and_lists(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "word/document.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                    <w:body>
                        <w:p><w:pPr><w:pStyle w:val="Heading 3"/></w:pPr><w:r><w:t>H3</w:t></w:r></w:p>
                        <w:p><w:pPr><w:pStyle w:val="heading 4"/></w:pPr><w:r><w:t>H4</w:t></w:r></w:p>
                        <w:p><w:pPr><w:pStyle w:val="heading 5"/></w:pPr><w:r><w:t>H5</w:t></w:r></w:p>
                        <w:p><w:pPr><w:pStyle w:val="heading 6"/></w:pPr><w:r><w:t>H6</w:t></w:r></w:p>
                        <w:p><w:pPr><w:numPr><w:ilvl w:val="not_a_num"/></w:numPr></w:pPr><w:r><w:t>List 0</w:t></w:r></w:p>
                    </w:body>
                </w:document>""",
            )
        md = docx_to_markdown(buf.getvalue())
        self.assertIn("### H3", md)
        self.assertIn("#### H4", md)
        self.assertIn("##### H5", md)
        self.assertIn("###### H6", md)
        self.assertIn("- List 0", md)

    def test_docx_strict_ooxml(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "word/document.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/main">
                    <w:body>
                        <w:p>
                            <w:r>
                                <w:rPr><w:b/></w:rPr>
                                <w:t>Strict Bold</w:t>
                            </w:r>
                        </w:p>
                    </w:body>
                </w:document>""",
            )
        md = docx_to_markdown(buf.getvalue())
        self.assertIn("**Strict Bold**", md)


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
                            <c r="C1" t="inlineStr"><is><t>InlineCol</t></is></c>
                            <c r="D1" t="b"><v>1</v></c>
                        </row>
                        <row r="2">
                            <c r="A2"><v>100</v></c>
                            <c r="B2"><v>200</v></c>
                            <c r="C2"><v>300</v></c>
                            <c r="D2" t="b"><v>0</v></c>
                        </row>
                    </sheetData>
                </worksheet>""",
            )
        return buf.getvalue()

    def test_xlsx_conversion(self):
        data = self._create_mock_xlsx()
        md = xlsx_to_markdown(data)
        self.assertIn("## Sales", md)
        self.assertIn("| Header A | Header B | InlineCol | TRUE |", md)
        self.assertIn("| 100 | 200 | 300 | FALSE |", md)

    def test_xlsx_fallback_sheets(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <sheetData>
                        <row r="1"><c r="A1"><v>42</v></c></row>
                    </sheetData>
                </worksheet>""",
            )
        md = xlsx_to_markdown(buf.getvalue())
        self.assertIn("## Sheet 1", md)
        self.assertIn("| 42 |", md)

    def test_xlsx_invalid(self):
        with self.assertRaises(ValueError):
            xlsx_to_markdown(b"not an xlsx")

    def test_xlsx_furigana_and_leading_slash(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "xl/sharedStrings.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">
                    <si>
                        <t>東京</t>
                        <rPh sb="0" eb="2"><t>とうきょう</t></rPh>
                    </si>
                </sst>""",
            )
            zf.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="/xl/worksheets/sheet1.xml"/>
                </Relationships>""",
            )
            zf.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <sheets><sheet name="Cities" sheetId="1" r:id="rId1"/></sheets>
                </workbook>""",
            )
            zf.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <sheetData>
                        <row r="1">
                            <c r="A1" t="s"><v>0</v></c>
                            <c><v>AutoCol</v></c>
                        </row>
                    </sheetData>
                </worksheet>""",
            )
        md = xlsx_to_markdown(buf.getvalue())
        self.assertIn("## Cities", md)
        self.assertIn("| 東京 | AutoCol |", md)
        self.assertNotIn("とうきょう", md)


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
                "ppt/slides/_rels/slide1.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rIdNotes" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
                </Relationships>""",
            )
            zf.writestr(
                "ppt/notesSlides/notesSlide1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                         xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <p:cSld>
                        <p:spTree>
                            <p:sp>
                                <p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>
                                <p:txBody>
                                    <a:p><a:r><a:t>Remember to mention quarterly growth.</a:t></a:r></a:p>
                                </p:txBody>
                            </p:sp>
                        </p:spTree>
                    </p:cSld>
                </p:notes>""",
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
                            <a:tbl>
                                <a:tr>
                                    <a:tc><a:txBody><a:p><a:r><a:t>TCol1</a:t></a:r></a:p></a:txBody></a:tc>
                                    <a:tc><a:txBody><a:p><a:r><a:t>TCol2</a:t></a:r></a:p></a:txBody></a:tc>
                                </a:tr>
                                <a:tr>
                                    <a:tc><a:txBody><a:p><a:r><a:t>TVal1</a:t></a:r></a:p></a:txBody></a:tc>
                                    <a:tc><a:txBody><a:p><a:r><a:t>TVal2</a:t></a:r></a:p></a:txBody></a:tc>
                                </a:tr>
                            </a:tbl>
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
        self.assertIn("| TCol1 | TCol2 |", md)
        self.assertIn("| TVal1 | TVal2 |", md)
        self.assertIn("### Speaker Notes:", md)
        self.assertIn("Remember to mention quarterly growth.", md)

    def test_pptx_fallback_slides(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "ppt/slides/slide1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Fallback Slide</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
                </p:sld>""",
            )
        md = pptx_to_markdown(buf.getvalue())
        self.assertIn("Fallback Slide", md)

    def test_pptx_invalid(self):
        with self.assertRaises(ValueError):
            pptx_to_markdown(b"invalid pptx")

    def test_pptx_fld_and_leading_slash(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "ppt/presentation.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>
                </p:presentation>""",
            )
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="/ppt/slides/slide1.xml"/>
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
                                <p:txBody>
                                    <a:p>
                                        <a:fld><a:t>Page 42</a:t></a:fld>
                                    </a:p>
                                </p:txBody>
                            </p:sp>
                        </p:spTree>
                    </p:cSld>
                </p:sld>""",
            )
        md = pptx_to_markdown(buf.getvalue())
        self.assertIn("Page 42", md)


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

    def test_epub_fallback_opf(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "book.opf",
                """<?xml version="1.0" encoding="UTF-8"?>
                <package xmlns="http://www.idpf.org/2007/opf">
                    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                        <dc:title>Direct OPF Book</dc:title>
                    </metadata>
                    <manifest><item id="c1" href="c1.html"/></manifest>
                    <spine><itemref idref="c1"/></spine>
                </package>""",
            )
            zf.writestr("c1.html", "<p>Direct content</p>")
        md = epub_to_markdown(buf.getvalue())
        self.assertIn("# Direct OPF Book", md)
        self.assertIn("Direct content", md)

    def test_epub_relative_and_encoded_paths(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0"?>
                <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                    <rootfiles>
                        <rootfile full-path="OEBPS/content/content.opf" media-type="application/oebps-package+xml"/>
                    </rootfiles>
                </container>""",
            )
            zf.writestr(
                "OEBPS/content/content.opf",
                """<?xml version="1.0" encoding="UTF-8"?>
                <package xmlns="http://www.idpf.org/2007/opf" version="2.0">
                    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Relative Book</dc:title></metadata>
                    <manifest><item id="c1" href="../text/my%20chapter.xhtml"/></manifest>
                    <spine><itemref idref="c1"/></spine>
                </package>""",
            )
            zf.writestr("OEBPS/text/my chapter.xhtml", "<p>Relative chapter text</p>")
        md = epub_to_markdown(buf.getvalue())
        self.assertIn("# Relative Book", md)
        self.assertIn("Relative chapter text", md)

    def test_epub_invalid(self):
        with self.assertRaises(ValueError):
            epub_to_markdown(b"not an epub")


class TestPDFToMarkdown(unittest.TestCase):
    def test_pdf_conversion(self):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        data = buf.getvalue()

        md = pdf_to_markdown(data)
        self.assertIsInstance(md, str)

    def test_pdf_text_and_layout_fallback(self):
        mock_p1 = MagicMock()
        mock_p1.extract_text.return_value = "Page 1 Content   \nLine 2   "

        mock_p2 = MagicMock()
        # First call with layout_mode=True raises exception, second call succeeds
        mock_p2.extract_text.side_effect = [Exception("Layout error"), "Page 2 Fallback Text"]

        mock_p3 = MagicMock()
        mock_p3.extract_text.return_value = ""

        mock_reader = MagicMock()
        mock_reader.pages = [mock_p1, mock_p2, mock_p3]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            md = pdf_to_markdown(b"%PDF-mock")
            self.assertIn("<!-- Page 1 -->", md)
            self.assertIn("Page 1 Content", md)
            self.assertIn("<!-- Page 2 -->", md)
            self.assertIn("Page 2 Fallback Text", md)

    def test_pdf_missing_pypdf(self):
        with patch.dict("sys.modules", {"pypdf": None}):
            with self.assertRaises(RuntimeError):
                pdf_to_markdown(b"%PDF-1.4...")


class TestConverterEngine(unittest.TestCase):
    def test_is_convertible(self):
        self.assertTrue(is_convertible("doc.pdf"))
        self.assertTrue(is_convertible("PDF"))
        self.assertTrue(is_convertible(".xlsx"))
        self.assertTrue(is_convertible("sheet.xlsx"))
        self.assertTrue(is_convertible("page.html"))
        self.assertFalse(is_convertible("binary.exe"))

    def test_convert_bytes_all_types(self):
        docx_data = TestDOCXToMarkdown()._create_mock_docx()
        xlsx_data = TestXLSXToMarkdown()._create_mock_xlsx()
        pptx_data = TestPPTXToMarkdown()._create_mock_pptx()
        epub_data = TestEPUBToMarkdown()._create_mock_epub()

        self.assertIn("# DOCX Document Title", convert_bytes(docx_data, ".docx"))
        self.assertIn("## Sales", convert_bytes(xlsx_data, ".xlsx"))
        self.assertIn("## Slide 1", convert_bytes(pptx_data, ".pptx"))
        self.assertIn("# Sample eBook", convert_bytes(epub_data, ".epub"))
        self.assertIn("| a | b |", convert_bytes(b"a,b\n1,2", ".csv"))
        self.assertIn("| a | b |", convert_bytes(b"a\tb\n1\t2", ".tsv"))
        self.assertIn("# Title", convert_bytes(b"<h1>Title</h1>", ".html"))
        with self.assertRaises(ValueError):
            convert_bytes(b"plain text", ".txt")
        with self.assertRaises(ValueError):
            convert_bytes(b'{"a": 1}', ".json")

    def test_convert_file_all_types(self):
        docx_data = TestDOCXToMarkdown()._create_mock_docx()
        xlsx_data = TestXLSXToMarkdown()._create_mock_xlsx()
        pptx_data = TestPPTXToMarkdown()._create_mock_pptx()
        epub_data = TestEPUBToMarkdown()._create_mock_epub()

        temp_files = []
        try:
            for ext, data in [
                (".docx", docx_data),
                (".xlsx", xlsx_data),
                (".pptx", pptx_data),
                (".epub", epub_data),
                (".csv", b"a,b\n1,2"),
                (".tsv", b"a\tb\n1\t2"),
                (".html", b"<h1>Hello</h1>"),
            ]:
                tf = tempfile.NamedTemporaryFile(suffix=ext, mode="wb", delete=False)
                tf.write(data)
                tf.close()
                temp_files.append(tf.name)
                res = convert_file(tf.name)
                self.assertTrue(len(res) > 0)

            # Test ipynb file
            nb = {"cells": [{"cell_type": "markdown", "source": ["# NB"]}]}
            tf_nb = tempfile.NamedTemporaryFile(suffix=".ipynb", mode="wb", delete=False)
            tf_nb.write(json.dumps(nb).encode("utf-8"))
            tf_nb.close()
            temp_files.append(tf_nb.name)
            self.assertIn("# NB", convert_file(tf_nb.name))

        finally:
            for p in temp_files:
                if os.path.exists(p):
                    os.unlink(p)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            convert_file("/path/to/nonexistent/file.docx")

    def test_convert_file_unsupported_format(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", mode="wb") as tf:
            tf.write(b"binary")
            tf.flush()
            with self.assertRaises(ValueError):
                convert_file(tf.name)


class TestConverterRegressions(unittest.TestCase):
    """Regression tests for converter bug fixes (layout mode, BOM, fences,
    nested tables, zip-bomb guards, etc.)."""

    # --- PDF: extraction_mode="layout" must actually be used ---

    def test_pdf_layout_mode_actually_used(self):
        # A plain extraction renders the two distant lines back-to-back
        # ("Header\nBody"); layout mode inserts blank lines between them.
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        page = writer.pages[0]
        from pypdf.generic import (
            DecodedStreamObject,
            DictionaryObject,
            NameObject,
        )

        stream = DecodedStreamObject()
        stream.set_data(
            b"BT /F1 24 Tf 72 720 Td (Header) Tj ET\nBT /F1 12 Tf 72 400 Td (Body far below) Tj ET\n"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        font = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        buf = io.BytesIO()
        writer.write(buf)

        md = pdf_to_markdown(buf.getvalue())
        self.assertIn("Header", md)
        self.assertIn("Body far below", md)
        # Plain mode would produce "Header\nBody far below" with no blank line.
        self.assertIn("Header\n\n", md)

    # --- ipynb: null source and fence content preservation ---

    def test_ipynb_null_source_skipped(self):
        nb = json.dumps(
            {"cells": [{"cell_type": "code", "source": None, "outputs": []}], "metadata": {}, "nbformat": 4}
        )
        self.assertEqual(convert_bytes(nb.encode(), ".ipynb"), "")

    def test_ipynb_preserves_blank_lines_in_code(self):
        nb = json.dumps(
            {
                "cells": [{"cell_type": "code", "source": ["x = 1", "\n", "\n", "\n", "\n", "y = 2"], "outputs": []}],
                "metadata": {},
                "nbformat": 4,
            }
        )
        md = convert_bytes(nb.encode(), ".ipynb")
        # The blank-line collapse must not touch content inside the fence.
        self.assertIn("x = 1\n\n\n\ny = 2", md)

    # --- CSV: UTF-8 BOM must not leak into the first header cell ---

    def test_csv_bom_stripped(self):
        md = convert_bytes(b"\xef\xbb\xbfa,b\n1,2", ".csv")
        self.assertIn("| a | b |", md)
        self.assertNotIn("\ufeff", md)

    # --- HTML: <title>, images in links, nested anchors and tables ---

    def test_html_title_used_when_no_heading(self):
        html = b"<html><head><title>My Page</title></head><body><p>Hi</p></body></html>"
        self.assertEqual(convert_bytes(html, ".html"), "# My Page\n\nHi")

    def test_html_title_not_duplicated_with_heading(self):
        html = b"<html><head><title>T</title></head><body><h1>H</h1></body></html>"
        self.assertEqual(convert_bytes(html, ".html"), "# H")

    def test_html_img_inside_link(self):
        html = b'<a href="http://x"><img src="a.png" alt="pic"></a>'
        self.assertEqual(convert_bytes(html, ".html"), "[![pic](a.png)](http://x)")

    def test_html_nested_anchor_keeps_outer_text(self):
        html = b'<a href="a">text <a href="b">nested</a> tail</a>'
        self.assertEqual(convert_bytes(html, ".html"), "[text nested tail](a)")

    def test_html_nested_table_data_preserved(self):
        html = b"<table><tr><td>outer<table><tr><td>inner</td></tr></table>after</td></tr></table>"
        md = convert_bytes(html, ".html")
        for fragment in ("outer", "inner", "after"):
            self.assertIn(fragment, md)
        # The flattened inner table stays inside the enclosing cell.
        self.assertTrue(md.startswith("| outer"))

    def test_html_preserves_blank_lines_in_pre(self):
        html = b"<pre>line1\n\n\n\nline2</pre>"
        md = convert_bytes(html, ".html")
        self.assertIn("line1\n\n\n\nline2", md)

    # --- DOCX: nested tables must not be dropped ---

    def test_docx_nested_table_data_preserved(self):
        xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:tbl>
<w:tr><w:tc><w:p><w:r><w:t>cell with</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>NESTED</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:tc></w:tr></w:tbl>
</w:body></w:document>"""
        md = docx_to_markdown(_wrap_docx(xml))
        self.assertIn("cell with", md)
        self.assertIn("NESTED", md)

    # --- utils: dynamic fence length ---

    def test_fenced_code_block_dynamic_length(self):
        from core.infrastructure.converter.utils import fenced_code_block

        self.assertEqual(fenced_code_block("x = 1"), "```\nx = 1\n```")
        block = fenced_code_block("code with ``` inline", lang="python")
        self.assertTrue(block.startswith("````python\n"))
        self.assertTrue(block.endswith("\n````"))


class TestConverterFixes(unittest.TestCase):
    """Regression tests for the 2026-08 converter fixes: block tags leaking
    out of table cells, charset detection, CDATA recovery, tracked changes,
    natural slide/sheet order, and xlsx date rendering."""

    # --- HTML: block tags inside table cells must not leak ---

    def test_html_heading_inside_table_cell(self):
        md = html_to_markdown(b"<table><tr><td><h4>Cell Title</h4>text</td></tr></table>")
        self.assertEqual(md, "| Cell Title text |\n| --- |")

    def test_html_list_inside_table_cell(self):
        md = html_to_markdown(b"<table><tr><td><ul><li>a</li><li>b</li></ul></td></tr></table>")
        self.assertEqual(md, "| a b |\n| --- |")

    def test_html_link_inside_table_cell(self):
        md = html_to_markdown(b'<table><tr><td><a href="x.html">link</a></td></tr></table>')
        self.assertEqual(md, "| [link](x.html) |\n| --- |")

    def test_html_paragraphs_inside_table_cell(self):
        md = html_to_markdown(b"<table><tr><td><p>One</p><p>Two</p></td></tr></table>")
        self.assertEqual(md, "| One Two |\n| --- |")

    def test_html_pre_inside_table_cell(self):
        md = html_to_markdown(b"<table><tr><td><pre>x=1</pre></td></tr></table>")
        # Code fences are flattened like any other cell content.
        self.assertEqual(md, "| ``` x=1 ``` |\n| --- |")

    def test_html_cdata_in_pre_preserved(self):
        md = html_to_markdown("<pre><![CDATA[x = 1]]></pre>")
        self.assertIn("x = 1", md)

    # --- HTML: charset detection ---

    def test_html_declared_meta_charset(self):
        html = '<html><head><meta charset="windows-1251"></head><body><h1>Заголовок</h1></body></html>'
        self.assertIn("# Заголовок", html_to_markdown(html.encode("cp1251")))

    def test_html_utf16_bom(self):
        self.assertIn("# Заголовок", html_to_markdown("<h1>Заголовок</h1>".encode("utf-16")))

    def test_html_undeclared_cp1251_heuristic(self):
        html = "<h1>Привет</h1><p>Содержимое страницы</p>".encode("cp1251")
        self.assertIn("# Привет", html_to_markdown(html))

    def test_html_latin1_fallback_unchanged(self):
        md = html_to_markdown(b"<h1>Header</h1><p>\xe9\xe0\xfc</p>")
        self.assertIn("# Header", md)
        self.assertIn("éàü", md)

    # --- DOCX: tracked changes and content controls ---

    def test_docx_tracked_changes_ins_kept_del_skipped(self):
        xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:ins><w:r><w:t>Inserted</w:t></w:r></w:ins><w:del><w:r><w:t>Deleted</w:t></w:r></w:del><w:r><w:t> kept</w:t></w:r></w:p></w:body></w:document>"""
        md = docx_to_markdown(_wrap_docx(xml))
        self.assertIn("Inserted", md)
        self.assertIn("kept", md)
        self.assertNotIn("Deleted", md)

    def test_docx_sdt_content_control_preserved(self):
        xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:sdt><w:sdtPr><w:alias w:val="Cover"/></w:sdtPr><w:sdtContent>
<w:p><w:r><w:t>Control text</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>TCell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:sdtContent></w:sdt></w:body></w:document>"""
        md = docx_to_markdown(_wrap_docx(xml))
        self.assertIn("Control text", md)
        self.assertIn("TCell", md)

    def test_docx_heading10_not_treated_as_level_one(self):
        xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:pPr><w:pStyle w:val="Heading10"/></w:pPr><w:r><w:t>LevelTen</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading 1"/></w:pPr><w:r><w:t>LevelOne</w:t></w:r></w:p>
</w:body></w:document>"""
        md = docx_to_markdown(_wrap_docx(xml))
        # "Heading10" must not match the "heading1" substring.
        self.assertNotIn("# LevelTen", md)
        self.assertIn("# LevelOne", md)

    # --- PPTX: fallback slide order ---

    def test_pptx_fallback_natural_slide_order(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(1, 12):
                zf.writestr(
                    f"ppt/slides/slide{i}.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                    f"<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Slide number {i}</a:t></a:r></a:p>"
                    "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>",
                )
        md = pptx_to_markdown(buf.getvalue())
        order = [int(m) for m in re.findall(r"Slide number (\d+)", md)]
        self.assertEqual(order, list(range(1, 12)))

    # --- XLSX: dates/percents and fallback sheet order ---

    def _create_xlsx(self, styles_xml: str, worksheet_xml: str, workbook_extras: str = "") -> bytes:
        ss = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/styles.xml", styles_xml)
            zf.writestr(
                "xl/workbook.xml",
                f'<?xml version="1.0"?><workbook xmlns="{ss}" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f"{workbook_extras}<sheets><sheet name=\"Data\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>",
            )
            zf.writestr(
                "xl/_rels/workbook.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            )
            zf.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        return buf.getvalue()

    def test_xlsx_builtin_date_style_rendered(self):
        ss = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        data = self._create_xlsx(
            f'<?xml version="1.0"?><styleSheet xmlns="{ss}"><cellXfs count="2">'
            '<xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>',
            f'<?xml version="1.0"?><worksheet xmlns="{ss}"><sheetData>'
            '<row r="1"><c r="A1" s="1"><v>45000</v></c><c r="B1"><v>42.5</v></c></row>'
            "</sheetData></worksheet>",
        )
        md = xlsx_to_markdown(data)
        self.assertIn("2023-03-15", md)
        self.assertIn("42.5", md)
        self.assertNotIn("45000", md)

    def test_xlsx_custom_date_and_percent_styles(self):
        ss = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        data = self._create_xlsx(
            f'<?xml version="1.0"?><styleSheet xmlns="{ss}">'
            '<numFmts count="3"><numFmt numFmtId="164" formatCode="yyyy-mm-dd hh:mm:ss"/>'
            '<numFmt numFmtId="165" formatCode="0.00%"/></numFmts>'
            '<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="165"/></cellXfs>'
            "</styleSheet>",
            f'<?xml version="1.0"?><worksheet xmlns="{ss}"><sheetData>'
            '<row r="1"><c r="A1" s="1"><v>45999.5</v></c><c r="B1" s="2"><v>0.155</v></c></row>'
            "</sheetData></worksheet>",
        )
        md = xlsx_to_markdown(data)
        self.assertIn("2025-12-08 12:00:00", md)
        self.assertIn("15.50%", md)

    def test_xlsx_fallback_natural_sheet_order(self):
        ss = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(1, 12):
                zf.writestr(
                    f"xl/worksheets/sheet{i}.xml",
                    f'<?xml version="1.0"?><worksheet xmlns="{ss}"><sheetData>'
                    f'<row r="1"><c r="A1"><v>{i}</v></c></row></sheetData></worksheet>',
                )
        md = xlsx_to_markdown(buf.getvalue())
        order = [int(m) for m in re.findall(r"## Sheet (\d+)", md)]
        self.assertEqual(order, list(range(1, 12)))


def _wrap_docx(document_xml: str) -> bytes:
    """Wrap a document.xml payload into a minimal DOCX zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


class TestConverterListQuoteAndRunFixes(unittest.TestCase):
    """Regression tests: list items torn apart by block tags, blockquote
    nesting, inline tags leaking out of <pre>, stray end tags, caption glue,
    docx run merging / numId=0 / merged cells, xlsx row indexing, ipynb
    language detection."""

    # --- HTML: block tags must not tear list items apart ---

    def test_html_paragraph_inside_list_item(self):
        md = html_to_markdown("<ul><li>a<p>b</p></li><li>c</li></ul>")
        self.assertEqual(md, "- a\n\n  b\n- c")

    def test_html_div_inside_list_item(self):
        md = html_to_markdown("<ul><li>a<div>b</div></li></ul>")
        self.assertEqual(md, "- a\n  b")

    def test_html_hr_inside_list_item_dropped(self):
        md = html_to_markdown("<ul><li>a<hr>b</li></ul>")
        self.assertEqual(md, "- ab")

    def test_html_blockquote_inside_list_item_flattened(self):
        md = html_to_markdown("<ul><li>a<blockquote>q</blockquote></li></ul>")
        self.assertEqual(md, "- aq")

    def test_html_br_inside_list_item_indents(self):
        md = html_to_markdown("<ul><li>a<br>b</li></ul>")
        self.assertEqual(md, "- a\n  b")

    def test_html_pre_inside_list_item_indented(self):
        md = html_to_markdown("<ul><li>item<pre>x=1</pre>tail</li></ul>")
        self.assertEqual(md, "- item\n  ```\n  x=1\n  ```\n  tail")

    # --- HTML: blockquote nesting and content prefixes ---

    def test_html_nested_blockquote(self):
        md = html_to_markdown("<blockquote><blockquote>deep</blockquote></blockquote>")
        self.assertIn("> > deep", md)

    def test_html_blockquote_paragraphs(self):
        md = html_to_markdown("<blockquote><p>one</p><p>two</p></blockquote>")
        self.assertIn("> one", md)
        self.assertIn("> two", md)

    def test_html_blockquote_keeps_list(self):
        md = html_to_markdown("<blockquote><ul><li>i1</li><li>i2</li></ul></blockquote>")
        self.assertIn("> - i1", md)
        self.assertIn("> - i2", md)

    def test_html_blockquote_keeps_pre(self):
        md = html_to_markdown("<blockquote><pre>x=1</pre></blockquote>")
        self.assertIn("> ```", md)
        self.assertIn("> x=1", md)

    def test_html_blockquote_inline_content(self):
        md = html_to_markdown("<blockquote>text <b>bold</b> more</blockquote>")
        self.assertEqual(md, "> text **bold** more")

    def test_html_blockquote_between_headings(self):
        md = html_to_markdown("<h2>Before</h2><blockquote>quoted</blockquote><h2>After</h2>")
        self.assertIn("> quoted", md)

    # --- HTML: <pre> must swallow inline tags verbatim ---

    def test_html_formatting_inside_pre_buffered(self):
        md = html_to_markdown("<pre>def f():\n    <b>bold</b> x = 1\n    return 2</pre>")
        self.assertFalse(md.startswith("****"))
        self.assertIn("```\ndef f():\n    bold x = 1\n    return 2\n```", md)

    def test_html_link_inside_pre_buffered(self):
        md = html_to_markdown('<pre>see <a href="/d">docs</a> here</pre>')
        self.assertTrue(md.startswith("```"))
        self.assertIn("see docs here", md)

    def test_html_img_inside_pre_dropped(self):
        md = html_to_markdown('<pre>x <img src="i.png"> y</pre>')
        self.assertEqual(md, "```\nx  y\n```")

    # --- HTML: stray end tags must not leak markers ---

    def test_html_stray_end_tags_dropped(self):
        md = html_to_markdown("<p>ok</p></b></i>tail")
        self.assertEqual(md, "ok\n\ntail")

    def test_html_unclosed_tag_auto_closed(self):
        md = html_to_markdown("<p>**start <b>bold</p>")
        self.assertIn("**bold**", md)

    # --- HTML: table interstitial text separated ---

    def test_html_caption_separated_from_table(self):
        md = html_to_markdown("<table><caption>Cap text</caption><tr><td>a</td><td>b</td></tr></table>")
        self.assertEqual(md, "Cap text\n\n| a | b |\n| --- | --- |")

    # --- HTML: escaping and charset ---

    def test_html_link_title_quotes_escaped(self):
        md = html_to_markdown('<a href="/x" title=\'a "b" c\'>L</a>')
        self.assertEqual(md, '[L](/x "a \\"b\\" c")')

    def test_html_img_alt_brackets_escaped(self):
        md = html_to_markdown('<img src="/i.png" alt="a [b] c">')
        self.assertEqual(md, "![a \\[b\\] c](/i.png)")

    def test_html_unbalanced_parens_in_href_escaped(self):
        md = html_to_markdown('<a href="http://x/a(b">link</a>')
        self.assertEqual(md, "[link](http://x/a\\(b)")

    def test_html_balanced_parens_in_href_untouched(self):
        md = html_to_markdown('<a href="http://x/a(b)">link</a>')
        self.assertEqual(md, "[link](http://x/a(b))")

    def test_html_space_in_url_encoded(self):
        md = html_to_markdown('<a href="/a b">L</a>')
        self.assertEqual(md, "[L](/a%20b)")

    def test_html_nbsp_preserved(self):
        md = html_to_markdown("<p>a&nbsp;b</p>")
        self.assertIn("a\xa0b", md)

    def test_html_dt_dd_block_separated(self):
        md = html_to_markdown("<dl><dt>Term</dt><dd>Def</dd></dl>")
        self.assertEqual(md, "Term\n\nDef")

    def test_html_cp1252_smart_quotes_recovered(self):
        md = html_to_markdown(b"<h1>Q&A \x93Section\x94</h1>")
        self.assertIn("“Section”", md)

    # --- DOCX: run merging, numId=0, merged cells ---

    def test_docx_adjacent_bold_runs_merged(self):
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p>"
            '<w:r><w:rPr><w:b/></w:rPr><w:t>Bold1 </w:t></w:r>'
            '<w:r><w:rPr><w:b/></w:rPr><w:t>Bold2</w:t></w:r>'
            "</w:p></w:body></w:document>"
        )
        md = docx_to_markdown(_wrap_docx(xml))
        self.assertEqual(md, "**Bold1 Bold2**")

    def test_docx_trailing_space_outside_emphasis(self):
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p>"
            '<w:r><w:rPr><w:b/></w:rPr><w:t>Bold </w:t></w:r>'
            "<w:r><w:t>tail</w:t></w:r>"
            "</w:p></w:body></w:document>"
        )
        md = docx_to_markdown(_wrap_docx(xml))
        self.assertEqual(md, "**Bold** tail")

    def test_docx_numid_zero_disables_list(self):
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p>"
            '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr></w:pPr>'
            "<w:r><w:t>Plain override</w:t></w:r>"
            "</w:p></w:body></w:document>"
        )
        md = docx_to_markdown(_wrap_docx(xml))
        self.assertEqual(md, "Plain override")

    def test_docx_gridspan_keeps_columns_aligned(self):
        w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        xml = (
            f"<w:document {w}><w:body><w:tbl>"
            '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
            "<w:p><w:r><w:t>Wide</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>b</w:t></w:r></w:p></w:tc></w:tr>"
            "</w:tbl></w:body></w:document>"
        )
        md = docx_to_markdown(_wrap_docx(xml))
        self.assertIn("| Wide |  |", md)
        self.assertIn("| a | b |", md)

    def test_docx_vmerge_continue_cell_emptied(self):
        w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        xml = (
            f"<w:document {w}><w:body><w:tbl>"
            '<w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr>'
            "<w:p><w:r><w:t>Merged</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc></w:tr>"
            '<w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p><w:r><w:t>cont</w:t></w:r></w:p></w:tc>'
            "<w:tc><w:p><w:r><w:t>y</w:t></w:r></w:p></w:tc></w:tr>"
            "</w:tbl></w:body></w:document>"
        )
        md = docx_to_markdown(_wrap_docx(xml))
        self.assertIn("| Merged | x |", md)
        self.assertIn("|  | y |", md)
        self.assertNotIn("cont", md)

    # --- XLSX: rows without r attribute after blank rows ---

    def test_xlsx_row_without_r_after_blank_row(self):
        import io as _io

        from core.infrastructure.converter.xlsx import xlsx_to_markdown

        ss = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "xl/workbook.xml",
                f'<?xml version="1.0"?><workbook xmlns="{ss}"><sheets>'
                '<sheet name="S" sheetId="1"/></sheets></workbook>',
            )
            zf.writestr(
                "xl/worksheets/sheet1.xml",
                f'<?xml version="1.0"?><worksheet xmlns="{ss}"><sheetData>'
                '<row r="1"><c r="A1" t="inlineStr"><is><t>h1</t></is></c>'
                '<c r="B1" t="inlineStr"><is><t>h2</t></is></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>v1</t></is></c></row>'
                '<row r="3"></row>'
                "<row>"
                '<c t="inlineStr"><is><t>v3a</t></is></c>'
                '<c t="inlineStr"><is><t>v3b</t></is></c></row>'
                "</sheetData></worksheet>",
            )
        md = xlsx_to_markdown(buf.getvalue())
        # The r-less row must land after v1, not overwrite it.
        self.assertIn("| v1 |  |", md)
        self.assertIn("| v3a | v3b |", md)

    # --- IPYNB: language detection and error propagation ---

    def test_ipynb_language_from_metadata(self):
        nb = {
            "metadata": {"language_info": {"name": "R"}},
            "cells": [{"cell_type": "code", "source": "x <- 1", "outputs": []}],
        }
        md = ipynb_to_markdown(json.dumps(nb))
        self.assertIn("```r\nx <- 1\n```", md)

    def test_ipynb_python3_normalized(self):
        nb = {
            "metadata": {"language_info": {"name": "python3"}},
            "cells": [{"cell_type": "code", "source": "x = 1", "outputs": []}],
        }
        md = ipynb_to_markdown(json.dumps(nb))
        self.assertIn("```python\nx = 1\n```", md)

    def test_ipynb_invalid_input_raises(self):
        with self.assertRaises(ValueError):
            ipynb_to_markdown(b"not json")
        with self.assertRaises(ValueError):
            ipynb_to_markdown([1, 2])


class TestDocConverterRegressionFixes(unittest.TestCase):
    # 1. XML Comment / Processing Instruction crash guard
    def test_xml_comment_and_pi_guard(self):
        # DOCX with comment & PI
        docx_buf = io.BytesIO()
        with zipfile.ZipFile(docx_buf, "w") as zf:
            zf.writestr(
                "word/document.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <?custom-pi data="test"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                    <!-- Top comment -->
                    <w:body>
                        <!-- Body comment -->
                        <?body-pi ?>
                        <w:p>
                            <!-- Paragraph comment -->
                            <w:r><w:t>Guarded Text</w:t></w:r>
                        </w:p>
                    </w:body>
                </w:document>""",
            )
        self.assertIn("Guarded Text", docx_to_markdown(docx_buf.getvalue()))

        # XLSX with comment & PI
        xlsx_buf = io.BytesIO()
        with zipfile.ZipFile(xlsx_buf, "w") as zf:
            zf.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <?sheet-pi ?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <!-- Sheet comment -->
                    <sheetData>
                        <!-- Row comment -->
                        <row r="1"><c r="A1" t="inlineStr"><!-- Cell comment --><is><t>XLSX Guarded</t></is></c></row>
                    </sheetData>
                </worksheet>""",
            )
        self.assertIn("XLSX Guarded", xlsx_to_markdown(xlsx_buf.getvalue()))

        # PPTX with comment & PI
        pptx_buf = io.BytesIO()
        with zipfile.ZipFile(pptx_buf, "w") as zf:
            zf.writestr(
                "ppt/slides/slide1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <?slide-pi ?>
                <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <!-- Slide comment -->
                    <p:cSld>
                        <p:spTree>
                            <!-- Tree comment -->
                            <p:sp><p:txBody><a:p><a:r><a:t>PPTX Guarded</a:t></a:r></a:p></p:txBody></p:sp>
                        </p:spTree>
                    </p:cSld>
                </p:sld>""",
            )
        self.assertIn("PPTX Guarded", pptx_to_markdown(pptx_buf.getvalue()))

        # EPUB with comment & PI
        epub_buf = io.BytesIO()
        with zipfile.ZipFile(epub_buf, "w") as zf:
            zf.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0"?>
                <!-- Container comment -->
                <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                    <rootfiles>
                        <!-- Rootfiles comment -->
                        <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
                    </rootfiles>
                </container>""",
            )
            zf.writestr(
                "content.opf",
                """<?xml version="1.0"?>
                <!-- OPF comment -->
                <package xmlns="http://www.idpf.org/2007/opf" version="2.0">
                    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>EPUB Guarded</dc:title></metadata>
                    <manifest><item id="c1" href="c1.html"/></manifest>
                    <spine><!-- Spine comment --><itemref idref="c1"/></spine>
                </package>""",
            )
            zf.writestr("c1.html", "<p>EPUB content</p>")
        self.assertIn("EPUB Guarded", epub_to_markdown(epub_buf.getvalue()))

    # 2. PDF resource leak and encrypted PDF handling
    def test_pdf_resource_leak_and_encryption(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buf = io.BytesIO()
        writer.write(buf)

        # File path handling and stream cleanup
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(buf.getvalue())
            pdf_path = f.name

        try:
            res = pdf_to_markdown(pdf_path)
            self.assertIsInstance(res, str)
        finally:
            os.remove(pdf_path)

        # Encrypted PDF with empty password
        enc_writer = PdfWriter()
        enc_writer.add_blank_page(width=100, height=100)
        enc_writer.encrypt("")
        enc_buf = io.BytesIO()
        enc_writer.write(enc_buf)
        res_enc = pdf_to_markdown(enc_buf.getvalue())
        self.assertIsInstance(res_enc, str)

        # Encrypted PDF with non-empty password handled gracefully
        secret_writer = PdfWriter()
        secret_writer.add_blank_page(width=100, height=100)
        secret_writer.encrypt("secret_pass")
        secret_buf = io.BytesIO()
        secret_writer.write(secret_buf)
        res_secret = pdf_to_markdown(secret_buf.getvalue())
        self.assertIsInstance(res_secret, str)

    # 3. PPTX speaker notes idx="1", subtitle, and list indent
    def test_pptx_notes_idx1_subtitle_and_indent(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "ppt/slides/_rels/slide1.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rNotes" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
                </Relationships>""",
            )
            # Notes slide using idx="1" without type="body"
            zf.writestr(
                "ppt/notesSlides/notesSlide1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                         xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <p:cSld><p:spTree><p:sp>
                        <p:nvSpPr><p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr>
                        <p:txBody><a:p><a:r><a:t>Speaker note via idx 1</a:t></a:r></a:p></p:txBody>
                    </p:sp></p:spTree></p:cSld>
                </p:notes>""",
            )
            # Slide with subtitle and indented list levels
            zf.writestr(
                "ppt/slides/slide1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <p:cSld><p:spTree>
                        <p:sp>
                            <p:nvSpPr><p:nvPr><p:ph type="subtitle"/></p:nvPr></p:nvSpPr>
                            <p:txBody><a:p><a:r><a:t>Slide Subtitle</a:t></a:r></a:p></p:txBody>
                        </p:sp>
                        <p:sp>
                            <p:txBody>
                                <a:p><a:pPr lvl="0"/><a:r><a:t>Level 0</a:t></a:r></a:p>
                                <a:p><a:pPr lvl="1"/><a:r><a:t>Level 1</a:t></a:r></a:p>
                                <a:p><a:pPr lvl="2"/><a:r><a:t>Level 2</a:t></a:r></a:p>
                            </p:txBody>
                        </p:sp>
                    </p:spTree></p:cSld>
                </p:sld>""",
            )
        md = pptx_to_markdown(buf.getvalue())
        self.assertIn("## Slide Subtitle", md)
        self.assertNotIn("# Slide Subtitle", [line.strip() for line in md.splitlines()])
        self.assertIn("Level 0", md)
        self.assertIn("  - Level 1", md)
        self.assertIn("    - Level 2", md)
        self.assertIn("Speaker note via idx 1", md)

    # 4. EPUB OPF path normalization and title duplication fix
    def test_epub_opf_path_and_title_dedup(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0"?>
                <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                    <rootfiles>
                        <rootfile full-path="/OEBPS/my%20content.opf" media-type="application/oebps-package+xml"/>
                    </rootfiles>
                </container>""",
            )
            zf.writestr(
                "OEBPS/my content.opf",
                """<?xml version="1.0" encoding="UTF-8"?>
                <package xmlns="http://www.idpf.org/2007/opf" version="2.0">
                    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Book Title</dc:title></metadata>
                    <manifest>
                        <item id="c1" href="chap1.xhtml"/>
                        <item id="c2" href="chap2.xhtml"/>
                    </manifest>
                    <spine>
                        <itemref idref="c1"/>
                        <itemref idref="c2"/>
                    </spine>
                </package>""",
            )
            zf.writestr(
                "OEBPS/chap1.xhtml",
                """<html><head><title>Book Title</title></head><body><p>Chapter 1 text</p></body></html>""",
            )
            zf.writestr(
                "OEBPS/chap2.xhtml",
                """<html><head><title>Book Title</title></head><body><p>Chapter 2 text</p></body></html>""",
            )
        md = epub_to_markdown(buf.getvalue())
        # "# Book Title" should appear only once as metadata header, not repeated per chapter
        self.assertEqual(md.count("# Book Title"), 1)
        self.assertIn("Chapter 1 text", md)
        self.assertIn("Chapter 2 text", md)

    # 5. HTML converter fixes: blockquote sentinels, br in link, colspan, nested delimiters
    def test_html_regression_fixes(self):
        # Mid-line sentinel splitting in blockquote
        html_bq = "<blockquote>Quote text</blockquote> After quote text"
        md_bq = html_to_markdown(html_bq)
        self.assertIn("> Quote text", md_bq)
        self.assertIn("After quote text", md_bq)

        # <br> inside link
        html_link = '<a href="https://example.com">Line 1<br/>Line 2</a>'
        md_link = html_to_markdown(html_link)
        self.assertIn("[Line 1 Line 2](https://example.com)", md_link)

        # Table colspan padding
        html_table = """
        <table>
            <tr><th colspan="2">Span Header</th><th>Single Header</th></tr>
            <tr><td>Cell 1</td><td>Cell 2</td><td>Cell 3</td></tr>
        </table>
        """
        md_table = html_to_markdown(html_table)
        self.assertIn("| Span Header |  | Single Header |", md_table)
        self.assertIn("| Cell 1 | Cell 2 | Cell 3 |", md_table)

        # Nested delimiters
        html_nested = "<p><b>A <strong>B</strong> C</b></p><p><i>X <em>Y</em> Z</i></p>"
        md_nested = html_to_markdown(html_nested)
        self.assertIn("**A B C**", md_nested)
        self.assertNotIn("**A **B** C**", md_nested)
        self.assertIn("*X Y Z*", md_nested)
        self.assertNotIn("*X *Y* Z*", md_nested)

    # 6. DOCX fixes: <w:cr/>, <w:sdt> table rows, URL sanitization
    def test_docx_cr_sdt_table_and_url_sanitization(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "word/_rels/document.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.org/path with spaces (test)"/>
                </Relationships>""",
            )
            zf.writestr(
                "word/document.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <w:body>
                        <w:p>
                            <w:r>
                                <w:t>Before CR</w:t>
                                <w:cr/>
                                <w:t>After CR</w:t>
                            </w:r>
                        </w:p>
                        <w:p>
                            <w:hyperlink r:id="rId1">
                                <w:r><w:t>Spaced URL</w:t></w:r>
                            </w:hyperlink>
                        </w:p>
                        <w:tbl>
                            <w:sdt>
                                <w:sdtContent>
                                    <w:tr>
                                        <w:tc><w:p><w:r><w:t>SDT Row Col 1</w:t></w:r></w:p></w:tc>
                                        <w:tc><w:p><w:r><w:t>SDT Row Col 2</w:t></w:r></w:p></w:tc>
                                    </w:tr>
                                </w:sdtContent>
                            </w:sdt>
                            <w:tr>
                                <w:tc><w:p><w:r><w:t>Regular Row 1</w:t></w:r></w:p></w:tc>
                                <w:tc><w:p><w:r><w:t>Regular Row 2</w:t></w:r></w:p></w:tc>
                            </w:tr>
                        </w:tbl>
                    </w:body>
                </w:document>""",
            )
        md = docx_to_markdown(buf.getvalue())
        self.assertIn("Before CR\nAfter CR", md)
        self.assertIn("[Spaced URL](https://example.org/path%20with%20spaces%20(test))", md)
        self.assertIn("| SDT Row Col 1 | SDT Row Col 2 |", md)
        self.assertIn("| Regular Row 1 | Regular Row 2 |", md)

    # 7. XLSX fixes: custom date format stripping, percent with #, inlineStr furigana
    def test_xlsx_date_percent_and_furigana(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "xl/styles.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <numFmts count="2">
                        <numFmt numFmtId="164" formatCode="0.00\\m"/>
                        <numFmt numFmtId="165" formatCode="0.##%"/>
                    </numFmts>
                    <cellXfs count="3">
                        <xf numFmtId="0"/>
                        <xf numFmtId="164"/>
                        <xf numFmtId="165"/>
                    </cellXfs>
                </styleSheet>""",
            )
            zf.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <sheetData>
                        <row r="1">
                            <c r="A1" t="inlineStr"><is><t>京都</t><rPh sb="0" eb="2"><t>きょうと</t></rPh></is></c>
                            <c r="B1" s="1"><v>123.45</v></c>
                            <c r="C1" s="2"><v>0.125</v></c>
                        </row>
                    </sheetData>
                </worksheet>""",
            )
        md = xlsx_to_markdown(buf.getvalue())
        self.assertIn("京都", md)
        self.assertNotIn("きょうと", md)
        # 123.45 with format 0.00\m should NOT be converted to a date
        self.assertIn("123.45", md)
        # 0.125 with format 0.##% should be 12.50%
        self.assertIn("12.50%", md)

    # 8. IPYNB fixes: ANSI escape regex and _as_text non-string handling
    def test_ipynb_ansi_and_as_text_types(self):
        nb = {
            "cells": [
                {
                    "cell_type": "code",
                    "source": ["print(1)"],
                    "outputs": [
                        {
                            "output_type": "error",
                            "ename": "TestError",
                            "evalue": "err",
                            "traceback": [
                                "\x1b[31;1mError Line\x1b[0m",
                                "\x1b[2KCleared",
                                42,  # non-string item in traceback list
                            ],
                        },
                        {
                            "output_type": "stream",
                            "text": [100, " text\n", None],
                        },
                    ],
                }
            ]
        }
        md = ipynb_to_markdown(nb)
        self.assertIn("Error Line", md)
        self.assertIn("Cleared", md)
        self.assertIn("42", md)
        self.assertNotIn("\x1b[", md)
        self.assertIn("100 text", md)

    # 9. OpenXML extensions in engine.py
    def test_engine_openxml_extensions(self):
        extensions = [".docm", ".dotx", ".dotm", ".potx", ".potm", ".xltx", ".xltm"]
        for ext in extensions:
            self.assertTrue(is_convertible(f"sample{ext}"))
            self.assertTrue(is_convertible(ext))

        # Test convert_bytes with dummy zip content
        docx_buf = io.BytesIO()
        with zipfile.ZipFile(docx_buf, "w") as zf:
            zf.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Docm Text</w:t></w:r></w:p></w:body></w:document>',
            )
        self.assertIn("Docm Text", convert_bytes(docx_buf.getvalue(), ".docm"))
        self.assertIn("Docm Text", convert_bytes(docx_buf.getvalue(), ".dotx"))
        self.assertIn("Docm Text", convert_bytes(docx_buf.getvalue(), ".dotm"))

        pptx_buf = io.BytesIO()
        with zipfile.ZipFile(pptx_buf, "w") as zf:
            zf.writestr(
                "ppt/slides/slide1.xml",
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Potx Text</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>',
            )
        self.assertIn("Potx Text", convert_bytes(pptx_buf.getvalue(), ".potx"))
        self.assertIn("Potx Text", convert_bytes(pptx_buf.getvalue(), ".potm"))

        xlsx_buf = io.BytesIO()
        with zipfile.ZipFile(xlsx_buf, "w") as zf:
            zf.writestr(
                "xl/worksheets/sheet1.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Xltx Text</t></is></c></row></sheetData></worksheet>',
            )
        self.assertIn("Xltx Text", convert_bytes(xlsx_buf.getvalue(), ".xltx"))
        self.assertIn("Xltx Text", convert_bytes(xlsx_buf.getvalue(), ".xltm"))

        # Test convert_file
        with tempfile.NamedTemporaryFile(suffix=".docm", delete=False) as f:
            f.write(docx_buf.getvalue())
            temp_path = f.name
        try:
            self.assertIn("Docm Text", convert_file(temp_path))
        finally:
            os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()


