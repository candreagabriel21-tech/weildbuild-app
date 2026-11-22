# Copyrighted (c) by Gabriel. All rights reserved.
import sys as _sys
import types as _types
import hashlib, hmac, json, logging, mimetypes, os, re, shutil, struct, subprocess, tempfile, time
import pathlib
import urllib.request, urllib.error

_CORE_SOURCE = r"""
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_NAME = "WeildBuild"
DATA_DIR_NAME = "weildbuild_data"
PARDON_DIR_NAME = "pardon"
MANIFEST_NAME = "manifest.json"
VERSION_FILE_PRIMARY = "wb_version.json"
VERSION_FILE_ALIAS = "wb-version.json"
PARDON_LIST_NAME = "pardon.txt"
PAYLOAD_DIR_NAME = "payload"
TOOLS_DIR_NAME = "tools"
UPDATER_STATE_NAME = "updater-state.json"
CONFIG_NAME = "launcher.cfg"

ENC_MAGIC = b"WBENC1"
ENC_PASSPHRASE = "weildbuild-local-storage-v1"
ENC_FORMAT_ID = "WBENC1"

REPO_DESKTOP = "candreagabriel21-tech/weildbuild-dektop"
REPO_MOBILE = "candreagabriel21-tech/weildbuild-mobile"
DEFAULT_PORT = 7777
LAUNCHER_MARKER_HEADER = "x-wb-launcher"
REPO_OVERRIDE_ENV = "WB_REPO_OVERRIDE"
USER_AGENT = "WeildBuild-Launcher/1.0 (+https://github.com/candreagabriel21-tech)"
NET_TIMEOUT = 30

EXTRA_MIME = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".html": "text/html; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".wasm": "application/wasm",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json",
}

for _ext, _mime in EXTRA_MIME.items():
    mimetypes.add_type(_mime, _ext)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_root(base_dir: Path | None = None) -> Path:
    return (base_dir or app_dir()) / DATA_DIR_NAME


def payload_root(base_dir: Path | None = None) -> Path:
    return data_root(base_dir) / PAYLOAD_DIR_NAME


def pardon_root(base_dir: Path | None = None) -> Path:
    return data_root(base_dir) / PARDON_DIR_NAME


def _sha256_key(material: bytes) -> bytes:
    return hashlib.sha256(material).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + struct.pack(">I", counter), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def wb_encrypt(plain: bytes) -> bytes:
    enc_key = _sha256_key(ENC_PASSPHRASE.encode("utf-8") + b":enc")
    mac_key = _sha256_key(ENC_PASSPHRASE.encode("utf-8") + b":mac")
    nonce = hashlib.sha256(plain + struct.pack(">Q", time.time_ns())).digest()[:16]
    stream = _keystream(enc_key, nonce, len(plain))
    cipher = bytes(a ^ b for a, b in zip(plain, stream))
    tag = hmac.new(mac_key, ENC_MAGIC + nonce + cipher, hashlib.sha256).digest()
    return ENC_MAGIC + nonce + cipher + tag


def wb_decrypt(blob: bytes) -> bytes:
    if len(blob) < len(ENC_MAGIC) + 16 + 32 or not blob.startswith(ENC_MAGIC):
        raise ValueError("not a WBENC1 blob")
    nonce = blob[6:22]
    cipher = blob[22:-32]
    tag = blob[-32:]
    mac_key = _sha256_key(ENC_PASSPHRASE.encode("utf-8") + b":mac")
    expected = hmac.new(mac_key, ENC_MAGIC + nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise ValueError("integrity check failed")
    enc_key = _sha256_key(ENC_PASSPHRASE.encode("utf-8") + b":enc")
    stream = _keystream(enc_key, nonce, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def loads_json_bytes(data: bytes):
    return json.loads(data.decode("utf-8"))


def parse_version_text(text: str) -> str:
    body = text.strip()
    match = re.search(r'version\s*=\s*["\']?([0-9][0-9A-Za-z.\-+]*)["\']?', body)
    if match:
        return match.group(1)
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict) and isinstance(parsed.get("version"), str):
            return parsed["version"]
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"([0-9][0-9A-Za-z.\-+]*)", body)
    if match:
        return match.group(1)
    raise ValueError("unparseable version file")


def version_tuple(version: str) -> tuple:
    parts = re.findall(r"[0-9A-Za-z\-+]+", version)
    out = []
    for part in parts[:4]:
        if part.isdigit():
            out.append((0, int(part)))
        else:
            out.append((1, part.lower()))
    while len(out) < 3:
        out.append((0, 0))
    return tuple(out)


def is_newer(candidate: str, current: str) -> bool:
    try:
        return version_tuple(candidate) > version_tuple(current)
    except (TypeError, ValueError):
        return False


def raw_urls_for(repo: str, file_name: str) -> list:
    return [
        f"https://raw.githubusercontent.com/{repo}/main/{file_name}",
        f"https://cdn.jsdelivr.net/gh/{repo}@main/{file_name}",
        f"https://cdn.jsdelivr.net/gh/{repo}@HEAD/{file_name}",
    ]


def fetch_url(urls: list, timeout: int = NET_TIMEOUT) -> bytes:
    last_error = None
    for url in urls:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
            continue
    raise ConnectionError(f"all sources failed: {last_error}")


def resolve_repo() -> str:
    override = os.environ.get(REPO_OVERRIDE_ENV, "").strip()
    if override:
        return override
    return load_config(app_dir()).get("repo", REPO_DESKTOP)


def fetch_repo_file(file_name: str) -> bytes:
    override = os.environ.get(REPO_OVERRIDE_ENV, "").strip()
    if override:
        if re.match(r"^https?://", override):
            base = override.rstrip("/")
            return fetch_url([f"{base}/{file_name}"])
        local = Path(override) / file_name
        if local.is_file():
            return local.read_bytes()
        raise FileNotFoundError(f"override file missing: {local}")
    return fetch_url(raw_urls_for(resolve_repo(), file_name))


def load_config(base_dir: Path | None = None) -> dict:
    path = (base_dir or app_dir()) / CONFIG_NAME
    config = {"repo": REPO_DESKTOP, "port": DEFAULT_PORT, "version": "0.0.0"}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            config.update({k: loaded[k] for k in config if k in loaded})
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return config


def save_config(config: dict, base_dir: Path | None = None) -> None:
    path = (base_dir or app_dir()) / CONFIG_NAME
    atomic_write(path, json.dumps(config, indent=2).encode("utf-8"))


def load_manifest(base_dir: Path | None = None) -> dict | None:
    path = data_root(base_dir) / MANIFEST_NAME
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict) and isinstance(parsed.get("files"), list):
            return parsed
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def manifest_entry_map(manifest: dict) -> dict:
    return {entry["path"]: entry for entry in manifest["files"] if isinstance(entry, dict) and "path" in entry}


def safe_join(root: Path, relative: str) -> Path:
    cleaned = relative.replace("\\", "/").lstrip("/")
    candidate = (root / cleaned).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"path escapes root: {relative}")
    return candidate


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.name)
    try:
        with os.fdopen(handle, "wb") as writer:
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def replace_locked(path: Path, data: bytes, base_dir: Path | None = None) -> None:
    try:
        atomic_write(path, data)
        return
    except PermissionError:
        pass
    quarantine = pardon_root(base_dir or path_anchor(path)) / "old-tools"
    quarantine.mkdir(parents=True, exist_ok=True)
    backup = quarantine / f"{path.name}.{int(time.time())}.old"
    try:
        os.rename(path, backup)
    except OSError:
        pass
    atomic_write(path, data)


def path_anchor(path: Path) -> Path:
    for parent in path.parents:
        if parent.name == DATA_DIR_NAME:
            return parent.parent
        if (parent / DATA_DIR_NAME).is_dir():
            return parent
    return path.parent


def clean_empty_dirs(root: Path) -> None:
    if not root.is_dir():
        return
    for dirpath, _dirnames, _filenames in sorted(os.walk(root, topdown=False), key=lambda item: len(item[0]), reverse=True):
        path = Path(dirpath)
        try:
            path.rmdir()
        except OSError:
            pass


def read_pardon_prefixes(base_dir: Path | None = None) -> list:
    prefixes = [f"{PARDON_DIR_NAME}/"]
    path = data_root(base_dir) / PARDON_LIST_NAME
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                prefixes.append(line.replace("\\", "/").strip("/") + "/" if not line.endswith("/") else line.replace("\\", "/"))
    except OSError:
        pass
    return prefixes


def is_pardoned(relative: str, prefixes: list) -> bool:
    normalized = relative.replace("\\", "/").lstrip("/")
    return any(normalized.startswith(prefix) for prefix in prefixes)


def setup_logging(base_dir: Path, name: str) -> logging.Logger:
    log_dir = pardon_root(base_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"wb.{name}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(stream)
    return logger


def python_launch_command() -> list:
    if is_frozen():
        return [sys.executable]
    if os.name == "nt":
        for candidate in ("pythonw.exe", "python.exe"):
            found = shutil.which(candidate)
            if found:
                return [found]
        return [sys.executable]
    return [sys.executable]


def sibling_tool_path(tool_name: str) -> Path:
    stem = Path(tool_name).stem
    if is_frozen():
        candidate = Path(sys.executable).resolve().parent / f"{stem}.exe"
        if candidate.is_file():
            return candidate
    base = app_dir()
    for name in (f"{stem}.py", f"{stem}.exe", tool_name):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return base / f"{stem}.py"


def spawn_tool(tool_name: str, extra_args: list | None = None, base_dir: Path | None = None) -> subprocess.Popen | None:
    tool_path = sibling_tool_path(tool_name)
    base = base_dir or app_dir()
    if tool_path.suffix.lower() == ".py":
        if not tool_path.is_file():
            return None
        command = python_launch_command() + [str(tool_path)]
    else:
        if not tool_path.is_file():
            return None
        command = [str(tool_path)]
    if extra_args:
        command += list(extra_args)
    try:
        return subprocess.Popen(command, cwd=str(base), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except OSError:
        return None


def windows_desktop_path() -> Path | None:
    if os.name != "nt":
        return None
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if output:
            return Path(output)
    except (OSError, subprocess.SubprocessError):
        pass
    fallback = Path.home() / "Desktop"
    return fallback if fallback.is_dir() else None


def create_desktop_shortcut(base_dir: Path, logger: logging.Logger | None = None) -> str | None:
    launcher_path = sibling_tool_path("weildbuild_launcher")
    if os.name == "nt":
        desktop = windows_desktop_path()
        if desktop is None:
            return None
        shortcut = desktop / "WeildBuild Launcher.lnk"
        if launcher_path.suffix.lower() == ".py":
            interpreter = python_launch_command()[0]
            target = interpreter
            arguments = f'"{launcher_path}"'
        else:
            target = str(launcher_path)
            arguments = ""
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('" + str(shortcut).replace("'", "''") + "'); "
            "$s.TargetPath = '" + target.replace("'", "''") + "'; "
            "$s.Arguments = '" + arguments.replace("'", "''") + "'; "
            "$s.WorkingDirectory = '" + str(base_dir).replace("'", "''") + "'; "
            "$s.Description = 'Run the WeildBuild app'; "
            "$s.Save()"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return str(shortcut)
        except (OSError, subprocess.SubprocessError):
            return None
    home = Path.home()
    if sys.platform == "darwin":
        command_path = desktop_or_home(home) / "WeildBuild Launcher.command"
        body = "#!/bin/sh\ncd \"" + str(base_dir) + "\"\nexec \"" + python_launch_command()[0] + "\" \"" + str(launcher_path) + "\"\n"
        atomic_write(command_path, body.encode("utf-8"))
        command_path.chmod(0o755)
        return str(command_path)
    applications = home / ".local" / "share" / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    entry = applications / "weildbuild-launcher.desktop"
    if launcher_path.suffix.lower() == ".py":
        exec_line = f'"{python_launch_command()[0]}" "{launcher_path}"'
    else:
        exec_line = f'"{launcher_path}"'
    body = (
        "[Desktop Entry]\nType=Application\nName=WeildBuild Launcher\n"
        f"Exec={exec_line}\nPath={base_dir}\n"
        "Comment=Run the WeildBuild app\nTerminal=false\nCategories=Game;\n"
    )
    atomic_write(entry, body.encode("utf-8"))
    entry.chmod(0o644)
    return str(entry)


def desktop_or_home(home: Path) -> Path:
    desktop = home / "Desktop"
    return desktop if desktop.is_dir() else home


def verify_installed_files(base_dir: Path) -> tuple:
    manifest = load_manifest(base_dir)
    if manifest is None:
        return False, []
    entries = manifest_entry_map(manifest)
    broken = []
    for relative, entry in entries.items():
        try:
            path = safe_join(base_dir, relative)
        except ValueError:
            broken.append(relative)
            continue
        if not path.is_file():
            broken.append(relative)
            continue
        if path.stat().st_size != entry.get("size"):
            broken.append(relative)
            continue
        expected = entry.get("sha256")
        if expected and sha256_hex(path.read_bytes()) != expected:
            broken.append(relative)
    return len(broken) == 0, broken


def guess_mime(file_name: str) -> str:
    mime, _encoding = mimetypes.guess_type(file_name)
    return mime or "application/octet-stream"
"""

