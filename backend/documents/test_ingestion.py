"""Tests for document ingestion: reading every file type with its
structure (extraction.py), splitting it into section-aware passages
(processing.py), and the upload rules around it.

The .docx, .odt and .doc files used here are built by the functions
below, byte by byte, so the tests do not need Word to be installed.
"""

import io
import os
import struct
import zipfile
from io import StringIO
from unittest import mock
from xml.sax.saxutils import escape

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase

from . import extraction
from .extraction import Block, ExtractionError, extract_blocks, looks_like_heading
from .models import Document, Passage
from .processing import OVERLAP_WORDS, PASSAGE_WORDS, IngestionError, make_passages, process_document
from .tests import TEST_MEDIA, DocumentTestCase, make_pdf

# ---------- Building test files ----------


def make_docx(paragraphs=(), table=None, document_xml=None):
    """A Word .docx file. paragraphs: (style, text) pairs, style None for
    normal text. table: rows of cells, placed after the paragraphs."""
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def para(style, text):
        props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{props}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"

    body = "".join(para(style, text) for style, text in paragraphs)
    if table:
        rows = "".join(
            "<w:tr>" + "".join(f"<w:tc>{para(None, cell)}</w:tc>" for cell in row) + "</w:tr>"
            for row in table
        )
        body += f"<w:tbl>{rows}</w:tbl>"
    if document_xml is None:
        document_xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>'

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        if document_xml is not False:
            archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def make_odt(content_xml):
    """An OpenDocument .odt file whose body is the given XML."""
    namespaces = (
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    )
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {namespaces}>'
        f"<office:body><office:text>{content_xml}</office:text></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", content)
    return buffer.getvalue()


NO_STREAM = 0xFFFFFFFF
END_OF_CHAIN = 0xFFFFFFFE


def build_ole(streams):
    """An OLE (compound) file holding the given streams: the container
    format of old Office files. Every stream must be a multiple of 512
    bytes and at least 4096 bytes long, which keeps the layout simple."""
    names = list(streams)
    fat = [NO_STREAM] * 128
    fat[0] = 0xFFFFFFFD  # sector 0 holds the FAT itself
    fat[1] = END_OF_CHAIN  # sector 1 holds the directory
    starts, next_sector = {}, 2
    for name in names:
        count = len(streams[name]) // 512
        starts[name] = next_sector
        for index in range(count - 1):
            fat[next_sector + index] = next_sector + index + 1
        fat[next_sector + count - 1] = END_OF_CHAIN
        next_sector += count

    def entry(name, kind, left=NO_STREAM, child=NO_STREAM, start=END_OF_CHAIN, size=0):
        raw = name.encode("utf-16-le") + b"\0\0" if name else b""
        return (
            raw.ljust(64, b"\0")
            + struct.pack("<HBBIII", len(raw), kind, 1, left, NO_STREAM, child)
            + b"\0" * 36
            + struct.pack("<IQ", start, size)
        )

    # Root -> WordDocument, whose left neighbour is 1Table (shorter names sort first).
    directory = (
        entry("Root Entry", 5, child=1)
        + entry(names[0], 2, left=2, start=starts[names[0]], size=len(streams[names[0]]))
        + entry(names[1], 2, start=starts[names[1]], size=len(streams[names[1]]))
        + entry("", 0, start=0)
    )
    header = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        + b"\0" * 16
        + struct.pack("<HHHHH", 0x003E, 0x0003, 0xFFFE, 9, 6)
        + b"\0" * 6
        + struct.pack("<9I", 0, 1, 1, 0, 0x1000, END_OF_CHAIN, 0, END_OF_CHAIN, 0)
        + struct.pack("<109I", 0, *([NO_STREAM] * 108))
    )
    return header + struct.pack("<128I", *fat) + directory + b"".join(streams[name] for name in names)


def make_doc(text, encrypted=False):
    """A Word 97-2003 .doc file. The first half of the text is stored with
    one byte per character and the second half as UTF-16, so both kinds
    of text piece are tested."""
    half = len(text) // 2
    first, second = text[:half], text[half:]
    word = bytearray(5120)
    struct.pack_into("<H", word, 0, extraction.FIB_MAGIC)
    struct.pack_into("<H", word, 0x0A, extraction.FLAG_TABLE_1 | (extraction.FLAG_ENCRYPTED if encrypted else 0))
    struct.pack_into("<i", word, extraction.FIB_CCP_TEXT, len(text))
    first_bytes, second_bytes = first.encode("cp1252"), second.encode("utf-16-le")
    word[2048 : 2048 + len(first_bytes)] = first_bytes
    word[3072 : 3072 + len(second_bytes)] = second_bytes

    pieces = struct.pack("<3i", 0, len(first), len(text))
    pieces += struct.pack("<HIH", 0, (2048 * 2) | extraction.COMPRESSED, 0)
    pieces += struct.pack("<HIH", 0, 3072, 0)
    clx = b"\x02" + struct.pack("<I", len(pieces)) + pieces
    struct.pack_into("<II", word, extraction.FIB_FC_CLX, 0, len(clx))
    table = bytearray(4096)
    table[: len(clx)] = clx
    return build_ole({"WordDocument": bytes(word), "1Table": bytes(table)})


