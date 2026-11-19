"""POS System - server control.

  control.py window            opens the control window
  control.py start             starts the API (Django, port 8100) and the web app (Vite, port 5180)
  control.py stop              stops both
  control.py restart           stops, then starts both
  control.py status            shows whether each is up (no password needed)
  control.py change-password   changes the server control password
  control.py phones-on         lets phones/tablets on the shop network use the web app (https, for cameras)
  control.py phones-off        back to this computer only

Start, Stop, Restart, Change password and closing the window all need the server control password.
Closing the window stops the servers. The password is chosen the first time it is asked for and stored
only as a PBKDF2-SHA256 hash in .run/control-password (outside anything the servers serve). Five wrong
passwords in a row lock the controls for 15 minutes. Every action is written to .run/control.log.

This password protects the server switches only; it is separate from the till/back-office logins and from
the database credentials.
"""
import getpass
import hashlib
import hmac
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, ".run")
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")
VENV_PY = os.path.join(BACKEND, ".venv", "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
PASSWORD_FILE = os.path.join(RUN, "control-password")
LOCK_FILE = os.path.join(RUN, "control-lock")
EVENT_LOG = os.path.join(RUN, "control.log")
ITERATIONS = 600_000
MAX_FAILS = 5
LOCK_SECONDS = 15 * 60
LAN_FILE = os.path.join(RUN, "lan-mode")  # present = "Phones on"

SERVERS = {
    "api": {"label": "API + admin", "port": 8100, "path": "/admin/"},
    "web": {"label": "POS + back office", "port": 5180, "path": "/"},
}
# If another program already uses a port, the next free one is used and remembered here.
PORTS_FILE = os.path.join(RUN, "ports.json")


def _set_port(name, port):
    SERVERS[name]["port"] = port
    SERVERS[name]["url"] = f"http://localhost:{port}{SERVERS[name]['path']}"


def load_ports():
    import json
    try:
        with open(PORTS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    for name in SERVERS:
        _set_port(name, int(saved.get(name, SERVERS[name]["port"])))


def save_ports():
    import json
    os.makedirs(RUN, exist_ok=True)
    with open(PORTS_FILE, "w", encoding="utf-8") as f:
        json.dump({n: s["port"] for n, s in SERVERS.items()}, f)


load_ports()


class Cancelled(Exception):
    pass


def lan_on():
    return os.path.exists(LAN_FILE)


def lan_addresses():
    """This computer's address(es) on the local network (no traffic is sent)."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def phone_urls():
    return [f"https://{ip}:{SERVERS['web']['port']}/#/count" for ip in lan_addresses()]


# ------------------------------------------------------------------ event log
def event(text):
    os.makedirs(RUN, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "?"
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(f"{stamp}  [{user}]  {text}\n")


# ------------------------------------------------------------------ control password
def hash_password(password, salt_hex, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8", "replace"), bytes.fromhex(salt_hex), iterations, 32).hex()


def load_password_record():
    values = {}
    with open(PASSWORD_FILE, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, _, v = line.strip().partition("=")
                values[k] = v
    return values


def verify(password):
    try:
        if not os.path.exists(PASSWORD_FILE):
            return False
        p = load_password_record()
        expected = hash_password(password, p.get("salt", ""), int(p.get("iterations", ITERATIONS)))
        return hmac.compare_digest(expected.encode(), p.get("hash", "").encode())
    except Exception:
        return False


def policy_problem(p):
    if len(p) < 12:
        return "at least 12 characters"
    if not re.search("[A-Z]", p) or not re.search("[a-z]", p):
        return "upper- and lower-case letters"
    if not re.search("[0-9]", p):
        return "a number"
    if not re.search("[^A-Za-z0-9]", p):
        return "a symbol"
    return None


def write_password(password):
    salt = secrets.token_hex(16)
    os.makedirs(RUN, exist_ok=True)
    tmp = PASSWORD_FILE + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# POS System - server control password (hash only). Delete this file to choose a new one.\n")
        f.write("algorithm=PBKDF2-HMAC-SHA256\niterations=%d\nsalt=%s\nhash=%s\nsetAt=%s\n" % (
            ITERATIONS, salt, hash_password(password, salt, ITERATIONS),
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")))
    os.replace(tmp, PASSWORD_FILE)


def lock_remaining():
    try:
        with open(LOCK_FILE, encoding="utf-8") as f:
            return max(0, int(f.read().strip()) - int(time.time()))
    except (OSError, ValueError):
        return 0


def record_failure(what):
    event(f"{what} refused: wrong control password")
    try:
        with open(EVENT_LOG, encoding="utf-8") as f:
            last = f.readlines()[-MAX_FAILS:]
        if sum("refused: wrong control password" in x for x in last) >= MAX_FAILS:
            with open(LOCK_FILE, "w", encoding="utf-8") as f:
                f.write(str(int(time.time()) + LOCK_SECONDS))
            event("Control password locked for 15 minutes")
    except OSError:
        pass


def new_password(read):
    a = read("New server control password")
    if a is None:
        raise Cancelled()
    problem = policy_problem(a)
    if problem:
        raise RuntimeError("The control password needs " + problem + ". Nothing was done.")
    b = read("Repeat the new password")
    if b is None:
        raise Cancelled()
    if a != b:
        raise RuntimeError("The two passwords do not match. Nothing was done.")
    write_password(a)


def assert_password(what, read):
    """Ask for the control password (choose it the first time). Raises Cancelled or RuntimeError."""
    if not os.path.exists(PASSWORD_FILE):
        new_password(read)
        event("Control password set")
        return
    left = lock_remaining()
    if left > 0:
        raise RuntimeError(f"Too many wrong passwords. Try again in {left // 60 + 1} minute(s).")
    pw = read("Server control password")
    if pw is None:
        raise Cancelled()
    if verify(pw):
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass
        return
    record_failure(what)
    raise RuntimeError("Wrong control password.")


def change_password(read):
    assert_password("Change password", read)
    new_password(read)
    event("Control password changed")
    return ["Control password changed."]


# ------------------------------------------------------------------ helpers
def port_open(port):
    """True if something listens on localhost:port (IPv4 or IPv6 - Node may bind ::1 only)."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
    return False


def is_ours(name, port):
    """Is the program on this port our own API / web app (e.g. started outside this tool)?"""
    import urllib.request
    url = f"http://127.0.0.1:{port}/api/branding/" if name == "api" else f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            body = r.read(4000).decode("utf-8", "replace")
    except Exception:
        try:  # web app with "Phones on" answers https
            import ssl
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(url.replace("http:", "https:"), timeout=1.5, context=ctx) as r:
                body = r.read(4000).decode("utf-8", "replace")
        except Exception:
            return False
    return ('"display_name"' in body or '"name"' in body) if name == "api" else "/src/main.tsx" in body


def free_port(start):
    for port in range(start, start + 200):
        if not port_open(port):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
    raise RuntimeError(f"No free port found from {start}.")


def claim_port(name):
    """Keep the usual port unless another program holds it; then move to the next free one."""
    srv = SERVERS[name]
    note = ""
    if port_open(srv["port"]) and read_pid(name) is None and not is_ours(name, srv["port"]):
        old = srv["port"]
        _set_port(name, free_port(old + 1))
        save_ports()
        note = f" (port {old} is used by another program, so it moved to {srv['port']})"
        event(f"{srv['label']}: port {old} busy, using {srv['port']}")
    return note


def pid_file(name):
    return os.path.join(RUN, f"{name}.pid")


def read_pid(name):
    try:
        with open(pid_file(name)) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def uptime(name):
    try:
        t = datetime.fromtimestamp(os.path.getmtime(pid_file(name)))
    except OSError:
        return ""
    if not port_open(SERVERS[name]["port"]):
        return ""
    secs = int((datetime.now() - t).total_seconds())
    h, rem = divmod(secs, 3600)
    return f"{h:d}:{rem // 60:02d}:{rem % 60:02d}"


def check_setup():
    problems = []
    if not os.path.exists(VENV_PY):
        problems.append("backend\\.venv is missing - see README (python -m venv .venv, pip install -r requirements.txt)")
    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        problems.append("frontend\\node_modules is missing - run: npm install (in the frontend folder)")
    return problems


def kill_tree(pid):
    if os.name == "nt":  # npm starts node as a child; /T ends the whole tree
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            pass


# ------------------------------------------------------------------ start / stop (no password checks here)
def start_one(name):
    srv = SERVERS[name]
    note = claim_port(name)
    if port_open(srv["port"]):
        mine = read_pid(name) is not None
        return f"{srv['label']}: already running on port {srv['port']}" + ("" if mine else " (started outside this tool)")
    os.makedirs(RUN, exist_ok=True)
    log = open(os.path.join(RUN, f"{name}.log"), "a", encoding="utf-8")
    log.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} start =====\n")
    log.flush()
    if name == "api":
        cmd = [VENV_PY, "manage.py", "runserver", f"127.0.0.1:{srv['port']}"]
        cwd = BACKEND
    else:
        # Host comes from vite.config.ts: 127.0.0.1, or the shop network (https) when phones are on.
        cmd = ["npm.cmd" if os.name == "nt" else "npm", "run", "dev"]
        cwd = FRONTEND
    api, web = SERVERS["api"]["port"], SERVERS["web"]["port"]
    env = {**os.environ, "POS_LAN": "1" if (name == "web" and lan_on()) else "0",
           # Each side learns where the other one is, whichever ports they ended up on.
           "POS_API": f"http://127.0.0.1:{api}", "POS_API_PORT": str(api), "POS_WEB_PORT": str(web),
           "POS_WEB_URL": f"{'https' if lan_on() else 'http'}://localhost:{web}/"}
    p = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW, start_new_session=(os.name != "nt"), env=env)
    with open(pid_file(name), "w") as f:
        f.write(str(p.pid))
    for _ in range(60):  # wait up to ~30 s for the port
        if port_open(srv["port"]):
            if name == "web" and lan_on():
                return f"{srv['label']}: started on https://localhost:{srv['port']}/{note} - phones: " + ", ".join(phone_urls())
            return f"{srv['label']}: started on {srv['url']}{note}"
        if p.poll() is not None:
            os.remove(pid_file(name))
            return f"{srv['label']}: FAILED to start - see .run\\{name}.log"
        time.sleep(0.5)
    return f"{srv['label']}: started but port {srv['port']} is not answering yet - see .run\\{name}.log"


