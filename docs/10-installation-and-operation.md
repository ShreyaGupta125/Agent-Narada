# 10. Installation and operation

[← Testing and results](09-testing-and-results.md) · [Contents](README.md) · [Next: Questions and answers →](11-questions-and-answers.md)

## 10.1 Requirements

| | Used for development | Minimum (estimate) |
|---|---|---|
| Operating system | Windows 11 | Windows 10/11, 64-bit |
| Processor | Intel Core i7-13700HX | any modern 64-bit processor |
| Memory | 16 GB | 8 GB |
| Graphics card | NVIDIA GeForce RTX 4050 Laptop, 6 GB | NVIDIA with about 2 GB free and a recent driver (without one, a CPU build of llama.cpp works, more slowly) |
| Disk | 2.4 GB (model 1.1 GB, llama.cpp with CUDA libraries 1.2 GB, Python packages 63 MB) | about 3 GB, with room for documents |
| Python | 3.13.9 | 3.10 or newer |
| Browser | Microsoft Edge / Google Chrome | any current browser |

## 10.2 Files that are downloaded separately

The model and llama.cpp are large and are not part of the shared project
folder. On a new computer, download them from their official pages and check
their SHA-256 fingerprints:

| File | From | Put it in | SHA-256 |
|------|------|-----------|---------|
| `qwen2.5-1.5b-instruct-q4_k_m.gguf` | huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF | `models\` | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` |
| `llama-b11588-bin-win-cuda-12.4-x64.zip` | github.com/ggml-org/llama.cpp/releases | unzip into `tools\llama.cpp\` | `b332d03139fbb8453c1ee7dd89321f10186aedaa35b9a2e326f6569e7dcaa04f` |
| `cudart-llama-bin-win-cuda-12.4-x64.zip` | the same release page | unzip into `tools\llama.cpp\` | `8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6` |

Check a file in PowerShell:

```powershell
(Get-FileHash models\qwen2.5-1.5b-instruct-q4_k_m.gguf -Algorithm SHA256).Hash
```

## 10.3 Starting Agent Narada (one command)

Open PowerShell in the `NARADA` folder and run:

```powershell
python main.py
```

`main.py` uses only Python's standard library (it must work before anything
is installed). It does, in order, and every step is safe to repeat:

| Step | What happens |
|------|--------------|
| 1 | checks the Python version (3.10 or newer) |
| 2 | creates the virtual environment `.venv` if it does not exist |
| 3 | installs the packages in `requirements.txt` (Django, Django REST Framework, pypdf, olefile …) |
| 4 | creates or updates the database tables (`migrate`; existing data is never deleted) |
| 5 | if no Super Admin exists, asks you to create one |
| 6 | creates a new random secret key, starts `llama-server.exe` with the model on `127.0.0.1:8080`, and waits until it is ready (its output goes to `tools\llama-server.log`) |
| 7 | starts Django on `127.0.0.1:8000` with the same key, and opens the browser |

If the model file or `llama-server.exe` is missing, `main.py` says so and
Agent Narada starts without the model (the chat then replies that the model
is not running).

Press **Ctrl+C** to stop. The model server is always stopped as well.

`python main.py --no-browser` starts everything without opening a browser.

## 10.4 One-time setup: hourly chat cleanup

Run once, from the `NARADA` folder:

```powershell
powershell -ExecutionPolicy Bypass -File schedule_chat_cleanup.ps1
```

This creates the Task Scheduler task **"Agent Narada - delete old chats"**,
which runs `manage.py delete_old_chats` every hour. To remove it:

```powershell
Unregister-ScheduledTask -TaskName "Agent Narada - delete old chats" -Confirm:$false
```

## 10.5 Everyday administration

| Task | How |
|------|-----|
| Create accounts | Super Admin → User Management → Add an account (choose the role) |
| Add a document | Upload Document (Admin: then the Super Admin approves it) |
| Correct who may read a document | Document Approval / My Documents → Change readers |
| Remove a document | Document Approval → Delete (its passages are removed too) |
| Re-read all documents after a code improvement | `python backend\manage.py reprocess_documents` |
| Run the automated tests | `cd backend` then `..\.venv\Scripts\python.exe manage.py test` |
| Back up | copy `backend\db.sqlite3`, `backend\media\` and `backend\.secret_key` while Agent Narada is stopped |

Before real use, delete the 11 fictional sample documents on the Document
Approval page, so fictional information is never mistaken for real UPES
information.

## 10.6 Troubleshooting

| Problem | Cause and fix |
|---------|---------------|
| "port 8000 is already in use" | Agent Narada is already running, or another program uses the port. Close the other window. |
| "port 8080 is already in use" | Another llama-server is running. Close it (Task Manager → llama-server.exe), then start again. |
| The chat says "Agent Narada's language model is not running right now" | The model did not start. Read `tools\llama-server.log`; check that the model file and the CUDA files are in place and the graphics driver is current. |
| "Too many failed attempts. Please wait 15 minutes" | 5 wrong passwords for that username. Wait 15 minutes, or restart the server (the count is kept in memory). |
| An upload is refused: "No text could be read" | The PDF is scanned (a picture). Upload a version with real text. |
| A role gets "couldn't find" for something in a document | Check "Who may read" for that document (Document Approval → Change readers), and that it is Approved. |
| PowerShell refuses to run scripts | Run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| The page looks old after an update | The `?v=` number changes automatically; if needed, press Ctrl+F5. |

## 10.7 Doing the steps by hand

`main.py` runs these for you; they are listed so each can be explained.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python backend\manage.py migrate
python backend\manage.py createsuperuser
tools\llama.cpp\llama-server.exe -m models\qwen2.5-1.5b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8080 -ngl 99 -c 4096 --api-key <a secret>
$env:NARADA_LLM_API_KEY = "<the same secret>"
python backend\manage.py runserver 127.0.0.1:8000
```
