use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

const REPO_RAW: &str = "https://raw.githubusercontent.com/candreagabriel21-tech/weildbuild-app/main/desktop";
const DEFAULT_PORT: u32 = 49231;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut dir: Option<PathBuf> = None;
    let mut port: Option<u32> = None;
    let mut mode_install = false;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--dir" | "-d" => { i += 1; dir = args.get(i).map(PathBuf::from); }
            "--port" | "-p" => { i += 1; port = args.get(i).and_then(|v| v.parse().ok()); }
            "--install" => mode_install = true,
            _ => {}
        }
        i += 1;
    }

    let exe_dir = std::env::current_exe().ok().and_then(|p| p.parent().map(|p| p.to_path_buf()));
    let config = exe_dir.as_ref().map(|d| read_config(&d.join("install.json"))).flatten();
    let app_dir = dir
        .or_else(|| config.as_ref().map(|c| PathBuf::from(&c.app_dir)))
        .unwrap_or_else(default_dir);
    let wanted_port = port.or_else(|| config.as_ref().map(|c| c.port)).unwrap_or(DEFAULT_PORT);

    let needs_install = mode_install || !app_dir.join("index.html").exists();
    if needs_install {
        println!("WeildBuild files not found - downloading them from GitHub...");
        match install(&app_dir, config.as_ref().map(|c| c.version.as_str())) {
            Ok(v) => println!("WeildBuild {} is ready.", v),
            Err(e) => {
                println!("Installation failed: {} {}", e.0, e.1);
                println!("Check your internet connection and start again.");
                wait_exit(1);
            }
        }
    }

    let (listener, bound_port) = match bind(wanted_port) {
        Ok(v) => v,
        Err(_) => {
            println!("Could not open a local port for WeildBuild ({} tried).", wanted_port);
            wait_exit(1);
        }
    };
    if let Some(cfg_path) = exe_dir.as_ref().map(|d| d.join("install.json")) {
        if let Some(mut cfg) = read_config(&cfg_path) {
            if cfg.port != bound_port {
                cfg.port = bound_port;
                let _ = std::fs::write(&cfg_path, serialize_config(&cfg));
            }
        }
    }

    let url = format!("http://127.0.0.1:{bound_port}/");
    println!("WeildBuild is running at {url}");
    println!("Your browser should open in a second.");
    println!("Keep this window open while you play - close it to stop WeildBuild.");
    open_browser(&url);

    let app_dir = Arc::new(app_dir);
    let shutting_down = Arc::new(AtomicBool::new(false));
    for stream in listener.incoming() {
        if shutting_down.load(Ordering::Relaxed) {
            break;
        }
        match stream {
            Ok(s) => {
                let dir = Arc::clone(&app_dir);
                std::thread::spawn(move || {
                    let _ = handle(s, &dir);
                });
            }
            Err(_) => continue,
        }
    }
}

struct Config {
    app_dir: String,
    port: u32,
    version: String,
}

fn read_config(path: &Path) -> Option<Config> {
    let raw = std::fs::read_to_string(path).ok()?;
    let app_dir = json_string(&raw, "app_dir").unwrap_or_default();
    let port = json_number(&raw, "port").unwrap_or(DEFAULT_PORT);
    let version = json_string(&raw, "version").unwrap_or_else(|| "1.1.0".into());
    Some(Config { app_dir, port, version })
}

fn serialize_config(cfg: &Config) -> String {
    format!(
        "{{\"app_dir\":\"{}\",\"port\":{},\"version\":\"{}\"}}",
        cfg.app_dir.replace('\\', "\\\\").replace('"', "\\\""),
        cfg.port,
        cfg.version
    )
}

fn json_string(raw: &str, key: &str) -> Option<String> {
    let needle = format!("\"{key}\"");
    let pos = raw.find(&needle)?;
    let after = &raw[pos + needle.len()..];
    let colon = after.find(':')?;
    let after = &after[colon + 1..];
    let q1 = after.find('"')?;
    let bytes = after.as_bytes();
    let mut i = q1 + 1;
    let mut out = String::new();
    while i < bytes.len() {
        let c = bytes[i] as char;
        if c == '\\' && i + 1 < bytes.len() {
            let n = bytes[i + 1] as char;
            if n == 'n' { out.push('\n'); } else if n == 't' { out.push('\t'); } else { out.push(n); }
            i += 2;
            continue;
        }
        if c == '"' {
            return Some(out);
        }
        out.push(c);
        i += 1;
    }
    None
}

fn json_number(raw: &str, key: &str) -> Option<u32> {
    let needle = format!("\"{key}\"");
    let pos = raw.find(&needle)?;
    let after = &raw[pos + needle.len()..];
    let colon = after.find(':')?;
    let num: String = after[colon + 1..].trim_start().chars().take_while(|c| c.is_ascii_digit()).collect();
    num.parse().ok()
}

