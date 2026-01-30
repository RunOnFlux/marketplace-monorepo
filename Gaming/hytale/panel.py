#!/usr/bin/env python3
from __future__ import annotations

import base64
import cgi
import json
import os
import re
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def env_str(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default)).strip()


PANEL_USERNAME = env_str("HYTALE_PANEL_USERNAME", "admin")
PANEL_PASSWORD = env_str("HYTALE_PANEL_PASSWORD", "")

CONSOLE_FILE = Path(env_str("HYTALE_CONSOLE_FILE", "/data/console.commands"))
LOG_FILE = Path(env_str("HYTALE_LOG_FILE", "/data/logs/hytale-server.log"))
PID_FILE = Path(env_str("HYTALE_SERVER_PID_FILE", "/tmp/hytale-server.pid"))
DOWNLOADER_PID_FILE = Path(env_str("HYTALE_DOWNLOADER_PID_FILE", "/tmp/hytale-downloader.pid"))
AUTH_HELPER_PID_FILE = Path(env_str("HYTALE_AUTH_HELPER_PID_FILE", "/tmp/hytale-auth.pid"))
TRIGGER_DOWNLOAD_FILE = Path(env_str("HYTALE_TRIGGER_DOWNLOAD_FILE", "/data/.hytale-flux.trigger-download"))
TRIGGER_AUTH_FILE = Path(env_str("HYTALE_TRIGGER_AUTH_FILE", "/data/.hytale-flux.trigger-auth"))

AUTH_STATE_PATH = Path(env_str("HYTALE_AUTH_STATE_PATH", "/data/auth/state.json"))
VERSION_MARKER_PATH = Path(env_str("HYTALE_VERSION_MARKER_PATH", "/data/.hytale-flux.version.json"))

SERVER_DIR = Path(env_str("HYTALE_SERVER_DIR", "/data/Server"))
ASSETS_PATH = Path(env_str("HYTALE_ASSETS_PATH", "/data/Assets.zip"))
JAR_PATH = Path(env_str("HYTALE_JAR_PATH", "/data/Server/HytaleServer.jar"))

MODS_DIR = Path("/data/Server/mods")
PLUGINS_DIR = Path("/data/Server/plugins")

GAME_BIND = env_str("HYTALE_BIND", "0.0.0.0:5520")
AUTH_MODE = env_str("HYTALE_AUTH_MODE", "authenticated")


def decode_basic_auth(header_value: str) -> tuple[str, str] | None:
    if not header_value:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    try:
        raw = base64.b64decode(parts[1].strip()).decode("utf-8", errors="replace")
    except Exception:
        return None
    if ":" not in raw:
        return None
    username, password = raw.split(":", 1)
    return username, password


def tail_lines(path: Path, *, lines: int, max_bytes: int = 4 * 1024 * 1024) -> str:
    try:
        if lines <= 0:
            return ""
        if not path.exists():
            return ""

        chunk_size = 64 * 1024
        buf = b""
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            while pos > 0 and buf.count(b"\n") <= lines + 1:
                read_size = chunk_size if pos >= chunk_size else pos
                pos -= read_size
                f.seek(pos, os.SEEK_SET)
                buf = f.read(read_size) + buf
                if len(buf) > max_bytes:
                    break

        text = buf.decode("utf-8", errors="replace")
        parts = text.splitlines()
        return "\n".join(parts[-lines:]) + ("\n" if parts else "")
    except Exception as exc:
        return f"[panel] Unable to read file: {exc}\n"


