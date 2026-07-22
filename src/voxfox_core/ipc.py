#!/usr/bin/env python3
# Copyright (C) 2025 - Daniël Vos
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


"""voxfox_core.ipc — Single-instance IPC, the socket server, and the CLI dispatcher."""


import fcntl, os, socket, stat, sys, threading
from .a11y import _clipboard_set
from .common import APP_NAME, LOCK_FILE, PID_FILE, RUNTIME_DIR, SOCKET_PATH, _, load_translations, log
from .ocr import OCR_SUPPORTED_EXTS, _tess_lang, ocr_file
from .state import load_state



# ── IPC ────────────────────────────────────────────────────────────────────────
def _ensure_runtime_dir():
    try:
        os.makedirs(RUNTIME_DIR, mode=0o700, exist_ok=True)
        # The /tmp fallback path is predictable; make sure nobody planted a
        # symlink or foreign directory there before we put our socket in it.
        st_ = os.lstat(RUNTIME_DIR)
        if stat.S_ISLNK(st_.st_mode) or st_.st_uid != os.getuid():
            raise RuntimeError("runtime dir is a symlink or not ours")
        os.chmod(RUNTIME_DIR, 0o700)
    except Exception as e:
        log.warning(f"Could not create runtime dir {RUNTIME_DIR}: {e}")


def send_command(cmd, timeout=2.0):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(SOCKET_PATH)
        s.sendall((cmd + "\n").encode("utf-8"))
        data = s.recv(1024)
        s.close()
        return data.decode("utf-8", errors="replace").strip()
    except Exception as e:
        log.debug(f"send_command failed: {e}")
        return None


def is_instance_running():
    if not os.path.exists(SOCKET_PATH):
        return False
    return send_command("ping", timeout=0.5) == "pong"


# Singleton lock: held for the lifetime of the running instance.
# Two simultaneous voxfox starts can't both acquire LOCK_EX, so the loser
# can safely conclude that the winner is the active instance.
_singleton_lock_fd = None


def acquire_singleton_lock():
    """Try to acquire the singleton lock. Returns True on success.
    The lock is released automatically when the process exits."""
    global _singleton_lock_fd
    _ensure_runtime_dir()
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        _singleton_lock_fd = fd  # keep open
        return True
    except (OSError, BlockingIOError):
        return False


