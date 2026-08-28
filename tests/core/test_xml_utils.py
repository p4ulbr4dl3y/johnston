import unittest

from core.infrastructure.runtime.xml_utils import escape_xml, escape_xml_attr, unescape_xml, wrap_cdata


class TestXmlUtils(unittest.TestCase):
    def test_escape_xml_basic(self):
        self.assertEqual(escape_xml("hello"), "hello")
        self.assertEqual(escape_xml("<b>bold</b> & 'quote'"), "&lt;b&gt;bold&lt;/b&gt; &amp; 'quote'")
        self.assertEqual(escape_xml(""), "")
        self.assertEqual(escape_xml(None), "")

    def test_escape_xml_attr(self):
        self.assertEqual(escape_xml_attr('val "1" & \'2\' <3>'), 'val &quot;1&quot; &amp; &apos;2&apos; &lt;3&gt;')
        self.assertEqual(escape_xml_attr(""), "")
        self.assertEqual(escape_xml_attr(None), "")

    def test_unescape_xml_roundtrip(self):
        raw = '<b>test</b> & "quotes" & \'single\''
        escaped = escape_xml_attr(raw)
        self.assertEqual(unescape_xml(escaped), raw)

    def test_unescape_xml_ampersand_order(self):
        # &amp;lt; should decode to &lt;, not <
        self.assertEqual(unescape_xml("&amp;lt;tag&amp;gt;"), "&lt;tag&gt;")
        self.assertEqual(unescape_xml(None), "")
        self.assertEqual(unescape_xml(""), "")

    def test_wrap_cdata(self):
        self.assertEqual(wrap_cdata(""), "")
        self.assertEqual(wrap_cdata(None), "")
        self.assertEqual(wrap_cdata("simple text"), "<![CDATA[\nsimple text\n]]>")
        self.assertEqual(wrap_cdata("<tags> & 'quotes'"), "<![CDATA[\n<tags> & 'quotes'\n]]>")
        self.assertEqual(
            wrap_cdata("contains ]]> closing"),
            "<![CDATA[\ncontains ]]]]><![CDATA[> closing\n]]>",
        )



if __name__ == "__main__":
    unittest.main()
