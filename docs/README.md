# Agent Narada — Technical Documentation

**Agent Narada** is an AI chatbot for UPES university. Students, teaching
staff and non-teaching staff ask questions in ordinary language. Agent Narada
answers **only** from the official university documents their role may read,
and names the document, section and page of every answer. If the
documents do not contain the answer, it says so instead of guessing.

Everything runs on one computer. The language model (**Qwen2.5-1.5B-Instruct**,
from Hugging Face) runs locally through **llama.cpp**, so no question,
document or answer is ever sent to the internet.

![A student's question answered with its source](screenshots/03-answer-with-sources.png)

---

## Chapters

| # | Chapter | What it explains |
|---|---------|------------------|
| 1 | [Introduction and requirements](01-introduction.md) | The problem, the objectives, the requirements and the scope |
| 2 | [System architecture](02-architecture.md) | The parts of the system, how a request flows, technology choices and why |
| 3 | [The language model](03-language-model.md) | **Why Qwen2.5-1.5B-Instruct**, why llama.cpp, quantisation, settings, speed |
| 4 | [Document ingestion and retrieval](04-ingestion-and-retrieval.md) | How documents are read, split, indexed and searched (BM25), spelling correction |
| 5 | [Answering with evidence](05-answering-with-evidence.md) | The full answering method: scope control, the prompt, JSON output, Django's checks, Cases A–D |
| 6 | [Roles, permissions and security](06-roles-and-security.md) | The five roles, the permission matrix, document access, the approval workflow, security measures |
| 7 | [Data model and API](07-data-model-and-api.md) | Database tables, chat history and 7-day retention, every API endpoint |
| 8 | [User guide with screenshots](08-user-guide.md) | Every screen, for every role |
| 9 | [Testing and results](09-testing-and-results.md) | 334 automated tests, live tests with the real model, measured results, known limitations |
| 10 | [Installation and operation](10-installation-and-operation.md) | Requirements, one-command start, maintenance commands, troubleshooting |
| 11 | [Questions and answers](11-questions-and-answers.md) | Short answers to the questions most often asked about the design |

---

## The system in one picture

```
 Browser (HTML, CSS, JavaScript)
        │  login, question, history, documents        (JSON over HTTP, on this computer)
        ▼
 Django + Django REST Framework  ── SQLite database (users, documents, passages, chats)
        │
        │  1. Is it small talk / off-topic / a follow-up?      (chat/scope.py)
        │  2. Correct spelling mistakes                        (documents/spelling.py)
        │  3. Find passages THIS USER's role may read (BM25)   (documents/retrieval.py)
        │  4. Ask the model for a JSON answer                  (chat/grounding.py, chat/llm.py)
        │  5. Check the answer against the passages            (chat/grounding.py)
        ▼
 llama-server.exe (llama.cpp) + Qwen2.5-1.5B-Instruct (GGUF, 4-bit)  on 127.0.0.1:8080, GPU
```

## Key facts

| | |
|---|---|
| Model | Qwen2.5-1.5B-Instruct, GGUF, Q4_K_M quantisation (1.12 GB file) |
| Model runtime | llama.cpp `llama-server.exe`, build 11588, CUDA 12.4, all layers on the GPU |
| Backend | Python 3.13, Django 5.2.17, Django REST Framework 3.18.1, SQLite |
| Frontend | HTML, CSS and plain JavaScript (no framework) |
| Document types | PDF, Word (.docx and .doc), OpenDocument (.odt), plain text (.txt) |
| Search | Keyword search with the BM25 formula, a relevance threshold and role filtering (no vector database) |
| Roles | Super Admin, Admin, Student, Teaching Staff, Non-Teaching Staff |
| Chat history | Private to each user, kept 7 days, deleted automatically every hour; users can delete one chat or all |
| Speed | About 2 seconds per answer on an RTX 4050 Laptop GPU (the model writes about 60 tokens, or word pieces, per second) |
| Tests | 334 automated tests, all passing; live tests with the real model: 0 wrong answers in the reviewed sets |

## Where things are in the code

```
NARADA/
├── main.py                     one-command launcher (starts the model and Django)
├── requirements.txt            Python packages, exact versions
├── schedule_chat_cleanup.ps1   creates the hourly "delete old chats" task
├── models/                     the Qwen GGUF model file
├── tools/llama.cpp/            llama-server.exe and its libraries
├── frontend/                   pages (HTML), styles (CSS), behaviour (JavaScript)
├── backend/
│   ├── config/                 settings, URL routes, page views
│   ├── accounts/               users, roles, permission matrix, login, user management
│   ├── documents/              upload, approval, text extraction, passages, search, spelling
│   ├── chat/                   chat API, scope control, prompt, answer checks, history
│   └── dashboard/              numbers for the two dashboards
├── sample_documents/           11 fictional UPES documents for testing, and TESTING_GUIDE.txt
└── docs/                       this documentation and its screenshots
```
