use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use chrono::NaiveDateTime;
use lazy_static::lazy_static;
use lz4::Decoder;
use serde_json::json;
use std::collections::HashMap;
use tar::Archive;
use walkdir::WalkDir;
use zip::ZipArchive;

lazy_static! {
    static ref PYTHON_PROCESS: Mutex<Option<std::process::Child>> = Mutex::new(None);
    static ref LOG_FILE_CACHE: Mutex<HashMap<String, Vec<String>>> = Mutex::new(HashMap::new());
}

pub fn init_python_engine() -> Result<(), String> {
    let mut process_guard = PYTHON_PROCESS.lock().unwrap();

    if process_guard.is_some() {
        return Ok(());
    }

    let child = Command::new("python3")
        .arg("pythonai/video.py")
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("无法启动 Python OCR 服务: {}", e))?;

    *process_guard = Some(child);

    println!("🚀 Python OCR 服务已启动");

    Ok(())
}

pub fn stop_python_engine() {
    let mut process_guard = PYTHON_PROCESS.lock().unwrap();

    if let Some(mut child) = process_guard.take() {
        let _ = child.kill();
        println!("🛑 Python OCR 服务已关闭");
    }
}

fn project_extract_dir() -> String {
    format!(
        "{}/log_hunter_extracted",
        std::env::current_dir().unwrap().to_string_lossy()
    )
}

fn project_audio_dir() -> Result<PathBuf, String> {
    let dir = std::env::current_dir()
        .map_err(|e| format!("获取项目目录失败: {}", e))?
        .join("log_hunter_audio");

    fs::create_dir_all(&dir).map_err(|e| format!("创建音频目录失败: {}", e))?;

    Ok(dir)
}

pub fn extract_audio_from_video(video_path: String) -> Result<String, String> {
    let video = Path::new(&video_path);

    if !video.exists() {
        return Err(format!("视频文件不存在: {}", video_path));
    }

    let stem = video
        .file_stem()
        .map(|v| v.to_string_lossy().to_string())
        .unwrap_or_else(|| "video".to_string())
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect::<String>();

    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| format!("获取时间失败: {}", e))?
        .as_millis();

    let output_path = project_audio_dir()?.join(format!("{}_{}.wav", stem, ts));

    let output = Command::new("ffmpeg")
        .arg("-y")
        .arg("-i")
        .arg(&video_path)
        .arg("-vn")
        .arg("-ac")
        .arg("1")
        .arg("-ar")
        .arg("16000")
        .arg("-f")
        .arg("wav")
        .arg(&output_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("无法启动 ffmpeg，请确认已安装: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("音频抽取失败:\n{}", stderr));
    }

    Ok(output_path.to_string_lossy().to_string())
}

pub fn prepare_logs_for_zip(zip_path: String) -> String {
    println!("📦 拖入 ZIP，开始自动解压: {}", zip_path);

    let extract_dir = project_extract_dir();

    match prepare_logs(&zip_path, &extract_dir) {
        Ok(_) => {
            LOG_FILE_CACHE.lock().unwrap().clear();
            format!("✅ ZIP 自动解压完成\n目录: {}", extract_dir)
        }
        Err(e) => format!("❌ ZIP 自动解压失败\n{}", e),
    }
}

pub fn prepare_logs(zip_path: &str, extract_dir: &str) -> Result<(), String> {
    let is_already_extracted = fs::read_dir(extract_dir)
        .map(|mut i| i.next().is_some())
        .unwrap_or(false);

    if !is_already_extracted {
        println!("📦 开始解压 ZIP");

        fs::create_dir_all(extract_dir).map_err(|e| format!("创建解压目录失败: {}", e))?;

        let zip_file = File::open(zip_path).map_err(|e| format!("打开 ZIP 失败: {}", e))?;

        let mut archive = ZipArchive::new(zip_file).map_err(|e| format!("ZIP 格式错误: {}", e))?;

        archive
            .extract(extract_dir)
            .map_err(|e| format!("ZIP 解压失败: {}", e))?;

        println!("✅ ZIP 解压完成");
    } else {
        println!("⚡ 使用已解压缓存");
    }

    extract_all_tar_lz4_flat(extract_dir)?;
    cleanup_extra_files(extract_dir)?;
    LOG_FILE_CACHE.lock().unwrap().clear();

    Ok(())
}

