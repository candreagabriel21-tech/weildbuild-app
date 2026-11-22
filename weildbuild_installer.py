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
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def default_install_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "WeildBuild"
    return Path.home() / "WeildBuild"


def normalize_repo_arg(repo: str | None) -> None:
    if repo:
        os.environ[core.REPO_OVERRIDE_ENV] = repo


def download_all(target_dir: Path, progress, should_stop) -> tuple:
    manifest_raw = core.fetch_repo_file(core.MANIFEST_NAME)
    manifest = core.loads_json_bytes(manifest_raw)
    version = core.parse_version_text(core.fetch_repo_file(core.VERSION_FILE_PRIMARY).decode("utf-8"))
    entries = manifest["files"]
    total = len(entries)
    done = 0
    failed = None

    data_dir = core.data_root(target_dir)
    payload_dir = core.payload_root(target_dir)
    tools_dir = target_dir / core.TOOLS_DIR_NAME
    pardon_dir = core.pardon_root(target_dir)
    for directory in (data_dir, payload_dir, tools_dir, pardon_dir / "logs", pardon_dir / "browser-profile", pardon_dir / "session"):
        directory.mkdir(parents=True, exist_ok=True)

    for entry in entries:
        if should_stop():
            return None, "cancelled"
        relative = entry["path"]
        repo_relative = entry.get("src", relative)
        try:
            blob = core.fetch_repo_file(repo_relative)
        except Exception as exc:
            failed = f"{repo_relative}: {exc}"
            break
        if core.sha256_hex(blob) != entry.get("sha256"):
            failed = f"{relative}: checksum mismatch"
            break
        try:
            destination = core.safe_join(target_dir, relative)
            core.replace_locked(destination, blob, target_dir)
        except ValueError as exc:
            failed = str(exc)
            break
        done += 1
        progress(done, total, relative)

    if failed:
        return None, failed

    pardon_blob = None
    try:
        pardon_blob = core.fetch_repo_file(core.PARDON_LIST_NAME)
    except Exception:
        pardon_blob = None
    if pardon_blob:
        core.atomic_write(core.data_root(target_dir) / core.PARDON_LIST_NAME, pardon_blob)
    else:
        core.atomic_write(core.data_root(target_dir) / core.PARDON_LIST_NAME, f"# Local-only files, never deleted by the updater\n{core.PARDON_DIR_NAME}/\n".encode("utf-8"))

    version_text = f'version = "{version}"\n'.encode("utf-8")
    core.atomic_write(data_dir / core.VERSION_FILE_PRIMARY, version_text)
    core.atomic_write(data_dir / core.VERSION_FILE_ALIAS, version_text)
    core.atomic_write(data_dir / core.MANIFEST_NAME, manifest_raw)

    existing_config = core.load_config(target_dir)
    config = {
        "repo": os.environ.get(core.REPO_OVERRIDE_ENV) or existing_config.get("repo") or core.REPO_DESKTOP,
        "port": existing_config.get("port", core.DEFAULT_PORT),
        "version": version,
    }
    core.save_config(config, target_dir)
    return manifest, version


def launch_installed(target_dir: Path) -> bool:
    launcher = target_dir / "weildbuild_launcher.py"
    exe = target_dir / "weildbuild_launcher.exe"
    if exe.is_file():
        command = [str(exe)]
    elif launcher.is_file():
        command = core.python_launch_command() + [str(launcher)]
    else:
        return False
    try:
        subprocess_detached(command, target_dir)
        return True
    except OSError:
        return False


def subprocess_detached(command: list, cwd: Path) -> None:
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200
    subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags)