def texts(blocks):
    return [(block.text, block.heading) for block in blocks]


# ---------- Reading each file type ----------


class HeadingGuessTests(SimpleTestCase):
    def test_headings_in_plain_text(self):
        for line, expected in [
            ("ATTENDANCE NOTICE", True),
            ("1. Minimum attendance", True),
            ("2.3 Fees and refunds", True),
            ("Contact:", True),
            ("Every student must attend 75% of classes.", False),  # a sentence
            ("1. The examinations run from Tuesday, 1 December 2026", False),  # a long list item
            ("Tuesday, 1 December 2026      Data Structures", False),
            ("", False),
        ]:
            with self.subTest(line=line):
                self.assertEqual(looks_like_heading(line), expected)


class ExtractionTests(SimpleTestCase):
    def test_txt_keeps_headings_and_paragraphs(self):
        text = "FEE RULES\n\n1. Tuition\nThe fee is Rs 2,000.\nPay by 15 January.\n\nLate fee: Rs 100 a day."
        self.assertEqual(
            texts(extract_blocks("fees.txt", text.encode())),
            [
                ("FEE RULES", True),
                ("1. Tuition", True),
                ("The fee is Rs 2,000.\nPay by 15 January.", False),
                ("Late fee: Rs 100 a day.", False),
            ],
        )

    def test_pdf_keeps_page_numbers(self):
        blocks = extract_blocks("rules.pdf", make_pdf(["Attendance is 75 percent.", "Fees are due in July."]))
        self.assertEqual([(b.text, b.page) for b in blocks], [("Attendance is 75 percent.", 1), ("Fees are due in July.", 2)])

    def test_docx_headings_paragraphs_and_tables(self):
        data = make_docx(
            [("Title", "Scholarship Policy"), ("Heading1", "Amounts"), (None, "The waiver depends on the category.")],
            table=[["Category", "Marks", "Waiver"], ["Gold", "95% and above", "50%"]],
        )
        self.assertEqual(
            texts(extract_blocks("policy.docx", data)),
            [
                ("Scholarship Policy", True),
                ("Amounts", True),
                ("The waiver depends on the category.", False),
                ("Category | Marks | Waiver\nGold | 95% and above | 50%", False),
            ],
        )

    def test_in_word_files_a_sentence_ending_with_a_colon_is_not_a_heading(self):
        data = make_docx([("Heading1", "Amounts"), (None, "The waiver depends on the category:")])
        self.assertEqual(
            texts(extract_blocks("policy.docx", data)),
            [("Amounts", True), ("The waiver depends on the category:", False)],
        )

    def test_odt_headings_lists_spaces_and_tables(self):
        data = make_odt(
            '<text:h text:outline-level="1">Sports timings</text:h>'
            '<text:p>Open<text:s text:c="2"/>6 am to 9 pm.</text:p>'
            "<text:list><text:list-item><text:p>Shoes are compulsory.</text:p></text:list-item></text:list>"
            "<table:table><table:table-row>"
            "<table:table-cell><text:p>Gym</text:p></table:table-cell>"
            "<table:table-cell><text:p>Rs 1,500</text:p></table:table-cell>"
            "</table:table-row></table:table>"
        )
        self.assertEqual(
            texts(extract_blocks("sports.odt", data)),
            [
                ("Sports timings", True),
                ("Open 6 am to 9 pm.", False),
                ("Shoes are compulsory.", False),
                ("Gym | Rs 1,500", False),
            ],
        )

    def test_doc_reads_both_kinds_of_text_piece_tables_and_fields(self):
        text = (
            "ANTI-RAGGING POLICY\r"
            "Ragging is punished with a fine.\r"
            "Fine\x07Rs 25,000\x07\x07"
            "Helpline \x13 HYPERLINK \x14extension 9999\x15 — any time.\r"
        )
        self.assertEqual(
            texts(extract_blocks("policy.doc", make_doc(text))),
            [
                ("ANTI-RAGGING POLICY", True),
                ("Ragging is punished with a fine.", False),
                ("Fine | Rs 25,000", False),
                ("Helpline extension 9999 — any time.", False),
            ],
        )

    def test_unreadable_files_raise_a_clear_error(self):
        not_a_doc = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600
        cases = {
            "unsupported type": ("notes.rtf", b"{\\rtf1 hello}"),
            "binary posing as text": ("notes.txt", b"MZ\x00\x00binary"),
            "pdf without text (scanned)": ("scan.pdf", make_pdf([""])),
            "damaged pdf": ("broken.pdf", b"%PDF-1.4 not really"),
            "docx that is not a zip": ("fake.docx", b"PK\x03\x04 not a zip"),
            "docx without document.xml": ("empty.docx", make_docx(document_xml=False)),
            "docx with a DOCTYPE": ("bomb.docx", make_docx(document_xml='<!DOCTYPE x [<!ENTITY a "b">]><x/>')),
            "odt without content.xml": ("empty.odt", make_docx()),
            "doc that is not an OLE file": ("fake.doc", b"not a word file at all" * 100),
            "damaged doc": ("broken.doc", not_a_doc),
            "password-protected doc": ("secret.doc", make_doc("Secret rules.\r", encrypted=True)),
            "only headings": ("headings.txt", b"FEES\n\nHOSTEL"),
        }
        for name, (filename, data) in cases.items():
            with self.subTest(name):
                with self.assertRaises(ExtractionError):
                    extract_blocks(filename, data)

    def test_an_oversized_xml_file_is_refused(self):
        data = make_docx([(None, "Hello")])
        with mock.patch.object(extraction, "MAX_XML_BYTES", 10):
            with self.assertRaisesMessage(ExtractionError, "too large"):
                extract_blocks("big.docx", data)


