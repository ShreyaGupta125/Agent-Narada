# 1. Introduction and requirements

[← Contents](README.md) · [Next: System architecture →](02-architecture.md)

## 1.1 The problem

University information is spread across many documents: attendance notices,
exam date sheets, fee structures, hostel rules, salary policies, holiday
lists and so on. To answer a simple question ("What is the minimum
attendance?", "When is the Data Structures exam?") a student or staff member
has to know which document to open and then search it.

General AI chatbots are not a solution:

- They **invent** answers that sound right ("hallucination"), which is
  dangerous for rules, dates and fees.
- They do not know the university's **own, current** documents.
- They send questions and documents to an **outside company**.
- They do not know **who may see what**: a student must not get answers
  from a staff salary policy.

## 1.2 What Agent Narada does

Agent Narada answers questions about UPES using only the university's
approved documents. Each answer:

1. comes **only from documents the user's role may read**;
2. is **checked by the program** against those documents before it is shown;
3. lists its **sources** (document, section and PDF page);
4. is replaced by an honest "I couldn't find sufficient information..."
   when the documents do not establish it.

The method is called **retrieval-augmented generation (RAG)**. For every question the
system first **retrieves** the relevant passages of the documents, then lets a
language model **generate** a short answer from them. The model is never trained
on the documents and does not memorise them.

## 1.3 Objectives

| # | Objective | Where it is met |
|---|-----------|-----------------|
| O1 | Answer UPES questions in natural language, including misspelled and informal questions | Chapters 4 and 5 |
| O2 | Never present an unverified answer as fact | Chapter 5 (Django's answer checks) |
| O3 | Show the evidence: document, section, page | Chapter 5.7 |
| O4 | Enforce role-based access to documents | Chapter 6 |
| O5 | Keep everything on the university's own computer (privacy) | Chapters 2 and 3 |
| O6 | Run on an ordinary laptop, quickly | Chapter 3 (model choice) |
| O7 | Let administrators manage documents and users without technical knowledge | Chapters 6 and 8 |
| O8 | Keep chat history private and short-lived (7 days) | Chapter 7 |

## 1.4 Requirements

These are the requirements the project was built to (final version, 13 October 2026).

### Functional requirements

| ID | Requirement |
|----|-------------|
| F1 | Five roles: **Super Admin**, **Admin**, **Student**, **Teaching Staff**, **Non-Teaching Staff**, enforced by the backend. |
| F2 | Super Admin manages user accounts (view, add, modify, deactivate, delete). |
| F3 | Admin and Super Admin upload documents and choose which roles may read each one. An Admin's upload waits for the Super Admin's approval; a Super Admin's upload is approved at once. |
| F4 | Documents may be PDF, TXT, DOCX, DOC or ODT. A document is usable only after its text has been read successfully ("processed"). |
| F5 | Students and staff chat with Agent Narada. Answers come only from approved documents open to their role. |
| F6 | **Scope**: greetings and polite small talk are answered; questions unrelated to the university are refused politely; follow-up questions in a conversation are understood. |
| F7 | **Evidence-grounded answers**, four cases: **A** fully answered with sources; **B** partly answered, naming what could not be confirmed; **C** not found, with the exact wording "I couldn't find sufficient information about this topic in the available UPES documents. I don't want to provide an unverified answer. Please consult the appropriate university department or administrator."; **D** documents the role may not read are never used or mentioned. |
| F8 | Chat history is private to each user, kept for 7 days and then deleted automatically. A user can delete one conversation or clear all, after a confirmation. |
| F9 | No activity log is kept (removed from the plan on 13 October 2026). |
| F10 | Users may write with spelling and grammar mistakes, chat shorthand or Hindi words in English letters; Agent Narada must still understand the topic. |

### Non-functional requirements

| ID | Requirement |
|----|-------------|
| N1 | **Local model**: a small open model from Hugging Face, run on the same computer. No cloud AI service. |
| N2 | **Simple, explainable technology**: HTML/CSS/JavaScript, Django, Django REST Framework, SQLite. No Docker, WSL, vector database or React. |
| N3 | Starts with **one command** (`python main.py`). |
| N4 | **Repeatable answers**: the same question with the same documents gets the same answer. |
| N5 | **Security**: hashed passwords, CSRF protection, login lockout, secret keys outside the code, the model reachable only by Django. |
| N6 | Every feature is **tested before it is called finished**. |

## 1.5 Scope and assumptions

- The system runs on one Windows computer with an NVIDIA graphics card and
  is used through a browser on the same computer (`127.0.0.1`). Putting it on
  a network for many users would need a production web server, HTTPS and
  `DEBUG = False` (see chapter 10.6).
- The 11 documents in `sample_documents/` are **fictional** UPES documents,
  written to test every feature (tables, multi-page PDF, Word, ODT,
  role-restricted documents). They must be replaced by real documents before
  real use.
- Agent Narada answers in English. It understands Hindi question words typed
  in English letters ("fee kitna hai") but always replies in English.
