# 2. System architecture

[← Introduction](01-introduction.md) · [Contents](README.md) · [Next: The language model →](03-language-model.md)

## 2.1 The three programs

Agent Narada is made of three programs that run on the same computer.
`main.py` starts the second and third.

```
┌────────────────────────────────────────────────────────────────────────┐
│  1. BROWSER                                                            │
│     frontend/*.html  pages        frontend/style.css  look             │
│     frontend/*.js    behaviour: sends JSON requests, shows replies     │
└───────────────┬────────────────────────────────────────────────────────┘
                │ HTTP on 127.0.0.1:8000  (session cookie + CSRF token)
┌───────────────▼────────────────────────────────────────────────────────┐
│  2. DJANGO SERVER  (Python)                                            │
│     config/     settings, URL routes, sends each page only to its roles│
│     accounts/   users, 5 roles, permission matrix, login, lockout      │
│     documents/  upload, approval, text extraction, passages, search    │
│     chat/       chat API, scope, prompt, answer checks, history        │
│     dashboard/  numbers for the dashboards                             │
│                         │                                              │
│                         ▼                                              │
│     SQLite database  backend/db.sqlite3                                │
│     uploaded files   backend/media/documents/<year>/<month>/           │
└───────────────┬────────────────────────────────────────────────────────┘
                │ HTTP on 127.0.0.1:8080, POST /v1/chat/completions
                │ with a secret key that changes on every start
┌───────────────▼────────────────────────────────────────────────────────┐
│  3. LANGUAGE MODEL SERVER                                              │
│     tools/llama.cpp/llama-server.exe                                   │
│     models/qwen2.5-1.5b-instruct-q4_k_m.gguf  (on the GPU)             │
└────────────────────────────────────────────────────────────────────────┘
```

Both servers listen on `127.0.0.1` ("this computer only"), so nothing is
reachable from the network.

## 2.2 Responsibilities: who decides what

A central design decision: **Django decides, the model only writes.**

| Decision | Made by | Why |
|----------|---------|-----|
| Who the user is, what their role may do | Django (`accounts/permissions.py`) | Security must not depend on a prompt |
| Which documents a user may read | Django (`Document.objects.visible_to`) | A database filter cannot be talked out of |
| Whether a message is small talk / off-topic | Django rules first; the model only for unclear cases, with a forced one-word reply | Predictable and testable |
| Which passages are relevant | Django (BM25 search) | Explainable, exact for numbers and names |
| The wording of the answer | **The model** | This is what a language model is good at |
| Whether the answer is supported by the documents | Django (`chat/grounding.py`) | A small model can be wrong; the program checks |
| The sources shown | Django | Only passages that really contain the answer |

## 2.3 What happens when a question is asked

Example: a student types "wat is attendence criteria for studnts".

```
Browser (script.js)
  POST /api/chat/  {"question": "...", "conversation_id": 12}     + session cookie + CSRF token
        │
Django  ChatView.post()                                           chat/views.py
  ├─ is the user logged in and allowed to chat? (role check)      CanChat permission
  ├─ is the question non-empty and under 1,000 characters?
  ├─ does conversation 12 belong to THIS user, within 7 days?
  └─ build_answer()
       1. small talk?            no                                chat/scope.py
       2. remove a greeting      ("Hi, what is..." → "what is...")
       3. correct spelling       → "wat is attendance criteria for students"   documents/spelling.py
       4. follow-up?             no (otherwise rewritten into a full question)
       5. clearly off-topic?     no
       6. search                 passages of APPROVED documents open to STUDENTS,
                                 scored with BM25, threshold applied           documents/retrieval.py
       7. ask the model          rules + 4 numbered passages + question,
                                 reply forced into JSON                        chat/grounding.py, chat/llm.py
       8. check the reply        numbers, dates, names, kind of answer,
                                 word support, sources                         chat/grounding.py
  ├─ save the question and answer (one transaction)               chat/models.py
  └─ reply {"answer": "...", "sources": [...], "conversation_id": 12}
        │
Browser shows the answer and "Sources: attendence notice (1. Minimum attendance)"
```