# ---------- Splitting into passages ----------


def words(count, word="word"):
    return " ".join(f"{word}{number}" for number in range(count))


class PassageTests(SimpleTestCase):
    def test_a_heading_becomes_the_section_of_the_passages_below_it(self):
        passages = make_passages(
            [Block("1. Fees", heading=True), Block("Pay by July."), Block("2. Hostel", heading=True), Block("Gates close at ten.")]
        )
        self.assertEqual(
            passages,
            [(None, "1. Fees", "1. Fees\nPay by July."), (None, "2. Hostel", "2. Hostel\nGates close at ten.")],
        )

    def test_paragraphs_are_kept_whole_and_packed_together(self):
        size = PASSAGE_WORDS // 2 - 5
        passages = make_passages([Block(words(size, "a")), Block(words(size, "b")), Block(words(size, "c"))])
        self.assertEqual(len(passages), 2)
        # The first two paragraphs fit in one passage; the third starts the next.
        # Paragraphs are separated by a blank line inside a passage.
        self.assertEqual(passages[0][2], words(size, "a") + "\n\n" + words(size, "b"))
        self.assertEqual(passages[1][2], words(size, "c"))

    def test_a_paragraph_longer_than_a_passage_is_cut_with_an_overlap(self):
        passages = make_passages([Block(words(300))])
        first, second = passages[0][2].split(), passages[1][2].split()
        self.assertEqual(len(first), PASSAGE_WORDS)
        self.assertEqual(first[-OVERLAP_WORDS:], second[:OVERLAP_WORDS])
        self.assertEqual(passages[-1][2].split()[-1], "word299")  # nothing is lost

    def test_a_passage_never_spans_two_pages(self):
        passages = make_passages([Block("Page one text.", page=1), Block("Page two text.", page=2)])
        self.assertEqual([(page, text) for page, _, text in passages], [(1, "Page one text."), (2, "Page two text.")])

    def test_headings_that_follow_each_other_are_all_kept(self):
        passages = make_passages(
            [Block("Scholarship Policy", heading=True), Block("2. Amounts", heading=True), Block("Gold | 50%")]
        )
        self.assertEqual(passages, [(None, "2. Amounts", "Scholarship Policy\n2. Amounts\nGold | 50%")])

    def test_a_long_block_is_split_between_lines_not_inside_one(self):
        rows = [f"Row {number} | {words(8, 'cell')}" for number in range(30)]  # 30 rows of 11 words
        passages = make_passages([Block("\n".join(rows), page=1)])
        self.assertGreater(len(passages), 1)
        for _, _, text in passages:
            for line in filter(None, text.split("\n")):  # blank lines separate paragraphs
                self.assertIn(line, rows)  # every line is a complete row

    def test_the_section_continues_onto_the_next_page(self):
        passages = make_passages([Block("EXAM RULES", page=1, heading=True), Block("Bring the ID card.", page=2)])
        self.assertEqual(passages, [(2, "EXAM RULES", "EXAM RULES\nBring the ID card.")])