core = _types.ModuleType("core")
core.__file__ = "<embedded-core>"
exec(compile(_CORE_SOURCE, "core.py", "exec"), core.__dict__)
_sys.modules["core"] = core

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit



class BlobCache:
    def __init__(self, capacity_bytes: int = 96 * 1024 * 1024):
        self.capacity = capacity_bytes
        self.used = 0
        self.entries = OrderedDict()

    def get(self, key: Path):
        stamp = key.stat().st_mtime_ns if key.is_file() else None
        cached = self.entries.get(key)
        if cached and cached[0] == stamp:
            self.entries.move_to_end(key)
            return cached[1]
        return None

    def put(self, key: Path, value: bytes):
        stamp = key.stat().st_mtime_ns if key.is_file() else 0
        if key in self.entries:
            self.used -= len(self.entries[key][1])
            del self.entries[key]
        while self.used + len(value) > self.capacity and self.entries:
            _old_key, old_value = self.entries.popitem(last=False)
            self.used -= len(old_value[1])
        self.entries[key] = (stamp, value)
        self.used += len(value)


CACHE = BlobCache()
RUNTIME = {"base_dir": None, "cfg": {}, "logger": None, "updater_proc": None, "server": None}


class AppHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WeildBuildLauncher/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        logger = RUNTIME.get("logger")
        if logger:
            logger.info("%s %s", self.address_string(), fmt % args)

    def send_bytes(self, status: int, body: bytes, content_type: str, extra_headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-WB-Launcher", "1")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        cache_control = "no-store"
        content_type_base = content_type.split(";")[0].strip()
        if content_type_base not in ("text/html", "application/json", "application/manifest+json", "text/plain"):
            cache_control = "public, max-age=3600"
        self.send_header("Cache-Control", cache_control)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_bytes(status, body, "application/json")

    def do_GET(self):
        self.handle_request("GET")

    def do_HEAD(self):
        self.handle_request("HEAD")

    def handle_request(self, method: str):
        base_dir = RUNTIME["base_dir"]
        path = unquote(urlsplit(self.path).path)
        try:
            if path in ("/wb-version.json", "/wb_version.json"):
                version_file = core.data_root(base_dir) / core.VERSION_FILE_PRIMARY
                body = version_file.read_bytes() if version_file.is_file() else b'version = "0.0.0"\n'
                self.send_bytes(200, body, "application/json")
                return
            if path == "/wb/ping":
                self.send_json({"app": "weildbuild-launcher", "version": RUNTIME["cfg"].get("version"), "port": self.server.server_address[1]})
                return
            if path == "/wb/update-status":
                state_file = core.pardon_root(base_dir) / core.UPDATER_STATE_NAME
                try:
                    self.send_json(core.loads_json_bytes(state_file.read_bytes()))
                except (OSError, ValueError):
                    self.send_json({"lastCheckAt": None, "latestVersion": None, "upToDate": None})
                return
            if path.startswith("/wb/"):
                self.send_json({"error": "not found"}, 404)
                return

            relative = path.lstrip("/")
            candidates = []
            if relative == "" or relative.endswith("/"):
                candidates.append(relative + "index.html")
            else:
                candidates.append(relative)
                candidates.append(relative + "/index.html")
                candidates.append(relative + ".html")
            seen = set()
            for candidate in candidates:
                candidate = candidate.lstrip("/")
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                body = self.read_blob(base_dir, candidate)
                if body is not None:
                    self.send_bytes(200, body, core.guess_mime(candidate))
                    return
            not_found = self.read_blob(base_dir, "404.html")
            if not_found is not None:
                self.send_bytes(404, not_found, "text/html; charset=utf-8")
                return
            self.send_json({"error": "not found", "path": path}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                self.send_json({"error": "internal error", "detail": str(exc)}, 500)
            except Exception:
                pass

    def read_blob(self, base_dir: Path, relative: str) -> bytes | None:
        try:
            blob_path = core.safe_join(core.payload_root(base_dir), relative + ".wbenc")
        except ValueError:
            return None
        if not blob_path.is_file():
            return None
        cached = CACHE.get(blob_path)
        if cached is not None:
            return cached
        plain = core.wb_decrypt(blob_path.read_bytes())
        CACHE.put(blob_path, plain)
        return plain


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def probe_existing_launcher(port: int) -> dict | None:
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/wb/ping", headers={"User-Agent": core.USER_AGENT})
        with urllib.request.urlopen(request, timeout=2) as response:
            marker = (response.headers.get("X-WB-Launcher") or "").strip()
            if marker:
                return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return None


def pick_port(preferred: int) -> tuple:
    for port in [preferred] + [p for p in range(core.DEFAULT_PORT, core.DEFAULT_PORT + 20) if p != preferred]:
        if not port_in_use(port):
            return port, False
        existing = probe_existing_launcher(port)
        if existing:
            return port, True
    raise RuntimeError("no free port in 7777-7797")


def find_browser() -> str | None:
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        candidates = [
            Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
        return None
    for name in ("msedge", "microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def browser_command(browser: str, url: str, base_dir: Path) -> list:
    profile = core.pardon_root(base_dir) / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return [
        browser,
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--new-window",
        f"--app={url}",
    ]


def ensure_installed(base_dir: Path, logger) -> bool:
    ok, broken = core.verify_installed_files(base_dir)
    if ok:
        return True
    logger.warning("integrity check failed on %d file(s), running repair", len(broken))
    installer = core.sibling_tool_path("weildbuild_installer")
    if installer.is_file() and installer.suffix.lower() == ".py":
        command = core.python_launch_command() + [str(installer), "--cli", "--dir", str(base_dir)]
        try:
            subprocess.run(command, cwd=str(base_dir), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error("repair failed: %s", exc)
            return False
    ok, broken = core.verify_installed_files(base_dir)
    if not ok:
        logger.error("installation still broken after repair: %s", broken[:10])
        return False
    return True


def shutdown_handler(signum, frame):
    raise KeyboardInterrupt


def main() -> int:
    parser = argparse.ArgumentParser(description="WeildBuild launcher")
    parser.add_argument("--dir", type=str, default=None, help="installation directory (default: next to this script)")
    parser.add_argument("--port", type=int, default=None, help="preferred local port")
    parser.add_argument("--no-browser", action="store_true", help="serve without opening a browser window")
    parser.add_argument("--plain-browser", action="store_true", help="open in a normal tab instead of an app window")
    parser.add_argument("--check-only", action="store_true", help="verify the installation and exit")
    parser.add_argument("--repo", type=str, default=None, help="repository override, stored into launcher.cfg")
    args = parser.parse_args()

    base_dir = Path(args.dir).expanduser().resolve() if args.dir else core.app_dir()
    logger = core.setup_logging(base_dir, "launcher")
    RUNTIME["base_dir"] = base_dir
    RUNTIME["logger"] = logger
    signal.signal(signal.SIGTERM, shutdown_handler)

    cfg = core.load_config(base_dir)
    if args.repo:
        cfg["repo"] = args.repo
    if args.port:
        cfg["port"] = args.port
    RUNTIME["cfg"] = cfg

    if args.check_only:
        ok, broken = core.verify_installed_files(base_dir)
        print("OK" if ok else f"BROKEN ({len(broken)} files)")
        return 0 if ok else 1

    if not ensure_installed(base_dir, logger):
        print("WeildBuild installation is broken and could not be repaired. Run the installer again.", file=sys.stderr)
        return 1

    port, already_running = pick_port(cfg.get("port", core.DEFAULT_PORT))
    if port != cfg.get("port"):
        cfg["port"] = port
        core.save_config(cfg, base_dir)
    url = f"http://127.0.0.1:{port}/"

    if already_running:
        logger.info("launcher already serving on port %d, opening a new window there", port)
        if not args.no_browser:
            browser = find_browser()
            if browser:
                subprocess.Popen(browser_command(browser, url, base_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import webbrowser

                webbrowser.open(url)
        return 0

    updater_proc = core.spawn_tool("weildbuild_updater", ["--dir", str(base_dir)], base_dir)
    RUNTIME["updater_proc"] = updater_proc
    if updater_proc:
        logger.info("updater started (pid %s)", updater_proc.pid)

    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    server.daemon_threads = True
    RUNTIME["server"] = server
    server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
    server_thread.start()
    logger.info("serving WeildBuild %s at %s", cfg.get("version"), url)

    browser_proc = None
    if not args.no_browser:
        browser = find_browser()
        if browser:
            try:
                browser_proc = subprocess.Popen(browser_command(browser, url, base_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                logger.warning("could not start %s: %s", browser, exc)
                browser_proc = None
        else:
            import webbrowser

            webbrowser.open(url)
            logger.info("opened the default browser (no Chromium-based browser found for app-window mode)")

    exit_code = 0
    try:
        if browser_proc is not None:
            while browser_proc.poll() is None:
                time.sleep(0.5)
            logger.info("app window closed")
        else:
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        if RUNTIME["updater_proc"]:
            try:
                RUNTIME["updater_proc"].terminate()
                RUNTIME["updater_proc"].wait(timeout=5)
            except Exception:
                try:
                    RUNTIME["updater_proc"].kill()
                except Exception:
                    pass
        logger.info("launcher stopped")
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