fn extract_all_tar_lz4_flat(extract_dir: &str) -> Result<(), String> {
    println!("🧩 开始平铺解压 tar.lz4");

    let lz4_files: Vec<PathBuf> = WalkDir::new(extract_dir)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file())
        .filter(|e| {
            e.path()
                .to_string_lossy()
                .to_lowercase()
                .ends_with(".tar.lz4")
        })
        .map(|e| e.path().to_path_buf())
        .collect();

    println!("📦 tar.lz4 数量: {}", lz4_files.len());

    for path in lz4_files {
        extract_one_tar_lz4_flat(&path)?;

        if let Err(e) = fs::remove_file(&path) {
            println!("⚠️ 删除 tar.lz4 失败: {} {}", path.display(), e);
        }
    }

    println!("✅ tar.lz4 平铺解压完成");

    Ok(())
}

fn extract_one_tar_lz4_flat(path: &Path) -> Result<(), String> {
    println!("📂 平铺解压: {}", path.display());

    let parent_dir = path
        .parent()
        .ok_or_else(|| "tar.lz4 没有父目录".to_string())?;

    let file = File::open(path).map_err(|e| format!("打开 lz4 失败 {}: {}", path.display(), e))?;

    let decoder =
        Decoder::new(file).map_err(|e| format!("lz4 解码失败 {}: {}", path.display(), e))?;

    let mut archive = Archive::new(decoder);

    let entries = archive
        .entries()
        .map_err(|e| format!("读取 tar entries 失败: {}", e))?;

    let mut count = 0usize;

    for entry_result in entries {
        let mut entry = match entry_result {
            Ok(v) => v,
            Err(e) => {
                println!("⚠️ 读取 tar entry 失败: {}", e);
                continue;
            }
        };

        if !entry.header().entry_type().is_file() {
            continue;
        }

        let entry_path = match entry.path() {
            Ok(v) => v.to_path_buf(),
            Err(_) => continue,
        };

        let file_name = match entry_path.file_name() {
            Some(v) => v.to_string_lossy().to_string(),
            None => continue,
        };

        let safe_name = file_name.replace("/", "_").replace("\\", "_");

        let target_file = parent_dir.join(&safe_name);

        if target_file.exists() {
            continue;
        }

        if let Err(e) = entry.unpack(&target_file) {
            println!(
                "⚠️ 解包失败: {} -> {}: {}",
                entry_path.display(),
                target_file.display(),
                e
            );
            continue;
        }

        count += 1;
    }

    println!("✅ {} 平铺解压完成，文件数: {}", path.display(), count);

    Ok(())
}

fn cleanup_extra_files(extract_dir: &str) -> Result<(), String> {
    println!("🧹 清理多余文件");

    let entries: Vec<PathBuf> = WalkDir::new(extract_dir)
        .into_iter()
        .filter_map(|e| e.ok())
        .map(|e| e.path().to_path_buf())
        .collect();

    for path in entries {
        let p = path.to_string_lossy().to_lowercase();

        if p.ends_with(".flat.done") || p.ends_with(".done") {
            let _ = fs::remove_file(&path);
            continue;
        }

        if path.is_dir() {
            let name = path
                .file_name()
                .map(|v| v.to_string_lossy().to_string())
                .unwrap_or_default();

            if name.ends_with(".tar") {
                let _ = fs::remove_dir_all(&path);
            }
        }
    }

    println!("✅ 清理完成");

    Ok(())
}

pub fn get_extract_dir() -> String {
    project_extract_dir()
}

pub fn get_log_dir(zip_inner_dir: String) -> String {
    let extract_dir = project_extract_dir();

    if zip_inner_dir.trim().is_empty() {
        extract_dir
    } else {
        format!("{}/{}", extract_dir, zip_inner_dir.trim())
    }
}

