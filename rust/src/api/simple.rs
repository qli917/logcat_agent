use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::Mutex;

use chrono::{Duration, NaiveDateTime};
use lazy_static::lazy_static;
use rayon::prelude::*;
use walkdir::WalkDir;
use zip::ZipArchive;

use lz4::Decoder;
use tar::Archive;

lazy_static! {
    static ref PYTHON_PROCESS: Mutex<Option<std::process::Child>> =
        Mutex::new(None);
}

// =========================
// Python OCR 服务
// =========================

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

// =========================
// 解压 ZIP
// =========================

pub fn prepare_logs(
    zip_path: &str,
    extract_dir: &str,
) -> Result<(), String> {
    let is_already_extracted = fs::read_dir(extract_dir)
        .map(|mut i| i.next().is_some())
        .unwrap_or(false);

    if !is_already_extracted {
        println!("📦 开始解压 ZIP");

        fs::create_dir_all(extract_dir)
            .map_err(|e| e.to_string())?;

        let zip_file = File::open(zip_path)
            .map_err(|e| format!("打开 ZIP 失败: {}", e))?;

        let mut archive = ZipArchive::new(zip_file)
            .map_err(|e| format!("ZIP 格式错误: {}", e))?;

        archive
            .extract(extract_dir)
            .map_err(|e| format!("ZIP 解压失败: {}", e))?;

        println!("✅ ZIP 解压完成");
    } else {
        println!("⚡ 使用缓存日志目录");
    }

    println!("🧩 开始解压 tar.lz4");

    let lz4_files: Vec<_> = WalkDir::new(extract_dir)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file())
        .filter(|e| {
            e.path()
                .to_string_lossy()
                .to_lowercase()
                .ends_with(".tar.lz4")
        })
        .collect();

    for entry in lz4_files {
        let path = entry.path();

        let out_dir = path.with_extension("");

        if out_dir.exists() {
            continue;
        }

        println!("📂 解压: {}", path.display());

        let file = File::open(path)
            .map_err(|e| format!("打开 lz4 失败: {}", e))?;

        let decoder = Decoder::new(file)
            .map_err(|e| format!("lz4 解码失败: {}", e))?;

        fs::create_dir_all(&out_dir)
            .map_err(|e| format!("创建目录失败: {}", e))?;

        let mut archive = Archive::new(decoder);

        archive
            .unpack(&out_dir)
            .map_err(|e| format!("tar 解包失败: {}", e))?;
    }

    println!("✅ tar.lz4 解压完成");

    Ok(())
}

// =========================
// 构建时间搜索 Key
// =========================

fn build_time_keys(
    target_timestamp: &str,
    range_ms: i32,
) -> Vec<String> {

    let mut keys = Vec::new();

    let dt = match NaiveDateTime::parse_from_str(
        target_timestamp,
        "%Y-%m-%d %H:%M:%S%.3f",
    ) {
        Ok(v) => v,

        Err(_) => {
            keys.push(target_timestamp.to_string());

            return keys;
        }
    };

    let mut offset = -range_ms;

    while offset <= range_ms {

        let t = dt + Duration::milliseconds(offset as i64);

        keys.push(
            t.format("%Y-%m-%d %H:%M:%S%.3f")
                .to_string(),
        );

        keys.push(
            t.format("%Y-%m-%d %H:%M:%S")
                .to_string(),
        );

        keys.push(
            t.format("%m-%d %H:%M:%S%.3f")
                .to_string(),
        );

        keys.push(
            t.format("%m-%d %H:%M:%S")
                .to_string(),
        );

        keys.push(
            t.format("%H:%M:%S")
                .to_string(),
        );

        offset += 100;
    }

    keys.sort();
    keys.dedup();

    keys
}

// =========================
// 时间匹配
// =========================

fn line_contains_any_time(
    line: &str,
    keys: &[String],
) -> bool {

    keys.iter().any(|k| line.contains(k))
}

// =========================
// TAG 匹配
// =========================

