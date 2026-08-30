import io
import json
import os
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
        self.assertEqual(ipynb_to_markdown(b"not json at all"), "")
        self.assertEqual(ipynb_to_markdown(json.dumps([1, 2, 3])), "")
        self.assertEqual(ipynb_to_markdown({"cells": "not a list"}), "")


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
        self.assertIn("```json", convert_bytes(b'{"a": 1}', ".json"))
        self.assertIn("```xml", convert_bytes(b"<x>1</x>", ".xml"))
        self.assertEqual(convert_bytes(b"plain text", ".txt"), "plain text")
        self.assertEqual(convert_bytes(b"\xe9", ".unknown"), "\xe9")

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
                (".json", b'{"x": 42}'),
                (".xml", b"<y>10</y>"),
                (".txt", b"plain"),
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

            # Test zip file
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("test.csv", "a,b\n1,2\n")
            tf_zip = tempfile.NamedTemporaryFile(suffix=".zip", mode="wb", delete=False)
            tf_zip.write(buf.getvalue())
            tf_zip.close()
            temp_files.append(tf_zip.name)
            self.assertIn("## File: test.csv", convert_file(tf_zip.name))

        finally:
            for p in temp_files:
                if os.path.exists(p):
                    os.unlink(p)

    def test_convert_zip_archive(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("test.csv", "a,b\n1,2\n")
            zf.writestr("notes.html", "<h1>Notes</h1>")
            zf.writestr("__MACOSX/._test.csv", "mac junk")
            zf.writestr("nested/__MACOSX/._inner.csv", "mac junk")
            zf.writestr(".DS_Store", "junk")
            zf.writestr("subfolder/", "")

        md = convert_bytes(buf.getvalue(), ".zip")
        self.assertIn("## File: notes.html", md)
        self.assertIn("# Notes", md)
        self.assertIn("## File: test.csv", md)
        self.assertIn("| a | b |", md)
        self.assertNotIn("__MACOSX", md)
        self.assertNotIn(".DS_Store", md)

    def test_zip_recursion_depth_limit(self):
        # Create 4 levels of nested zip
        inner_buf = io.BytesIO()
        with zipfile.ZipFile(inner_buf, "w") as zf:
            zf.writestr("deep.txt", "deep text")

        for _ in range(4):
            outer_buf = io.BytesIO()
            with zipfile.ZipFile(outer_buf, "w") as zf:
                zf.writestr("nested.zip", inner_buf.getvalue())
            inner_buf = outer_buf

        md = convert_bytes(inner_buf.getvalue(), ".zip")
        # Ensure it terminates cleanly without infinite recursion
        self.assertIsInstance(md, str)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            convert_file("/path/to/nonexistent/file.docx")


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

    # --- ZIP: decompression-bomb guards ---

    def test_zip_member_size_guard(self):
        big = b"a,b\n" + b"1,2\n" * (1024 * 1024)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.csv", big)
        with patch("core.infrastructure.converter.utils.MAX_MEMBER_BYTES", 64):
            md = convert_bytes(buf.getvalue(), ".zip")
        self.assertEqual(md, "")

    def test_zip_total_budget_guard(self):
        rows = b"a,b\n" + b"1,2\n" * 4096
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("one.csv", rows)
            zf.writestr("two.csv", rows)
        # engine binds MAX_ZIP_TOTAL_BYTES at import time, so patch it there.
        # Budget is checked before each member: exactly one member fits.
        with patch("core.infrastructure.converter.engine.MAX_ZIP_TOTAL_BYTES", len(rows)):
            md = convert_bytes(buf.getvalue(), ".zip")
        self.assertIn("one.csv", md)
        self.assertNotIn("two.csv", md)

    def test_zip_legitimate_content_still_converted(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data.csv", "a,b\n1,2\n")
        md = convert_bytes(buf.getvalue(), ".zip")
        self.assertIn("## File: data.csv", md)
        self.assertIn("| a | b |", md)

    # --- utils: dynamic fence length ---

    def test_fenced_code_block_dynamic_length(self):
        from core.infrastructure.converter.utils import fenced_code_block

        self.assertEqual(fenced_code_block("x = 1"), "```\nx = 1\n```")
        block = fenced_code_block("code with ``` inline", lang="python")
        self.assertTrue(block.startswith("````python\n"))
        self.assertTrue(block.endswith("\n````"))


def _wrap_docx(document_xml: str) -> bytes:
    """Wrap a document.xml payload into a minimal DOCX zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()