pub fn process_files(
    target_timestamp: String,
    zip_path: String,
    zip_inner_dir: String,
    tag_keyword: String,
    _range_ms: i32,
) -> String {
    println!("==============================");
    println!("🚀 Rust 只执行日志检索");
    println!("📦 ZIP: {}", zip_path);
    println!("📁 目录: {}", zip_inner_dir);

    let extract_dir = project_extract_dir();
    let log_dir = if zip_inner_dir.trim().is_empty() {
        extract_dir.clone()
    } else {
        format!("{}/{}", extract_dir, zip_inner_dir.trim())
    };

    if !Path::new(&log_dir).exists() {
        return format!(
            "❌ 日志目录不存在\n{}\n请先拖入 ZIP 完成解压后再 Run",
            log_dir
        );
    }

    if target_timestamp.trim().is_empty() {
        return format!("✅ 日志解压完成\n{}", log_dir);
    }

    search_logs_by_tag(&log_dir, &target_timestamp, &tag_keyword)
}

fn normalize_tag(tag: &str) -> String {
    tag.trim()
        .trim_end_matches('_')
        .trim_end_matches(':')
        .to_lowercase()
}

fn line_contains_tag(line: &str, tag: &str) -> bool {
    let tag = normalize_tag(tag);

    if tag.is_empty() {
        return true;
    }

    line.to_lowercase().contains(&tag)
}

fn normalize_time_key(timestamp: &str) -> String {
    let value = timestamp.trim();

    if value.len() >= 19 && value.as_bytes().get(4) == Some(&b'-') {
        return value[5..19].to_string();
    }

    if value.len() >= 14 {
        return value[..14].to_string();
    }

    value.to_string()
}

fn extract_log_time(line: &str) -> String {
    let bytes = line.as_bytes();

    for i in 0..bytes.len().saturating_sub(13) {
        if bytes[i].is_ascii_digit()
            && bytes.get(i + 1).is_some_and(u8::is_ascii_digit)
            && bytes.get(i + 2) == Some(&b'-')
            && bytes.get(i + 3).is_some_and(u8::is_ascii_digit)
            && bytes.get(i + 4).is_some_and(u8::is_ascii_digit)
            && bytes.get(i + 5) == Some(&b' ')
            && bytes.get(i + 6).is_some_and(u8::is_ascii_digit)
            && bytes.get(i + 7).is_some_and(u8::is_ascii_digit)
            && bytes.get(i + 8) == Some(&b':')
            && bytes.get(i + 9).is_some_and(u8::is_ascii_digit)
            && bytes.get(i + 10).is_some_and(u8::is_ascii_digit)
            && bytes.get(i + 11) == Some(&b':')
            && bytes.get(i + 12).is_some_and(u8::is_ascii_digit)
            && bytes.get(i + 13).is_some_and(u8::is_ascii_digit)
        {
            let mut end = i + 14;

            while end < bytes.len() && (bytes[end].is_ascii_digit() || bytes[end] == b'.') {
                end += 1;
            }

            return line[i..end].to_string();
        }
    }

    String::new()
}

fn is_main_log_file(path: &Path) -> bool {
    if !path.is_file() {
        return false;
    }

    let Some(name) = path.file_name().map(|v| v.to_string_lossy().to_lowercase()) else {
        return false;
    };

    if !name.starts_with("main_log") {
        return false;
    }

    ![".zip", ".tar", ".lz4", ".done", ".db", ".md"]
        .iter()
        .any(|ext| name.ends_with(ext))
}

fn collect_main_log_files(log_dir: &str) -> Vec<String> {
    if let Some(cached) = LOG_FILE_CACHE.lock().unwrap().get(log_dir).cloned() {
        return cached;
    }

    let mut files = Vec::new();

    for entry in WalkDir::new(log_dir).into_iter().flatten() {
        let path = entry.path();

        if is_main_log_file(path) {
            files.push(path.to_string_lossy().to_string());
        }
    }

    files.sort();

    LOG_FILE_CACHE
        .lock()
        .unwrap()
        .insert(log_dir.to_string(), files.clone());

    files
}

fn parse_timestamp_for_scoring(timestamp: &str) -> Option<NaiveDateTime> {
    let normalized = normalize_time_key(timestamp);
    let candidate = format!("2026-{}", normalized);

    NaiveDateTime::parse_from_str(&candidate, "%Y-%m-%d %H:%M:%S").ok()
}

fn parse_time_from_filename(path: &str) -> Option<NaiveDateTime> {
    let name = Path::new(path)
        .file_name()
        .map(|v| v.to_string_lossy().to_string())
        .unwrap_or_default();

    let digits: String = name.chars().filter(|c| c.is_ascii_digit()).collect();

    if digits.len() < 14 {
        return None;
    }

    NaiveDateTime::parse_from_str(&digits[..14], "%Y%m%d%H%M%S").ok()
}