fn default_dir() -> PathBuf {
    if cfg!(target_os = "windows") {
        let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| std::env::var("USERPROFILE").unwrap_or_default());
        PathBuf::from(base).join("WeildBuild")
    } else {
        let base = std::env::var("HOME").unwrap_or_default();
        PathBuf::from(base).join(".local/share/weildbuild")
    }
}

struct ErrCode(String, String);

fn install(app_dir: &Path, known_version: Option<&str>) -> Result<String, ErrCode> {
    if std::fs::create_dir_all(app_dir).is_err() {
        return Err(ErrCode("FIL-007".into(), "Couldn't create the install folder.".into()));
    }
    let version_path = app_dir.join("wb-version.json");
    fetch(&format!("{REPO_RAW}/wb-version.json"), &version_path)?;
    let version = std::fs::read_to_string(&version_path)
        .ok()
        .and_then(|raw| parse_version_text(&raw))
        .or_else(|| known_version.map(|s| s.to_string()))
        .unwrap_or_else(|| "1.1.0".into());

    let manifest_path = app_dir.join(".wb-files-tmp.json");
    fetch(&format!("{REPO_RAW}/wb-files.json"), &manifest_path)?;
    let raw = std::fs::read_to_string(&manifest_path).unwrap_or_default();
    let _ = std::fs::remove_file(&manifest_path);
    let files = parse_manifest(&raw)
        .ok_or(ErrCode("UPD-005".into(), "Invalid update information.".into()))?;
    let total: u64 = files.iter().map(|f| f.1).sum();
    println!("Download size: {} ({} files)", human(total), files.len());

    for (i, (path, size)) in files.iter().enumerate() {
        println!("[{}/{}] Downloading: {} ({})", i + 1, files.len(), path, human(*size));
        let dest = app_dir.join(path);
        if let Some(parent) = dest.parent() {
            if std::fs::create_dir_all(parent).is_err() {
                return Err(ErrCode("FIL-007".into(), format!("Couldn't write file: {path}")));
            }
        }
        if let Err(e) = fetch(&format!("{REPO_RAW}/{path}"), &dest) {
            let _ = std::fs::remove_file(&dest);
            return Err(e);
        }
    }
    Ok(version)
}

fn fetch(url: &str, dest: &Path) -> Result<(), ErrCode> {
    let out = Command::new(curl_program())
        .args(["-fsSL", "--retry", "2", "--connect-timeout", "20", "--max-time", "300", "-o"])
        .arg(dest)
        .arg(url)
        .output();
    let out = match out {
        Ok(o) => o,
        Err(_) => return Err(ErrCode("SYS-004".into(), "curl is not available on this machine.".into())),
    };
    if out.status.success() {
        return Ok(());
    }
    let code = out.status.code().unwrap_or(1);
    Err(match code {
        6 => ErrCode("NET-001".into(), "No internet connection.".into()),
        7 | 35 | 56 => ErrCode("NET-002".into(), "Unable to reach server.".into()),
        28 => ErrCode("NET-003".into(), "Server answered too late.".into()),
        22 => ErrCode("FIL-002".into(), "Files not found on the server.".into()),
        _ => ErrCode("NET-005".into(), "Connection interrupted.".into()),
    })
}

fn curl_program() -> &'static str {
    if cfg!(target_os = "windows") { "curl.exe" } else { "curl" }
}

fn parse_version_text(raw: &str) -> Option<String> {
    let line = raw.trim();
    let line = line.strip_prefix("version").unwrap_or(line);
    let line = line.trim_start_matches(['=', ' ', '\t']);
    let line = line.trim().trim_matches('"');
    let parts: Vec<&str> = line.split('.').collect();
    if parts.len() >= 2 && parts.iter().all(|p| p.chars().all(|c| c.is_ascii_digit()) && !p.is_empty()) {
        Some(line.to_string())
    } else {
        None
    }
}

fn parse_manifest(raw: &str) -> Option<Vec<(String, u64)>> {
    let files_pos = raw.find("\"files\"")?;
    let mut rest = &raw[files_pos..];
    let mut out = Vec::new();
    loop {
        let obj_start = rest.find('{')?;
        let (obj, after) = balanced_object(&rest[obj_start..])?;
        let path = json_string(obj, "path")?;
        let size = json_number64(obj, "size").unwrap_or(0);
        out.push((path, size));
        rest = after;
        if out.len() > 100_000 || !rest.contains('{') {
            break;
        }
    }
    if out.is_empty() { None } else { Some(out) }
}

fn balanced_object(s: &str) -> Option<(&str, &str)> {
    let bytes = s.as_bytes();
    let mut depth = 0usize;
    let mut in_string = false;
    let mut escaped = false;
    for (i, &b) in bytes.iter().enumerate() {
        let c = b as char;
        if in_string {
            if escaped {
                escaped = false;
            } else if c == '\\' {
                escaped = true;
            } else if c == '"' {
                in_string = false;
            }
        } else {
            match c {
                '"' => in_string = true,
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        return Some((&s[..=i], &s[i + 1..]));
                    }
                }
                _ => {}
            }
        }
    }
    None
}

