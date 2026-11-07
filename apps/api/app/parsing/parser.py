"""PDF/DOCX parsing into immutable, citable source spans.

Anchors:
- PDF: 1-based page number + [char_start, char_end) within the canonical page text, which is
  defined as "\\n".join(block texts in reading order) for parser version PARSER_VERSION.
- DOCX: body paragraph index (document.paragraphs) or table cell "t{table}:r{row}:c{col}", plus
  [char_start, char_end) within that paragraph/cell text. DOCX has no reliable page numbers, so none
  are reported.

Scanned/empty/garbled documents are reported as NEEDS_OCR_OR_REVIEW instead of pretending text exists.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

PARSER_VERSION = "sl-parse-1"

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_BULLET_LINE = re.compile(r"^\s*(?:[-•–*▪●]|\d{1,2}(?:\.\d{1,2})*[.)]?\s|[a-zа-я]\)\s)", re.IGNORECASE)
_WS = re.compile(r"\s+")
MAX_SPAN_CHARS = 900


class ParseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ParsedSpan:
    anchor_type: str
    char_start: int
    char_end: int
    exact_quote: str
    page: int | None = None
    paragraph_index: int | None = None
    table_ref: str | None = None
    heading: str | None = None

    @property
    def normalized_text(self) -> str:
        return normalize(self.exact_quote)


@dataclass
class ParsedDocument:
    mime: str
    spans: list[ParsedSpan]
    page_count: int | None
    text_chars: int
    status: str  # PARSED | NEEDS_OCR_OR_REVIEW
    quality: dict[str, object] = field(default_factory=dict)


def normalize(text: str) -> str:
    return _WS.sub(" ", text.replace("­", "")).strip()


def sniff_mime(data: bytes, filename: str) -> str:
    """Decide the type from magic bytes (not the client-provided content type)."""
    if data[:5] == b"%PDF-":
        return PDF_MIME
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" in zf.namelist():
                    return DOCX_MIME
        except zipfile.BadZipFile:
            pass
    raise ParseError("UNSUPPORTED_FILE_TYPE", "Only text-based PDF and DOCX files are supported")


def _looks_like_heading(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 90 or t.endswith((".", ";", ",")):
        return False
    if re.match(r"^(\d{1,2}(\.\d{1,2})*\.?|[IVX]{1,4}\.)\s+\S", t):
        return True
    letters = [c for c in t if c.isalpha()]
    return bool(letters) and (sum(c.isupper() for c in letters) / len(letters) > 0.7 or t.endswith(":"))


def _segment(text: str) -> list[tuple[int, int]]:
    """Split a block/paragraph into bullet/numbered segments and cap their length; returns offsets."""
    lines: list[tuple[int, int]] = []
    pos = 0
    for line in text.split("\n"):
        lines.append((pos, pos + len(line)))
        pos += len(line) + 1
    segments: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end = 0
    for start, end in lines:
        line = text[start:end]
        if not line.strip():
            continue
        if cur_start is None:
            cur_start, cur_end = start, end
        elif _BULLET_LINE.match(line):
            segments.append((cur_start, cur_end))
            cur_start, cur_end = start, end
        else:
            cur_end = end
    if cur_start is not None:
        segments.append((cur_start, cur_end))

    out: list[tuple[int, int]] = []
    for s, e in segments:
        while e - s > MAX_SPAN_CHARS:
            window = text[s : s + MAX_SPAN_CHARS]
            cut = max(window.rfind(". "), window.rfind("; "))
            cut = s + (cut + 1 if cut > MAX_SPAN_CHARS // 3 else MAX_SPAN_CHARS)
            out.append((s, cut))
            s = cut
            while s < e and text[s].isspace():
                s += 1
        if e > s:
            out.append((s, e))
    # Trim whitespace at both ends so quotes are exact and tidy.
    trimmed = []
    for s, e in out:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            trimmed.append((s, e))
    return trimmed


def _quality(spans: list[ParsedSpan], page_chars: list[int] | None) -> tuple[str, dict[str, object]]:
    all_text = "".join(s.exact_quote for s in spans)
    non_ws = [c for c in all_text if not c.isspace()]
    letters = sum(c.isalpha() for c in non_ws)
    letter_ratio = (letters / len(non_ws)) if non_ws else 0.0
    quality: dict[str, object] = {
        "text_chars": len(all_text),
        "span_count": len(spans),
        "letter_ratio": round(letter_ratio, 3),
    }
    reasons = []
    if len(all_text) < 200:
        reasons.append("LOW_TEXT")
    if non_ws and letter_ratio < 0.5:
        reasons.append("GARBLED_TEXT")
    if page_chars is not None:
        empty_pages = sum(1 for c in page_chars if c < 20)
        quality["empty_pages"] = empty_pages
        if page_chars and empty_pages / len(page_chars) > 0.5:
            reasons.append("MOSTLY_EMPTY_PAGES")
    quality["issues"] = reasons
    return ("NEEDS_OCR_OR_REVIEW" if reasons else "PARSED"), quality


def parse_pdf(data: bytes, max_pages: int) -> ParsedDocument:
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParseError("CORRUPT_FILE", "The PDF could not be opened") from exc
    with doc:
        if doc.needs_pass:
            raise ParseError("ENCRYPTED_FILE", "Password-protected PDFs are not supported")
        if doc.page_count > max_pages:
            raise ParseError("TOO_MANY_PAGES", f"The PDF has {doc.page_count} pages (limit {max_pages})")
        spans: list[ParsedSpan] = []
        page_chars: list[int] = []
        heading: str | None = None
        for page_index, page in enumerate(doc):
            blocks = [b for b in page.get_text("blocks", sort=True) if b[6] == 0]  # text blocks only
            block_texts = [b[4].rstrip("\n") for b in blocks]
            page_text = "\n".join(block_texts)
            page_chars.append(len(page_text.strip()))
            offset = 0
            for block in block_texts:
                for s, e in _segment(block):
                    quote = block[s:e]
                    if not normalize(quote):
                        continue
                    if _looks_like_heading(quote):
                        heading = normalize(quote).rstrip(":")
                    spans.append(
                        ParsedSpan(
                            anchor_type="PDF_PAGE",
                            page=page_index + 1,
                            char_start=offset + s,
                            char_end=offset + e,
                            exact_quote=quote,
                            heading=heading,
                        )
                    )
                offset += len(block) + 1
        status, quality = _quality(spans, page_chars)
        return ParsedDocument(PDF_MIME, spans, doc.page_count, quality["text_chars"], status, quality)  # type: ignore[arg-type]


def parse_docx(data: bytes) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ParseError("CORRUPT_FILE", "The DOCX could not be opened") from exc

    spans: list[ParsedSpan] = []
    heading: str | None = None
    # document.paragraphs / document.tables are exactly the body-level w:p / w:tbl children in
    # order, so running counters give stable indexes into them.
    p_counter = 0
    t_counter = 0

    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, document)
            text = p.text
            idx = p_counter
            p_counter += 1
            style = (p.style.name if p.style is not None else "") or ""
            is_heading = style.startswith(("Heading", "Title")) or _looks_like_heading(text)
            if is_heading and normalize(text):
                heading = normalize(text).rstrip(":")
            for s, e in _segment(text):
                spans.append(
                    ParsedSpan(
                        anchor_type="DOCX_PARAGRAPH",
                        paragraph_index=idx,
                        char_start=s,
                        char_end=e,
                        exact_quote=text[s:e],
                        heading=heading,
                    )
                )
        elif tag == "tbl":
            t = Table(child, document)
            t_idx = t_counter
            t_counter += 1
            seen: list[object] = []  # holding references keeps lxml proxies (and identities) alive
            for r_idx, row in enumerate(t.rows):
                for c_idx, cell in enumerate(row.cells):
                    if any(cell._tc is tc for tc in seen):  # merged cells repeat the same element
                        continue
                    seen.append(cell._tc)
                    text = cell.text
                    for s, e in _segment(text):
                        spans.append(
                            ParsedSpan(
                                anchor_type="DOCX_TABLE_CELL",
                                table_ref=f"t{t_idx}:r{r_idx}:c{c_idx}",
                                char_start=s,
                                char_end=e,
                                exact_quote=text[s:e],
                                heading=heading,
                            )
                        )
    status, quality = _quality(spans, None)
    return ParsedDocument(DOCX_MIME, spans, None, quality["text_chars"], status, quality)  # type: ignore[arg-type]


def parse_document(data: bytes, mime: str, *, max_pages: int = 200) -> ParsedDocument:
    if mime == PDF_MIME:
        return parse_pdf(data, max_pages)
    if mime == DOCX_MIME:
        return parse_docx(data)
    raise ParseError("UNSUPPORTED_FILE_TYPE", f"Unsupported type {mime}")


def anchor_label(anchor_type: str, page: int | None, paragraph_index: int | None, table_ref: str | None) -> str:
    """Machine-neutral anchor string (the UI localizes it)."""
    if anchor_type == "PDF_PAGE":
        return f"p.{page}"
    if anchor_type == "DOCX_PARAGRAPH":
        return f"¶{(paragraph_index or 0) + 1}"
    return f"table {table_ref}"
