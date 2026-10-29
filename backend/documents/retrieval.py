"""Retrieval: find the passages that best match a question.

    question  ->  keywords  ->  passages THIS USER may read that contain
                                enough of them  ->  scored  ->  the best few

The permission check comes first. search() starts from
Document.objects.visible_to(user), so a passage from a document that is
not approved, or not open to the user's role, is never even looked at.
Nothing the user types can change that.
"""

import math
import re
from collections import Counter

from django.db.models import Q

from .models import Document, Passage
from .text import keywords

# A long question is cut to this many keywords.
MAX_QUESTION_TERMS = 20

# RELEVANCE THRESHOLD, part 1: coverage.
# A passage must contain at least this share of the question's keyword
# WEIGHT. Each keyword weighs as much as it is rare (see rarity()), so a
# passage that shares only the common words of a question ("staff",
# "rate") and misses its rare, important word ("overtime") is dropped.
MIN_COVERAGE = 0.45

# RELEVANCE THRESHOLD, part 2: compared with the best match.
# A passage scoring below this share of the best passage's score is
# dropped, so a weak extra match is not given to the model (or listed
# as a source) just because there was room for it.
MIN_SHARE_OF_BEST = 0.6

# Passages scoring within this share of the best are treated as equally
# good matches, and kept in the order they appear in their document.
NEAR_TIE = 0.15

# The two standard settings of the BM25 formula (see score() below).
K1 = 1.5
B = 0.75


def question_parts(question):
    """A question with several parts ("What is the minimum attendance,
    and can I get an exemption?") split into its parts. Each part is also
    searched on its own, so a part that IS covered by the documents is
    found even when another part is not."""
    parts = re.split(r"\?|;|,?\s+and\s+", question, flags=re.IGNORECASE)
    parts = [part for part in parts if keywords(part)]
    return parts if len(parts) > 1 else []


def uncovered_parts(user, question):
    """The parts of a several-part question that NO passage this user may
    read covers. Used to say clearly what could not be confirmed (a
    partial answer), for example: "can I get an exemption for sports events"."""
    return [part.strip(" ,.?") for part in question_parts(question) if not search_text(user, part)]


def search(user, question, limit=4):
    """The passages most relevant to the question, best first.
    Each returned passage has .score and .coverage attributes.

    The whole question is searched, then each of its parts; passages
    found for the whole question come first."""
    results = search_text(user, question)
    for part in question_parts(question):
        for passage in search_text(user, part):
            if passage.pk not in {found.pk for found in results}:
                results.append(passage)
    return results[:limit]


def search_text(user, question):
    """search() for one piece of text."""
    terms = list(dict.fromkeys(keywords(question)))[:MAX_QUESTION_TERMS]  # no repeats
    if not terms:
        return []

    # 1. PERMISSION: only passages of documents this user may read.
    permitted = Passage.objects.filter(document__in=Document.objects.visible_to(user))

    # 2. CANDIDATES: of those, the passages containing at least one keyword.
    contains_a_keyword = Q()
    for term in terms:
        contains_a_keyword |= Q(terms__contains=f" {term} ")
    candidates = list(permitted.filter(contains_a_keyword).select_related("document"))
    if not candidates:
        return []

    # 3. SCORE each candidate.
    total_passages = permitted.count()
    word_lists = [passage.terms.split() for passage in candidates]
    average_length = sum(len(words) for words in word_lists) / len(word_lists)
    # In how many passages does each keyword appear? (Every passage that
    # contains a keyword is a candidate, so counting candidates is enough.)
    passages_with = Counter(term for words in word_lists for term in set(words) if term in terms)
    weight = {term: rarity(passages_with[term], total_passages) for term in terms}
    # A question word found in NO permitted passage ("criteria" in "What
    # is the attendance criteria?") is often just the user's own wording.
    # It may weigh at most as much as the rarest word that IS found, so it
    # cannot outweigh the real topic. (A question whose real topic is
    # missing is still refused later, by the answer checks.)
    found = [weight[term] for term in terms if passages_with[term]]
    if found:
        cap = max(found)
        weight = {term: min(value, cap) for term, value in weight.items()}
    total_weight = sum(weight.values())

    results = []
    for passage, words in zip(candidates, word_lists):
        # Threshold part 1: enough of the question's weight must be here.
        present = set(words)
        passage.coverage = sum(weight[term] for term in terms if term in present) / total_weight
        if passage.coverage < MIN_COVERAGE:
            continue
        passage.score = score(words, terms, passages_with, total_passages, average_length)
        results.append(passage)
    if not results:
        return []

    # Threshold part 2: keep only passages close to the best one.
    best = max(passage.score for passage in results)
    results = [passage for passage in results if passage.score >= MIN_SHARE_OF_BEST * best]

    # Order: best first. Passages that match almost equally well (within
    # NEAR_TIE of the best) come in document order instead: a notice or
    # policy usually states its main rule first. So for "attendance
    # rules", "1. Minimum attendance" comes before "7. Contact".
    near_ties = [p for p in results if p.score >= (1 - NEAR_TIE) * best]
    others = [p for p in results if p.score < (1 - NEAR_TIE) * best]
    near_ties.sort(key=lambda passage: (passage.document_id, passage.number))
    others.sort(key=lambda passage: passage.score, reverse=True)
    return near_ties + others


def rarity(found_in, total_passages):
    """How informative a keyword is: high when few passages contain it.
    This is the "IDF" part of BM25. (For a keyword found in no permitted
    passage at all, search_text() limits the weight; see there.)"""
    return math.log(1 + (total_passages - found_in + 0.5) / (found_in + 0.5))


def score(words, terms, passages_with, total_passages, average_length):
    """How well one passage matches the question (the BM25 formula).

    For every keyword of the question found in the passage:
      - a RARE keyword counts more than one found in many passages
        (so "attendance" outweighs "university");
      - a keyword that appears SEVERAL times counts more, but each
        repeat adds less than the one before;
      - a LONG passage gets no advantage just for containing more words.
    """
    counts = Counter(words)
    total = 0.0
    for term in terms:
        times = counts.get(term, 0)
        if times == 0:
            continue
        length = 1 - B + B * len(words) / average_length
        total += rarity(passages_with[term], total_passages) * times * (K1 + 1) / (times + K1 * length)
    return total