fn json_number64(raw: &str, key: &str) -> Option<u64> {
    let needle = format!("\"{key}\"");
    let pos = raw.find(&needle)?;
    let after = &raw[pos + needle.len()..];
    let colon = after.find(':')?;
    let num: String = after[colon + 1..].trim_start().chars().take_while(|c| c.is_ascii_digit()).collect();
    num.parse().ok()
}

fn human(bytes: u64) -> String {
    let units = ["b", "kb", "mb", "gb", "tb", "pb"];
    let mut value = bytes as f64;
    let mut unit = 0;
    while value >= 1024.0 && unit < units.len() - 1 {
        value /= 1024.0;
        unit += 1;
    }
    if value >= 100.0 {
        format!("{:.0} {}", value, units[unit])
    } else {
        format!("{:.1} {}", value, units[unit])
    }
}

fn bind(wanted: u32) -> std::io::Result<(TcpListener, u32)> {
    for offset in 0..20u32 {
        let p = wanted + offset;
        if let Ok(l) = TcpListener::bind(("127.0.0.1", p as u16)) {
            return Ok((l, p));
        }
    }
    Err(std::io::Error::new(std::io::ErrorKind::AddrInUse, "no port"))
}

fn open_browser(url: &str) {
    let result = if cfg!(target_os = "windows") {
        Command::new("cmd").args(["/C", "start", "", url]).spawn()
    } else if cfg!(target_os = "macos") {
        Command::new("open").arg(url).spawn()
    } else {
        Command::new("xdg-open").arg(url).spawn()
    };
    let _ = result;
}

fn handle(mut stream: TcpStream, app_dir: &Path) -> std::io::Result<()> {
    let mut buf = Vec::new();
    let mut byte = [0u8; 1];
    loop {
        match stream.read(&mut byte) {
            Ok(0) => break,
            Ok(_) => {
                buf.push(byte[0]);
                if buf.len() >= 4 && &buf[buf.len() - 4..] == b"\r\n\r\n" {
                    break;
                }
                if buf.len() > 16384 {
                    break;
                }
            }
            Err(_) => break,
        }
    }
    let text = String::from_utf8_lossy(&buf);
    let first_line = text.lines().next().unwrap_or("");
    let mut parts = first_line.split_whitespace();
    let method = parts.next().unwrap_or("");
    let target = parts.next().unwrap_or("/");
    let path = decode_path(target);
    if method != "GET" && method != "HEAD" {
        write_response(&mut stream, 405, "Method Not Allowed", "text/plain; charset=utf-8", b"use GET", true)?;
        return Ok(());
    }
    let rel = if path == "/" || path.is_empty() { "/index.html" } else { &path };
    let safe = match safe_join(app_dir, rel) {
        Some(p) => p,
        None => {
            write_response(&mut stream, 403, "Forbidden", "text/plain; charset=utf-8", b"forbidden", true)?;
            return Ok(());
        }
    };
    match std::fs::read(&safe) {
        Ok(body) => {
            let ctype = content_type(rel);
            let _ = write_response(&mut stream, 200, "OK", ctype, &body, method != "HEAD");
        }
        Err(_) => {
            write_response(&mut stream, 404, "Not Found", "text/plain; charset=utf-8", b"not found", method != "HEAD")?;
        }
    }
    Ok(())
}

fn decode_path(target: &str) -> String {
    let no_query = target.split(['?', '#']).next().unwrap_or("/");
    let mut out = String::new();
    let bytes = no_query.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(v) = u8::from_str_radix(&no_query[i + 1..i + 3], 16) {
                out.push(v as char);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i] as char);
        i += 1;
    }
    out
}

fn safe_join(app_dir: &Path, rel: &str) -> Option<PathBuf> {
    if rel.contains("..") {
        return None;
    }
    let cleaned = rel.trim_start_matches('/');
    let p = app_dir.join(cleaned);
    if p.starts_with(app_dir) {
        Some(p)
    } else {
        None
    }
}

fn content_type(path: &str) -> &'static str {
    let ext = path.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "html" => "text/html; charset=utf-8",
        "js" => "application/javascript",
        "css" => "text/css",
        "json" => "application/json",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "webp" => "image/webp",
        "avif" => "image/avif",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "ttf" => "font/ttf",
        "wasm" => "application/wasm",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "m4a" => "audio/mp4",
        "webmanifest" => "application/manifest+json",
        "txt" => "text/plain",
        _ => "application/octet-stream",
    }
}

fn write_response(stream: &mut TcpStream, code: u16, reason: &str, ctype: &str, body: &[u8], with_body: bool) -> std::io::Result<()> {
    let head = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n",
        code, reason, ctype, body.len()
    );
    stream.write_all(head.as_bytes())?;
    if with_body {
        stream.write_all(body)?;
    }
    Ok(())
}

fn wait_exit(code: i32) -> ! {
    println!();
    println!("Press Enter to close this window...");
    let _ = std::io::stdout().flush();
    let mut line = String::new();
    let _ = std::io::stdin().read_line(&mut line);
    std::process::exit(code);
}