class IPCServer:
    def __init__(self, app):
        self.app     = app
        self.sock    = None
        self.thread  = None
        self.running = False

    def start(self):
        _ensure_runtime_dir()
        if os.path.exists(SOCKET_PATH):
            try:
                if not is_instance_running():
                    os.unlink(SOCKET_PATH)
            except Exception:
                try:
                    os.unlink(SOCKET_PATH)
                except Exception:
                    pass
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.bind(SOCKET_PATH)
            os.chmod(SOCKET_PATH, 0o600)
            self.sock.listen(4)
        except OSError as e:
            log.error(f"Could not bind IPC socket: {e}")
            return False
        try:
            with open(PID_FILE, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass
        self.running = True
        self.thread  = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        log.info(f"IPC listening on {SOCKET_PATH}")
        return True

    def stop(self):
        self.running = False
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        for path in (SOCKET_PATH, PID_FILE, LOCK_FILE):
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                pass

    def _serve(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                break
            try:
                conn.settimeout(2.0)
                data  = conn.recv(256).decode("utf-8", errors="replace").strip()
                reply = self._handle(data)
                conn.sendall((reply + "\n").encode("utf-8"))
            except Exception as e:
                log.debug(f"IPC client error: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def _handle(self, cmd):
        cmd = (cmd or "").lower().strip()
        if cmd == "ping":
            return "pong"
        if cmd == "read":
            self.app.root.after(0, self.app.do_read)
            return "ok"
        if cmd == "stop":
            self.app.root.after(0, self.app.do_stop)
            return "ok"
        if cmd in ("toggle-slot", "switch", "swap"):
            self.app.root.after(0, self.app.do_toggle_slot)
            return "ok"
        if cmd in ("hover-toggle", "hover"):
            self.app.root.after(0, self.app.do_hover)
            return "ok"
        if cmd in ("whisper-toggle", "whisper", "speak"):
            self.app.root.after(0, self.app.do_whisper)
            return "ok"
        if cmd in ("ocr-select", "select", "region"):
            self.app.root.after(0, self.app.do_ocr_select)
            return "ok"
        if cmd in ("read-page", "page"):
            self.app.root.after(0, self.app.do_read_page)
            return "ok"
        if cmd in ("live-toggle", "live"):
            log.info("ipc: received live-toggle command")
            self.app.root.after(0, self.app.do_live_toggle)
            return "ok"
        if cmd in ("pause-toggle", "pause", "resume"):
            self.app.root.after(0, self.app.do_pause)
            return "ok"
        if cmd == "quit":
            self.app.root.after(0, self.app.on_close)
            return "ok"
        return f"unknown: {cmd}"


# ── GUI ────────────────────────────────────────────────────────────────────────

def run_cli(args):
    # --ocr werkt standalone (geen draaiende instantie nodig) zodat
    # de gebruiker een bestand kan voorlezen zonder de GUI te starten.
    if getattr(args, "ocr", None):
        load_translations()
        file_path = args.ocr
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in OCR_SUPPORTED_EXTS:
            print(f"Niet-ondersteund bestandstype: {ext}. "
                  f"Gebruik: {', '.join(sorted(OCR_SUPPORTED_EXTS))}",
                  file=sys.stderr)
            sys.exit(1)
        # Laad actieve taalinstellingen voor de Tesseract-taalcode
        state = load_state()
        active_cfg = state[state.get("active_slot", "slot1")]
        tess_lang  = _tess_lang(active_cfg.get("lang", "English"))
        print(f"OCR: {file_path} (taal: {tess_lang})")
        text, err = ocr_file(
            file_path,
            tess_lang=tess_lang,
            progress_cb=lambda m: print(m))
        if err:
            print(f"Fout: {err}", file=sys.stderr)
            sys.exit(1)
        if not text:
            print(_("No text found."), file=sys.stderr)
            sys.exit(0)
        print(f"--- {len(text.split())} woorden gevonden ---")
        # Stuur de tekst naar de draaiende VoxFox-instantie als die er is,
        # anders gewoon printen naar stdout (bruikbaar in scripts).
        if is_instance_running():
            # Zet tekst op klembord en stuur read-commando
            if _clipboard_set(text):
                reply = send_command("read")
                if reply == "ok":
                    print("Voorgelezen via draaiende VoxFox.")
                    sys.exit(0)
        # Geen draaiende instantie: print de tekst zodat scripts hem kunnen gebruiken
        print(text)
        sys.exit(0)

    cmd_map = {
        "read":           "read",
        "stop":           "stop",
        "toggle_slot":    "toggle-slot",
        "hover_toggle":   "hover-toggle",
        "whisper_toggle": "whisper-toggle",
        "ocr_select":     "ocr-select",
        "read_page":      "read-page",
        "live_toggle":    "live-toggle",
        "pause":          "pause-toggle",
        "status":         "ping",
        "quit":           "quit",
    }
    chosen = next((ipc for attr, ipc in cmd_map.items()
                   if getattr(args, attr, False)), None)
    if chosen is None:
        return False

    reply = send_command(chosen)
    if chosen == "ping":
        if reply == "pong":
            print(f"{APP_NAME} is running (PID file: {PID_FILE})")
            sys.exit(0)
        else:
            print(f"{APP_NAME} is not running")
            sys.exit(1)
    if reply is None:
        print(f"Error: no running {APP_NAME} instance found.", file=sys.stderr)
        print(f"Start {APP_NAME} first (run 'voxfox' without arguments).",
              file=sys.stderr)
        sys.exit(1)
    if reply.startswith("unknown"):
        print(f"Error: {reply}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


__all__ = [
    "_ensure_runtime_dir",
    "send_command",
    "is_instance_running",
    "_singleton_lock_fd",
    "acquire_singleton_lock",
    "IPCServer",
    "run_cli",
]
