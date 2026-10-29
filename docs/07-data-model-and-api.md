# 7. Data model and API

[← Roles, permissions and security](06-roles-and-security.md) · [Contents](README.md) · [Next: User guide →](08-user-guide.md)

## 7.1 The database tables

The database is one SQLite file, `backend/db.sqlite3`. Django creates and
updates the tables from the model classes (migrations).

```
  User ──1────many──► Conversation ──1────many──► Message
   │
   ├──1────many──► Document  (as uploaded_by)
   └──1────many──► Document  (as reviewed_by)

  Document ──1────many──► Passage
```

| Table | Fields | Deleted when |
|-------|--------|--------------|
| **User** | username, password (hash), first and last name, email, **role**, is_active, last_login, date_joined | the Super Admin deletes the account |
| **Document** | title, description, file, **for_students**, **for_teaching_staff**, **for_non_teaching_staff**, uploaded_by, uploaded_at, **status** (PENDING / APPROVED / REJECTED), reviewed_by, reviewed_at, rejection_reason, passage_count, **processed_at** | an Admin or the Super Admin deletes it (its file is removed too) |
| **Passage** | document, number (reading order), page (PDF), **section**, text, **terms** (its keywords, stored once) | its document is deleted (CASCADE) |
| **Conversation** | user, title (the first question, shortened to 60 characters), created_at, updated_at | the user deletes it, all its messages expire, or the user is deleted |
| **Message** | conversation, sender (user / assistant), text, **sources** (JSON: document_id, title, section, page), created_at | it is older than 7 days, its conversation is deleted |

Deleting a user deletes their chat history, but **never** their documents
(`uploaded_by` becomes empty; the document stays).

## 7.2 Chat history and the 7-day rule

- **Private**: every chat API starts from "this user's own conversations",
  so anyone else's gives 404. Conversations and messages are deliberately
  **not** shown on Django's admin site, so not even the Super Admin can read
  them.
- **7 days** (`CHAT_RETENTION_DAYS = 7`), counted from each message's own
  time. Older messages are no longer shown, and a conversation whose
  messages have all expired disappears from the list.
- **Automatic deletion**: `python manage.py delete_old_chats` permanently
  deletes every message older than 7 days, then every conversation left
  empty. If a kept conversation lost its first question, its title is
  replaced by the oldest question still kept, so no expired text remains.
  It is safe to run any number of times.
- **Every hour**: Windows Task Scheduler runs it (task "Agent Narada -
  delete old chats", created by `schedule_chat_cleanup.ps1`). It uses
  `pythonw.exe` (no window), runs on battery, and catches up when the laptop
  wakes if a run was missed.
- **Manual deletion**: the × next to a conversation deletes it; "Clear all
  history" deletes all of the user's conversations. Both ask "Are you sure?"
  first, and deletion is permanent.
- Times are stored in UTC and shown in India time (`Asia/Kolkata`).
- A question and its answer are saved together in one transaction: a
  question is never stored without its answer.

## 7.3 API endpoints

All endpoints take and return JSON, use the login session, and (except GET)
need the CSRF token.

### Login

| Method and address | What it does | Replies |
|--------------------|--------------|---------|
| `POST /api/auth/login/` | `{"username", "password"}` | 200 with name, role, permissions and start page · 401 wrong details · 429 locked for 15 minutes |
| `POST /api/auth/logout/` | ends the session | 200 |
| `GET /api/auth/me/` | who is logged in | 200 · 403 not logged in |

### Chat (Student, Teaching Staff, Non-Teaching Staff)

| Method and address | What it does | Replies |
|--------------------|--------------|---------|
| `POST /api/chat/` | `{"question": "...", "conversation_id": 12}` (id optional: without it a new conversation starts) | 200 `{"answer", "sources", "conversation_id"}` · 400 empty/too long/bad id · 403 wrong role · 404 not your conversation or expired · 503 model not running |
| `GET /api/chat/conversations/` | own conversations, newest first | 200 `[{"id", "title", "updated_at"}]` |
| `GET /api/chat/conversations/<id>/` | one own conversation with its messages | 200 · 404 |
| `DELETE /api/chat/conversations/<id>/` | delete one own conversation | 204 · 404 |
| `DELETE /api/chat/conversations/` | `{"confirm": true}`: delete **all** own conversations | 200 `{"deleted_conversations": n}` · 400 without the confirmation |

Example:

```json
POST /api/chat/
{"question": "condonaton fee kitna hai"}

200 OK
{
  "answer": "Rs 2,000 per course",
  "sources": [{"document_id": 11, "title": "attendence notice",
               "section": "3. Condonation of attendance shortage", "page": null}],
  "conversation_id": 41
}
```

### Documents (Admin and Super Admin)

| Method and address | What it does | Replies |
|--------------------|--------------|---------|
| `GET /api/documents/` | Admin: own documents; Super Admin: all. Optional `?status=PENDING` | 200 |
| `POST /api/documents/` | upload: form with title, description, file, the three access fields | 201 stored **and** text read · 400 bad file or text unreadable (nothing kept) |
| `PATCH /api/documents/<id>/` | change who may read it (all three access fields) | 200 · 400 approved document (Admin) or no group ticked · 404 |
| `DELETE /api/documents/<id>/` | delete the document and its file | 204 · 400 approved document (Admin) · 404 |
| `GET /api/documents/<id>/file/` | download the original file | 200 · 404 |
| `POST /api/documents/<id>/approve/` | Super Admin only | 200 · 400 text never read |
| `POST /api/documents/<id>/reject/` | Super Admin only, `{"reason": "..."}` | 200 · 400 no reason |

### Users (Super Admin)

| Method and address | What it does | Replies |
|--------------------|--------------|---------|
| `GET /api/users/` | every account | 200 |
| `POST /api/users/` | create: username, password, role, optional names, email, is_active | 201 · 400 one message per field |
| `PATCH /api/users/<id>/` | modify (only the fields sent; an empty password keeps the old one) | 200 · 400 (e.g. changing your own role) · 404 |
| `DELETE /api/users/<id>/` | delete | 204 · 400 your own account · 404 |

### Dashboards

| Method and address | Returns |
|--------------------|---------|
| `GET /api/dashboard/super-admin/` | users by role, documents by status (Super Admin) |
| `GET /api/dashboard/admin/` | the Admin's own documents by status (Admin) |

## 7.4 Management commands

| Command (run from `backend/`) | What it does |
|-------------------------------|--------------|
| `python manage.py delete_old_chats` | delete chat messages older than 7 days (run hourly by Task Scheduler) |
| `python manage.py reprocess_documents` | read every stored document again from its file (after improving how documents are read) |
| `python manage.py createsuperuser` | create a Super Admin account |
| `python manage.py test` | run all 334 automated tests |
| `python manage.py migrate` | create or update the database tables (main.py does this) |
