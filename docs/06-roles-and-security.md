# 6. Roles, permissions and security

[← Answering with evidence](05-answering-with-evidence.md) · [Contents](README.md) · [Next: Data model and API →](07-data-model-and-api.md)

## 6.1 The five roles

| Role | Uses | Starts on |
|------|------|-----------|
| **Super Admin** | user management, document approval, upload (approved at once), dashboard. No chatbot. | Super Admin dashboard |
| **Admin** | upload documents (they wait for approval), see own uploads, dashboard. No chatbot. | Admin dashboard |
| **Student** | the chatbot, own chat history | chat page |
| **Teaching Staff** | the chatbot, own chat history | chat page |
| **Non-Teaching Staff** | the chatbot, own chat history | chat page |

The role is stored in the database (`accounts.User.role`) and is set only by
the Super Admin. A new account is a **Student** unless the Super Admin
chooses otherwise. Django's own `is_staff`/`is_superuser` flags always follow
the role, so the two can never disagree.

## 6.2 The permission matrix (accounts/permissions.py)

All permissions are in **one table**. The rest of the backend asks one
question, `user_can(user, action)`. A role or action missing from the table
is refused.

| Action | Super Admin | Admin | Student | Teaching | Non-Teaching |
|--------|:-:|:-:|:-:|:-:|:-:|
| `chat` | | | ✔ | ✔ | ✔ |
| `view_own_chat_history` | | | ✔ | ✔ | ✔ |
| `delete_own_chat_history` | | | ✔ | ✔ | ✔ |
| `upload_document` (and manage own documents) | ✔ | ✔ | | | |
| `approve_document` | ✔ | | | | |
| `manage_users` | ✔ | | | | |
| `super_admin_dashboard` | ✔ | | | | |
| `admin_dashboard` | | ✔ | | | |

Each API view names the action it needs (`permission_classes = [CanChat]`);
Django REST Framework refuses everyone else with **403 Forbidden** before the
view runs. A deactivated account has no permissions at all.

On top of the role, **ownership** is checked: a user's conversations, and an
Admin's documents, are found with `filter(user=...)` / `filter(uploaded_by=...)`.
Asking for someone else's gives **404 Not Found**, as if it did not exist, so
not even its existence is revealed.

A test (`config/test_roles.py`) checks **every role against every page and
API**.

## 6.3 Which documents a role may read

Each document has three tickboxes: **Students**, **Teaching staff**,
**Non-teaching staff**. A document reaches the chatbot for a user only if

```
status = APPROVED   and   processed (text read)   and   ticked for the user's role
```

(`Document.objects.visible_to(user)` in `documents/models.py`). This filter is
applied **before** the search, the spelling vocabulary and the model, so a
document the role may not read is never searched, never given to the model,
and its title is never shown (Case D).

With the sample documents:

| Document | Students | Teaching | Non-teaching |
|----------|:-:|:-:|:-:|
| Attendance notice | ✔ | ✔ | |
| Exam Date Sheet (PDF, 3 pages) | ✔ | ✔ | |
| Faculty Directory | ✔ | ✔ | ✔ |
| Faculty Salary and Leave Policy | | ✔ | |
| Non-Teaching Staff Handbook | | | ✔ |
| Hostel Rules | ✔ | | |
| Fee Structure | ✔ | | |
| Library Rules | ✔ | ✔ | ✔ |
| Holiday List | ✔ | ✔ | ✔ |
| Scholarship Policy (Word .docx) | ✔ | | |
| Sports Facilities (OpenDocument .odt) | ✔ | ✔ | ✔ |

## 6.4 The document workflow

```
Admin uploads        ──► PENDING ──► Super Admin approves ──► APPROVED  (used for answers)
                                 └─► Super Admin rejects  ──► REJECTED  (with a reason the Admin sees)
Super Admin uploads  ──► APPROVED immediately
```

- The status is set by the `Document` model itself, **never** by the upload
  request, so an Admin cannot make their own upload active.
- The uploader is the logged-in user, never a value from the form.
- A document whose text could not be read cannot be approved.
- Before uploading, the page asks for confirmation and names the groups that
  **will** and **will not** get answers from the document, so a missing tick
  is noticed at once.
- "**Change readers**" corrects the three groups later without uploading
  again. The status, file and passages stay as they are; the next question
  already uses the new readers. At least one group must stay ticked.

| Who can do what | Admin | Super Admin |
|-----------------|-------|-------------|
| upload | yes (Pending) | yes (Approved) |
| see documents | own only | all |
| download the file | own only | all |
| approve / reject | no | yes |
| delete | own, unless approved | any |
| change who may read | own, unless approved | any |

Uploaded files are stored in `backend/media/`, which has **no web address**.
The only way to download one is `/api/documents/<id>/file/`, which checks the
role and the ownership first.

## 6.5 User management rules

- Only the Super Admin can create, modify, deactivate or delete accounts and
  assign roles.
- A Super Admin **cannot delete, deactivate or change the role of their own
  account**, so there is always at least one working Super Admin.
- Passwords must pass Django's four checks: not too similar to the username,
  at least 8 characters, not a common password, not only digits.
- Passwords are stored only as **hashes** (Django's PBKDF2 with SHA-256 and
  a random salt), never as plain text, and are never sent to the browser.

## 6.6 Security measures

| Threat | Protection |
|--------|------------|
| Guessing passwords | **Login lockout**: after **5** wrong passwords for one username from one computer, that username is locked there for **15 minutes**. The same "Invalid username or password." message for every failure, so an attacker cannot learn which usernames exist. |
| Stealing a session from another website (CSRF) | Every request that changes something must carry Django's CSRF token (`X-CSRFToken` header); another website cannot read it. |
| Using another role's page or API | Role check on every page and every API request (section 6.2) |
| Reading another user's chats or an Admin's documents | Ownership filters; 404 for anything not one's own |
| Malicious uploads | Only PDF, DOCX, DOC, ODT, TXT; the **first bytes** must match the type (a renamed .exe is refused); at most **10 MB**; zip-bomb limit of 50 MB for .docx/.odt XML |
| Code hidden in documents or questions (XSS) | The browser puts every server text into the page with `textContent`, never as HTML |
| Instructions hidden in documents or questions ("prompt injection") | The model is told passages and questions are information, not instructions; it only sees passages the user may read anyway; Django checks every answer against the passages; scope rules are in Django, not in the prompt |
| Another program using the model | llama-server listens on 127.0.0.1 only and requires a **new random key on every start** |
| Secret key in the code | Django's `SECRET_KEY` comes from the environment variable `NARADA_SECRET_KEY`, or from the file `backend/.secret_key`, created with a random value on first start (not in the code) |
| Enormous requests | Questions are limited to 1,000 characters; `conversation_id` must be a number |
| Wiping someone's history by a stray request | "Clear all" needs `{"confirm": true}` in the request as well as the confirmation in the page |
| Showing the site inside another site (clickjacking) | Django's `X-Frame-Options` protection |
| Privacy of chats | Each user sees only their own chats; messages are deleted after 7 days; **no activity log**; server log messages contain only reasons, never questions, documents or answers |

## 6.7 Before putting it on a network

The project runs on one computer for development and demonstration
(`DEBUG = True`, `127.0.0.1`). To serve real users over a network:

1. set `DEBUG = False` and `ALLOWED_HOSTS` to the server's name;
2. serve Django with a production server (for example Waitress on Windows)
   behind HTTPS, and set `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE`;
3. keep llama-server on `127.0.0.1` (only Django talks to it);
4. replace the sample documents with real, approved ones.
