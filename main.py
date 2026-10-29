"""
AGENT NARADA - one-command launcher

Run:   python main.py

It prepares everything and then starts the whole project:

  1. checks the Python version
  2. creates the virtual environment (.venv) if it does not exist
  3. installs the packages listed in requirements.txt
  4. creates / updates the SQLite database tables
  5. makes sure a Super Admin account exists
  6. starts the language model (llama-server + Qwen2.5-1.5B-Instruct)
  7. starts the Django server and opens the browser

Every step is safe to repeat, so the same command is used for the first
run and for every run after it. Press Ctrl+C to stop the server.

This file uses only Python's standard library, because it has to work
before any package has been installed.
"""

import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import venv
import webbrowser
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

# ---------- Where things are ----------
ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"

# The virtual environment's own Python. Running this file directly is what
# "activating the environment" does, so no activation step is needed.
if os.name == "nt":  # Windows
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"

# The language model. llama-server.exe (from llama.cpp) runs the Qwen
# model file and answers on LLM_PORT. Both were downloaded from their
# official pages; see README.txt.
LLAMA_SERVER = ROOT / "tools" / "llama.cpp" / "llama-server.exe"
MODEL_FILE = ROOT / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
LLM_PORT = 8080  # must match LLM_SERVER_URL in backend/config/settings.py
LLM_LOG = ROOT / "tools" / "llama-server.log"

TOTAL_STEPS = 7


def step(number, message):
    print(f"\n[{number}/{TOTAL_STEPS}] {message}")


def stop(message):
    """Print a clear reason and end the program."""
    print(f"\nSTOPPED: {message}")
    sys.exit(1)


def run(command, **options):
    """Run a command and stop the launcher if it fails."""
    result = subprocess.run([str(part) for part in command], **options)
    if result.returncode != 0:
        stop("the command above failed. Fix the error it printed, then run main.py again.")
    return result


def manage(*arguments, **options):
    """Run a Django management command with the environment's Python."""
    return run([VENV_PYTHON, "manage.py", *arguments], cwd=BACKEND_DIR, **options)