def run_cli(args) -> int:
    core.setup_logging(args.dir, "installer")
    target = args.dir.expanduser().resolve()
    normalize_repo_arg(args.repo)
    print(f"WeildBuild installer -> {target}")
    state = {"done": 0, "total": 0}

    def progress(done, total, relative):
        state["done"] = done
        state["total"] = total
        print(f"[{done}/{total}] {relative}")

    def stop():
        return False

    started = time.time()
    manifest, error = download_all(target, progress, stop)
    if manifest is None:
        print(f"INSTALL FAILED: {error}", file=sys.stderr)
        return 1
    version = manifest.get("version", "?") if isinstance(manifest, dict) else "?"
    shortcut = core.create_desktop_shortcut(target)
    elapsed = time.time() - started
    print(f"Installed WeildBuild {version} in {elapsed:.1f}s")
    if shortcut:
        print(f"Desktop shortcut: {shortcut}")
    if args.launch:
        launch_installed(target)
    return 0


COLORS = {
    "outer": "#020617",
    "card": "#0f172a",
    "border": "#4f46e5",
    "title": "#a5b4fc",
    "subtitle": "#94a3b8",
    "body": "#cbd5e1",
    "muted": "#64748b",
    "button": "#4f46e5",
    "button_hover": "#6366f1",
    "track": "#1e293b",
    "track_border": "#334155",
    "fill": "#3b82f6",
    "success": "#34d399",
    "error": "#f87171",
    "icon": "#4f46e5",
}