# ---------- Uploading ----------


def stored_files():
    """Every file in the test media folder."""
    return [os.path.join(root, name) for root, _, names in os.walk(TEST_MEDIA) for name in names]


class IngestionUploadTests(DocumentTestCase):
    def post(self, filename, content, title="Rules"):
        return self.client.post(
            "/api/documents/",
            {"title": title, "file": SimpleUploadedFile(filename, content), "for_students": "true"},
        )

    def test_every_supported_file_type_is_read_and_stored(self):
        uploads = {
            "rules.txt": b"HOSTEL RULES\n\nGates close at 10 pm.",
            "rules.pdf": make_pdf(["HOSTEL RULES", "Gates close at 10 pm."]),
            "rules.docx": make_docx([("Heading1", "Hostel rules"), (None, "Gates close at 10 pm.")]),
            "rules.odt": make_odt("<text:h>Hostel rules</text:h><text:p>Gates close at 10 pm.</text:p>"),
            "rules.doc": make_doc("HOSTEL RULES\rGates close at 10 pm.\r"),
        }
        self.client.force_login(self.super_admin)
        for filename, content in uploads.items():
            with self.subTest(filename):
                response = self.post(filename, content, title=filename)
                self.assertEqual(response.status_code, 201, response.content)
                self.assertTrue(response.json()["processed"])
                passage = Document.objects.get(title=filename).passages.get()
                self.assertIn("Gates close at 10 pm.", passage.text)
                self.assertEqual(passage.section.lower(), "hostel rules")

    def test_a_file_whose_text_cannot_be_read_is_not_stored_and_the_reason_is_shown(self):
        for user in (self.admin, self.super_admin):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.post("scan.pdf", make_pdf([""]))
                self.assertEqual(response.status_code, 400)
                self.assertIn("scanned", response.json()["file"][0])
        # Nothing is left behind: no document, no passage, no saved file.
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(Passage.objects.count(), 0)
        self.assertEqual(stored_files(), [])

    def test_a_file_that_is_not_what_its_name_says_is_refused(self):
        self.client.force_login(self.admin)
        for filename in ("fake.docx", "fake.odt", "fake.doc"):
            with self.subTest(filename):
                response = self.post(filename, b"just some text pretending")
                self.assertEqual(response.status_code, 400)
                self.assertIn("not a real", response.json()["file"][0])
        self.assertEqual(Document.objects.count(), 0)


class ReprocessCommandTests(DocumentTestCase):
    def test_every_document_is_read_again(self):
        document = Document.objects.create(
            title="Hostel",
            file=SimpleUploadedFile("hostel.txt", b"HOSTEL RULES\n\nGates close at 10 pm."),
            uploaded_by=self.super_admin,
            for_students=True,
        )
        self.assertIsNone(document.processed_at)  # never read

        output = StringIO()
        call_command("reprocess_documents", stdout=output, stderr=StringIO())

        document.refresh_from_db()
        self.assertIsNotNone(document.processed_at)
        self.assertEqual(document.passages.get().section, "HOSTEL RULES")
        self.assertIn("Processed 1 document(s). 0 could not be read.", output.getvalue())

    def test_a_document_that_can_no_longer_be_read_is_taken_out_of_search(self):
        document = Document.objects.create(
            title="Broken",
            file=SimpleUploadedFile("broken.txt", b"Readable at first."),
            uploaded_by=self.super_admin,
            for_students=True,
        )
        process_document(document)
        with document.file.open("wb") as file:
            file.write(b"\x00\x01 binary now")

        errors = StringIO()
        call_command("reprocess_documents", stdout=StringIO(), stderr=errors)

        document.refresh_from_db()
        self.assertIsNone(document.processed_at)
        self.assertEqual(document.passages.count(), 0)
        self.assertIn('NOT READ: "Broken"', errors.getvalue())
        self.assertFalse(Document.objects.visible_to(self.student).exists())

    def test_processing_failure_raises_ingestion_error(self):
        document = Document.objects.create(
            title="Empty", file=SimpleUploadedFile("empty.txt", b"   "), uploaded_by=self.super_admin
        )
        with self.assertRaises(IngestionError):
            process_document(document)