def port_is_in_use(port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        return connection.connect_ex((HOST, port)) == 0


# ---------- The steps ----------


def check_python():
    step(1, "Checking Python")
    if sys.version_info < (3, 10):
        stop("Python 3.10 or newer is required. You are using " + sys.version.split()[0])
    print(f"      Python {sys.version.split()[0]}")


def create_environment():
    step(2, "Virtual environment")
    if VENV_PYTHON.exists():
        print("      .venv already exists")
        return
    print("      creating .venv (first run only, this takes a moment)")
    venv.create(VENV_DIR, with_pip=True)


def install_requirements():
    step(3, "Installing packages from requirements.txt")
    # pip skips every package that is already installed, so this is quick
    # on every run after the first.
    run(
        [VENV_PYTHON, "-m", "pip", "install", "-r", REQUIREMENTS,
         "--quiet", "--disable-pip-version-check"]
    )
    print("      all packages are installed")


def prepare_database():
    step(4, "Preparing the SQLite database")
    # migrate creates the tables on the first run and applies only the
    # new changes afterwards. It never deletes existing data.
    manage("migrate", "--verbosity", "0")
    print("      database is up to date")


def ensure_super_admin():
    step(5, "Checking for a Super Admin account")
    result = manage(
        "shell", "--no-imports", "-c",
        "from accounts.models import Role, User;"
        "print(User.objects.filter(role=Role.SUPER_ADMIN, is_active=True).count())",
        capture_output=True, text=True,
    )
    if int(result.stdout.split()[-1]) > 0:
        print("      a Super Admin exists")
        return

    create_later = "Create one with:  python backend\\manage.py createsuperuser"

    if not sys.stdin.isatty():
        # Started by another program, so nobody can type a password.
        print(f"      none yet. {create_later}")
        return

    print("      none yet. Create the first Super Admin now.")
    print("      (the password stays invisible while you type)\n")
    # Not run through manage(): skipping this step must not stop the launcher.
    result = subprocess.run(
        [str(VENV_PYTHON), "manage.py", "createsuperuser"], cwd=BACKEND_DIR
    )
    if result.returncode != 0:
        print(f"\n      no account was created. {create_later}")


def model_is_ready():
    """True once llama-server has loaded the model. Its /health address
    answers "200 OK" only when it is ready for questions."""
    opener = build_opener(ProxyHandler({}))  # this computer: never use a proxy
    try:
        with opener.open(f"http://{HOST}:{LLM_PORT}/health", timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def start_language_model(api_key):
    """Start llama-server with the model. Returns the running process, or
    None if it could not start (Agent Narada still runs; the chat then
    says the model is not running)."""
    step(6, "Starting the language model (Qwen2.5-1.5B-Instruct)")

    for path, what in ((LLAMA_SERVER, "llama-server.exe"), (MODEL_FILE, "the model file")):
        if not path.exists():
            print(f"      {what} was not found at {path}")
            print("      Agent Narada will start without its language model.")
            return None

    if port_is_in_use(LLM_PORT):
        stop(
            f"port {LLM_PORT} is already in use. Another llama-server may be "
            f"running - close it first, then run main.py again."
        )

    command = [
        LLAMA_SERVER,
        "-m", MODEL_FILE,
        "--host", HOST,            # this computer only, never the network
        "--port", LLM_PORT,
        "-ngl", "99",              # put every layer of the model on the graphics card
        "-c", "4096",              # how much text it reads at once (question + passages)
        "--api-key", api_key,      # requests without this key are refused
    ]
    # llama-server prints a lot. It goes to a log file, read when
    # something goes wrong, instead of filling this window.
    log = open(LLM_LOG, "w", encoding="utf-8")
    process = subprocess.Popen([str(part) for part in command], stdout=log, stderr=log)

    print("      loading the model", end="")
    for _ in range(120):  # wait up to 60 seconds
        if model_is_ready():
            print(" - ready")
            return process
        if process.poll() is not None:  # it stopped by itself: an error
            break
        print(".", end="")
        time.sleep(0.5)

    print(" - FAILED")
    print(f"      see {LLM_LOG} for the reason.")
    print("      Agent Narada will start without its language model.")
    stop_language_model(process)
    return None


def stop_language_model(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def start_server(open_browser, api_key):
    step(7, "Starting Agent Narada")
    if port_is_in_use():
        stop(
            f"port {PORT} is already in use. Agent Narada may already be "
            f"running at {URL} - close the other one first."
        )

    def open_when_ready():
        # Wait until Django accepts connections, then open the browser.
        for _ in range(60):
            if port_is_in_use():
                webbrowser.open(URL)
                return
            time.sleep(0.5)

    if open_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()

    # Django reads the language model's key from this environment variable
    # (LLM_API_KEY in settings.py). It exists only while Django runs.
    environment = dict(os.environ, NARADA_LLM_API_KEY=api_key)

    print(f"      open {URL} in your browser")
    print("      press Ctrl+C to stop\n")
    try:
        subprocess.run(
            [str(VENV_PYTHON), "manage.py", "runserver", f"{HOST}:{PORT}"],
            cwd=BACKEND_DIR,
            env=environment,
        )
    except KeyboardInterrupt:
        pass


def main():
    # "python main.py --no-browser" starts everything without opening a browser.
    open_browser = "--no-browser" not in sys.argv

    # Show each line immediately, in the right order, even when the output
    # is being captured by another program.
    sys.stdout.reconfigure(line_buffering=True)

    print("=" * 50)
    print(" AGENT NARADA")
    print("=" * 50)

    check_python()
    create_environment()
    install_requirements()
    prepare_database()
    ensure_super_admin()

    # A new random secret for every run, shared only by llama-server and
    # Django. Nobody has to type or remember it, and it is never saved.
    api_key = secrets.token_urlsafe(32)
    model_process = start_language_model(api_key)
    try:
        start_server(open_browser, api_key)
    finally:
        # Whatever happens, do not leave the model running in the background.
        stop_language_model(model_process)
        print("\nAgent Narada stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl+C during one of the setup steps.
        print("\nStopped.")