class InstallWizard:
    def __init__(self, args):
        self.args = args
        self.queue = queue.Queue()
        self.cancelled = False
        self.result_version = None
        import tkinter as tk
        from tkinter import filedialog, font as tkfont

        self.tk = tk
        self.filedialog = filedialog
        self.root = tk.Tk()
        self.root.title("WeildBuild Setup")
        self.root.configure(bg=COLORS["outer"])
        self.root.overrideredirect(True)
        width, height = 560, 440
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = max(40, (screen_h - height) // 2 - 40)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.attributes("-topmost", True)

        self.card = tk.Frame(self.root, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        self.card.pack(fill="both", expand=True, padx=16, pady=16)
        self.card.pack_propagate(False)

        self.topbar = tk.Frame(self.card, bg=COLORS["card"])
        self.topbar.pack(fill="x", padx=12, pady=(8, 0))
        self.close_label = tk.Label(self.topbar, text="\u2715", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 11, "bold"), cursor="hand2")
        self.close_label.pack(side="right")
        self.close_label.bind("<Button-1>", lambda e: self.root.destroy())
        self.close_label.bind("<Enter>", lambda e: self.close_label.configure(fg="#ffffff"))
        self.close_label.bind("<Leave>", lambda e: self.close_label.configure(fg=COLORS["muted"]))

        self.icon_canvas = tk.Canvas(self.card, width=64, height=64, bg=COLORS["card"], highlightthickness=0)
        self.icon_canvas.pack(pady=(2, 6))
        self.icon_canvas.create_oval(6, 6, 58, 58, fill=COLORS["icon"], outline="")
        self.icon_canvas.create_line(32, 18, 32, 40, fill="#ffffff", width=4, capstyle="round")
        self.icon_canvas.create_line(32, 40, 23, 31, fill="#ffffff", width=4, capstyle="round")
        self.icon_canvas.create_line(32, 40, 41, 31, fill="#ffffff", width=4, capstyle="round")
        self.icon_canvas.create_line(22, 46, 42, 46, fill="#ffffff", width=4, capstyle="round")

        self.title_label = tk.Label(self.card, text="WeildBuild Setup", bg=COLORS["card"], fg=COLORS["title"], font=("Segoe UI", 18, "bold"))
        self.title_label.pack()
        self.subtitle_label = tk.Label(self.card, text=f"Version {self.args.version or 'latest'}", bg=COLORS["card"], fg=COLORS["subtitle"], font=("Consolas", 10))
        self.subtitle_label.pack(pady=(2, 8))

        self.body = tk.Frame(self.card, bg=COLORS["card"])
        self.body.pack(fill="both", expand=True, padx=36)

        self.header_area = tk.Frame(self.card, bg=COLORS["card"], height=28)
        self.header_area.pack(fill="x", padx=12)
        for widget in (self.header_area, self.title_label, self.subtitle_label, self.icon_canvas):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        self.show_welcome()
        self.root.after(80, self.poll_queue)

    def start_drag(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def do_drag(self, event):
        self.root.geometry(f"+{event.x_root - self.drag_x}+{event.y_root - self.drag_y}")

    def clear_body(self):
        for child in self.body.winfo_children():
            child.destroy()

    def make_button(self, parent, text, command, primary=True):
        colors = COLORS
        button = self.tk.Button(
            parent,
            text=text,
            command=command,
            bg=colors["button"] if primary else colors["track"],
            fg="#ffffff" if primary else colors["body"],
            activebackground=colors["button_hover"] if primary else colors["track_border"],
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=18,
            pady=7,
            cursor="hand2",
            font=("Segoe UI", 10, "bold" if primary else "normal"),
        )
        return button

    def show_welcome(self):
        self.clear_body()
        self.title_label.configure(text="WeildBuild Setup", fg=COLORS["title"])
        self.subtitle_label.configure(text=f"Version {self.args.version or 'latest'}")
        description = self.tk.Label(
            self.body,
            text="This wizard installs WeildBuild on this computer.\nEverything is downloaded from the official WeildBuild repository,\nkept encrypted on disk, and updated automatically in the background.",
            bg=COLORS["card"],
            fg=COLORS["body"],
            font=("Segoe UI", 10),
            justify="center",
        )
        description.pack(pady=(8, 14))

        dir_row = self.tk.Frame(self.body, bg=COLORS["card"])
        dir_row.pack(fill="x")
        dir_caption = self.tk.Label(dir_row, text="Install to", bg=COLORS["card"], fg=COLORS["subtitle"], font=("Segoe UI", 9))
        dir_caption.pack(anchor="w")
        entry_row = self.tk.Frame(self.body, bg=COLORS["card"])
        entry_row.pack(fill="x", pady=(2, 6))
        default_dir = self.args.dir if self.args.dir else default_install_dir()
        self.dir_var = self.tk.StringVar(value=str(default_dir))
        entry = self.tk.Entry(entry_row, textvariable=self.dir_var, bg=COLORS["track"], fg=COLORS["body"], insertbackground=COLORS["body"], relief="flat", font=("Consolas", 10))
        entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
        browse = self.make_button(entry_row, "Browse...", self.browse_dir, primary=False)
        browse.pack(side="right")

        buttons = self.tk.Frame(self.body, bg=COLORS["card"])
        buttons.pack(pady=(14, 4))
        install = self.make_button(buttons, "Install now", self.begin_install)
        install.pack(side="left", padx=6)
        cancel = self.make_button(buttons, "Not now", self.root.destroy, primary=False)
        cancel.pack(side="left", padx=6)

    def browse_dir(self):
        chosen = self.filedialog.askdirectory(initialdir=self.dir_var.get() or str(Path.home()))
        if chosen:
            self.dir_var.set(chosen)

    def show_progress(self):
        self.clear_body()
        self.title_label.configure(text="Installing WeildBuild", fg=COLORS["title"])
        self.status_label = self.tk.Label(self.body, text="Preparing...", bg=COLORS["card"], fg=COLORS["subtitle"], font=("Segoe UI", 10))
        self.status_label.pack(pady=(10, 8))
        bar_row = self.tk.Frame(self.body, bg=COLORS["card"])
        bar_row.pack(fill="x")
        self.bar = self.tk.Canvas(bar_row, width=440, height=14, bg=COLORS["card"], highlightthickness=0)
        self.bar.pack()
        self.bar.create_rectangle(0, 0, 440, 14, fill=COLORS["track"], outline=COLORS["track_border"])
        self.detail_label = self.tk.Label(self.body, text="", bg=COLORS["card"], fg=COLORS["muted"], font=("Consolas", 8), wraplength=440, justify="left")
        self.detail_label.pack(pady=(8, 4), anchor="w")

    def set_progress(self, fraction, status_text, detail_text):
        if hasattr(self, "bar"):
            self.bar.delete("fill")
            width = max(2, int(438 * min(1.0, max(0.0, fraction))))
            self.bar.create_rectangle(1, 1, width, 13, fill=COLORS["fill"], outline="", tags="fill")
        if hasattr(self, "status_label"):
            self.status_label.configure(text=status_text)
        if hasattr(self, "detail_label"):
            self.detail_label.configure(text=detail_text)

    def show_done(self, version):
        self.clear_body()
        self.title_label.configure(text="Success!", fg=COLORS["success"])
        self.subtitle_label.configure(text=f"WeildBuild {version} installed")
        message = self.tk.Label(
            self.body,
            text="WeildBuild is ready.\nA WeildBuild Launcher shortcut was placed on your desktop.\nThe updater runs in the background and keeps the app fresh.",
            bg=COLORS["card"],
            fg=COLORS["body"],
            font=("Segoe UI", 10),
            justify="center",
        )
        message.pack(pady=(12, 16))
        buttons = self.tk.Frame(self.body, bg=COLORS["card"])
        buttons.pack()
        launch = self.make_button(buttons, "Launch WeildBuild", lambda: self.finish(launch_now=True))
        launch.pack(side="left", padx=6)
        finish = self.make_button(buttons, "Finish", lambda: self.finish(launch_now=False), primary=False)
        finish.pack(side="left", padx=6)

    def show_error(self, message):
        self.clear_body()
        self.title_label.configure(text="Oh snap-", fg=COLORS["error"])
        self.subtitle_label.configure(text="The installation failed")
        detail = self.tk.Label(self.body, text=message, bg=COLORS["card"], fg=COLORS["body"], font=("Consolas", 9), wraplength=440, justify="left")
        detail.pack(pady=(10, 14))
        buttons = self.tk.Frame(self.body, bg=COLORS["card"])
        buttons.pack()
        retry = self.make_button(buttons, "Try again", self.show_welcome)
        retry.pack(side="left", padx=6)
        close = self.make_button(buttons, "Close", self.root.destroy, primary=False)
        close.pack(side="left", padx=6)

    def begin_install(self):
        target = Path(self.dir_var.get()).expanduser()
        normalize_repo_arg(self.args.repo)
        self.show_progress()
        self.set_progress(0.0, "Contacting the WeildBuild repository...", "")
        worker = threading.Thread(target=self.install_worker, args=(target.resolve(),), daemon=True)
        worker.start()

    def install_worker(self, target):
        try:
            core.setup_logging(target, "installer")

            def progress(done, total, relative):
                self.queue.put(("progress", done, total, relative))

            def stop():
                return self.cancelled

            manifest, version = download_all(target, progress, stop)
            if manifest is None:
                self.queue.put(("error", version))
                return
            shortcut = core.create_desktop_shortcut(target)
            self.queue.put(("done", version, shortcut))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def poll_queue(self):
        try:
            while True:
                message = self.queue.get_nowait()
                kind = message[0]
                if kind == "progress":
                    _, done, total, relative = message
                    self.set_progress(done / max(1, total), f"Downloading WeildBuild files... {done}/{total}", relative)
                elif kind == "done":
                    _, version, shortcut = message
                    self.show_done(version)
                elif kind == "error":
                    self.show_error(message[1])
        except queue.Empty:
            pass
        self.root.after(80, self.poll_queue)

    def finish(self, launch_now):
        if launch_now and self.last_target:
            launch_installed(self.last_target)
        self.root.destroy()

    def run(self):
        self.last_target = None
        original_done = self.show_done

        def capture_done(version):
            self.last_target = Path(self.dir_var.get()).expanduser().resolve()
            original_done(version)

        self.show_done = capture_done
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="WeildBuild installer wizard")
    parser.add_argument("--cli", action="store_true", help="run without the graphical wizard")
    parser.add_argument("--dir", type=str, default=None, help="installation directory")
    parser.add_argument("--repo", type=str, default=None, help="repository override (owner/name or https base url)")
    parser.add_argument("--version", type=str, default=None, help="version shown in the wizard header")
    parser.add_argument("--launch", action="store_true", help="launch the app after a CLI install")
    args = parser.parse_args()

    if args.cli:
        target = Path(args.dir).expanduser().resolve() if args.dir else default_install_dir().resolve()
        args.dir = target
        return run_cli(args)
    wizard = InstallWizard(args)
    wizard.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
