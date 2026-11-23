use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::Command;

const REPO_RAW: &str = "https://raw.githubusercontent.com/candreagabriel21-tech/weildbuild-app/main/desktop";
const PORT: u32 = 49231;

fn main() {
    println!("WeildBuild installer");
    println!("====================");
    let default_dir = default_install_dir();
    println!("Where should WeildBuild be installed?");
    println!("Press Enter for the default, or type a folder path.");
    print!("[{}]: ", default_dir.display());
    let _ = io::stdout().flush();
    let mut answer = String::new();
    let _ = io::stdin().read_line(&mut answer);
    let answer = answer.trim().to_string();
    let dir = if answer.is_empty() { default_dir } else { PathBuf::from(answer) };

    let version = match install(&dir) {
        Ok(v) => v,
        Err(code) => {
            println!();
            println!("Installation failed: {} {}", code.0, code.1);
            println!("Nothing was broken - run the installer again to retry.");
            wait_exit(1);
        }
    };
    println!();
    println!("WeildBuild {} installed in {}", version, dir.display());
    println!("A shortcut was created on your desktop. The installer will close now.");
    wait_exit(0);
}

struct ErrCode(String, String);

fn install(dir: &Path) -> Result<String, ErrCode> {
    if std::fs::create_dir_all(dir).is_err() {
        return Err(ErrCode("FIL-007".into(), "Couldn't create the install folder.".into()));
    }
    let tmp = dir.join(".wb-install-tmp");
    let _ = std::fs::create_dir_all(&tmp);

    println!("Checking the WeildBuild servers...");
    let version_tmp = tmp.join("wb-version.json");
    fetch(&format!("{REPO_RAW}/wb-version.json"), &version_tmp)?;
    let version = read_version_file(&version_tmp);

    println!("Checking how big the update is...");
    let manifest_tmp = tmp.join("wb-files.json");
    fetch(&format!("{REPO_RAW}/wb-files.json"), &manifest_tmp)?;
    let raw = std::fs::read_to_string(&manifest_tmp).unwrap_or_default();
    let files = parse_manifest(&raw)
        .ok_or(ErrCode("UPD-005".into(), "Invalid update information.".into()))?;
    let total: u64 = files.iter().map(|f| f.1).sum();
    println!("Update size: {} ({} files)", human(total), files.len());

    for (i, (path, size)) in files.iter().enumerate() {
        println!("[{}/{}] Updating: {} ({})", i + 1, files.len(), path, human(*size));
        let dest = dir.join(path);
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

    let launcher_name = if cfg!(target_os = "windows") { "weildbuild-launcher.exe" } else { "weildbuild-launcher" };
    println!("Setting up the launcher...");
    let launcher_dest = dir.join(launcher_name);
    fetch(&format!("{REPO_RAW}/bin/{launcher_name}"), &launcher_dest)?;
    make_executable(&launcher_dest);

    let install_json = dir.join("install.json");
    let app_dir_json = json_escape(&dir.to_string_lossy());
    std::fs::write(
        &install_json,
        format!(
            "{{\"app_dir\":\"{app_dir_json}\",\"port\":{PORT},\"version\":\"{}\"}}",
            version.as_deref().unwrap_or("1.1.0")
        ),
    )
    .map_err(|_| ErrCode("FIL-007".into(), "Couldn't write install.json".into()))?;

    let _ = std::fs::remove_dir_all(&tmp);

    println!("Creating the desktop shortcut...");
    create_shortcut(&launcher_dest, dir);

    println!("Cleaning up...");
    delete_self();
    Ok(version.unwrap_or_else(|| "1.1.0".into()))
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

fn default_install_dir() -> PathBuf {
    if cfg!(target_os = "windows") {
        let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| std::env::var("USERPROFILE").unwrap_or_default());
        PathBuf::from(base).join("WeildBuild")
    } else {
        let base = std::env::var("HOME").unwrap_or_default();
        PathBuf::from(base).join(".local/share/weildbuild")
    }
}

fn read_version_file(path: &Path) -> Option<String> {
    let raw = std::fs::read_to_string(path).ok()?;
    parse_version_text(&raw)
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
    let body = &raw[files_pos..];
    let mut out = Vec::new();
    let mut rest = body;
    loop {
        let obj_start = rest.find('{')?;
        let (obj, after) = balanced_object(&rest[obj_start..])?;
        let path = string_field(obj, "path")?;
        let size = number_field(obj, "size").unwrap_or(0);
        out.push((path, size));
        rest = after;
        if out.len() > 100_000 {
            return None;
        }
        if !rest.contains('{') {
            break;
        }
    }
    if out.is_empty() { None } else { Some(out) }
}

fn balanced_object(s: &str) -> Option<(&str, &str)> {
    let bytes = s.as_bytes();
    let mut i = 0;
    let mut depth = 0usize;
    let mut in_string = false;
    let mut escaped = false;
    while i < bytes.len() {
        let c = bytes[i] as char;
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
        i += 1;
    }
    None
}

fn string_field(obj: &str, key: &str) -> Option<String> {
    let needle = format!("\"{key}\"");
    let pos = obj.find(&needle)?;
    let after_key = &obj[pos + needle.len()..];
    let colon = after_key.find(':')?;
    let after_colon = &after_key[colon + 1..];
    let q1 = after_colon.find('"')?;
    let bytes = after_colon.as_bytes();
    let mut i = q1 + 1;
    let mut out = String::new();
    while i < bytes.len() {
        let c = bytes[i] as char;
        if c == '\\' && i + 1 < bytes.len() {
            let n = bytes[i + 1] as char;
            match n {
                'n' => out.push('\n'),
                't' => out.push('\t'),
                'r' => out.push('\r'),
                'u' => {
                    if i + 6 <= bytes.len() {
                        if let Ok(cp) = u32::from_str_radix(&after_colon[i + 2..i + 6], 16) {
                            if let Some(ch) = char::from_u32(cp) {
                                out.push(ch);
                            }
                        }
                        i += 6;
                        continue;
                    }
                    return None;
                }
                other => out.push(other),
            }
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

fn number_field(obj: &str, key: &str) -> Option<u64> {
    let needle = format!("\"{key}\"");
    let pos = obj.find(&needle)?;
    let after_key = &obj[pos + needle.len()..];
    let colon = after_key.find(':')?;
    let after_colon = &after_key[colon + 1..];
    let num: String = after_colon.trim_start().chars().take_while(|c| c.is_ascii_digit()).collect();
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

fn json_escape(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}

fn make_executable(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = std::fs::metadata(path) {
            let mut perms = meta.permissions();
            perms.set_mode(0o755);
            let _ = std::fs::set_permissions(path, perms);
        }
    }
    let _ = path;
}

fn create_shortcut(launcher: &Path, dir: &Path) {
    if cfg!(target_os = "windows") {
        let ps = format!(
            "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -COM WScript.Shell).CreateShortcut(\"$d\\WeildBuild.lnk\"); $s.TargetPath='{}'; $s.WorkingDirectory='{}'; $s.Save()",
            launcher.display(),
            dir.display()
        );
        let _ = Command::new("powershell.exe").args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &ps]).output();
    } else {
        let home = std::env::var("HOME").unwrap_or_default();
        let entry = format!(
            "[Desktop Entry]\nType=Application\nName=WeildBuild\nExec=\"{}\"\nCategories=Game;\n",
            launcher.display()
        );
        let _ = std::fs::create_dir_all(format!("{home}/.local/share/applications"));
        let _ = std::fs::write(format!("{home}/.local/share/applications/weildbuild.desktop"), &entry);
        if std::path::Path::new(&format!("{home}/Desktop")).is_dir() {
            let _ = std::fs::write(format!("{home}/Desktop/weildbuild.desktop"), &entry);
        }
        make_executable(launcher);
    }
    let _ = dir;
}

fn delete_self() {
    let self_path = std::env::current_exe().unwrap_or_default();
    if cfg!(target_os = "windows") {
        use std::os::windows::process::CommandExt;
        const DETACHED: u32 = 0x00000008 | 0x00000200;
        let cmd = format!("timeout /t 2 /nobreak >nul & del /f /q \"{}\"", self_path.display());
        let _ = Command::new("cmd").args(["/C", &cmd]).creation_flags(DETACHED).spawn();
    } else {
        let _ = std::fs::remove_file(&self_path);
    }
}

fn wait_exit(code: i32) -> ! {
    println!();
    println!("Press Enter to close this window...");
    let _ = io::stdout().flush();
    let mut line = String::new();
    let _ = io::stdin().read_line(&mut line);
    std::process::exit(code);
}
