"""XML/HTML character escaping and unescaping utilities for safe prompt interpolation."""

from __future__ import annotations

from typing import Optional


def escape_xml(s: Optional[str]) -> str:
    """Escape XML/HTML special characters for safe interpolation into element text content.

    Handles null/empty strings safely.
    """
    if not s:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_xml_attr(s: Optional[str]) -> str:
    """Escape for interpolation into a double- or single-quoted XML attribute value.

    `<tag attr="${here}">`. Escapes quotes in addition to `& < >`.
    """
    if not s:
        return ""
    return escape_xml(s).replace('"', "&quot;").replace("'", "&apos;")


def unescape_xml(s: Optional[str]) -> str:
    """Decode XML/HTML entities back to literal characters.

    Decodes &lt;, &gt;, &quot;, &apos; first, then &amp; last to avoid premature double-decoding.
    """
    if not s:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def wrap_cdata(s: Optional[str]) -> str:
    """Wrap content in an XML CDATA block, escaping nested closing markers.

    Handles null/empty strings safely.
    """
    if not s:
        return ""
    if not isinstance(s, str):
        s = str(s)
    safe = s.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[\n{safe}\n]]>"