fn line_contains_tag(
    line: &str,
    tag_keyword: &str,
) -> bool {

    let tag = tag_keyword.trim();

    if tag.is_empty() {
        return true;
    }

    line.to_lowercase()
        .contains(&tag.to_lowercase())
}

// =========================
// 搜索日志
// =========================

pub fn search_in_logs(
    search_dir: &str,
    target_timestamp: &str,
    tag_keyword: &str,
    range_ms: i32,
) -> Option<String> {

    let time_keys = build_time_keys(
        target_timestamp,
        range_ms,
    );

    println!("📂 搜索目录: {}", search_dir);

    let entries: Vec<_> = WalkDir::new(search_dir)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file())
        .filter(|e| {
            let p = e.path()
                .to_string_lossy()
                .to_lowercase();

            !p.ends_with(".zip")
                && !p.ends_with(".tar")
                && !p.ends_with(".lz4")
        })
        .collect();

    println!("📄 文件数: {}", entries.len());

    entries.par_iter().find_map_any(|entry| {

        let path = entry.path();

        let file = File::open(path).ok()?;

        let reader = BufReader::new(file);

        for (index, line_result) in reader.lines().enumerate() {

            let line = line_result.ok()?;

            let time_match =
                line_contains_any_time(
                    &line,
                    &time_keys,
                );

            if !time_match {
                continue;
            }

            let tag_match =
                line_contains_tag(
                    &line,
                    tag_keyword,
                );

            if tag_match {

                return Some(format!(
                    "{}:{}\n{}",
                    path.to_str().unwrap_or(""),
                    index + 1,
                    line
                ));
            }

            // TAG为空时直接返回
            if tag_keyword.trim().is_empty() {

                return Some(format!(
                    "{}:{}\n{}",
                    path.to_str().unwrap_or(""),
                    index + 1,
                    line
                ));
            }
        }

        None
    })
}

pub fn prepare_logs_for_zip(zip_path: String) -> String {
    println!("📦 拖入 ZIP，开始自动解压: {}", zip_path);

    let extract_dir = format!(
        "{}/log_hunter_extracted",
        std::env::current_dir()
            .unwrap()
            .to_string_lossy()
    );

    match prepare_logs(&zip_path, &extract_dir) {
        Ok(_) => format!("✅ ZIP 自动解压完成\n目录: {}", extract_dir),
        Err(e) => format!("❌ ZIP 自动解压失败\n{}", e),
    }
}
// =========================
// 主入口
// =========================

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

  let extract_dir = format!(
    "{}/log_hunter_extracted",
    std::env::current_dir()
        .unwrap()
        .to_string_lossy()
);
    if let Err(e) =
        prepare_logs(&zip_path, &extract_dir)
    {
        return format!(
            "❌ 日志准备失败\n{}",
            e
        );
    }

    let search_dir =
        if zip_inner_dir.trim().is_empty() {

            extract_dir.to_string()

        } else {

            format!(
                "{}/{}",
                extract_dir,
                zip_inner_dir.trim()
            )
        };

    if !Path::new(&search_dir).exists() {

        return format!(
            "❌ 搜索目录不存在\n{}",
            search_dir
        );
    }

    println!("🔍 开始搜索...");

    if let Some(result) =
        search_in_logs(
            &search_dir,
            &target_timestamp,
            &tag_keyword,
            range_ms,
        )
    {

        println!("✅ 找到结果");

        let file_part = result
            .split('\n')
            .next()
            .unwrap_or("");

        let _ = Command::new("subl")
            .arg(file_part)
            .spawn();

        return format!(
            "✅ 找到结果\n\n{}",
            result
        );
    }

    println!("⚠️ 未找到匹配");

    format!(
        "⚠️ 未找到匹配\n\n时间戳: {}\n目录: {}\nTAG: {}\n范围: ±{}ms",
        target_timestamp,
        zip_inner_dir,
        tag_keyword,
        range_ms
    )
}