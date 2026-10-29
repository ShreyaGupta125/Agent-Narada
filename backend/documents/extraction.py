"""Reading the text out of an uploaded file, keeping its structure.

    file  ->  blocks

A block is one heading, one paragraph, or one table. Keeping them apart
(instead of one long string) is what lets processing.py keep headings,
sections, tables, dates and numbers together and name the section an
answer came from.

Supported files and how each is read:
    .pdf   pypdf, page by page, so page numbers are kept
    .txt   Python's own text decoding
    .docx  a zip of XML files: Python's own zipfile and xml modules
    .odt   also a zip of XML files: the same modules
    .doc   the old Word 97-2003 format: olefile opens the file, and
           read_doc() below finds the text inside it

If no usable text can be read, ExtractionError explains why. The upload
is then refused and the administrator sees the reason.
"""

import io
import logging
import re
import struct
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

import olefile
from pypdf import PdfReader
from pypdf.errors import PdfReadError

# pypdf prints a warning for every small flaw in a PDF. A file that
# cannot be read is already reported by ExtractionError, so only real
# errors are let through.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# A .docx or .odt file is a zip. A zip can hold a small file that grows
# enormous when unpacked (a "zip bomb"), so the XML read from one is
# limited to this size.
MAX_XML_BYTES = 50 * 1024 * 1024


class ExtractionError(Exception):
    """The file's text could not be read. The message is shown to the
    administrator who uploaded it."""


@dataclass
class Block:
    """One piece of a document, in reading order."""

    text: str
    page: int | None = None  # PDF page number; None for other files
    heading: bool = False


# ---------- Recognising headings in plain text ----------

# "1. Fees", "2.3 Hostel rules", "IV. Leave", "Section 4 ...", "Chapter 2 ..."
NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+)*[.)]?|[IVX]+\.|Section\s+\d+|Chapter\s+\d+)\s+\S", re.IGNORECASE)


def looks_like_heading(line, colon_counts=True):
    """Guess whether a line of plain text is a heading.

    A heading is short, is not a sentence, and is either ALL CAPITALS,
    numbered ("2. Fees"), or ends with a colon. Word and ODT files say
    which paragraphs are headings, so for them a colon does not count:
    there, "The waiver depends on the category:" is a sentence that
    introduces a table, not a heading.
    """
    line = line.strip()
    words = line.split()
    if not words or len(words) > 10 or line.endswith((".", ",", ";")):
        return False
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters):
        return True
    if NUMBERED_HEADING.match(line) and len(words) <= 6:
        return True
    return colon_counts and line.endswith(":")


def blocks_from_lines(text, page=None):
    """Plain text -> blocks. A blank line ends a paragraph; a heading
    line becomes a block of its own."""
    blocks = []
    paragraph = []

    def finish_paragraph():
        if paragraph:
            blocks.append(Block("\n".join(paragraph), page))
            paragraph.clear()

    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())  # tidy runs of spaces
        if not line:
            finish_paragraph()
        elif looks_like_heading(line):
            finish_paragraph()
            blocks.append(Block(line, page, heading=True))
        else:
            paragraph.append(line)
    finish_paragraph()
    return blocks


# ---------- PDF and TXT ----------


def read_pdf(data):
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("The PDF is protected with a password. Upload a copy without one.")
        blocks = []
        for number, page in enumerate(reader.pages, start=1):
            blocks += blocks_from_lines(page.extract_text() or "", page=number)
        return blocks
    except ExtractionError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as error:
        raise ExtractionError("The PDF is damaged and could not be opened.") from error


def read_txt(data):
    if b"\x00" in data:
        raise ExtractionError("This is not a plain text file.")
    # utf-8-sig also removes the invisible mark some editors put at the
    # start of a file. A byte that is not valid text becomes a "?" sign.
    return blocks_from_lines(data.decode("utf-8-sig", errors="replace"))


# ---------- DOCX and ODT (zip files of XML) ----------


