"""Turning text into keywords.

The same function is used on a document's passages (when they are stored)
and on a user's question (when it is asked), so both sides are reduced
to the same form and can be compared word by word.
"""

import re

# Very common words carry no meaning for a search, so they are dropped.
STOPWORDS = {
    "a", "about", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be",
    "been", "but", "by", "can", "could", "did", "do", "does", "for", "from", "get",
    "give", "had", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its",
    "know", "many", "may", "me", "much", "my", "need", "no", "not", "of", "on", "or",
    "our", "please", "shall", "should", "so", "some", "tell", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "to", "us", "want",
    "was", "we", "were", "what", "when", "where", "which", "who", "why", "will",
    "with", "would", "you", "your",
    # Words that only shape a question ("the LAST date", "attendance
    # REQUIRED") and almost never appear in the document that answers it.
    # Kept, they would count as missing topics and hide the right passage.
    "actually", "allowed", "amount", "cost", "currently", "details", "ever",
    "exactly", "generally", "her", "his", "info", "information", "last",
    "mean", "means", "needed", "normally", "once", "possible", "price",
    "rate", "really", "require", "required", "requires", "time", "usually",
    # Words that only connect a question ("what HAPPENS if it is LESS than ...").
    "happen", "happens", "happened", "hapen", "less", "more",
    # Chat shorthand and common misspellings of question words.
    "abt", "hw", "pls", "plz", "ur", "wat", "wen", "whn", "wht", "whats", "wt",
    # Hinglish question words ("fee kitna hai?", "exam kab hai?").
    "batao", "bata", "chahiye", "hai", "hain", "hoga", "kab", "kahan", "kaise",
    "kitna", "kitne", "kitni", "kya", "mein", "mera", "meri", "mujhe",
}

WORD = re.compile(r"[a-z0-9]+")

# Words that mean the same thing in university documents, reduced to one
# form, so a question saying "exam" finds a document saying "examination".
SAME_MEANING = {
    "examination": "exam",
    "examinations": "exam",
    "exams": "exam",
    "sick": "medical",
    "sickness": "medical",
    "ill": "medical",
    "illness": "medical",
    "unwell": "medical",
    # Everyday words students use for what documents call otherwise.
    "visit": "visitor",
    "visits": "visitor",
    "curfew": "gate",
    "criteria": "minimum",
    "criterion": "minimum",
    "requirement": "minimum",
    "requirements": "minimum",
    "submit": "pay",
    "submission": "pay",
    "deposit": "pay",
    "paid": "pay",
    "payment": "pay",
    "payments": "pay",
}


def normalise(word):
    """Reduce a plural to its singular, so "policies" matches "policy"
    and "fees" matches "fee". This is deliberately simple."""
    if word in SAME_MEANING:
        return SAME_MEANING[word]
    # "checking" -> "check", "borrowing" -> "borrow", "timings" -> "tim".
    # Both the documents and the questions are reduced the same way, so
    # they still match each other.
    if word.endswith("ings") and len(word) > 6:
        word = word[:-1]
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        return word[:-1]
    return word


def keywords(text):
    """The meaningful words of a text: lower case, no punctuation,
    no stopwords, plurals reduced.

    keywords("What are the Attendance Policies?") -> ["attendance", "policy"]
    """
    return [
        normalise(word)
        for word in WORD.findall(text.lower())
        if word not in STOPWORDS and len(word) > 1
    ]
