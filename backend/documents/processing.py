"""Document ingestion: make an uploaded file's contents searchable.

    uploaded file  ->  blocks (extraction.py)  ->  passages  ->  database

This runs when a document is uploaded. The original file is kept, AND
its text is extracted, split into passages, given keywords (the search
index) and stored in the database, linked to the document and so to its
access permissions.

Qwen does not "learn" or memorise the document. When a question is
asked, retrieval.py finds the matching passages and they are given to
the model as context.
"""

from django.db import transaction
from django.utils import timezone

from .extraction import Block, ExtractionError, extract_blocks
from .models import Passage
from .text import keywords

# A passage holds about this many words. Small enough for a small model
# to read carefully, large enough to keep a rule and its conditions together.
PASSAGE_WORDS = 120

# When one paragraph is longer than a passage, it is cut into pieces that
# share this many words, so a sentence cut at the edge is whole in the next.
OVERLAP_WORDS = 20

# The longest section name kept for a passage.
SECTION_LENGTH = 200


class IngestionError(Exception):
    """The document could not be made searchable. The message says why
    and is shown to the administrator."""


def split_long_text(text):
    """Cut a text longer than PASSAGE_WORDS into overlapping pieces."""
    words = text.split()
    step = PASSAGE_WORDS - OVERLAP_WORDS
    pieces = []
    for start in range(0, len(words), step):
        pieces.append(" ".join(words[start : start + PASSAGE_WORDS]))
        if start + PASSAGE_WORDS >= len(words):
            break  # the last piece reached the end of the text
    return pieces


def smaller_blocks(blocks):
    """Break a block that is longer than a passage at its line breaks, so
    the split falls between lines (a table row, a list item) rather than
    in the middle of one. PDF pages often arrive as one long block."""
    for block in blocks:
        if not block.heading and len(block.text.split()) > PASSAGE_WORDS and "\n" in block.text:
            for line in block.text.split("\n"):
                if line.strip():
                    yield Block(line, block.page)
        else:
            yield block


def make_passages(blocks):
    """Group blocks into passages: a list of (page, section, text).

    - A heading starts a new passage, and becomes the "section" of the
      passages under it, so a source can say which section it came from.
      Headings that follow each other ("Fees" then "2. Hostel fees") are
      all kept at the top of the passage; the last one is its section.
    - Paragraphs, lines and tables are added whole until a passage is
      full: a rule, a table row or a directory entry is never cut in half
      (unless one line alone is longer than a passage).
    - A passage never spans two PDF pages, so its page number is exact.
    - The section heading is repeated at the start of each passage's
      text, so the model and the search both see it.
    """
    passages = []
    headings = []  # the headings above the current text
    lines = []
    words = 0
    page = None
    heading_pending = False  # True right after a heading, before any text

    def finish():
        nonlocal lines, words
        if lines:
            section = headings[-1] if headings else ""
            # Headings one per line, then the paragraphs with a blank line
            # between them, so each paragraph (a rule, a directory entry)
            # stays recognisable as one unit (see grounding.py's checks).
            body = "\n\n".join(lines)
            passages.append((page, section[:SECTION_LENGTH], "\n".join(headings + [body])))
        lines, words = [], 0

    for block in smaller_blocks(blocks):
        if block.heading:
            finish()
            if not heading_pending:
                headings = []  # a new section: forget the previous headings
            headings.append(block.text)
            heading_pending = True
            continue
        heading_pending = False

        size = len(block.text.split())
        if lines and (block.page != page or words + size > PASSAGE_WORDS):
            finish()
        page = block.page

        if size > PASSAGE_WORDS:
            for piece in split_long_text(block.text):
                lines, words = [piece], PASSAGE_WORDS
                finish()
        else:
            lines.append(block.text)
            words += size
    finish()
    return passages


def process_document(document):
    """Extract, split, index and store the document's text.

    Raises IngestionError if that fails. Nothing is stored then, and the
    document is NOT marked as processed. processed_at is set only at the
    very end, after every passage has been saved.
    """
    try:
        with document.file.open("rb") as file:
            data = file.read()
    except OSError as error:
        raise IngestionError("The uploaded file could not be opened.") from error

    try:
        blocks = extract_blocks(document.file.name, data)
    except ExtractionError as error:
        raise IngestionError(str(error)) from error

    pieces = make_passages(blocks)
    if not pieces:
        raise IngestionError("No text could be read from this file.")

    # The document's title words are added to every passage's keywords,
    # so "fee structure" finds the passages of the "Fee Structure" document.
    title_terms = keywords(document.title)

    with transaction.atomic():
        document.passages.all().delete()  # start clean if it was processed before
        Passage.objects.bulk_create(
            Passage(
                document=document,
                number=number,
                page=page,
                section=section,
                text=text,
                terms=" " + " ".join(keywords(text) + title_terms) + " ",
            )
            for number, (page, section, text) in enumerate(pieces, start=1)
        )
        document.passage_count = len(pieces)
        document.processed_at = timezone.now()
        document.save(update_fields=["passage_count", "processed_at"])
    return document


def mark_unprocessed(document):
    """Take a document out of search: no passages, not processed."""
    with transaction.atomic():
        document.passages.all().delete()
        document.passage_count = 0
        document.processed_at = None
        document.save(update_fields=["passage_count", "processed_at"])
