import re
from io import BytesIO


def rows_to_dicts(data: dict) -> list[dict]:
    """Convert columnar API response to list of named dicts."""
    cols = data["columnNames"]
    return [dict(zip(cols, row)) for row in data.get("rowData", [])]


def strip_xml_tags(text: str) -> str:
    """Remove XML/HTML tags from a field value and clean whitespace."""
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_html_href(html: str) -> str:
    """Extract the href URL from an HTML anchor string like <a href="...">...</a>."""
    if not html:
        return ""
    # Match href with or without surrounding quotes
    m = re.search(r'href=["\']?([^"\'>\s]+)["\']?', html)
    if m:
        url = m.group(1).strip('"\'')
        # Make sure it's an absolute URL
        if url.startswith("http"):
            return url
    return ""


def extract_xml_text(xml_string: str) -> str:
    """Parse full XML document and return clean plain text."""
    from lxml import etree

    if not xml_string:
        return ""

    xml_bytes = (
        xml_string.encode("utf-8") if isinstance(xml_string, str) else xml_string
    )

    for use_recovery in (False, True):
        try:
            parser = etree.XMLParser(recover=use_recovery)
            root = etree.fromstring(xml_bytes, parser=parser)
            text = " ".join(t.strip() for t in root.itertext() if t.strip())
            return re.sub(r"\s+", " ", text).strip()
        except Exception:
            if not use_recovery:
                continue
    return ""


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    import pdfplumber

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() for p in pdf.pages if p.extract_text()]
            return "\n\n".join(pages)
    except Exception:
        return ""


def extract_year_from_tunniste(tunniste: str) -> str:
    """Extract parliamentary year from an identifier like 'HE 7/2024 vp'."""
    m = re.search(r"/(\d{4})\s+(?:vp|rd)", tunniste)
    return m.group(1) if m else ""


def first_identifier(tunniste: str) -> str:
    """Return the first document identifier from a comma-separated Tunniste string."""
    return tunniste.split(",")[0].strip()