The details of steps 1–8 are in chapters 4 and 5.

## 2.4 How pages are protected

The HTML pages are served by Django (not opened as files), so each page is
sent **only to the roles allowed to see it**. A student who types
`/users/` in the address bar is sent back to the chat page. The pages'
JavaScript then calls the JSON API, which checks the role **again** on every
request. Hiding a button in the page is only for convenience; the server is
the real gate.

| Page | Address | Roles |
|------|---------|-------|
| Login | `/login/` | everyone |
| Chat | `/` | Student, Teaching Staff, Non-Teaching Staff |
| Super Admin dashboard | `/dashboard/super-admin/` | Super Admin |
| Admin dashboard | `/dashboard/admin/` | Admin |
| User management | `/users/` | Super Admin |
| Documents (Document Approval / My Documents) | `/documents/` | Super Admin, Admin |
| Upload document | `/documents/upload/` | Super Admin, Admin |
| Django's own admin site | `/admin/` | Super Admin |

After login, Django sends each role to its own start page (`ROLE_HOME` in
`accounts/permissions.py`): Super Admin and Admin to their dashboards, the
three chatbot roles to the chat page.

## 2.5 Technology choices and the reasons

| Technology | Used for | Why this and not something else |
|------------|----------|----------------------------------|
| **Python 3.13** | All server code and the launcher | One language for web, text processing and tests; widely taught |
| **Django 5.2** | Web framework | Comes with user accounts, password hashing, sessions, CSRF protection, database models, migrations, an admin site and a test framework. These would otherwise have to be written by hand, with risk of security mistakes. |
| **Django REST Framework 3.18** | JSON API | Clean API views with permission classes (`permission_classes = [CanChat]`) and input validation (serializers) |
| **SQLite** | Database | A single file, no database server to install or run; enough for one university department's documents and users. Django can switch to PostgreSQL by changing one setting. |
| **HTML, CSS, plain JavaScript** | Frontend | No build step, no framework to learn; every line can be explained |
| **llama.cpp (llama-server.exe)** | Runs the model | One program, no Python AI libraries, uses the GPU, supports quantised models and forced JSON output (chapter 3) |
| **Qwen2.5-1.5B-Instruct** | Writes the answers | Small, fast, good at following instructions and producing JSON, open licence (chapter 3) |
| **pypdf** | Reading PDF files | Pure Python, keeps page numbers |
| **olefile** | Reading old Word (.doc) files | Opens the Word 97-2003 container; the text is then read by our own code |
| Python's own `zipfile` + `xml` | Reading .docx and .odt | These formats are zip files of XML, so no extra package is needed |
| **BM25 keyword search** | Finding passages | Explainable, exact for numbers and names, works directly with the role filter in SQL, needs no second AI model (chapter 4.7) |

Not used, on purpose (requirement N2): Docker, WSL, a vector database,
React, Ollama, any cloud AI service.

## 2.6 The frontend files

| File | What it does |
|------|--------------|
| `api.js` | `apiRequest()`: every call to the server, with the CSRF token; turns replies into `{ok, status, data}` |
| `header.js` | Asks the server who is logged in (`/api/auth/me/`), fills the name, role chip and side menu, logout |
| `login.js` | Login form; after login goes to the page the server names for the role |
| `script.js` | Chat page: send a question, show answer and sources, history list, new chat, delete one chat, clear all |
| `dashboard.js` | Dashboard numbers |
| `users.js` | User management (Super Admin) |
| `documents.js` | Document list, filters, approve, reject, delete, change readers |
| `upload.js` | Upload form with the "who will / will not get answers" confirmation |
| `style.css` | The whole look, including the mobile layout |

Every text that comes from the server is put into the page with
`textContent`, never as HTML, so a document or a question containing
`<script>` cannot run code in the browser.

CSS and JavaScript addresses end with `?v=<number>`, where the number is the
time of the newest frontend file (`config/context_processors.py`). After a
change, the browser loads the new file instead of an old cached copy.