def stop_one(name):
    srv = SERVERS[name]
    pid = read_pid(name)
    if pid is None:
        if port_open(srv["port"]):
            return f"{srv['label']}: running on port {srv['port']} but was not started by this tool - stop it where it was started"
        return f"{srv['label']}: already stopped"
    kill_tree(pid)
    try:
        os.remove(pid_file(name))
    except OSError:
        pass
    for _ in range(20):
        if not port_open(srv["port"]):
            break
        time.sleep(0.25)
    return f"{srv['label']}: stopped"


def _start():
    problems = check_setup()
    if problems:
        return problems
    # Settle both ports first: each server is told where the other one is.
    for n in SERVERS:
        if read_pid(n) is None:
            claim_port(n)
    out = [start_one(n) for n in SERVERS]
    event("Started: " + " | ".join(out))
    return out


def _stop():
    out = [stop_one(n) for n in reversed(list(SERVERS))]
    event("Stopped: " + " | ".join(out))
    return out


def status():
    out = []
    for name, srv in SERVERS.items():
        up = port_open(srv["port"])
        extra = f"  up {uptime(name)}" if up and uptime(name) else ""
        out.append(f"{srv['label']:<18} port {srv['port']}  {'RUNNING' if up else 'stopped'}{extra}")
    if lan_on():
        out.append("Phones ON (https on the shop network): " + (", ".join(phone_urls()) or "no network address found"))
    else:
        out.append("Phones off (this computer only)")
    return out


