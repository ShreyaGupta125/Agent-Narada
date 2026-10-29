<div align="center">

<img src="frontend/img/Narada_logo.jpeg" alt="Agent Narada logo" width="120">

# Agent Narada

**A private, evidence-grounded AI assistant for UPES university documents**

Students and staff ask questions in plain language. Agent Narada answers only from the
official documents their role is allowed to read, cites the exact source, and says
so when the answer isn't there instead of guessing.

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2_LTS-092E20?logo=django&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-database-003B57?logo=sqlite&logoColor=white)
![llama.cpp](https://img.shields.io/badge/llama.cpp-local_LLM-black)
![Qwen](https://img.shields.io/badge/Qwen2.5--1.5B-Instruct-6E44FF)
![Tests](https://img.shields.io/badge/tests-334_passing-brightgreen)

</div>

<p align="center">
  <img src="docs/screenshots/03-answer-with-sources.png" alt="A student's question answered with its source" width="85%">
</p>

---

## Table of contents

- [Why Agent Narada](#why-agent-narada)
- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Roles and permissions](#roles-and-permissions)
- [Screenshots](#screenshots)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Documentation](#documentation)
- [Limitations](#limitations)

---

## Why Agent Narada

University information is spread across notices, handbooks and policy PDFs, and different
people are allowed to see different parts of it. A general chatbot can make up answers or
leak restricted information. Agent Narada is built to avoid both:

- **Runs fully offline.** The language model runs on the local machine through llama.cpp.
  No question, document or answer is ever sent to the internet.
- **Permission-first.** Django filters documents by the user's role *before* anything reaches
  the model. The model only writes the answer; it never decides who may see what.
- **Evidence-grounded.** Every answer is checked against the source passages, and an answer
  that can't be verified is replaced with an honest "couldn't find" reply.

## Features

| Area | What it does |
|------|--------------|
| **Chat** | Natural-language questions, follow-up questions, small talk, and a polite refusal for anything outside UPES |
| **Cited answers** | Each answer names the document, section and PDF page it came from |
| **Partial answers** | When only part of a question is covered, the answer says which part it couldn't confirm |
| **Typo tolerance** | Corrects misspellings using the documents' own words (`attendence` → `attendance`), expands short forms (`hod`, `sem`), and understands chat shorthand and Hinglish (`kitna`, `kab`) |
| **Document ingestion** | Reads PDF, DOCX, DOC, ODT and TXT, keeping headings, paragraphs and table rows intact |
| **Approval workflow** | Admin uploads start as *Pending* until a Super Admin approves or rejects them (with a reason) |
| **Role-based access** | Each document is marked readable by students, teaching staff and/or non-teaching staff. Readers can be changed later without re-uploading |
| **Private chat history** | Each user sees only their own chats. Messages are kept for 7 days and deleted automatically every hour. Users can delete one chat or all of them |
| **Security** | Login lockout after 5 failed attempts, secret key kept out of the code, and the model server locked with a new random key on every run |

## How it works

```text
 Browser (HTML, CSS, JavaScript)
        │  login, question, history, documents     (JSON over HTTP, localhost only)
        ▼
 Django + Django REST Framework ── SQLite (users, documents, passages, chats)
        │
        │  1. Small talk, off-topic or follow-up?        chat/scope.py
        │  2. Correct spelling mistakes                  documents/spelling.py
        │  3. Find passages this user's role may read    documents/retrieval.py  (BM25)
        │  4. Ask the model for a JSON answer            chat/grounding.py, chat/llm.py
        │  5. Verify the answer against the passages     chat/grounding.py
        ▼
 llama-server (llama.cpp) + Qwen2.5-1.5B-Instruct (GGUF, 4-bit)   127.0.0.1:8080, GPU
```

**Retrieval.** Uploaded documents are split into section-aware passages of about 120 words
and indexed by keyword. A question is matched with the **BM25** ranking formula, then passed
through a two-part relevance threshold so that weak matches are dropped. No vector database is
needed.

**Answering.** The model must reply in a fixed JSON shape (`answer`, `evidence`, `status`,
`missing`), enforced by llama-server. Django then checks that every number, date and weekday
in the answer appears in the passages, that the fact sits in a sentence about what was asked,
that the answer is the right kind (an amount for a fee question, a date for "when"), and that most
of its words come from the sources. If any check fails, the user gets the "couldn't find" reply
rather than an unverified answer. Temperature is 0, so the same question always gets the same
answer.

## Tech stack

| Layer | Technology |
|-------|------------|
| Frontend | HTML, CSS, vanilla JavaScript (no framework) |
| Backend | Python 3.13, Django 5.2 LTS, Django REST Framework 3.18 |
| Database | SQLite |
| Document parsing | `pypdf` for PDF, `olefile` for legacy `.doc`, the standard library for `.docx` / `.odt` / `.txt` |
| Language model | [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF), GGUF Q4_K_M (1.1 GB, Apache 2.0) |
| Model runtime | [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server`, build b11588, CUDA 12.4 |
| Search | Keyword index + BM25 ranking with role filtering |

## Getting started

### Requirements

- Windows 10/11 (64-bit)
- Python 3.10 or newer (developed on 3.13)
- An NVIDIA GPU with about 2 GB of free memory is recommended. A CPU build of llama.cpp also works, but more slowly.
- About 3 GB of free disk space

### 1. Clone the repository

```powershell
git clone https://github.com/ShreyaGupta125/NARADA.git
cd NARADA
```

### 2. Download the model and runtime

These files are too large for Git and are not included in the repository. Download them from the
official sources and put them in the folders shown:

| File | Source | Destination |
|------|--------|-------------|
| `qwen2.5-1.5b-instruct-q4_k_m.gguf` | [Hugging Face: Qwen/Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) | `models\` |
| `llama-b11588-bin-win-cuda-12.4-x64.zip` | [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) | unzip into `tools\llama.cpp\` |
| `cudart-llama-bin-win-cuda-12.4-x64.zip` | same release page | unzip into `tools\llama.cpp\` |

<details>
<summary>SHA-256 checksums</summary>

| File | SHA-256 |
|------|---------|
| `qwen2.5-1.5b-instruct-q4_k_m.gguf` | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` |
| `llama-b11588-bin-win-cuda-12.4-x64.zip` | `b332d03139fbb8453c1ee7dd89321f10186aedaa35b9a2e326f6569e7dcaa04f` |
| `cudart-llama-bin-win-cuda-12.4-x64.zip` | `8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6` |

Verify a file in PowerShell:

```powershell
(Get-FileHash models\qwen2.5-1.5b-instruct-q4_k_m.gguf -Algorithm SHA256).Hash
```

</details>

### 3. Run it

```powershell
python main.py
```

`main.py` handles everything, and every step is safe to repeat:

1. Checks the Python version
2. Creates the `.venv` virtual environment and installs `requirements.txt`
3. Creates or updates the database tables
4. Asks you to create a Super Admin account on the first run
5. Starts `llama-server` with the model and a new random API key
6. Starts Django and opens **http://127.0.0.1:8000**

Press **Ctrl+C** to stop both servers. Use `python main.py --no-browser` to start without opening a browser.

### 4. Optional: schedule the hourly chat cleanup

```powershell
powershell -ExecutionPolicy Bypass -File schedule_chat_cleanup.ps1
```

This registers a Windows Task Scheduler job that deletes chat messages older than 7 days.

### 5. Try it with sample data

`sample_documents/` contains 11 **fictional** UPES documents (attendance notice, exam date sheet,
fee structure, hostel rules and more). [`TESTING_GUIDE.txt`](sample_documents/TESTING_GUIDE.txt)
lists which roles to upload each one for, along with test questions and their expected answers.
Delete the sample documents before any real use.

<details>
<summary>Manual setup (without <code>main.py</code>)</summary>

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python backend\manage.py migrate
python backend\manage.py createsuperuser
tools\llama.cpp\llama-server.exe -m models\qwen2.5-1.5b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8080 -ngl 99 -c 4096 --api-key <secret>
$env:NARADA_LLM_API_KEY = "<same secret>"
python backend\manage.py runserver 127.0.0.1:8000
```

</details>

## Roles and permissions

There is no public signup. The Super Admin creates every account and assigns its role.

| Permission | Super Admin | Admin | Student / Teaching / Non-Teaching Staff |
|------------|:-----------:|:-----:|:---------------------------------------:|
| Use the chatbot | – | – | ✅ |
| View and delete own chat history | – | – | ✅ |
| Upload and manage documents | ✅ | ✅ (own only) | – |
| Approve or reject documents | ✅ | – | – |
| Manage users | ✅ | – | – |
| Dashboard | Super Admin | Admin | – |

The matrix is defined in [`backend/accounts/permissions.py`](backend/accounts/permissions.py)
and enforced by Django on every request. Hiding a button in the UI is never the security mechanism.

## Screenshots

| Chat | Spelling mistakes understood |
|------|------------------------------|
| ![Chat welcome](docs/screenshots/02-chat-welcome.png) | ![Spelling mistakes](docs/screenshots/04-spelling-mistakes.png) |
| **Not found / role limit** | **Partial answer** |
| ![Not found](docs/screenshots/07-not-found-and-role-limit.png) | ![Partial answer](docs/screenshots/08-partial-answer.png) |
| **Super Admin dashboard** | **Document approval** |
| ![Super Admin dashboard](docs/screenshots/13-super-admin-dashboard.png) | ![Document approval](docs/screenshots/15-document-approval-pending.png) |

More screens for every role are in the [user guide](docs/08-user-guide.md).

## Project structure

```text
NARADA/
├── main.py                     One-command launcher (model server + Django)
├── requirements.txt            Pinned Python dependencies
├── schedule_chat_cleanup.ps1   Registers the hourly chat-cleanup task
├── frontend/                   HTML pages, CSS and JavaScript
├── backend/
│   ├── config/                 Settings, URL routes, page views
│   ├── accounts/               Users, roles, permission matrix, login
│   ├── documents/              Upload, approval, extraction, passages, search, spelling
│   ├── chat/                   Chat API, scope control, prompt, answer checks, history
│   └── dashboard/              Dashboard statistics
├── sample_documents/           Fictional test documents and TESTING_GUIDE.txt
├── docs/                       Technical documentation (11 chapters) and screenshots
├── models/                     Qwen GGUF model (downloaded separately)
└── tools/llama.cpp/            llama-server and its libraries (downloaded separately)
```

## Testing

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py test
```

The suite has **334 automated tests** covering every role against every page and API, document
ingestion for each file type, retrieval, spelling correction, every answer-verification check,
chat privacy and 7-day retention, plus a complete workflow from an Admin's upload to the automatic
cleanup. The tests use a fake model, so `llama-server` doesn't need to be running.

Live results with the real model on the sample documents:

| Test set | Result |
|----------|--------|
| 42 document questions | **0 wrong answers**; 28 of 31 answerable questions fully answered; 11 of 11 correct "not found" replies |
| 36 scope and follow-up messages | 7/7 small talk, 8/8 off-topic questions refused, 0 wrong follow-ups |
| 28 misspelled questions | 25 answered correctly, 3 safely "couldn't find", 0 wrong |
| 45 everyday phrasings | Right section found for 44 |

## Documentation

Full technical documentation is in [`docs/`](docs/README.md):

1. [Introduction and requirements](docs/01-introduction.md)
2. [System architecture](docs/02-architecture.md)
3. [The language model](docs/03-language-model.md)
4. [Document ingestion and retrieval](docs/04-ingestion-and-retrieval.md)
5. [Answering with evidence](docs/05-answering-with-evidence.md)
6. [Roles, permissions and security](docs/06-roles-and-security.md)
7. [Data model and API](docs/07-data-model-and-api.md)
8. [User guide with screenshots](docs/08-user-guide.md)
9. [Testing and results](docs/09-testing-and-results.md)
10. [Installation and operation](docs/10-installation-and-operation.md)
11. [Questions and answers](docs/11-questions-and-answers.md)

## Limitations

- **Keyword search.** A question worded very differently from the document can miss it.
- **Text-based files only.** Scanned PDFs (images of text) are refused because no text can be read.
- **Local use only.** Django runs with `DEBUG` on and binds to `127.0.0.1`. Putting it on a network
  would need a production web server, HTTPS and `DEBUG` turned off.
- **Small model.** Qwen2.5-1.5B is fast on a laptop GPU. The verification layer catches the
  mistakes it makes, but it sometimes answers "couldn't find" where a larger model would succeed.

---

<div align="center">

Built as an academic project at **UPES**, Dehradun.

The sample documents are fictional and are not official UPES information.

</div>