fn choose_nearest_files(files: &[String], timestamp: &str, limit: usize) -> Vec<String> {
    let Some(target) = parse_timestamp_for_scoring(timestamp) else {
        return files.iter().take(limit).cloned().collect();
    };

    let mut items: Vec<(i64, String)> = files
        .iter()
        .map(|file| {
            let diff = parse_time_from_filename(file)
                .map(|dt| (dt - target).num_seconds().abs())
                .unwrap_or(i64::MAX / 2);
            (diff, file.clone())
        })
        .collect();

    items.sort_by_key(|(diff, _)| *diff);
    items
        .into_iter()
        .take(limit)
        .map(|(_, file)| file)
        .collect()
}

fn find_hit(files: &[String], time_key: &str, tag: &str) -> Option<serde_json::Value> {
    let mut tag_fallback = None;
    let mut time_fallback = None;

    for file in files {
        let Ok(handle) = File::open(file) else {
            continue;
        };

        for (index, line_result) in BufReader::new(handle).lines().enumerate() {
            let Ok(line) = line_result else {
                continue;
            };

            let line_no = index + 1;
            let has_time = !time_key.is_empty() && line.contains(time_key);
            let has_tag = line_contains_tag(&line, tag);

            if has_time && has_tag {
                return Some(json!({
                    "file": file,
                    "line": line_no,
                    "text": line,
                    "mode": if normalize_tag(tag).is_empty() { "time" } else { "time + tag" },
                }));
            }

            if has_time && time_fallback.is_none() {
                time_fallback = Some(json!({
                    "file": file,
                    "line": line_no,
                    "text": line,
                    "mode": "time",
                }));
            }

            if has_tag && tag_fallback.is_none() && !normalize_tag(tag).is_empty() {
                tag_fallback = Some(json!({
                    "file": file,
                    "line": line_no,
                    "text": line,
                    "mode": "tag fallback",
                }));
            }
        }
    }

    tag_fallback.or(time_fallback)
}

fn collect_current_file_tag_lines(file: &str, tag: &str) -> Vec<serde_json::Value> {
    let tag = normalize_tag(tag);

    if tag.is_empty() {
        return Vec::new();
    }

    let Ok(handle) = File::open(file) else {
        return Vec::new();
    };

    let mut result = Vec::new();

    for (index, line_result) in BufReader::new(handle).lines().enumerate() {
        let Ok(line) = line_result else {
            continue;
        };

        if !line.to_lowercase().contains(&tag) {
            continue;
        }

        result.push(json!({
            "line": index + 1,
            "time": extract_log_time(&line),
            "text": line,
        }));
    }

    result
}

fn search_logs_by_tag(log_dir: &str, timestamp: &str, tag: &str) -> String {
    let files = collect_main_log_files(log_dir);
    let time_key = normalize_time_key(timestamp);
    let scan_files = choose_nearest_files(&files, timestamp, 3);

    if files.is_empty() {
        return json!({
            "success": false,
            "error": "没有找到 main_log 文件",
            "timestamp": timestamp,
            "time_key": time_key,
            "tag": tag,
            "log_dir": log_dir,
            "files": files,
            "hit": null,
            "current_file_tag_lines": [],
            "current_file_tag_total": 0,
        })
        .to_string();
    }

    let hit = find_hit(&scan_files, &time_key, tag);

    let Some(hit_value) = hit else {
        return json!({
            "success": false,
            "error": "未找到匹配日志",
            "timestamp": timestamp,
            "time_key": time_key,
            "tag": tag,
            "log_dir": log_dir,
            "files": files,
            "hit": null,
            "current_file_tag_lines": [],
            "current_file_tag_total": 0,
        })
        .to_string();
    };

    let file = hit_value
        .get("file")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    let tag_lines = collect_current_file_tag_lines(file, tag);

    json!({
        "success": true,
        "timestamp": timestamp,
        "time_key": time_key,
        "tag": tag,
        "log_dir": log_dir,
        "files": scan_files,
        "hit": hit_value,
        "current_file_tag_lines": tag_lines,
        "current_file_tag_total": tag_lines.len(),
    })
    .to_string()
}