def _phones(on):
    os.makedirs(RUN, exist_ok=True)
    if on:
        open(LAN_FILE, "w").close()
    elif lan_on():
        os.remove(LAN_FILE)
    event("Phones " + ("ON" if on else "off"))
    out = [f"Phones {'ON' if on else 'off'}."]
    if port_open(SERVERS["web"]["port"]):  # restart the web app so the change takes effect
        out += [stop_one("web"), start_one("web")]
    if on:
        out.append("Phones open the address above and accept the security warning once (the certificate is "
                   "made on this computer). Windows may ask to allow Node.js through the firewall on private networks.")
    return out


ACTIONS = {"start": ("Start", _start), "stop": ("Stop", _stop), "restart": ("Restart", lambda: _stop() + _start()),
           "phones-on": ("Phones on", lambda: _phones(True)), "phones-off": ("Phones off", lambda: _phones(False))}


def guarded(action, read):
    """Run start/stop/restart only after the control password checks out."""
    label, fn = ACTIONS[action]
    assert_password(label, read)
    return fn()


# ------------------------------------------------------------------ window
def window(title):
    import threading
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=16)
    frame.pack()
    ttk.Label(frame, text=title, font=("Segoe UI", 14, "bold")).pack(pady=(0, 4))
    ttk.Label(frame, text="Start, Stop, Restart and closing need the control password.", foreground="gray").pack(pady=(0, 8))
    rows = {}
    for name, srv in SERVERS.items():
        r = ttk.Frame(frame)
        r.pack(fill="x", pady=2)
        ttk.Label(r, text=f"{srv['label']}  (port {srv['port']})", width=28).pack(side="left")
        lamp = tk.Label(r, text="●", font=("Segoe UI", 14))
        lamp.pack(side="left")
        state = ttk.Label(r, text="", width=20)
        state.pack(side="left")
        rows[name] = (lamp, state)
    msg = ttk.Label(frame, text="", foreground="gray", wraplength=420, justify="left")
    msg.pack(fill="x", pady=(8, 8))
    buttons = ttk.Frame(frame)
    buttons.pack()

    def ask(prompt):
        """Modal password box on the UI thread; returns the text or None if cancelled."""
        result = {"v": None}
        d = tk.Toplevel(root)
        d.title(title)
        d.transient(root)
        d.resizable(False, False)
        ttk.Label(d, text=prompt, padding=(16, 14, 16, 4)).pack(anchor="w")
        var = tk.StringVar()
        e = ttk.Entry(d, textvariable=var, show="•", width=34)
        e.pack(padx=16, pady=4)
        bar = ttk.Frame(d, padding=(16, 8, 16, 14))
        bar.pack(fill="x")

        def ok(_=None):
            result["v"] = var.get()
            d.destroy()

        ttk.Button(bar, text="OK", command=ok).pack(side="right")
        ttk.Button(bar, text="Cancel", command=d.destroy).pack(side="right", padx=6)
        e.bind("<Return>", ok)
        d.bind("<Escape>", lambda _: d.destroy())
        e.focus_set()
        d.grab_set()
        root.wait_window(d)
        return result["v"]

    def refresh():
        for name, (lamp, state) in rows.items():
            up = port_open(SERVERS[name]["port"])
            lamp.config(fg="#0ca30c" if up else "#d03b3b")
            state.config(text=("Running  " + uptime(name)).strip() if up else "Stopped")
        root.after(1000, refresh)

    def busy(on):
        for b in btns:
            b.state(["disabled"] if on else ["!disabled"])

    def run(action):
        label = ACTIONS[action][0]
        try:
            assert_password(label, ask)  # on the UI thread (dialog)
        except Cancelled:
            return
        except RuntimeError as e:
            msg.config(text=str(e))
            return

        def work():
            busy(True)
            msg.config(text=f"{label}...")
            msg.config(text="\n".join(ACTIONS[action][1]()))
            busy(False)
        threading.Thread(target=work, daemon=True).start()

    def do_change():
        try:
            msg.config(text="\n".join(change_password(ask)))
        except Cancelled:
            pass
        except RuntimeError as e:
            msg.config(text=str(e))

    btns = [
        ttk.Button(buttons, text="Start", command=lambda: run("start")),
        ttk.Button(buttons, text="Stop", command=lambda: run("stop")),
        ttk.Button(buttons, text="Restart", command=lambda: run("restart")),
        ttk.Button(buttons, text="Open POS", command=lambda: webbrowser.open(SERVERS["web"]["url"])),
        ttk.Button(buttons, text="Back office", command=lambda: webbrowser.open(SERVERS["web"]["url"] + "#/office")),
        ttk.Button(buttons, text="Phones on/off", command=lambda: run("phones-off" if lan_on() else "phones-on")),
        ttk.Button(buttons, text="Change password", command=do_change),
    ]
    for b in btns:
        b.pack(side="left", padx=3)

    def on_close():
        """Closing needs the password and always stops the servers this tool started."""
        try:
            assert_password("Close window", ask)
        except Cancelled:
            return
        except RuntimeError as e:
            messagebox.showerror(title, str(e))
            return
        if any(read_pid(n) for n in SERVERS):
            msg.config(text="Stopping servers...")
            root.update()
            _stop()
        event("Control window closed")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    refresh()
    root.mainloop()


def console_read(prompt):
    try:
        return getpass.getpass(prompt + ": ")
    except (EOFError, KeyboardInterrupt):
        return None


def main():
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "window"
    title = sys.argv[2] if len(sys.argv) > 2 else "POS System server control"
    try:
        if cmd == "window":
            window(title)
        elif cmd == "status":
            print("\n".join(status()))
        elif cmd in ACTIONS:
            print("\n".join(guarded(cmd, console_read)))
        elif cmd == "change-password":
            print("\n".join(change_password(console_read)))
        else:
            print(__doc__)
            sys.exit(2)
    except Cancelled:
        print("Cancelled. Nothing was done.")
        sys.exit(1)
    except RuntimeError as e:
        print(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
