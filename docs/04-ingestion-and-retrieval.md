# 4. Document ingestion and retrieval

[← The language model](03-language-model.md) · [Contents](README.md) · [Next: Answering with evidence →](05-answering-with-evidence.md)

This chapter explains how an uploaded file becomes searchable
(**ingestion**), and how the right passages are found for a question
(**retrieval**).

```
UPLOAD (once per document)
  file ──► blocks ──► passages (~120 words) ──► keywords ──► database
           headings,   one section each,         lower case,
           paragraphs, page number kept          no common words,
           tables                                plurals reduced

QUESTION (every time)
  question ──► spelling corrected ──► keywords ──► passages THIS ROLE may read
           ──► coverage threshold ──► BM25 score ──► keep close to best ──► top 4
```

## 4.1 Reading the file (documents/extraction.py)

The text is read **with its structure**, as a list of *blocks*: a heading, a
paragraph or a table.

| Type | How it is read | Headings come from |
|------|----------------|--------------------|
| `.pdf` | `pypdf`, page by page, so every block knows its **page number** | text rules (below) |
| `.txt` | Python's own decoding (UTF-8, an invisible "BOM" mark removed) | text rules |
| `.docx` | A zip of XML files, read with Python's `zipfile` and `xml` | Word's heading styles |
| `.odt` | Also a zip of XML files, read the same way | the document's heading tags |
| `.doc` | Word 97-2003: `olefile` opens the container, our code reads the text pieces | text rules |

**Text rules for headings** (PDF, TXT, DOC): a line of at most 10 words that
does not end like a sentence is a heading if it is ALL CAPITALS, numbered
("2. Fees", "IV. Leave", "Section 4"), or ends with a colon.

**Tables** are kept row by row, cells separated by `|`, so a row such as
`Gold | 95% and above | 50%` keeps its numbers together.

**Failures are refused, with the reason.** If no text can be read, the
upload fails and nothing is kept:

| Problem | Message shown to the administrator |
|---------|------------------------------------|
| Scanned PDF (a picture of text) | "No text could be read from this file. A scanned document (a picture of text) cannot be read; upload a version with real text." |
| Password-protected PDF | "The PDF is protected with a password. Upload a copy without one." |
| Damaged or fake file | e.g. "This file is not a real PDF." (the first bytes are checked, not just the name) |
| Larger than 10 MB | "The file is larger than 10 MB." |

A `.docx`/`.odt` is a zip file; a small zip can unpack into an enormous file
(a "zip bomb"). The XML read from one is therefore limited to 50 MB.

## 4.2 Splitting into passages (documents/processing.py)

A whole document is too long to give to a small model, so the text is cut
into **passages** of about **120 words**:

- A **heading starts a new passage** and becomes the passage's **section**
  (shown in the sources, e.g. "3. Condonation of attendance shortage").
- Paragraphs, table rows and list items are added **whole** until the
  passage is full. A rule, a row or a directory entry is never cut in half.
  Only a single paragraph longer than 120 words is cut, with **20 words
  repeated** at the cut so a sentence at the edge is whole in one of them.
- A passage **never spans two PDF pages**, so its page number is exact.
- The section heading is repeated at the top of each passage's text, so both
  the search and the model see it.
- Paragraphs inside a passage are separated by a blank line, so each one
  (a rule, a directory entry) can be recognised again by the answer checks.

Why 120 words: small enough for a 1.5B model to read carefully (four
passages fit easily in its context), large enough to keep a rule together
with its conditions.

The document is marked **processed** (`processed_at`) only **after every
passage has been stored**, inside one database transaction. A document that
is not processed is never searched and cannot be approved.

## 4.3 Keywords (documents/text.py)

The **same** function turns both a passage and a question into keywords, so
both sides can be compared word by word:

1. lower case, punctuation removed;
2. **stopwords** removed: common words ("the", "is", "what"), words that
   only shape a question ("required", "last", "exactly", "once"), chat
   shorthand ("wat", "pls", "abt", "ur"), and Hindi question words typed in
   English ("kitna", "hai", "kab", "batao", "chahiye");
3. **plurals and "-ing" reduced**: "policies" → "policy", "fees" → "fee",
   "borrowing" → "borrow";
4. **same-meaning words** reduced to one form:

| Written by the user | Treated as |
|---------------------|-----------|
| examination, examinations, exams | exam |
| sick, sickness, ill, illness, unwell | medical |
| visit, visits | visitor |
| curfew | gate |
| criteria, criterion, requirement(s) | minimum |
| submit, submission, deposit, paid, payment(s) | pay |

Example: `keywords("What are the Attendance Policies?")` → `["attendance", "policy"]`.

Each passage's keywords are stored once, at upload, in its `terms` column
(with the document title's keywords added, so "fee structure" finds the
passages of the "Fee Structure" document).

## 4.4 Correcting spelling mistakes (documents/spelling.py)

The search matches words exactly, so "attendence" would never find
"attendance". Before searching, each word of the question is checked:

1. **Short forms are written out**: dbms → database management systems,
   hod → head of department, cse → computer science, sem → semester,
   vc → vice chancellor, ds → data structures, prof → professor, lib → library …
2. A word that appears in **no document the user may read** is compared with
   the words that do appear there, using Python's `difflib.SequenceMatcher`
   (similarity from 0 to 1). It is replaced by the closest word if:
   - the word has **4 or more letters**;
   - the **first letter is the same** (typing mistakes rarely change it);
   - the lengths differ by **at most 2 letters**;
   - the similarity is at least **0.8** (0.75 for words of 4–5 letters);
   - it is not a common word, a short form or a word with a known meaning,
     and not just another form of a known word ("teach" for "teaching").
