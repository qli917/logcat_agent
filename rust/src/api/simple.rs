use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;

use chrono::{Duration, NaiveDateTime};
use lazy_static::lazy_static;
use lz4::Decoder;
use rayon::prelude::*;
use tar::Archive;
use walkdir::WalkDir;
use zip::ZipArchive;

lazy_static! {
    static ref PYTHON_PROCESS: Mutex<Option<std::process::Child>> =
        Mutex::new(None);
}

struct LogHit {
    file_path: String,
    line_number: usize,
    line_text: String,
}

pub fn init_python_engine() -> Result<(), String> {
    let mut process_guard = PYTHON_PROCESS.lock().unwrap();

    if process_guard.is_some() {
        return Ok(());
    }

    let child = Command::new("python3")
        .arg("pythonai/video.py")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
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

pub fn prepare_logs_for_zip(zip_path: String) -> String {
    let extract_dir = project_extract_dir();

    println!("📦 拖入 ZIP，开始自动解压: {}", zip_path);
    println!("📂 解压目录: {}", extract_dir);

    match prepare_logs(&zip_path, &extract_dir) {
        Ok(_) => format!("✅ ZIP 自动解压完成\n目录: {}", extract_dir),
        Err(e) => format!("❌ ZIP 自动解压失败\n{}", e),
    }
}

pub fn prepare_logs(zip_path: &str, extract_dir: &str) -> Result<(), String> {
    let is_already_extracted = fs::read_dir(extract_dir)
        .map(|mut i| i.next().is_some())
        .unwrap_or(false);

    if !is_already_extracted {
        println!("📦 开始解压 ZIP");

        fs::create_dir_all(extract_dir).map_err(|e| e.to_string())?;

        let zip_file =
            File::open(zip_path).map_err(|e| format!("打开 ZIP 失败: {}", e))?;

        let mut archive =
            ZipArchive::new(zip_file).map_err(|e| format!("ZIP 格式错误: {}", e))?;

        archive
            .extract(extract_dir)
            .map_err(|e| format!("ZIP 解压失败: {}", e))?;

        println!("✅ ZIP 解压完成");
    } else {
        println!("⚡ 使用缓存日志目录");
    }

    extract_all_tar_lz4_flat(extract_dir)?;
    cleanup_extra_files(extract_dir)?;

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

    let file =
        File::open(path).map_err(|e| format!("打开 lz4 失败 {}: {}", path.display(), e))?;

    let decoder =
        Decoder::new(file).map_err(|e| format!("lz4 解码失败 {}: {}", path.display(), e))?;

    let mut archive = Archive::new(decoder);

    let entries = archive
        .entries()
        .map_err(|e| format!("读取 tar entries 失败: {}", e))?;

    let mut count = 0;

    for entry_result in entries {
        let mut entry = match entry_result {
            Ok(v) => v,
            Err(_) => continue,
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
    println!("🧹 清理多余文件...");

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

fn build_time_keys(target_timestamp: &str, range_ms: i32) -> Vec<String> {
    let mut keys = Vec::new();

    let dt = match NaiveDateTime::parse_from_str(
        target_timestamp,
        "%Y-%m-%d %H:%M:%S%.3f",
    ) {
        Ok(v) => v,
        Err(_) => {
            keys.push(target_timestamp.to_string());

            if target_timestamp.len() >= 14 {
                keys.push(target_timestamp.to_string());
            }

            keys.sort();
            keys.dedup();

            return keys;
        }
    };

    let mut offset = -range_ms;

    while offset <= range_ms {
        let t = dt + Duration::milliseconds(offset as i64);

        keys.push(t.format("%Y-%m-%d %H:%M:%S%.3f").to_string());
        keys.push(t.format("%Y-%m-%d %H:%M:%S").to_string());
        keys.push(t.format("%m-%d %H:%M:%S%.3f").to_string());
        keys.push(t.format("%m-%d %H:%M:%S").to_string());
        keys.push(t.format("%H:%M:%S").to_string());

        offset += 100;
    }

    keys.sort();
    keys.dedup();

    keys
}

fn line_contains_any_time(line: &str, keys: &[String]) -> bool {
    keys.iter().any(|k| !k.is_empty() && line.contains(k))
}

fn line_contains_tag(line: &str, tag_keyword: &str) -> bool {
    let tag = tag_keyword.trim();

    if tag.is_empty() {
        return true;
    }

    line.to_lowercase().contains(&tag.to_lowercase())
}

fn is_searchable_file(path: &Path) -> bool {
    let p = path.to_string_lossy().to_lowercase();

    !p.ends_with(".zip")
        && !p.ends_with(".tar")
        && !p.ends_with(".lz4")
        && !p.ends_with(".done")
        && !p.ends_with(".flat.done")
}

pub fn search_in_logs(
    search_dir: &str,
    target_timestamp: &str,
    tag_keyword: &str,
    range_ms: i32,
) -> Option<String> {
    let time_keys = build_time_keys(target_timestamp, range_ms);

    println!("📂 搜索目录: {}", search_dir);
    println!("🕒 时间Key数量: {}", time_keys.len());
    println!("🏷 TAG: {}", tag_keyword);

    let entries: Vec<_> = WalkDir::new(search_dir)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file())
        .filter(|e| is_searchable_file(e.path()))
        .collect();

    println!("📄 可搜索文件数: {}", entries.len());

    if !tag_keyword.trim().is_empty() {
        let tag_files = find_files_by_tag(&entries, tag_keyword);

        println!("🏷 TAG命中文件数: {}", tag_files.len());

        if tag_files.is_empty() {
            return None;
        }

        if let Some(time_hit) = find_file_by_time(&tag_files, &time_keys) {

    if let Some(tag_hit) =
        search_tag_in_file(&time_hit.file_path, tag_keyword)
    {
        return Some(format!(
            "✅ TAG文件时间命中\n\n{}:{}\n{}\n\n时间行:{}",
            tag_hit.file_path,
            tag_hit.line_number,
            tag_hit.line_text,
            time_hit.line_number
        ));
    }

    return Some(format!(
        "✅ 时间命中\n\n{}:{}\n{}",
        time_hit.file_path,
        time_hit.line_number,
        time_hit.line_text
    ));
}

        return None;
    }

    if let Some(time_hit) = find_file_by_time(&entries, &time_keys) {
        return Some(format!(
            "✅ 时间命中\n\n{}:{}\n{}",
            time_hit.file_path,
            time_hit.line_number,
            time_hit.line_text
        ));
    }

    None
}

fn find_file_by_time(entries: &[walkdir::DirEntry], time_keys: &[String]) -> Option<LogHit> {
    entries.par_iter().find_map_any(|entry| {
        let path = entry.path();

        let file = File::open(path).ok()?;
        let reader = BufReader::new(file);

        for (index, line_result) in reader.lines().enumerate() {
            let line = line_result.ok()?;

            if line_contains_any_time(&line, time_keys) {
                return Some(LogHit {
                    file_path: path.to_str().unwrap_or("").to_string(),
                    line_number: index + 1,
                    line_text: line,
                });
            }
        }

        None
    })
}

fn search_tag_in_file(file_path: &str, tag_keyword: &str) -> Option<LogHit> {
    let file = File::open(file_path).ok()?;
    let reader = BufReader::new(file);

    for (index, line_result) in reader.lines().enumerate() {
        let line = line_result.ok()?;

        if line_contains_tag(&line, tag_keyword) {
            return Some(LogHit {
                file_path: file_path.to_string(),
                line_number: index + 1,
                line_text: line,
            });
        }
    }

    None
}

fn open_in_sublime(result: &str) {
    let first_line = result.lines().find(|line| line.starts_with('/')).unwrap_or("");

    if first_line.is_empty() {
        return;
    }

    let Some(split_index) = first_line.rfind(':') else {
        let _ = Command::new("subl").arg(first_line).spawn();
        return;
    };

    let file_path = &first_line[..split_index];
    let line_num = &first_line[split_index + 1..];

    if !Path::new(file_path).exists() {
        println!("⚠️ Sublime文件不存在: {}", file_path);
        return;
    }

    let open_arg = format!("{}:{}", file_path, line_num);

    println!("📝 打开 Sublime: {}", open_arg);

    let _ = Command::new("subl").arg(open_arg).spawn();
}




pub fn process_files(
    target_timestamp: String,
    zip_path: String,
    zip_inner_dir: String,
    tag_keyword: String,
    range_ms: i32,
) -> String {
    println!("==============================");
    println!("🚀 开始日志检索");
    println!("🕒 时间戳: {}", target_timestamp);
    println!("📦 ZIP: {}", zip_path);
    println!("📁 目录: {}", zip_inner_dir);
    println!("🏷 TAG: {}", tag_keyword);
    println!("⏱ 范围: ±{}ms", range_ms);

    let extract_dir = project_extract_dir();

    if let Err(e) = prepare_logs(&zip_path, &extract_dir) {
        return format!("❌ 日志准备失败\n{}", e);
    }

    let search_dir = if zip_inner_dir.trim().is_empty() {
        extract_dir.clone()
    } else {
        format!("{}/{}", extract_dir, zip_inner_dir.trim())
    };

    if !Path::new(&search_dir).exists() {
        return format!("❌ 搜索目录不存在\n{}", search_dir);
    }

    println!("🔍 开始搜索...");

    if let Some(result) = search_in_logs(&search_dir, &target_timestamp, &tag_keyword, range_ms) {
        println!("✅ 找到结果");

        open_in_sublime(&result);

        return format!("✅ 找到结果\n\n{}", result);
    }

    println!("⚠️ 未找到匹配");

    format!(
        "⚠️ 未找到匹配\n\n时间戳: {}\n目录: {}\nTAG: {}\n范围: ±{}ms",
        target_timestamp, zip_inner_dir, tag_keyword, range_ms
    )
}

fn find_files_by_tag(
    entries: &[walkdir::DirEntry],
    tag_keyword: &str,
) -> Vec<walkdir::DirEntry> {
    entries
        .par_iter()
        .filter_map(|entry| {
            let path = entry.path();

            let file = File::open(path).ok()?;
            let reader = BufReader::new(file);

            for line_result in reader.lines() {
                let line = line_result.ok()?;

                if line_contains_tag(&line, tag_keyword) {
                    return Some(entry.clone());
                }
            }

            None
        })
        .collect()
}