"""Correcting spelling mistakes in a question before it is searched.

Users type fast: "wat is attendence criteria for studnts". The search
matches words exactly, so "attendence" would never find "attendance".

So each word of the question that appears in NO document the user may
read is compared with the words that DO appear there, and replaced by
the closest one if it is very similar:

    attendence -> attendance    hostal -> hostel    libary -> library
    scolarship -> scholarship   borow  -> borrow    salry  -> salary

Python's own difflib measures how similar two words are (0 = nothing in
common, 1 = the same). Safety rules, so a correct word is never turned
into a different one:
  - only words of 4 letters or more are corrected;
  - the first letter must be the same (typing mistakes rarely change it);
  - the length may differ by at most 2 letters;
  - the words must be very similar (see CUTOFF below);
  - common words, short forms and words with a known meaning
    (text.STOPWORDS, text.SAME_MEANING) are never changed.

Short forms students use are written out first: "dbms" -> "database
management systems", "hod" -> "head of department".
"""

import difflib
import re
from collections import Counter

from .text import SAME_MEANING, STOPWORDS, normalise

WORD = re.compile(r"[A-Za-z][A-Za-z.]*[A-Za-z]|[A-Za-z]")

# Short forms, written out in full so they match the documents' words.
SHORT_FORMS = {
    "dbms": "database management systems",
    "hod": "head of department",
    "hods": "heads of department",
    "cse": "computer science",
    "btech": "B.Tech",
    "mtech": "M.Tech",
    "vc": "vice chancellor",
    "ai": "artificial intelligence",
    "ds": "data structures",
    "sem": "semester",
    "dept": "department",
    "prof": "professor",
    "lib": "library",
}


def similarity_needed(word):
    """How similar a word must be to be corrected: stricter for longer
    words, where one wrong letter matters less."""
    return 0.8 if len(word) >= 6 else 0.75


def closest_known_word(word, vocabulary):
    """The vocabulary word closest to a misspelled word, or None.
    When several are equally close ("fess": "fees" or "fest"), the one
    used most often in the documents wins."""
    needed = similarity_needed(word)
    best, best_key = None, None
    for known, count in vocabulary.items():
        if known[0] != word[0] or abs(len(known) - len(word)) > 2:
            continue
        ratio = difflib.SequenceMatcher(None, word, known).ratio()
        if ratio >= needed and (best_key is None or (ratio, count) > best_key):
            best, best_key = known, (ratio, count)
    return best


def correct_spelling(text, vocabulary, extra_words=()):
    """The text with short forms written out and misspelled words
    replaced by the closest word of the documents (vocabulary: a Counter
    of lower-case words and how often they appear). extra_words are
    tried only when no document word is close enough. Everything else in
    the text is kept as it was."""
    known_forms = {normalise(known) for known in [*vocabulary, *SAME_MEANING]} | set(SAME_MEANING.values())
    # The words with a known meaning ("submission" = "pay") are known too,
    # so "submision" -> "submission" -> "pay".
    extra = Counter(word for word in [*extra_words, *SAME_MEANING] if word not in vocabulary)

    def fix(match):
        word = match.group(0)
        lower = word.lower()
        if lower in SHORT_FORMS:
            return SHORT_FORMS[lower]
        if (
            len(lower) < 4
            or not lower.isalpha()
            or lower in vocabulary
            or lower in STOPWORDS
            or lower in SAME_MEANING
            # Only another form of a document word ("teach" for "teaching"):
            # not a mistake, and it already matches after normalise().
            or normalise(lower) in known_forms
        ):
            return word
        return closest_known_word(lower, vocabulary) or closest_known_word(lower, extra) or word

    return WORD.sub(fix, text)


def vocabulary_of(texts):
    """Every word (lower case, 3+ letters) in the given texts, with how
    often it appears."""
    words = Counter()
    for text in texts:
        words.update(word for word in re.findall(r"[a-z]+", text.lower()) if len(word) >= 3)
    return words
