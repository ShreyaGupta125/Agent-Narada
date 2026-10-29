==================================================
AGENT NARADA
Smart University AI Assistant
==================================================

Agent Narada is an AI-powered university knowledge and communication
assistant. Users ask questions in natural language and receive answers
based on official university documents. What a user can see depends on
their role.

The whole system runs on one local machine. No cloud LLM is used.


--------------------------------------------------
ARCHITECTURE
--------------------------------------------------

  User
    |
  Frontend (HTML + CSS + JavaScript)
    |
  Django backend
    - Authentication
    - User roles and permissions
    - Chat API
    - Document management
    |
  SQLite database + university documents
    |   (only the passages the user's role may read)
  llama-server (llama.cpp) running Qwen2.5-1.5B-Instruct
    |
  Django backend -> Frontend -> User

The frontend talks only to Django. It never talks directly to the
database, the document storage, or the language model.

Permissions are checked by Django BEFORE any information is given to
the language model. The model only writes the answer; it never decides
who is allowed to see what.


--------------------------------------------------
TECHNOLOGY STACK
--------------------------------------------------

  Frontend     : HTML, CSS, vanilla JavaScript
  Backend      : Django 5.2 (LTS), Django REST Framework
  Documents    : PDF (pypdf), Word .docx and OpenDocument .odt (Python's own
                 zipfile and xml), Word 97-2003 .doc (olefile), TXT
  Database     : SQLite
  LLM          : Qwen2.5-1.5B-Instruct, file qwen2.5-1.5b-instruct-q4_k_m.gguf
                 (1.1 GB), from huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
                 License: Apache 2.0
  LLM runtime  : llama.cpp's llama-server.exe (build b11588, CUDA 12.4),
                 from github.com/ggml-org/llama.cpp/releases
                 Runs on the graphics card (RTX 4050), about 120 tokens a second
  Python       : 3.13
  Methodology  : Agile


--------------------------------------------------
USER ROLES
--------------------------------------------------

  1. SUPER_ADMIN         - system administration; no chatbot
  2. ADMIN               - document management only; no chatbot
  3. STUDENT             - chatbot; sees student-permitted information
  4. TEACHING_STAFF      - chatbot; sees teaching-staff information
  5. NON_TEACHING_STAFF  - chatbot; sees non-teaching-staff information

Three experiences. After login Django sends each role to its own page:

  SUPER_ADMIN                          ->  /dashboard/super-admin/
  ADMIN                                ->  /dashboard/admin/
  STUDENT, TEACHING_STAFF,
  NON_TEACHING_STAFF                   ->  /   (the chatbot)

A user who opens a page that belongs to another role is sent back to
their own page. The APIs behind those pages reply "403 Forbidden".

Permission matrix (defined in backend/accounts/permissions.py):

                            SUPER           STUDENT / TEACHING /
                            ADMIN   ADMIN   NON-TEACHING STAFF
  chat                      no      no      yes
  view own chat history     no      no      yes
  delete own chat history   no      no      yes
  upload/manage documents   yes     yes     no
  approve documents         yes     no      no
  manage users              yes     no      no
  super admin dashboard     yes     no      no
  admin dashboard           no      yes     no

Django checks this table on every request. Hiding a button in the
frontend is only for convenience; it is never the security mechanism.
Only the Super Admin can open /admin/.

A user's role is decided by the backend and database, never by what the
user selects at signup.


--------------------------------------------------
DOCUMENT WORKFLOW
--------------------------------------------------

  Admin uploads        -> PENDING -> Super Admin approves -> APPROVED
                                  -> Super Admin rejects  -> REJECTED (with a reason)
  Super Admin uploads  -> APPROVED immediately

Only APPROVED documents are used to answer questions. Every document
also records which chatbot roles may read it (students, teaching staff,
non-teaching staff).

The starting status is set by the Document model itself, not by the
request, so an Admin can never make their own upload active.

Who can do what with documents:

                                    ADMIN            SUPER ADMIN
  upload                            yes (Pending)    yes (Approved)
  see documents                     own only         all
  download the file                 own only         all
  approve / reject                  no               yes
  delete                            own, unless      any
                                    approved
  change who may read               own, unless      any
                                    approved

Upload rules checked by Django: PDF, DOCX, DOC, ODT or TXT only; the
file must really be that type (its first bytes are checked, not just
its name); at most 10 MB; a title; and at least one group that may
read the document.

Before the upload is sent, the page asks for confirmation and names
the groups that WILL and will NOT get answers from the document, so a
missing tick is noticed at once (a missing "Teaching staff" tick once
kept the attendance notice from teachers).

Who may read a document can be corrected later, without uploading it
again: "Change readers" on the documents page shows three tickboxes.
Only the three groups change; the status (approved stays approved),
the file and the passages stay as they are, and the next question
already uses the new readers. At least one group must stay ticked.


--------------------------------------------------
DOCUMENT INGESTION AND RETRIEVAL
--------------------------------------------------

Uploading does not just save the file. Ingestion makes its contents
searchable (documents/extraction.py and documents/processing.py):

  file -> blocks (headings, paragraphs, tables) -> passages -> keywords
       -> database, linked to the document and its access permissions

  - Text is read with its structure: Word and ODT headings come from
    their heading styles; in PDF, TXT and DOC files a short line that is
    ALL CAPITALS, numbered ("2. Fees") or ends with ":" is a heading.
    A table is kept as rows, cells separated by " | ", so a row such
    as "Gold | 95% and above | 50%" stays together with its numbers.
  - Passages are about 120 words. A paragraph, table row or list item
    is never cut in half; only a single line longer than a passage is
    cut, with 20 words repeated at the cut. A passage never spans two
    PDF pages, so its page number is exact.
  - Each passage remembers its section (the heading above it). Sources
    under an answer name the document, the section and the PDF page.
  - Each passage is indexed by its keywords (lower case, no punctuation,
    no common words, plurals reduced) plus the document title's.
  - The document is marked processed (processed_at) only after every
    passage is stored. If the text cannot be read (a scanned PDF, a
    password, a damaged or fake file) the upload is refused, nothing is
    kept, and the administrator sees the reason.
  - A document that is not processed is never searched and cannot be
    approved. "python manage.py reprocess_documents" reads every stored
    document again (use it after improving how documents are read).

Qwen does not learn or memorise documents. Each time a question is
asked, the matching passages are found and given to it as context.

Retrieval (every time a question is asked):

  1. PERMISSION  only passages of documents that are APPROVED and open
                 to the user's role are considered. This comes first.
  2. MATCH       RELEVANCE THRESHOLD, part 1: a passage must hold at
                 least 45% of the question's keyword WEIGHT. Rare words
                 weigh more, so sharing only common words is not enough.
                 A word found in no document ("criteria") may weigh at
                 most as much as the rarest word that is found, so the
                 user's own wording cannot hide the real topic.
  3. RANK        each is scored with the BM25 formula: rare words count
                 more, repeated words count more (less each time), and
                 long passages get no advantage.
  4. KEEP        RELEVANCE THRESHOLD, part 2: only passages scoring at
                 least 60% of the best one; near-equal matches (within
                 15%) in document order, because a notice states its main
                 rule first; then the best 4.
  5. PARTS       a question with several parts ("... and ...") is also
                 searched part by part; a part that finds nothing is
                 remembered as not covered.

Keywords: lower case, no punctuation, no common or question-shaping
words ("the", "last", "required", "rate", "once"), plurals and "-ing"
reduced ("checking" = "check"), and a few same-meaning words: "exam" =
"examination", "sick" = "medical", "visit" = "visitor", "curfew" =
"gate", "criteria" / "requirement" = "minimum", "submission" /
"payment" = "pay". Chat shorthand ("wat", "pls", "abt") and Hindi words
written in English ("kitna", "hai", "kab", "batao") are common words too.

Spelling mistakes (documents/spelling.py), done before the search:

  - Short forms are written out: "dbms" -> "database management
    systems", "hod" -> "head of department", "sem" -> "semester".
  - A word found in NO document the user may read is replaced by the
    closest word that is found, measured with Python's difflib:
    "attendence" -> "attendance", "hostal" -> "hostel", "salry" ->
    "salary". Only words the user's role may read are used, so a
    correction can never reveal a restricted document's words.
  - Safety rules, so a correct word is never changed into another:
    4+ letters, same first letter, at most 2 letters longer or shorter,
    at least 75-80% similar, and common words, short forms and words
    with a known meaning are left alone ("teach" stays "teach").
  - Greetings with typos ("helo", "gud morning", "thnx") are small talk.
  - The model is told the question may have spelling or grammar
    mistakes, so it reads "can i pay fess in cash" for its meaning.

Measured with 28 misspelled questions: 25 answered correctly, 3 safely
"couldn't find", 0 wrong (search alone: right section 27 of 28, was
15 of 28 before the correction).

Measured with 45 questions phrased the way students and staff really
ask ("how much attendance do I need", "hostel curfew time", "can I pay
fees in cash?"): the right section is found for 44.

No vector database is used. The search is by keyword, so a question
worded very differently from the document can miss it.

Scope: what Agent Narada talks about (chat/scope.py, chat/views.py)

Every message is sorted IN DJANGO before any document is searched, so
the restriction does not depend on the model obeying its prompt:

  1. Small talk        "Hi", "Good morning", "Thank you", "How are you?",
                       "What can you do?", "Bye" -> a friendly reply written
                       in scope.py. No search, no model.
                       "Hi, what is the late fee?" is a question: the
                       greeting is removed and the question answered.
  2. Clearly off-topic off-topic words (cricket, movie, election, python
                       ...) and no university word -> the polite reply:
                       "I'm Agent Narada, designed to help with UPES
                       university-related information. I can assist you
                       with university policies, attendance, examinations,
                       academic information, and other UPES-related
                       queries."
  3. Follow-up         "and for twin sharing?", "what is her email?" -> the
                       model rewrites it into a complete question, using
                       ONLY the user's previous question (never an earlier
                       answer). That question is then searched with the
                       user's CURRENT permissions, so a follow-up can never
                       reach a document the user may not read now. Passages
                       must contain the follow-up's own words, and each
                       fact in the answer must sit on a line about them.
  4. No document found a university question (university words such as
                       exam, hostel, fee) -> the "couldn't find sufficient
                       information" reply. An unclear one ("What is the
                       capital of France?") -> the model answers one narrow
                       question, forced to "university" or "other".

Measured (36 messages, Qwen2.5-1.5B): 7/7 small talk, 8/8 off-topic
refused, 2/2 university questions without a document answered "couldn't
find", follow-ups: 5 answered correctly, 3 safely "couldn't find",
0 wrong.

Answering with evidence (chat/views.py, chat/grounding.py, chat/llm.py):

  1. No passage found  -> Django replies at once (Case C):
                          "I couldn't find sufficient information about
                          this topic in the available UPES documents. I
                          don't want to provide an unverified answer.
                          Please consult the appropriate university
                          department or administrator."
                          The model is not asked, so it cannot invent one.
  2. Passages found    -> Qwen gets the question and the passages, and
                          must reply in a fixed JSON shape (forced by
                          llama-server): answer, evidence (the sentence it
                          used), status (answered / partial / not_found),
                          missing (what is not covered).
  3. Django checks it  -> a relevance score is not proof, so Django checks
                          the answer itself, and throws it away (reply 1)
                          if any check fails:
                          - every number, month and weekday in the answer
                            is in the passages or the question
                          - each fact is in a sentence about what was asked,
                            not in a neighbouring row or sentence
                          - the answer is the right kind: a fee question
                            gets an amount, "when" a date or time, "how
                            many" a number
                          - 75% of the answer's words are in the passages
                          - it does not say "not mentioned" or similar
                          A leading "Yes," / "No," is removed: it cannot
                          be checked, and a small model often gets it wrong.
  4. Partial (Case B)  -> if the model says "partial", or a part of the
                          question found no document, the answer ends with
                          "What I couldn't confirm from the available UPES
                          documents: ..." naming that part.
  5. Sources           -> only the passages that really contain the answer
                          (document, section and PDF page).
  6. Model not running -> the user gets a polite "try again" message
                          (503); the technical reason is printed in the
                          server's window.

Documents a user's role may not read are never searched, so their title
and contents can never appear in an answer (Case D). Temperature 0: the
same question with the same documents always gets the same answer.

Measured with sample_documents (42 questions, Qwen2.5-1.5B): 0 wrong
answers, 11 of 11 correct "not found" replies, 28 of 31 answerable
questions fully answered; see sample_documents/TESTING_GUIDE.txt.

The model runs as a separate program, llama-server.exe, on
127.0.0.1:8080 (this computer only). main.py starts it with a new random
secret key on every run and gives the same key to Django, so no other
program or web page can use the model. The key is never saved.


--------------------------------------------------
DATABASE TABLES
--------------------------------------------------

  User (accounts)
      username, password (hashed), name, email, role, is_active

  Document (documents)
      title, description, file
      for_students, for_teaching_staff, for_non_teaching_staff
      uploaded_by, uploaded_at
      status (PENDING / APPROVED / REJECTED)
      reviewed_by, reviewed_at, rejection_reason
      passage_count, processed_at

  Passage (documents)
      document, number, page, section, text, terms (its keywords)
      (deleted together with its document)

  Conversation (chat)
      user, title (the first question, shortened),
      created_at, updated_at (time of the newest message)
      (deleted together with its user)

  Message (chat)
      conversation, sender (user / assistant), text, sources, created_at
      (deleted together with its conversation)

  User 1 -- many Conversation 1 -- many Message

Chat history is private: every chat API starts from "this user's own
conversations", so another user's conversation gives 404 Not Found. It
is not on Django's admin site either, so not even the Super Admin can
read it. Deleting a user deletes their chat history, but never
documents.

Deleting chats, like Claude and ChatGPT: in the "Recent chats" panel each
conversation has a small "x" button, and "Clear all history" deletes
every conversation of the user. Both ask "Are you sure?" first, and
Django refuses to clear everything unless the request says
{"confirm": true}. Deleting is permanent: the conversation and (through
CASCADE) its messages are removed from the database; nothing is kept.
A user can only ever delete their own conversations. The 7-day automatic
deletion keeps running whether or not a user deletes anything.

Retention: a message is kept for 7 days (CHAT_RETENTION_DAYS in
settings.py), counted from its own created_at. Older messages are no
longer shown, and a conversation whose messages have all expired
disappears from the list. Times are stored in UTC and shown in India
time (Asia/Kolkata).

Automatic deletion: "python manage.py delete_old_chats" permanently
deletes every message older than 7 days, then every conversation left
with no messages. If a kept conversation lost its first question, its
title is replaced by the oldest question still kept, so no expired text
remains anywhere. It is safe to run any number of times, and it never
touches messages newer than 7 days, whoever they belong to.

Windows Task Scheduler runs it every hour. Set this up once, from the
NARADA folder:

     powershell -ExecutionPolicy Bypass -File schedule_chat_cleanup.ps1

The task is called "Agent Narada - delete old chats". It uses
pythonw.exe (no window pops up), runs on battery too, and catches up
as soon as the laptop is back on if a run was missed. To remove it:

     Unregister-ScheduledTask -TaskName "Agent Narada - delete old chats" -Confirm:$false

There is no activity log: the project deliberately does not track
what users do (decided on 13 October 2026).

Uploaded files are stored in backend/media/. There is no web address
for that folder: files are reached only through Django, which checks
the user's role first.


--------------------------------------------------
FOLDER STRUCTURE
--------------------------------------------------

  NARADA/
    frontend/           the pages the user sees (served by Django)
      login.html        login page
      login.js          sends the username and password to Django
      index.html        chat page (students and staff only), with the
                        "Recent chats" panel on the left
      script.js         chat behaviour: asking, the recent-chats list,
                        reopening a chat, and "+ New chat"
      superadmin.html   Super Admin dashboard (overview numbers)
      admin.html        Admin dashboard (overview numbers)
      dashboard.js      shared: fetches a dashboard's numbers and shows them
      users.html        user management page (Super Admin only)
      users.js          account list; add, modify and delete accounts
      upload.html       upload a document (Admin and Super Admin)
      upload.js         sends the upload form, with its file, to Django
      documents.html    document list: "My Documents" for an Admin,
                        "Document Approval" for the Super Admin
      documents.js      the list, filters, approve, reject and delete
      header.js         shared: shows who is logged in, handles Log out,
                        builds the dashboards' section list
      api.js            shared helper for every request to Django
      style.css         all styling
      img/              logos
    backend/            Django project
      manage.py         command-line tool for running and managing Django
      db.sqlite3        the SQLite database (a single file)
      .secret_key       the random secret key, created on the first run
                        (signs login sessions; never share this file)
      config/           project settings
        test_roles.py   automated test: every role against every page and API
        settings.py     all configuration, including the database
        urls.py         maps web addresses to code
        views.py        sends the HTML pages to the browser
        context_processors.py  adds a version number to CSS/JS addresses so
                        browsers never keep using an old copy after an update
        wsgi.py/asgi.py entry points a web server uses to start Django
      accounts/         users, roles and authentication
        models.py       the User model and the five roles
        permissions.py  the permission matrix: what each role may do
        serializers.py  checks account data before it is saved
        views.py        login, logout, "who am I" and user endpoints
        urls.py         addresses of those endpoints
        admin.py        shows users on Django's admin site
        tests.py        automated tests
        migrations/     instructions Django uses to build the database tables
      chat/             the chat API and each user's private chat history
        models.py       Conversation and Message, and the 7-day retention rule
        views.py        receives a question, finds the permitted passages,
                        asks the model, saves the exchange and returns the
                        answer with sources; lists and opens a user's own chats
        urls.py         addresses of those endpoints
        management/commands/delete_old_chats.py
                        the command that deletes chats older than 7 days
        scope.py        small talk, the UPES-only scope, follow-up questions
        grounding.py    evidence-grounded answers: the prompt, the forced
                        JSON reply shape, and Django's checks of every answer
        llm.py          the connection to llama-server: sends a conversation,
                        returns the reply (knows nothing about users)
        admin.py        empty on purpose: chat history is private
        tests.py        automated tests: chat API, saving, privacy, retention
        test_cleanup.py automated tests: the 7-day automatic deletion
        test_scope.py   automated tests: small talk, scope, follow-ups
        test_workflow.py  automated test: one complete journey, from an
                        Admin's upload to the 7-day cleanup
        test_grounding.py  automated tests: every evidence check, with the
                        real mistakes it catches
        test_llm.py     automated tests: the connection
                        (they use a fake model, so llama-server is not needed)
      documents/        university documents
        models.py       Document (approval workflow, role access), Passage
        serializers.py  checks an upload before it is stored
        views.py        upload, list, download, approve, reject, delete
        urls.py         addresses of those endpoints
        text.py         turns text into keywords
        extraction.py   reads the text of PDF, DOCX, DOC, ODT and TXT files,
                        keeping headings, paragraphs and tables
        processing.py   ingestion: splits the text into section-aware
                        passages, indexes and stores them, marks processed
        management/commands/reprocess_documents.py
                        reads every stored document again
        test_ingestion.py  automated tests: every file type, splitting,
                        refused uploads
        retrieval.py    finds the passages that best match a question
        admin.py        shows documents on Django's admin site
        tests.py        automated tests: workflow and API
        test_retrieval.py  automated tests: processing and retrieval
      dashboard/        the numbers shown on the two dashboards
        views.py        totals of users and documents, per role
        tests.py        automated tests
      media/            uploaded files (created on the first upload)
    docs/               the technical documentation (11 chapters, start at
                        docs/README.md) and its screenshots (docs/screenshots/)
    main.py             one-command launcher: sets everything up and runs it
    sample_documents/   FICTIONAL test documents (attendance notice, exam
                        date sheet PDF, faculty directory, fees, hostel,
                        library, holidays, staff policies) and
                        TESTING_GUIDE.txt: what to upload, for which
                        roles, and the questions with their correct answers
    schedule_chat_cleanup.ps1  run once: makes Windows run the 7-day chat
                        cleanup every hour (Task Scheduler)
    models/            the Qwen model file (downloaded, 1.1 GB; not shared)
    tools/llama.cpp/    llama-server.exe and the files it needs (downloaded;
                        not shared)
    tools/llama-server.log  what llama-server printed on the last run
    .venv/              Python virtual environment (not shared, not edited by hand)
    requirements.txt    list of Python packages the project needs
    README.txt          this file


--------------------------------------------------
HOW TO RUN (ONE COMMAND)
--------------------------------------------------

Open PowerShell inside the NARADA folder and run:

     python main.py

main.py does everything, in this order:

  1. checks the Python version (3.10 or newer)
  2. creates the virtual environment (.venv) if it does not exist
  3. installs the packages from requirements.txt
  4. creates / updates the SQLite database tables
  5. asks you to create a Super Admin if none exists
  6. starts the language model (llama-server with Qwen) and waits until
     it is ready. If the model file or llama-server.exe is missing, it
     says so and Agent Narada starts without it.
  7. starts the Django server and opens http://127.0.0.1:8000

The same command is used for the first run and every run after it.
Every step is safe to repeat. Press Ctrl+C to stop both servers.

The model files are not part of the project folder you share. On a new
computer, download them again from the official pages (see TECHNOLOGY
STACK) and check their SHA-256 fingerprints:

  models\qwen2.5-1.5b-instruct-q4_k_m.gguf
      6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e
  llama-b11588-bin-win-cuda-12.4-x64.zip   (unzip into tools\llama.cpp)
      b332d03139fbb8453c1ee7dd89321f10186aedaa35b9a2e326f6569e7dcaa04f
  cudart-llama-bin-win-cuda-12.4-x64.zip   (unzip into tools\llama.cpp)
      8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6

  Check one with:  (Get-FileHash <file> -Algorithm SHA256).Hash

To start without opening a browser:   python main.py --no-browser

Then:
  - the chat is at        http://127.0.0.1:8000
  - the admin site is at  http://127.0.0.1:8000/admin


--------------------------------------------------
DOING THE STEPS BY HAND
--------------------------------------------------

main.py runs these for you. They are listed so each step can be
explained and run on its own.

  Create the environment      py -3.13 -m venv .venv
  Activate it                 .venv\Scripts\Activate.ps1
  Install the packages        pip install -r requirements.txt
  Create the database tables  python backend\manage.py migrate
  Create a Super Admin        python backend\manage.py createsuperuser
  Start the server            python backend\manage.py runserver
  Run the automated tests     cd backend, then: python manage.py test

Accounts made with createsuperuser always get the SUPER_ADMIN role.

If PowerShell refuses to run Activate.ps1, run this once and try again:

     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

To leave the virtual environment, type:  deactivate


--------------------------------------------------
PAGES AND API ENDPOINTS
--------------------------------------------------

Pages:

  /login/                   login page
  /                         chatbot (Student, Teaching Staff, Non-Teaching Staff)
  /dashboard/super-admin/   Super Admin dashboard
  /dashboard/admin/         Admin dashboard
  /users/                   manage users: view, add, modify and delete
                            accounts (Super Admin only)
  /documents/               document list (Admin: own documents;
                            Super Admin: all, with approve and reject)
  /documents/upload/        upload a document (Admin and Super Admin)
  /admin/                   Django admin site (Super Admin only; a built-in
                            backup tool, not needed for normal use)

  Not logged in        -> every page redirects to /login/
  Wrong role for page  -> redirected to the role's own start page

API endpoints (JSON):

  POST /api/auth/login/    body: {"username": "...", "password": "..."}
                           200 = logged in (the reply includes "home", the
                           page this role starts on)
                           401 = wrong username or password
  POST /api/auth/logout/   ends the session
  GET  /api/auth/me/       the logged-in user's name, role, permissions
                           and start page
                           403 = not logged in
  GET  /api/users/         every account and its role (Super Admin only)
                           403 = any other role, or not logged in
  POST /api/users/         add an account (Super Admin only)
                           body: {"username", "password", "role"} plus
                                 optional "first_name", "last_name", "email",
                                 "is_active"
                           201 = created, 400 = bad data (one message per
                           field), 403 = any other role, or not logged in
  PATCH /api/users/<id>/   modify an account (Super Admin only)
                           body: only the fields to change; an empty
                                 "password" keeps the current one
                           200 = saved, 400 = bad data, 404 = no such account
  DELETE /api/users/<id>/  delete an account (Super Admin only)
                           204 = deleted, 404 = no such account

  A Super Admin cannot delete, deactivate or change the role of their
  own account (400), so the system always keeps a working Super Admin.
  GET  /api/documents/     the documents this user may see (Admin: own;
                           Super Admin: all). Optional ?status=PENDING
  POST /api/documents/     upload (a form with a file): title, description,
                           file, for_students, for_teaching_staff,
                           for_non_teaching_staff
                           201 = stored AND its text read and indexed
                           400 = bad file, missing field, or the text could
                                 not be read (nothing is kept; "file" says why)
  GET  /api/documents/<id>/file/      download the file
  POST /api/documents/<id>/approve/   Super Admin only; 400 if the document's
                                      text was never read
  POST /api/documents/<id>/reject/    Super Admin only; body {"reason": "..."}
  PATCH  /api/documents/<id>/         change who may read it; body with all three
                                      of for_students, for_teaching_staff,
                                      for_non_teaching_staff (true/false)
  DELETE /api/documents/<id>/         remove the document and its file

  All document endpoints: 403 = students and staff, or not logged in;
  404 = the document is not one this user may see.

  GET  /api/dashboard/super-admin/
                           totals of users by role and documents by status
                           (Super Admin only)
  GET  /api/dashboard/admin/
                           totals of the Admin's own documents by status
                           (Admin only)
  POST /api/chat/          body: {"question": "...", "conversation_id": 12}
                           (conversation_id is optional: without it a new
                           conversation starts)
                           200 = {"answer": "...", "sources": [{"document_id",
                                  "title", "page"}, ...], "conversation_id": 12}
                           400 = empty or too long, or a bad conversation_id
                           403 = not logged in, or Super Admin / Admin
                           404 = the conversation is not this user's, or expired
                           503 = the language model is not running
                           (the question and answer are saved only on 200)
  GET  /api/chat/conversations/
                           this user's own conversations, newest first:
                           [{"id", "title", "updated_at"}, ...]
  GET  /api/chat/conversations/<id>/
                           one of this user's own conversations with its
                           messages, oldest first; 404 for anyone else's
  DELETE /api/chat/conversations/<id>/
                           delete one of this user's own conversations and
                           its messages: 204; 404 for anyone else's
  DELETE /api/chat/conversations/   body: {"confirm": true}
                           delete ALL of this user's conversations:
                           200 = {"deleted_conversations": 3}
                           400 = "confirm" is not exactly true (nothing deleted)
  All of these: students and staff only (403 for Admin, Super Admin,
  visitors). Only messages from the last 7 days are returned. Editing a
  conversation is not possible (405).

How login works: Django checks the password against its stored hash,
creates a session in the database, and gives the browser a cookie that
holds only the session id. Every later request carries that cookie, so
Django knows who is asking. Every POST must also carry the CSRF token.

Security:
  - Password guessing: after 5 wrong passwords for one username from one
    computer, that username is locked there for 15 minutes (429 "Too
    many failed attempts"). A successful login resets the count.
  - Secret key: not written in the code. It comes from NARADA_SECRET_KEY,
    or from backend/.secret_key, created with a random key on the first
    run. Never share that file.
  - DEBUG stays on, because Agent Narada runs on this computer only
    (127.0.0.1) and the development server needs it to send the CSS and
    JavaScript. It must be turned off, with a proper web server and
    HTTPS, if the system is ever put on a network.
  - The language model listens on 127.0.0.1 only and needs a secret key
    that main.py creates on every run (see above).

There is no public signup. Accounts of every role are created by the
Super Admin on the Manage users page, so nobody can give themselves a role.


--------------------------------------------------
PROJECT STATUS
--------------------------------------------------

  [done]  Chat frontend
  [done]  Frontend connected to the backend (login, logout, chat API)
  [done]  One-command launcher (main.py)
  [done]  Python virtual environment and requirements.txt
  [done]  Django project foundation with SQLite
  [done]  User model and roles
  [done]  Authentication (login, logout, session)
  [done]  Role-based authorization (permission matrix)
  [done]  User management by the Super Admin: view, add, modify, delete
  [done]  Role-specific permission matrix and routing after login
  [done]  Models: documents, passages, conversations, messages
  [done]  Super Admin dashboard and Admin dashboard (layout, section
          list and live overview numbers)
  [done]  Document management and approval workflow (upload, list,
          download, approve, reject, delete)
  [done]  Document processing and role-based retrieval
  [done]  Document ingestion: PDF, DOCX, DOC, ODT, TXT; headings, sections
          and tables kept; processed only on success; failures refused
          with the reason; section names in sources
  [done]  Language model: Qwen2.5-1.5B-Instruct from Hugging Face, run by
          llama.cpp's llama-server, started by main.py with a secret key;
          answers written from the permitted passages, with sources
  [done]  Saving conversations: private to each account, only the last
          7 days shown (APIs to list and open your own chats)
  [done]  Automatic deletion of messages older than 7 days (management
          command delete_old_chats, run every hour by Task Scheduler)
  [done]  Chat history panel on the chat page: the user's own chats from
          the last 7 days, reopen and continue one, or start a new chat
  [done]  Evidence-grounded answers: relevance threshold, Django checks
          that the passages support each answer, partial answers (Case B),
          new "not found" wording (Case C), only supporting sources
  [done]  UPES-only scope enforced in Django: small talk, polite refusal
          of off-topic questions, follow-up questions within the user's
          current permissions
  [done]  Delete one conversation / clear all chat history: own only,
          confirmation in the page and in the API, permanent
  [done]  Security: login lockout after 5 wrong passwords, secret key out
          of the code, model locked with a per-run key
  [done]  Final verification (14 October 2026): 310 automated tests,
          including one complete workflow and every role against every
          page and API; live tests with the real model (42 sample
          questions, 36 scope/follow-up messages, 50 everyday phrasings),
          and an end-to-end run on the real database and accounts
  [done]  The 11 sample documents are uploaded and approved in the system
  [done]  Spelling and grammar mistakes understood (14 October 2026):
          misspelled words corrected from the documents' own words, short
          forms, chat shorthand, Hindi words in English, typo greetings;
          324 automated tests; documents reprocessed
  [done]  Correcting who may read a document after upload ("Change
          readers"), and a confirmation naming the groups before each
          upload; 334 automated tests
  [removed] Super Admin conversation monitoring screen and System
          Activity screen (taken out of the plan on 3 October 2026)
  [removed] Activity log: table, app and recording of document events
          (taken out of the plan on 13 October 2026)
  [done]  Technical documentation in docs/ (14 October 2026): 11 chapters
          (architecture, model choice, retrieval, answering method, roles
          and security, data model and API, user guide, testing, operation,
          questions and answers) with 21 screenshots; start at docs/README.md
  [todo]  Confirm a .doc file saved by real Microsoft Word uploads correctly
