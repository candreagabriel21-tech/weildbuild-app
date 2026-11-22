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


def probe_interpreter(candidate: str) -> bool:
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        completed = subprocess.run([candidate, "-c", "print(1)"], capture_output=True, timeout=15, creationflags=flags)
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_INTERPRETER_CACHE: list | None = None


def pick_interpreter() -> list | None:
    global _INTERPRETER_CACHE
    if _INTERPRETER_CACHE is not None:
        return list(_INTERPRETER_CACHE)
    if is_frozen():
        _INTERPRETER_CACHE = [sys.executable]
        return list(_INTERPRETER_CACHE)
    candidates = [sys.executable]
    if os.name == "nt":
        candidates += ["py.exe", "python.exe", "python3.exe"]
    else:
        candidates += ["python3", "python"]
    seen = set()
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved is None and Path(candidate).is_absolute() and Path(candidate).is_file():
            resolved = candidate
        if not resolved or resolved.lower() in seen:
            continue
        seen.add(resolved.lower())
        if probe_interpreter(resolved):
            _INTERPRETER_CACHE = [resolved]
            return list(_INTERPRETER_CACHE)
    return None


def python_launch_command() -> list | None:
    return pick_interpreter()


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
        interpreter = pick_interpreter()
        if interpreter is None:
            return None
        command = interpreter + [str(tool_path)]
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
    interpreter = pick_interpreter()
    if launcher_path.suffix.lower() == ".py" and interpreter is None:
        return None
    if os.name == "nt":
        desktop = windows_desktop_path()
        if desktop is None:
            return None
        shortcut = desktop / "WeildBuild Launcher.lnk"
        if launcher_path.suffix.lower() == ".py":
            target = interpreter[0]
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
        body = "#!/bin/sh\ncd \"" + str(base_dir) + "\"\nexec \"" + interpreter[0] + "\" \"" + str(launcher_path) + "\"\n"
        atomic_write(command_path, body.encode("utf-8"))
        command_path.chmod(0o755)
        return str(command_path)
    applications = home / ".local" / "share" / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    entry = applications / "weildbuild-launcher.desktop"
    if launcher_path.suffix.lower() == ".py":
        exec_line = f'"{interpreter[0]}" "{launcher_path}"'
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
import sys
import time
from pathlib import Path