def read_zip_xml(data, name, kind):
    """Read one XML file from inside a .docx or .odt zip, safely."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo(name)
    except (zipfile.BadZipFile, KeyError) as error:
        raise ExtractionError(f"This is not a valid {kind} file.") from error
    if info.file_size > MAX_XML_BYTES:
        raise ExtractionError(f"This {kind} file is too large to read.")
    xml = archive.read(name)
    # Office files never need a DOCTYPE. Refusing it blocks XML tricks
    # (such as "billion laughs") that make a parser use huge memory.
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ExtractionError(f"This {kind} file contains content that is not allowed.")
    try:
        return ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise ExtractionError(f"This {kind} file is damaged.") from error


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(element):
    """The text inside a Word paragraph or table cell."""
    parts = []
    for node in element.iter():
        if node.tag == W + "t" and node.text:
            parts.append(node.text)
        elif node.tag == W + "tab":
            parts.append(" ")
        elif node.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return " ".join("".join(parts).split())


def table_block(rows, page=None):
    """A table as one block: one line per row, cells separated by " | ",
    so a row such as "Gold | 95% and above | 50%" stays together."""
    lines = [" | ".join(cell for cell in row) for row in rows if any(row)]
    return Block("\n".join(lines), page) if lines else None


def read_docx(data):
    body = read_zip_xml(data, "word/document.xml", "Word (.docx)").find(W + "body")
    if body is None:
        raise ExtractionError("This is not a valid Word (.docx) file.")
    blocks = []
    for element in body:
        if element.tag == W + "p":
            text = docx_text(element)
            if not text:
                continue
            style = element.find(f"{W}pPr/{W}pStyle")
            style_name = style.get(W + "val", "") if style is not None else ""
            # Word's own heading styles: "Title", "Heading1", "Heading2" ...
            is_heading = style_name.lower().startswith(("heading", "title")) or looks_like_heading(
                text, colon_counts=False
            )
            blocks.append(Block(text, heading=is_heading))
        elif element.tag == W + "tbl":
            rows = [[docx_text(cell) for cell in row.iter(W + "tc")] for row in element.iter(W + "tr")]
            block = table_block(rows)
            if block:
                blocks.append(block)
    return blocks


TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"


def odt_text(element):
    """The text inside an ODT paragraph or heading, including its
    special space, tab and line-break elements."""
    parts = [element.text or ""]
    for child in element:
        if child.tag == TEXT + "s":
            parts.append(" " * int(child.get(TEXT + "c", "1")))
        elif child.tag == TEXT + "tab":
            parts.append(" ")
        elif child.tag == TEXT + "line-break":
            parts.append("\n")
        else:
            parts.append(odt_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def read_odt_container(container, blocks):
    """Walk an ODT body in reading order. Lists and sections hold more
    paragraphs inside them, so they are walked as well."""
    for element in container:
        if element.tag in (TEXT + "h", TEXT + "p"):
            text = " ".join(odt_text(element).split())
            if text:
                is_heading = element.tag == TEXT + "h" or looks_like_heading(text, colon_counts=False)
                blocks.append(Block(text, heading=is_heading))
        elif element.tag == TABLE + "table":
            rows = []
            for row in element.iter(TABLE + "table-row"):
                cells = [
                    " ".join(" ".join(odt_text(p) for p in cell.iter(TEXT + "p")).split())
                    for cell in row.iter(TABLE + "table-cell")
                ]
                rows.append(cells)
            block = table_block(rows)
            if block:
                blocks.append(block)
        else:
            read_odt_container(element, blocks)  # lists, sections, frames ...


def read_odt(data):
    root = read_zip_xml(data, "content.xml", "OpenDocument (.odt)")
    text_body = root.find(f"{OFFICE}body/{OFFICE}text")
    if text_body is None:
        raise ExtractionError("This is not a valid OpenDocument text (.odt) file.")
    blocks = []
    read_odt_container(text_body, blocks)
    return blocks


# ---------- DOC (Word 97-2003) ----------
#
# A .doc file is a small file system of its own (an "OLE" file). olefile
# opens it. Inside, the "WordDocument" stream holds the text, and the
# table stream ("0Table" or "1Table") holds the "piece table": a list of
# where each piece of the text is, and whether it is stored with one
# byte per character (Windows-1252) or two (UTF-16).
# Field positions come from Microsoft's published [MS-DOC] specification.

FIB_MAGIC = 0xA5EC
FLAG_ENCRYPTED = 0x0100
FLAG_TABLE_1 = 0x0200  # the table stream is "1Table" (otherwise "0Table")
FIB_CCP_TEXT = 0x004C  # number of characters in the main text
FIB_FC_CLX = 0x01A2  # where the piece table starts in the table stream
FIB_LCB_CLX = 0x01A6  # and how long it is
COMPRESSED = 0x40000000


def doc_pieces(word_stream, table_stream):
    """The text of the main document, put together from its pieces."""
    magic = struct.unpack_from("<H", word_stream, 0)[0]
    flags = struct.unpack_from("<H", word_stream, 0x0A)[0]
    if magic != FIB_MAGIC:
        raise ExtractionError("This is not a valid Word 97-2003 (.doc) file.")
    if flags & FLAG_ENCRYPTED:
        raise ExtractionError("The Word file is protected with a password. Upload a copy without one.")

    text_length = struct.unpack_from("<i", word_stream, FIB_CCP_TEXT)[0]
    fc_clx, lcb_clx = struct.unpack_from("<II", word_stream, FIB_FC_CLX)
    clx = table_stream[fc_clx : fc_clx + lcb_clx]

    # The CLX starts with optional formatting records (type 1), then the
    # piece table itself (type 2).
    position = 0
    while position < len(clx) and clx[position] == 0x01:
        size = struct.unpack_from("<H", clx, position + 1)[0]
        position += 3 + size
    if position >= len(clx) or clx[position] != 0x02:
        raise ExtractionError("The Word file's text could not be found.")
    plc_size = struct.unpack_from("<I", clx, position + 1)[0]
    plc = clx[position + 5 : position + 5 + plc_size]

    # PlcPcd: (n + 1) character positions, then n piece descriptors of 8 bytes.
    count = (len(plc) - 4) // 12
    positions = struct.unpack_from(f"<{count + 1}i", plc, 0)
    parts = []
    for index in range(count):
        start, end = positions[index], min(positions[index + 1], text_length)
        if start >= end:
            continue
        fc = struct.unpack_from("<I", plc, (count + 1) * 4 + index * 8 + 2)[0]
        length = end - start
        if fc & COMPRESSED:
            offset = (fc & ~COMPRESSED) // 2
            parts.append(word_stream[offset : offset + length].decode("cp1252", errors="replace"))
        else:
            parts.append(word_stream[fc : fc + 2 * length].decode("utf-16-le", errors="replace"))
    return "".join(parts)


def clean_doc_text(raw):
    """Turn Word's special characters into plain text.

    Fields such as page numbers are stored as \\x13 instructions \\x14
    result \\x15; only the result is kept. \\x07 ends a table cell, and
    two in a row end a table row.
    """
    out = []
    stack = []  # one entry per open field: True once its result part starts
    for char in raw.replace("\x07\x07", "\x07\r"):
        if char == "\x13":
            stack.append(False)
        elif char == "\x14":
            if stack:
                stack[-1] = True
        elif char == "\x15":
            if stack:
                stack.pop()
        elif all(stack):
            out.append(char)
    text = "".join(out)
    replacements = {"\r": "\n", "\x0b": "\n", "\x0c": "\n", "\x07": " | ", "\x1e": "-", "\xa0": " "}
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[\x00-\x08\x0e-\x1f]", "", text)


def read_doc(data):
    if not olefile.isOleFile(io.BytesIO(data)):
        raise ExtractionError("This is not a valid Word 97-2003 (.doc) file.")
    try:
        with olefile.OleFileIO(io.BytesIO(data)) as ole:
            if not ole.exists("WordDocument"):
                raise ExtractionError("This is not a Word document.")
            word_stream = ole.openstream("WordDocument").read()
            flags = struct.unpack_from("<H", word_stream, 0x0A)[0]
            table_name = "1Table" if flags & FLAG_TABLE_1 else "0Table"
            if not ole.exists(table_name):
                raise ExtractionError("The Word file is damaged.")
            table_stream = ole.openstream(table_name).read()
    except ExtractionError:
        raise
    except (OSError, struct.error, ValueError) as error:
        raise ExtractionError("The Word file is damaged and could not be opened.") from error

    try:
        text = clean_doc_text(doc_pieces(word_stream, table_stream))
    except struct.error as error:
        raise ExtractionError("The Word file is damaged.") from error

    # Paragraphs come one per line. Table rows keep their " | " cells.
    blocks = []
    for line in text.split("\n"):
        line = " ".join(line.split()).strip(" |")
        if line:
            blocks.append(Block(line, heading=looks_like_heading(line)))
    return blocks


# ---------- The entry point ----------

READERS = {
    "pdf": read_pdf,
    "txt": read_txt,
    "docx": read_docx,
    "odt": read_odt,
    "doc": read_doc,
}


def extract_blocks(filename, data):
    """The file's text as a list of blocks, in reading order.
    Raises ExtractionError if no text can be read."""
    extension = filename.rsplit(".", 1)[-1].lower()
    reader = READERS.get(extension)
    if reader is None:
        raise ExtractionError(f"Files of type .{extension} are not supported.")
    blocks = [block for block in reader(data) if block.text.strip()]
    if not any(not block.heading for block in blocks):
        raise ExtractionError(
            "No text could be read from this file. A scanned document (a picture "
            "of text) cannot be read; upload a version with real text."
        )
    return blocks