def read_int_file(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return int(raw, 10)
    except Exception:
        return None


def server_pid() -> int | None:
    pid = read_int_file(PID_FILE)
    if not pid or pid <= 1:
        return None
    return pid


def is_pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    return Path(f"/proc/{pid}").exists()


def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        return None
    except Exception:
        return None


def safe_list_dir(path: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    try:
        if not path.exists() or not path.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for entry in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            try:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    continue
                st = entry.stat()
                items.append({"name": entry.name, "size": int(st.st_size), "mtime": int(st.st_mtime)})
                if len(items) >= limit:
                    break
            except Exception:
                continue
        return items
    except Exception:
        return []


_RE_AUTH_CODE = re.compile(r"Authorization code:\s*([A-Z0-9-]+)", re.IGNORECASE)
_RE_DEVICE_VERIFY = re.compile(r"(https?://\S+)", re.IGNORECASE)
_RE_AUTH_HELPER_URL = re.compile(r"^\s*-\s*URL:\s*(https?://\S+)\s*$", re.IGNORECASE)
_RE_AUTH_HELPER_CODE = re.compile(r"^\s*-\s*Code:\s*([A-Z0-9-]+)\s*$", re.IGNORECASE)
_RE_USER_CODE_QUERY = re.compile(r"[?&]user_code=([A-Z0-9-]+)", re.IGNORECASE)


def extract_device_auth_from_log(log_text: str) -> dict[str, Any] | None:
    lines = log_text.splitlines()
    device_url: str | None = None
    device_code: str | None = None
    source: str | None = None

    for idx, line in enumerate(lines):
        if "Please visit the following URL to authenticate" in line:
            next_line = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
            match = _RE_DEVICE_VERIFY.search(next_line)
            if match:
                device_url = match.group(1).strip()
                source = "downloader"
            continue

        match = _RE_AUTH_CODE.search(line)
        if match:
            device_code = match.group(1).strip()
            source = source or "downloader"
            continue

        match = _RE_AUTH_HELPER_URL.match(line)
        if match:
            device_url = match.group(1).strip()
            source = "auth-helper"
            continue

        match = _RE_AUTH_HELPER_CODE.match(line)
        if match:
            device_code = match.group(1).strip()
            source = "auth-helper"
            continue

    if device_url and not device_code:
        match = _RE_USER_CODE_QUERY.search(device_url)
        if match:
            device_code = match.group(1).strip()

    if not device_url and not device_code:
        return None

    return {"url": device_url, "code": device_code, "source": source or "unknown"}


def last_meaningful_log_line(log_text: str) -> str | None:
    for line in reversed(log_text.splitlines()):
        s = line.strip()
        if not s:
            continue
        if s.startswith("[panel] Listening"):
            continue
        return s
    return None


def status_payload() -> dict[str, Any]:
    pid = server_pid()
    state = read_json_file(AUTH_STATE_PATH) or {}
    session = state.get("session") if isinstance(state.get("session"), dict) else {}

    version = None
    marker = read_json_file(VERSION_MARKER_PATH) or {}
    if isinstance(marker, dict):
        version = str(marker.get("version") or "").strip() or None

    downloader_pid = read_int_file(DOWNLOADER_PID_FILE)
    auth_helper_pid = read_int_file(AUTH_HELPER_PID_FILE)

    log_tail = tail_lines(LOG_FILE, lines=700)
    device = extract_device_auth_from_log(log_tail)
    last_hint = last_meaningful_log_line(log_tail)

    return {
        "time": int(time.time()),
        "server": {
            "pid": pid,
            "running": is_pid_running(pid),
            "bind": GAME_BIND,
            "authMode": AUTH_MODE,
            "version": version,
            "filesPresent": bool(JAR_PATH.exists() and ASSETS_PATH.exists()),
        },
        "auth": {
            "stateFilePresent": AUTH_STATE_PATH.exists(),
            "sessionExpiresAt": str(session.get("expiresAt") or "").strip() or None,
            "profile": (
                {
                    "uuid": str(state.get("profile", {}).get("uuid", "")).strip(),
                    "username": str(state.get("profile", {}).get("username", "")).strip(),
                }
                if isinstance(state.get("profile"), dict)
                else None
            ),
        },
        "setup": {
            "triggerDownloadPresent": TRIGGER_DOWNLOAD_FILE.exists(),
            "triggerAuthPresent": TRIGGER_AUTH_FILE.exists(),
            "downloaderRunning": is_pid_running(downloader_pid),
            "authHelperRunning": is_pid_running(auth_helper_pid),
            "device": device,
            "lastHint": last_hint,
        },
        "paths": {
            "consoleFile": str(CONSOLE_FILE),
            "logFile": str(LOG_FILE),
            "serverDir": str(SERVER_DIR),
            "jarPath": str(JAR_PATH),
            "assetsPath": str(ASSETS_PATH),
        },
    }


def load_index_html() -> str:
    html_path = Path(__file__).with_name("panel.html")
    try:
        return html_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        msg = f"Unable to load {html_path}: {exc}"
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Hytale Panel</title></head>
<body style="font-family: system-ui; background:#0b1020; color:#e8eefc; padding:18px;">
<h1>Hytale Panel</h1>
<p>{msg}</p>
</body></html>
"""


INDEX_HTML = load_index_html()


class Handler(BaseHTTPRequestHandler):
    server_version = "FluxHytalePanel/2.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _unauthorized(self) -> None:
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Hytale Server Panel"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Unauthorized\n")

    def _require_auth(self) -> bool:
        if not PANEL_PASSWORD:
            return True
        creds = decode_basic_auth(self.headers.get("Authorization", ""))
        if not creds:
            self._unauthorized()
            return False
        username, password = creds
        if username != PANEL_USERNAME or password != PANEL_PASSWORD:
            self._unauthorized()
            return False
        return True

    def do_GET(self) -> None:
        if not self._require_auth():
            return
        parsed = urlparse(self.path)

        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/status":
            body = json.dumps(status_payload(), indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/log":
            qs = parse_qs(parsed.query)
            lines_raw = (qs.get("lines") or ["400"])[0]
            try:
                lines = max(1, min(int(lines_raw, 10), 20000))
            except Exception:
                lines = 400
            body = tail_lines(LOG_FILE, lines=lines).encode("utf-8", errors="replace")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/console":
            qs = parse_qs(parsed.query)
            lines_raw = (qs.get("lines") or ["30"])[0]
            try:
                lines = max(1, min(int(lines_raw, 10), 2000))
            except Exception:
                lines = 30
            body = tail_lines(CONSOLE_FILE, lines=lines).encode("utf-8", errors="replace")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/mods/list":
            qs = parse_qs(parsed.query)
            kind = (qs.get("kind") or ["mods"])[0]
            target = MODS_DIR if kind == "mods" else PLUGINS_DIR
            body = json.dumps(safe_list_dir(target), indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not found\n")

    def do_POST(self) -> None:
        if not self._require_auth():
            return
        parsed = urlparse(self.path)

        if parsed.path == "/api/command":
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Invalid JSON\n")
                return

            cmd = str(payload.get("command") or "").strip()
            if not cmd:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Missing command\n")
                return
            if not cmd.startswith("/"):
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Command must start with '/'\n")
                return

            try:
                CONSOLE_FILE.parent.mkdir(parents=True, exist_ok=True)
                with CONSOLE_FILE.open("a", encoding="utf-8") as f:
                    f.write(cmd + "\n")
                try:
                    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with LOG_FILE.open("a", encoding="utf-8") as lf:
                        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
                        lf.write(f"[panel] {ts} queued command: {cmd}\n")
                except Exception:
                    pass
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Failed writing to console file: {exc}\n".encode("utf-8", errors="replace"))
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return

        if parsed.path == "/api/setup/download":
            try:
                TRIGGER_DOWNLOAD_FILE.write_text("1\n", encoding="utf-8")
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Failed creating trigger: {exc}\n".encode("utf-8", errors="replace"))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return

        if parsed.path == "/api/setup/auth":
            try:
                TRIGGER_AUTH_FILE.write_text("1\n", encoding="utf-8")
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Failed creating trigger: {exc}\n".encode("utf-8", errors="replace"))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return

        if parsed.path == "/api/setup/reset-auth":
            try:
                if AUTH_STATE_PATH.exists():
                    AUTH_STATE_PATH.unlink()
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Failed clearing auth state: {exc}\n".encode("utf-8", errors="replace"))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return

        if parsed.path == "/api/console/clear":
            try:
                CONSOLE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CONSOLE_FILE.write_text("", encoding="utf-8")
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Failed clearing console file: {exc}\n".encode("utf-8", errors="replace"))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return

        if parsed.path == "/api/mods/delete":
            qs = parse_qs(parsed.query)
            kind = (qs.get("kind") or ["mods"])[0]
            name = (qs.get("name") or [""])[0]
            name = os.path.basename(name)
            if not name:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Missing name\n")
                return
            target_dir = MODS_DIR if kind == "mods" else PLUGINS_DIR
            target_path = target_dir / name
            try:
                if not target_path.exists() or not target_path.is_file():
                    raise FileNotFoundError(str(target_path))
                target_path.unlink()
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Delete failed: {exc}\n".encode("utf-8", errors="replace"))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return

        if parsed.path == "/api/mods/upload":
            qs = parse_qs(parsed.query)
            kind = (qs.get("kind") or ["mods"])[0]
            target_dir = MODS_DIR if kind == "mods" else PLUGINS_DIR
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            ctype, _ = cgi.parse_header(self.headers.get("content-type", ""))
            if ctype != "multipart/form-data":
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Expected multipart/form-data\n")
                return

            try:
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
            except Exception as exc:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Upload parse failed: {exc}\n".encode("utf-8", errors="replace"))
                return

            item = form["file"] if "file" in form else None
            if not item or not getattr(item, "filename", ""):
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Missing file\n")
                return

            filename = os.path.basename(str(item.filename))
            if not filename:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Invalid filename\n")
                return

            max_bytes = 200 * 1024 * 1024
            written = 0
            out_path = target_dir / filename
            try:
                with out_path.open("wb") as f:
                    while True:
                        chunk = item.file.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError("File too large (max 200MB).")
                        f.write(chunk)
            except Exception as exc:
                try:
                    out_path.unlink()
                except Exception:
                    pass
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Upload failed: {exc}\n".encode("utf-8", errors="replace"))
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not found\n")


def parse_bind(bind: str) -> tuple[str, int]:
    bind = bind.strip()
    if not bind:
        return "0.0.0.0", 3000
    if ":" not in bind:
        return bind, 3000
    host, port_raw = bind.rsplit(":", 1)
    try:
        port = int(port_raw, 10)
    except Exception:
        port = 3000
    return host or "0.0.0.0", port


def main() -> int:
    bind = env_str("HYTALE_PANEL_BIND", "0.0.0.0:3000")
    host, port = parse_bind(bind)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"[panel] Listening on http://{host}:{port} (basic auth user: {PANEL_USERNAME})", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