def read_installed_version(base_dir: Path) -> str:
    version_file = core.data_root(base_dir) / core.VERSION_FILE_PRIMARY
    try:
        return core.parse_version_text(version_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "0.0.0"


def write_state(base_dir: Path, state: dict) -> None:
    core.atomic_write(core.pardon_root(base_dir) / core.UPDATER_STATE_NAME, json.dumps(state, indent=2).encode("utf-8"))


def load_state(base_dir: Path) -> dict:
    path = core.pardon_root(base_dir) / core.UPDATER_STATE_NAME
    try:
        state = core.loads_json_bytes(path.read_bytes())
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def download_manifest(repo_unused: str) -> tuple:
    manifest_raw = core.fetch_repo_file(core.MANIFEST_NAME)
    manifest = core.loads_json_bytes(manifest_raw)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("manifest.json has no files list")
    return manifest_raw, manifest


def reconcile_payload(base_dir: Path, manifest: dict, prefixes: list) -> list:
    entries = core.manifest_entry_map(manifest)
    expected = set(entries)
    payload_dir = core.payload_root(base_dir)
    deleted = []
    if not payload_dir.is_dir():
        return deleted
    for path in sorted(payload_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_file():
            continue
        relative = path.relative_to(core.data_root(base_dir)).as_posix()
        if core.is_pardoned(relative, prefixes):
            continue
        if f"{core.DATA_DIR_NAME}/{relative}" in expected:
            continue
        try:
            path.unlink()
            deleted.append(relative)
        except OSError as exc:
            print(f"could not delete {relative}: {exc}", file=sys.stderr)
    core.clean_empty_dirs(payload_dir)
    return deleted


def apply_update(base_dir: Path, manifest_raw: bytes, manifest: dict, version: str, logger) -> dict:
    prefixes = core.read_pardon_prefixes(base_dir)
    entries = core.manifest_entry_map(manifest)
    changed = []
    for relative, entry in entries.items():
        path = core.safe_join(base_dir, relative)
        wanted_sha = entry.get("sha256")
        wanted_size = entry.get("size")
        if path.is_file() and path.stat().st_size == wanted_size and (not wanted_sha or core.sha256_hex(path.read_bytes()) == wanted_sha):
            continue
        repo_relative = entry.get("src", relative)
        blob = core.fetch_repo_file(repo_relative)
        if wanted_sha and core.sha256_hex(blob) != wanted_sha:
            raise ValueError(f"{repo_relative}: checksum mismatch after download")
        if wanted_size is not None and len(blob) != wanted_size:
            raise ValueError(f"{repo_relative}: size mismatch after download")
        core.replace_locked(path, blob, base_dir)
        changed.append(relative)
    deleted = reconcile_payload(base_dir, manifest, prefixes)
    version_text = f'version = "{version}"\n'.encode("utf-8")
    core.atomic_write(core.data_root(base_dir) / core.VERSION_FILE_PRIMARY, version_text)
    core.atomic_write(core.data_root(base_dir) / core.VERSION_FILE_ALIAS, version_text)
    core.atomic_write(core.data_root(base_dir) / core.MANIFEST_NAME, manifest_raw)
    try:
        pardon_blob = core.fetch_repo_file(core.PARDON_LIST_NAME)
        core.atomic_write(core.data_root(base_dir) / core.PARDON_LIST_NAME, pardon_blob)
    except Exception:
        pass
    cfg = core.load_config(base_dir)
    cfg["version"] = version
    core.save_config(cfg, base_dir)
    logger.info("update applied: %s (+%d changed, -%d deleted)", version, len(changed), len(deleted))
    return {"version": version, "changed": changed, "deleted": deleted}


def check_cycle(base_dir: Path, logger) -> dict:
    state = load_state(base_dir)
    try:
        remote_text = core.fetch_repo_file(core.VERSION_FILE_PRIMARY).decode("utf-8")
        remote_version = core.parse_version_text(remote_text)
    except Exception as exc:
        state["lastCheckAt"] = int(time.time())
        state["lastError"] = str(exc)
        state["networkTrouble"] = True
        logger.warning("check failed: %s", exc)
        write_state(base_dir, state)
        return state

    installed_version = read_installed_version(base_dir)
    state["lastCheckAt"] = int(time.time())
    state["latestVersion"] = remote_version
    state["installedVersion"] = installed_version
    state["lastError"] = None
    state["networkTrouble"] = False
    if core.is_newer(remote_version, installed_version):
        logger.info("update available: %s -> %s", installed_version, remote_version)
        try:
            manifest_raw, manifest = download_manifest(remote_version)
            applied = apply_update(base_dir, manifest_raw, manifest, remote_version, logger)
            state["upToDate"] = True
            state["updateApplied"] = {"version": applied["version"], "at": int(time.time()), "changed": applied["changed"], "deleted": applied["deleted"]}
        except Exception as exc:
            logger.error("update failed: %s", exc)
            state["upToDate"] = False
            state["updateFailed"] = str(exc)
    else:
        state["upToDate"] = True
    write_state(base_dir, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="WeildBuild background updater")
    parser.add_argument("--dir", type=str, default=None, help="installation directory (default: next to this script)")
    parser.add_argument("--repo", type=str, default=None, help="repository override (owner/name or https base url)")
    parser.add_argument("--interval", type=int, default=60, help="seconds between checks")
    parser.add_argument("--once", action="store_true", help="run a single check and exit")
    args = parser.parse_args()

    base_dir = Path(args.dir).expanduser().resolve() if args.dir else core.app_dir()
    if args.repo:
        os.environ[core.REPO_OVERRIDE_ENV] = args.repo
    logger = core.setup_logging(base_dir, "updater")
    pardon_dir = core.pardon_root(base_dir)
    pardon_dir.mkdir(parents=True, exist_ok=True)

    while True:
        check_cycle(base_dir, logger)
        if args.once:
            return 0
        try:
            time.sleep(max(15, args.interval))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
