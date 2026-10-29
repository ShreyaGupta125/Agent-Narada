# 11. Questions and answers

[← Installation and operation](10-installation-and-operation.md) · [Contents](README.md)

Short answers to the questions most often asked about the design, with the
chapter that explains each in full.

**What is Agent Narada, in one sentence?**
A local AI chatbot that answers UPES questions only from the approved
documents each user's role may read, shows the sources, and says "couldn't
find" rather than guess. (Chapter 1)

**Why Qwen2.5-1.5B-Instruct and not a bigger model?**
The model only has to read four short passages and write a short answer from
them; it never has to *know* anything about UPES. A 1.5B instruction-tuned
model does that well, runs in about 2 seconds on a laptop GPU, fits in 1.1 GB,
has an open Apache 2.0 licence, and produces reliable JSON. Its mistakes are
caught by Django's checks, so a bigger, slower model is not needed. (Chapter 3.2)

**Why not ChatGPT or another online AI?**
University documents and students' questions would be sent to an outside
company; it needs internet and payment; and the requirement was a local
model from Hugging Face. (Chapter 3.2)

**Did you train or fine-tune the model?**
No. The method is retrieval-augmented generation: for each question the
relevant passages are found and given to the model with the question. New
documents are used as soon as they are approved, with no training. (Chapter 3.1)

**What is quantisation, and does it hurt quality?**
Storing the model's weights with fewer bits. Q4_K_M keeps the sensitive
weights at higher precision and the rest at 4 bits: the file is about 3×
smaller (1.1 GB instead of ~3.1 GB) with quality very close to the
original. (Chapter 3.3)

**Why llama.cpp instead of Python libraries like Transformers, or Ollama?**
One program with no Python AI libraries, GPU support, quantised GGUF models,
a standard API, forced JSON output, and a per-run secret key. Ollama is a
background service that manages its own models; llama-server runs only while
Agent Narada runs, with the exact file we chose. (Chapter 3.4)

**How does it stop the model from making things up ("hallucination")?**
Four layers: (1) the model sees only relevant passages the user may read;
(2) the prompt forbids outside knowledge; (3) the reply is forced into JSON
with a status; (4) Django checks every number, date and name against the
passages, checks that each fact comes from the right row or entry, that the
answer is the right kind, and that 75% of its words are in the passages. A
failed check gives "couldn't find". (Chapter 5.5)

**How does it make sure a student cannot see staff documents?**
Every search starts from a database filter: approved, processed, and ticked
for the user's role. A restricted document is never searched, never given to
the model, never used for spelling correction, and never named. This is
Django code, not a prompt instruction, so no question can get round it.
(Chapter 6.3)

**How does the search work, and why no vector database?**
Keywords (stopwords removed, plurals reduced, same-meaning words joined)
scored with BM25, with a two-part relevance threshold. It is explainable,
exact for numbers, dates and names, needs no second AI model, and works with
the role filter in SQL. Its weakness, very different wording, is reduced by
same-meaning words and spelling correction, and fails safely. (Chapter 4)

**How are spelling mistakes handled?**
Words not found in the user's permitted documents are replaced by the most
similar document word (Python's difflib), under strict rules (same first
letter, similar length, 75–80% similarity). Short forms like "dbms" are
written out; chat shorthand and Hindi question words are ignored. (Chapter 4.4)

**What happens with a follow-up like "and for how many days?"**
The model rewrites it into a full question using only the previous question,
which is then searched with the user's current permissions and checked like
any question. (Chapter 5.3)

**Why are answers always the same for the same question?**
Temperature 0 and llama-server's prompt cache switched off. (Chapter 3.5)

**What are the four cases A–D?**
A: answered with sources. B: partly answered, naming what could not be
confirmed. C: not found, with the exact required wording. D: documents the
role may not read are never used or mentioned. (Chapter 5.6)

**How is chat history kept private, and for how long?**
Each user sees only their own conversations (others get 404; they are not
even on the admin site). Messages are deleted after 7 days by an hourly
scheduled task; users can delete one chat or all. There is no activity log.
(Chapter 7.2)

**How was it tested?**
334 automated tests (including every role against every page and API, and a
complete workflow), plus live tests with the real model: 42 sample questions,
36 scope messages, 50 everyday phrasings and 28 misspelled questions, with
0 wrong answers in every reviewed set. (Chapter 9)

**What are its limitations?**
Some questions get a safe "couldn't find" although the answer is in a
document (the small model reads a neighbouring row, or the wording is very
different); English answers only; scanned PDFs cannot be read; it is set up
for one computer, not yet for a network. (Chapter 9.4)

**What would you improve next?**
A larger model on stronger hardware, an optional meaning-based search, OCR
for scanned PDFs, Hindi answers, and a production deployment with HTTPS.
(Chapter 9.5)
