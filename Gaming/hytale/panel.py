#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
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
AUTH_STATE_PATH = Path(env_str("HYTALE_AUTH_STATE_PATH", "/data/auth/state.json"))
VERSION_MARKER_PATH = Path(env_str("HYTALE_VERSION_MARKER_PATH", "/data/.hytale-flux.version.json"))
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


def tail_lines(path: Path, *, lines: int) -> str:
    try:
        if lines <= 0:
            return ""
        data = path.read_text(encoding="utf-8", errors="replace")
        parts = data.splitlines()
        return "\n".join(parts[-lines:]) + ("\n" if parts else "")
    except FileNotFoundError:
        return ""
    except Exception as exc:
        return f"[panel] Unable to read log file: {exc}\n"


def server_pid() -> int | None:
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        pid = int(raw, 10)
        if pid <= 1:
            return None
        return pid
    except Exception:
        return None


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


def status_payload() -> dict[str, Any]:
    pid = server_pid()
    state = read_json_file(AUTH_STATE_PATH) or {}
    session = state.get("session") if isinstance(state.get("session"), dict) else {}

    version = None
    marker = read_json_file(VERSION_MARKER_PATH) or {}
    if isinstance(marker, dict):
        version = str(marker.get("version") or "").strip() or None

    return {
        "time": int(time.time()),
        "server": {
            "pid": pid,
            "running": is_pid_running(pid),
            "bind": GAME_BIND,
            "authMode": AUTH_MODE,
            "version": version,
        },
        "auth": {
            "stateFilePresent": AUTH_STATE_PATH.exists(),
            "sessionExpiresAt": str(session.get("expiresAt") or "").strip() or None,
            "profile": (
                {"uuid": str(state.get("profile", {}).get("uuid", "")).strip(), "username": str(state.get("profile", {}).get("username", "")).strip()}
                if isinstance(state.get("profile"), dict)
                else None
            ),
        },
        "paths": {
            "consoleFile": str(CONSOLE_FILE),
            "logFile": str(LOG_FILE),
        },
    }


INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Hytale Server Panel</title>
    <style>
      :root { color-scheme: dark; }
      body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; background: #0b1020; color: #e8eefc; }
      header { padding: 18px 20px; background: linear-gradient(90deg, #0f1733, #0b1020); border-bottom: 1px solid #1c2a57; }
      h1 { margin: 0; font-size: 16px; letter-spacing: 0.3px; }
      main { padding: 16px 20px; max-width: 1100px; margin: 0 auto; }
      .grid { display: grid; grid-template-columns: 1fr; gap: 14px; }
      @media (min-width: 900px) { .grid { grid-template-columns: 1fr 1fr; } }
      .card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px; }
      .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
      .badge { display: inline-flex; padding: 2px 9px; border-radius: 999px; font-size: 12px; border: 1px solid rgba(255,255,255,0.15); }
      .ok { background: rgba(34,197,94,0.13); border-color: rgba(34,197,94,0.4); }
      .bad { background: rgba(239,68,68,0.13); border-color: rgba(239,68,68,0.4); }
      code { background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 6px; }
      input, button { background: rgba(255,255,255,0.06); color: #e8eefc; border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; padding: 10px 12px; }
      input { width: min(720px, 100%); }
      button { cursor: pointer; }
      button:hover { background: rgba(255,255,255,0.09); }
      pre { margin: 0; background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 12px; overflow: auto; max-height: 520px; }
      .muted { color: rgba(232,238,252,0.72); }
      .kv { display: grid; grid-template-columns: 140px 1fr; gap: 8px 12px; margin-top: 10px; }
      .kv div { min-width: 0; }
      .kv .k { color: rgba(232,238,252,0.75); }
    </style>
  </head>
  <body>
    <header>
      <div class="row">
        <h1>Hytale Server Panel</h1>
        <span id="statusBadge" class="badge">Loading…</span>
      </div>
      <div class="muted" style="margin-top: 6px;">This panel can send console commands and show logs. Keep it password-protected.</div>
    </header>
    <main>
      <div class="grid">
        <section class="card">
          <div class="row" style="justify-content: space-between;">
            <div>
              <div class="muted">Server status</div>
              <div id="statusLine" style="margin-top: 4px;">Loading…</div>
            </div>
            <button id="refreshBtn" type="button">Refresh</button>
          </div>
          <div class="kv">
            <div class="k">Bind</div><div><code id="bindVal"></code></div>
            <div class="k">Auth mode</div><div><code id="authModeVal"></code></div>
            <div class="k">Version</div><div><code id="versionVal"></code></div>
            <div class="k">Console file</div><div><code id="consoleVal"></code></div>
            <div class="k">Log file</div><div><code id="logVal"></code></div>
          </div>
        </section>

        <section class="card">
          <div class="muted">Send a console command</div>
          <div class="row" style="margin-top: 10px;">
            <input id="cmdInput" placeholder="/help" autocomplete="off" />
            <button id="sendBtn" type="button">Send</button>
          </div>
          <div id="cmdResult" class="muted" style="margin-top: 10px;"></div>
          <div class="muted" style="margin-top: 10px;">
            Tip: for device auth via server console, send <code>/auth login device</code>.
          </div>
        </section>
      </div>

      <section class="card" style="margin-top: 14px;">
        <div class="row" style="justify-content: space-between;">
          <div>
            <div class="muted">Logs</div>
            <div class="muted" style="margin-top: 4px;">Showing the last <code id="logLinesVal">250</code> lines.</div>
          </div>
          <div class="row">
            <button id="log250" type="button">250</button>
            <button id="log1000" type="button">1000</button>
            <button id="log5000" type="button">5000</button>
          </div>
        </div>
        <pre id="logBox" style="margin-top: 12px;">Loading…</pre>
      </section>
    </main>
    <script>
      let logLines = 250;

      function el(id) { return document.getElementById(id); }
      function setBadge(ok) {
        const b = el("statusBadge");
        b.classList.remove("ok", "bad");
        if (ok) { b.classList.add("ok"); b.textContent = "Running"; }
        else { b.classList.add("bad"); b.textContent = "Not running"; }
      }

      async function refreshStatus() {
        const r = await fetch("/api/status");
        if (!r.ok) throw new Error("status failed");
        const s = await r.json();
        const running = !!(s.server && s.server.running);
        setBadge(running);
        el("statusLine").textContent = running ? `Server PID ${s.server.pid} is running` : "Server not running (or PID unknown)";
        el("bindVal").textContent = s.server.bind || "";
        el("authModeVal").textContent = s.server.authMode || "";
        el("versionVal").textContent = s.server.version || "unknown";
        el("consoleVal").textContent = (s.paths && s.paths.consoleFile) || "";
        el("logVal").textContent = (s.paths && s.paths.logFile) || "";
      }

      async function refreshLogs() {
        el("logLinesVal").textContent = String(logLines);
        const r = await fetch(`/api/log?lines=${logLines}`);
        if (!r.ok) throw new Error("log failed");
        el("logBox").textContent = await r.text();
        el("logBox").scrollTop = el("logBox").scrollHeight;
      }

      async function sendCommand() {
        const cmd = el("cmdInput").value || "";
        el("cmdResult").textContent = "Sending…";
        const r = await fetch("/api/command", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ command: cmd }),
        });
        const txt = await r.text();
        if (r.ok) el("cmdResult").textContent = "OK: command written to console file.";
        else el("cmdResult").textContent = `Error: ${txt}`;
      }

      el("refreshBtn").addEventListener("click", async () => {
        try { await refreshStatus(); await refreshLogs(); } catch (e) {}
      });
      el("sendBtn").addEventListener("click", async () => {
        try { await sendCommand(); await refreshLogs(); } catch (e) {}
      });
      el("cmdInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") el("sendBtn").click();
      });
      el("log250").addEventListener("click", async () => { logLines = 250; await refreshLogs(); });
      el("log1000").addEventListener("click", async () => { logLines = 1000; await refreshLogs(); });
      el("log5000").addEventListener("click", async () => { logLines = 5000; await refreshLogs(); });

      (async () => {
        try { await refreshStatus(); } catch (e) { setBadge(false); }
        try { await refreshLogs(); } catch (e) { el("logBox").textContent = "Unable to load logs."; }
        setInterval(async () => { try { await refreshStatus(); } catch (e) {} }, 5000);
        setInterval(async () => { try { await refreshLogs(); } catch (e) {} }, 10000);
      })();
    </script>
  </body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "HytalePanel/1.0"

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

    def log_message(self, fmt: str, *args: Any) -> None:
        return

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
            lines_raw = (qs.get("lines") or ["250"])[0]
            try:
                lines = max(1, min(int(lines_raw, 10), 20000))
            except Exception:
                lines = 250
            body = tail_lines(LOG_FILE, lines=lines).encode("utf-8", errors="replace")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
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
        if parsed.path != "/api/command":
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found\n")
            return

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