3. If two words are equally close ("fess": "fees" or "fest"?), the one used
   more often in the documents wins.
4. Only if no document word is close enough are the scope word lists tried
   ("crikcet" → "cricket", so it is still recognised as off-topic).

**Privacy:** the vocabulary is built only from the documents **this user's
role may read**, so a correction can never hint at a restricted document's
contents.

| The user typed | Searched as |
|----------------|-------------|
| wat is attendence criteria for studnts | wat is **attendance** criteria for **students** (then "wat" and "is" are stopwords; "criteria" means "minimum") |
| condonaton fee kitna hai | **condonation** fee kitna hai ("kitna", "hai" are stopwords) |
| hostal gate closing time | **hostel** gate closing time |
| salry of assistent professor | **salary** of **assistant** professor |
| who teach dbms | who teach **database management systems** |

The user's own words are what is saved in their chat history; only the
search uses the corrected question.

## 4.5 Retrieval (documents/retrieval.py)

### Step 1 — Permission first

The search starts from `Document.objects.visible_to(user)`: only documents
that are **approved**, **processed**, and open to the **user's role**. A
passage of any other document is never even read. Nothing the user types can
change this filter.

### Step 2 — Candidates

Passages containing at least one of the question's keywords (at most 20
keywords are used from a very long question).

### Step 3 — Relevance threshold, part 1: coverage

Every keyword gets a **weight**: rare words weigh more ("overtime" appears
in few passages; "staff" in many). A passage must contain at least **45% of
the question's total keyword weight**. A passage sharing only the common
words of a question is dropped.

A word found in **no** permitted passage ("criteria" in "attendance
criteria?") is often only the user's own wording. Its weight is capped at
the weight of the rarest word that *is* found, so it cannot hide the real
topic.

### Step 4 — Scoring with BM25

Each remaining passage is scored with **BM25**, the standard ranking
formula of search engines:

```
score(passage) =  sum, over the question's words found in the passage, of

                         IDF(word) × times × (k1 + 1)
              ─────────────────────────────────────────────────────
               times + k1 × (1 − b + b × length / average length)

IDF(word) = ln( 1 + (N − n + 0.5) / (n + 0.5) )

  N      = number of passages the user may read
  n      = how many of them contain the word
  times  = how often the word appears in this passage
  length = number of keywords in this passage
  k1 = 1.5,  b = 0.75   (the standard values)
```

In plain words:

- a **rare** word counts more than a common one (IDF);
- a word appearing **several times** counts more, but each repeat adds less (k1);
- a **long** passage gets no advantage just for having more words (b).

### Step 5 — Relevance threshold, part 2: close to the best

Only passages scoring at least **60% of the best passage's score** are kept.
A weak extra match is not given to the model (or shown as a source) just
because there was room for it.

Passages within **15%** of the best are treated as equally good and kept **in
document order**, because a notice usually states its main rule first ("1.
Minimum attendance" before "7. Contact").

### Step 6 — Several-part questions

"What is the late fee, and is there a discount for early payment?" is also
searched part by part (split at "and", ";", "?"). The best **4** passages
overall are given to the model. A part for which **no** permitted passage is
found is remembered as **not covered** and named in the answer (Case B,
chapter 5).

## 4.6 A worked example

Question by a **student**: "What is the minimum attendance required?"

| Step | Result |
|------|--------|
| Keywords | `minimum`, `attendance` ("what", "is", "the" are stopwords; "required" only shapes the question) |
| Permission | passages of the 9 documents open to students |
| Coverage | the passages of the attendance notice contain both words → kept |
| BM25 | "1. Minimum attendance" scores highest (both words, short passage) |
| Kept | that passage, plus close matches |
| Answer | "Every student must attend at least 75% of the classes in each course, counted separately for lectures, tutorials and labs." — Source: attendance notice (1. Minimum attendance) |

The same question by a **non-teaching staff** member finds **no** passage
(the attendance notice is not open to that role), so the reply is the
"couldn't find" message without asking the model (Case C/D).

## 4.7 Why keyword search and not a vector database

Many RAG systems turn text into "embeddings" (lists of numbers) with a second
AI model and search a vector database by meaning. Agent Narada does not, by
requirement (N2) and for these reasons:

| | BM25 keyword search (used) | Embeddings + vector database |
|---|---|---|
| Extra software | none (Python + SQLite) | an embedding model and a vector store |
| Explainable | yes: every score can be calculated by hand | hard: similarity of 384+ numbers |
| Numbers, dates, names, course codes | matched exactly | often blurred ("Rs 2,000" ≈ "Rs 20,000") |
| Role filter | one SQL filter before the search | must be kept in sync in a second store |
| Different wording | weaker; helped by same-meaning words, stopwords and spelling correction | stronger |

The weakness of keyword search (a question worded very differently from the
document can miss it) is reduced by sections 4.3 and 4.4, and its failure
mode is **safe**: a miss gives "couldn't find", never a wrong answer.

## 4.8 Re-reading documents

If the way documents are read is improved, every stored document can be read
again from its original file:

```
python backend\manage.py reprocess_documents
```

This was done on 14 October 2026 after the spelling and keyword changes
(11 documents processed, 0 failed).
