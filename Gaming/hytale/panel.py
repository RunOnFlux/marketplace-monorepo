#!/usr/bin/env python3
from __future__ import annotations

import base64
import cgi
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
        },
        "paths": {
            "consoleFile": str(CONSOLE_FILE),
            "logFile": str(LOG_FILE),
            "serverDir": str(SERVER_DIR),
            "jarPath": str(JAR_PATH),
            "assetsPath": str(ASSETS_PATH),
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
      .warn { background: rgba(234,179,8,0.13); border-color: rgba(234,179,8,0.4); }
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
      .small { font-size: 12px; }
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
              <div class="muted">Setup</div>
              <div class="small muted" style="margin-top: 4px;">Flow: download server files → authenticate → server starts.</div>
            </div>
            <button id="setupRefreshBtn" type="button">Refresh</button>
          </div>
          <div class="row" style="margin-top: 12px;">
            <span id="filesBadge" class="badge">Files: …</span>
            <button id="downloadBtn" type="button">Start download</button>
            <span id="authBadge" class="badge">Auth: …</span>
            <button id="authBtn" type="button">Start auth</button>
          </div>
          <div id="setupHint" class="muted" style="margin-top: 10px;"></div>
        </section>

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
            Tip: commands are only processed when the server is running (they’re queued in the console file).
          </div>
        </section>
      </div>

      <section class="card" style="margin-top: 14px;">
        <div class="row" style="justify-content: space-between;">
          <div>
            <div class="muted">Console queue</div>
            <div class="muted" style="margin-top: 4px;">Last <code id="consoleLinesVal">20</code> lines written to the console file.</div>
          </div>
          <div class="row">
            <button id="console20" type="button">20</button>
            <button id="console100" type="button">100</button>
          </div>
        </div>
        <pre id="consoleBox" style="margin-top: 12px;">Loading…</pre>
      </section>

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

      <section class="card" style="margin-top: 14px;">
        <div class="row" style="justify-content: space-between;">
          <div>
            <div class="muted">Mods / Plugins (experimental)</div>
            <div class="muted" style="margin-top: 4px;">Manage files in <code>/data/Server/mods</code> and <code>/data/Server/plugins</code>.</div>
          </div>
          <button id="modsRefreshBtn" type="button">Refresh</button>
        </div>
        <div class="grid" style="margin-top: 12px;">
          <div class="card">
            <div class="muted">Mods</div>
            <div id="modsList" class="muted small" style="margin-top: 8px;">Loading…</div>
            <form id="modsUploadForm" style="margin-top: 10px;">
              <input type="file" id="modsFile" />
              <button type="submit" style="margin-top: 8px;">Upload to mods</button>
            </form>
          </div>
          <div class="card">
            <div class="muted">Plugins</div>
            <div id="pluginsList" class="muted small" style="margin-top: 8px;">Loading…</div>
            <form id="pluginsUploadForm" style="margin-top: 10px;">
              <input type="file" id="pluginsFile" />
              <button type="submit" style="margin-top: 8px;">Upload to plugins</button>
            </form>
          </div>
        </div>
      </section>
    </main>
    <script>
      let logLines = 250;
      let consoleLines = 20;

      function el(id) { return document.getElementById(id); }
      function setBadge(ok) {
        const b = el("statusBadge");
        b.classList.remove("ok", "bad");
        if (ok) { b.classList.add("ok"); b.textContent = "Running"; }
        else { b.classList.add("bad"); b.textContent = "Not running"; }
      }

      function setSetupBadges(s) {
        const filesOk = !!(s.server && s.server.filesPresent);
        const downloaderRunning = !!(s.setup && s.setup.downloaderRunning);
        const authRunning = !!(s.setup && s.setup.authHelperRunning);
        const authReady = !!(s.auth && s.auth.stateFilePresent);

        const fb = el("filesBadge");
        fb.classList.remove("ok", "bad", "warn");
        if (filesOk) { fb.classList.add("ok"); fb.textContent = "Files: ready"; }
        else if (downloaderRunning) { fb.classList.add("warn"); fb.textContent = "Files: downloading…"; }
        else { fb.classList.add("bad"); fb.textContent = "Files: missing"; }

        const ab = el("authBadge");
        ab.classList.remove("ok", "bad", "warn");
        if (authReady) { ab.classList.add("ok"); ab.textContent = "Auth: state present"; }
        else if (authRunning) { ab.classList.add("warn"); ab.textContent = "Auth: in progress…"; }
        else { ab.classList.add("bad"); ab.textContent = "Auth: not ready"; }

        let hint = "";
        if (!filesOk) {
          hint = "Click “Start download”, then follow any device-login URL/code shown in Logs.";
        } else if (!authReady && (s.server && s.server.authMode === "authenticated")) {
          hint = "Click “Start auth” (device-login URL/code will appear in Logs).";
        } else {
          hint = "Setup looks OK. If the server isn’t running yet, check Logs for the next required action.";
        }
        el("setupHint").textContent = hint;
      }

      async function refreshStatus() {
        const r = await fetch("/api/status");
        if (!r.ok) throw new Error("status failed");
        const s = await r.json();
        const running = !!(s.server && s.server.running);
        setBadge(running);
        setSetupBadges(s);
        el("statusLine").textContent = running ? `Server PID ${s.server.pid} is running` : "Server not running (or PID unknown)";
        el("bindVal").textContent = s.server.bind || "";
        el("authModeVal").textContent = s.server.authMode || "";
        el("versionVal").textContent = s.server.version || "unknown";
        el("consoleVal").textContent = (s.paths && s.paths.consoleFile) || "";
        el("logVal").textContent = (s.paths && s.paths.logFile) || "";
      }

      async function refreshConsole() {
        el("consoleLinesVal").textContent = String(consoleLines);
        const r = await fetch(`/api/console?lines=${consoleLines}`);
        if (!r.ok) throw new Error("console failed");
        el("consoleBox").textContent = await r.text();
        el("consoleBox").scrollTop = el("consoleBox").scrollHeight;
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
        if (r.ok) el("cmdResult").textContent = "OK: queued (see Console queue + Logs).";
        else el("cmdResult").textContent = `Error: ${txt}`;
      }

      async function triggerDownload() {
        el("setupHint").textContent = "Triggering download…";
        const r = await fetch("/api/setup/download", { method: "POST" });
        if (!r.ok) throw new Error("download trigger failed");
        await refreshStatus();
        await refreshLogs();
      }

      async function triggerAuth() {
        el("setupHint").textContent = "Triggering auth…";
        const r = await fetch("/api/setup/auth", { method: "POST" });
        if (!r.ok) throw new Error("auth trigger failed");
        await refreshStatus();
        await refreshLogs();
      }

      async function refreshMods() {
        const r1 = await fetch("/api/mods/list?kind=mods");
        const r2 = await fetch("/api/mods/list?kind=plugins");
        const mods = r1.ok ? await r1.json() : [];
        const plugins = r2.ok ? await r2.json() : [];

        el("modsList").innerHTML = mods.length ? mods.map(x => `<div><code>${x.name}</code> <span class="muted">(${x.size} bytes)</span> <button data-kind="mods" data-name="${encodeURIComponent(x.name)}">Delete</button></div>`).join("") : "<div class='muted'>No files found.</div>";
        el("pluginsList").innerHTML = plugins.length ? plugins.map(x => `<div><code>${x.name}</code> <span class="muted">(${x.size} bytes)</span> <button data-kind="plugins" data-name="${encodeURIComponent(x.name)}">Delete</button></div>`).join("") : "<div class='muted'>No files found.</div>";

        for (const btn of document.querySelectorAll("#modsList button, #pluginsList button")) {
          btn.addEventListener("click", async () => {
            const kind = btn.getAttribute("data-kind");
            const name = btn.getAttribute("data-name");
            if (!kind || !name) return;
            if (!confirm("Delete this file?")) return;
            await fetch(`/api/mods/delete?kind=${kind}&name=${name}`, { method: "POST" });
            await refreshMods();
          });
        }
      }

      async function upload(kind, fileInputId) {
        const fi = el(fileInputId);
        const f = fi.files && fi.files[0];
        if (!f) return;
        const fd = new FormData();
        fd.append("file", f);
        const r = await fetch(`/api/mods/upload?kind=${kind}`, { method: "POST", body: fd });
        if (!r.ok) { alert(await r.text()); return; }
        fi.value = "";
        await refreshMods();
      }

      el("refreshBtn").addEventListener("click", async () => {
        try { await refreshStatus(); await refreshConsole(); await refreshLogs(); } catch (e) {}
      });
      el("sendBtn").addEventListener("click", async () => {
        try { await sendCommand(); await refreshConsole(); await refreshLogs(); } catch (e) {}
      });
      el("cmdInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") el("sendBtn").click();
      });
      el("log250").addEventListener("click", async () => { logLines = 250; await refreshLogs(); });
      el("log1000").addEventListener("click", async () => { logLines = 1000; await refreshLogs(); });
      el("log5000").addEventListener("click", async () => { logLines = 5000; await refreshLogs(); });
      el("console20").addEventListener("click", async () => { consoleLines = 20; await refreshConsole(); });
      el("console100").addEventListener("click", async () => { consoleLines = 100; await refreshConsole(); });
      el("setupRefreshBtn").addEventListener("click", async () => { try { await refreshStatus(); } catch (e) {} });
      el("downloadBtn").addEventListener("click", async () => { try { await triggerDownload(); } catch (e) {} });
      el("authBtn").addEventListener("click", async () => { try { await triggerAuth(); } catch (e) {} });
      el("modsRefreshBtn").addEventListener("click", async () => { try { await refreshMods(); } catch (e) {} });
      el("modsUploadForm").addEventListener("submit", async (e) => { e.preventDefault(); await upload("mods", "modsFile"); });
      el("pluginsUploadForm").addEventListener("submit", async (e) => { e.preventDefault(); await upload("plugins", "pluginsFile"); });

      (async () => {
        try { await refreshStatus(); } catch (e) { setBadge(false); }
        try { await refreshConsole(); } catch (e) { el("consoleBox").textContent = "Unable to load console queue."; }
        try { await refreshLogs(); } catch (e) { el("logBox").textContent = "Unable to load logs."; }
        try { await refreshMods(); } catch (e) {}
        setInterval(async () => { try { await refreshStatus(); } catch (e) {} }, 5000);
        setInterval(async () => { try { await refreshConsole(); } catch (e) {} }, 7000);
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

        if parsed.path == "/api/console":
            qs = parse_qs(parsed.query)
            lines_raw = (qs.get("lines") or ["20"])[0]
            try:
                lines = max(1, min(int(lines_raw, 10), 2000))
            except Exception:
                lines = 20
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
        return


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
