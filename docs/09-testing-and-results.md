# 9. Testing and results

[← User guide](08-user-guide.md) · [Contents](README.md) · [Next: Installation and operation →](10-installation-and-operation.md)

Agent Narada was tested in two ways:

1. **Automated tests** (334): run in seconds, without the real model, after
   every change.
2. **Live tests** with the real Qwen2.5-1.5B-Instruct model and the 11
   sample documents: hundreds of questions, every answer reviewed by hand.

The rule throughout the project: **a feature is not called finished until it
has been tested.**

## 9.1 Automated tests

Run them with:

```
cd backend
..\.venv\Scripts\python.exe manage.py test
```

Result on 14 October 2026: **334 tests, all passing** (about 35 seconds).

| File | Tests | What is tested |
|------|------:|----------------|
| `accounts/tests.py` | 75 | roles, permission matrix, login, logout, lockout after 5 failures, user management, a Super Admin cannot lock themselves out, password rules |
| `config/test_roles.py` | 4 | **every role against every page and API** (allowed roles get in, all others are refused) |
| `config/tests.py` | 1 | every page loads its CSS and JavaScript with a version number, so browsers never use an outdated copy |
| `dashboard/tests.py` | 7 | dashboard totals, an Admin sees only their own documents, only the right role gets each dashboard's numbers |
| `documents/tests.py` | 61 | upload checks (type, real file, size, at least one group), approval workflow, Admin/Super Admin rights, downloads, delete, **change readers**, role-based visibility |
| `documents/test_ingestion.py` | 22 | reading PDF (with pages), TXT, DOCX, DOC, ODT; headings and tables kept; scanned / password / damaged / fake files refused with nothing kept |
| `documents/test_retrieval.py` | 50 | keywords, BM25 ranking, relevance threshold, role filtering, several-part questions, spelling end-to-end, follow-ups and scope with a fake model |
| `documents/test_spelling.py` | 7 | common mistakes corrected, correct words never changed, short forms, ties, the first-letter rule, short words left alone |
| `chat/tests.py` | 36 | chat API: validation, saving, own conversations only, 7-day visibility, delete one / clear all with confirmation, model not running (503) |
| `chat/test_grounding.py` | 33 | every answer check: invented facts, neighbouring rows, wrong names, wrong kind of answer, word support, yes/no handling, sources, partial answers |
| `chat/test_scope.py` | 15 | small talk (including misspellings), off-topic refusal, follow-up recognition |
| `chat/test_llm.py` | 11 | the request sent to llama-server (key, temperature, JSON schema), errors turned into "model not running" |
| `chat/test_cleanup.py` | 11 | 7-day deletion: old messages deleted, new kept, empty conversations removed, titles replaced, safe to repeat |
| `chat/test_workflow.py` | 1 | one complete journey: Admin uploads → stays pending (not used) → Super Admin approves → student asks → answer with source → follow-up → a teacher is not given the student document → the student deletes the chat → the 7-day cleanup |

The automated tests replace the language model with a **fake model** that
returns fixed replies. That way they test Django's own logic (permissions,
search, checks) exactly and quickly, without depending on the GPU.

## 9.2 Live tests with the real model

The questions and their expected answers are listed in
`sample_documents/TESTING_GUIDE.txt`, so anyone can repeat them by hand.

### Before and after the evidence checks

The same questions were asked before and after the grounding checks of
chapter 5 were added:

| | First run (13 Oct, model answers directly) | After the evidence checks |
|---|---|---|
| Questions | 31 | 42 (the 31 + Word/ODT + partial questions) |
| **Wrong answers** | **5** | **0** |
| Correct "couldn't find" (Cases C and D) | — | 11 of 11 |
| Answerable questions fully answered | — | 28 of 31 |

The five wrong answers of the first run, all fixed:

| Question | First run (wrong) | Now |
|----------|-------------------|-----|
| Who teaches Database Management Systems? | Dr. Vikram Mehta (the entry above) | Ms. Priya Nair |
| What is the overtime rate? (asked by a student) | "Rs 5 per day" (the library fine) | couldn't find (students may not read the staff handbook) |
| When do the hostel gates close? (teaching staff) | an answer about holidays | couldn't find (hostel rules are for students) |
| When is the Data Structures exam? (non-teaching staff) | a professor's office hours | couldn't find (date sheet not open to them) |
| When is the Business Law exam? | Friday, 4 December (the next row) | couldn't find (safe miss, see 9.4) |

### Final results (14 October 2026)

| Test set | Result |
|----------|--------|
| 42 sample questions | **0 wrong answers**; 11/11 correct "couldn't find"; repeated twice with identical answers |
| 36 scope and follow-up messages | small talk 7/7, off-topic refused 8/8, follow-ups 6 correct and 2 safely "couldn't find", 0 wrong |
| 50 everyday phrasings ("how much attendance do I need", "hostel curfew time", "can I pay fees in cash?") | 41 of 45 answered correctly, 4 safely "couldn't find", 5 of 5 refusals correct, 0 wrong |
| 28 questions with spelling mistakes, shorthand and Hinglish | **25 answered correctly, 3 safely "couldn't find", 0 wrong**; 3 of 3 off-topic refused |
| Search only, the same 28 misspelled questions | right section found for 27 of 28 (15 of 28 before spelling correction) |
| Real database with the real accounts (Jo, Sneha, Viki) | every answer correct or safely refused; every role got only its own documents; all test chats deleted afterwards |

**Wrong answers in every reviewed set: 0.** When the system is unsure it says
"couldn't find", which is the behaviour the requirements ask for.

## 9.3 Browser tests

The pages were also checked in a browser: login for each role, the chat page,
history (open, delete one, clear all), dashboards, user management, upload
(with the readers confirmation), approval, rejection and "Change readers"
(including the refusal when no group is ticked). The screenshots in chapter 8
come from these checks.

## 9.4 Known limitations

All of these are **safe misses**: the reply is "couldn't find", never a
wrong fact.

| Question | Why it is missed |
|----------|------------------|
| When is the Business Law exam? | The small model keeps reading the neighbouring row of the date sheet; Django's row check refuses that answer |
| and for twin sharing? / and Discrete Mathematics? (follow-ups) | The rewritten question is not precise enough; the checks refuse the result |
| can my parents visit me in the hostel? · when does the winter break start? · I lost my ID card, what should I do? | Worded very differently from the documents, or the model picks a sentence that fails the checks |
| who teach dbms · exam date of bussiness law · can i use kettel in hostel room (misspelled) | Same reasons as above |

Incomplete but not wrong:

| Question | Answer given |
|----------|--------------|
| holidays in November | only the first holiday (Diwali) |
| BBA exam dates | only the first date |
| B.Tech tuition fee and the fee due date | only the fee |

Other limits:

- Keyword search can miss a question worded completely differently from the
  document (section 4.7).
- The model replies in English only.
- A scanned PDF (picture of text) cannot be read; a version with real text
  must be uploaded.

## 9.5 Possible future improvements

- A larger model (3B) on a stronger computer, to reduce the safe misses.
  Only one line in `main.py` (the model file) would change.
- An optional meaning-based search beside BM25, for very differently worded
  questions.
- OCR (reading text from images) for scanned PDFs.
- Answers in Hindi.
- A production deployment for many users (chapter 6.7).
