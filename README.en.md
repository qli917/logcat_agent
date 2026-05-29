# Logcat Agent

[中文](./README.md) | [English](./README.en.md)

An intelligent Logcat assistant for Android log analysis.

---

## Overview

Logcat Agent helps process Android log packages, recognize timestamps from screenshots or videos, locate log lines by time, search key log entries, and summarize log context with AI.

Common problems this project aims to solve:

- Log packages can be large and slow to process
- A log package may contain many files
- Timestamps in screen recordings often need manual checking
- Developers need to locate log lines quickly by timestamp
- Complex logs require time-consuming manual analysis

Logcat Agent combines Flutter, Rust, Python, and AI features to build a local log analysis assistant.

---

## Core Features

### 1. Log Package Processing

- Extract log packages
- Scan log and text files
- Build timestamp indexes
- Support fast search after indexing

### 2. Timestamp Search

Locate the corresponding log file and target line by timestamp.

Supported timestamp examples:

```text
05-07 16:46:59.170
2026-05-07 16:46:59
16:46:59
```

### 3. OCR Timestamp Recognition

Use a Python OCR service to recognize timestamps from screenshots or video frames.

Current focus:

- Video frame extraction
- Timestamp region cropping
- OCR recognition
- Timestamp format correction
- Matching OCR timestamps with log timestamps

### 4. AI Log Analysis

Analyze located log snippets with an AI service to help identify possible causes.

Use cases:

- Error log summarization
- Crash and ANR analysis
- Key call chain extraction
- Suspicious log explanation
- Debugging suggestion generation

### 5. Flutter User Interface

Use Flutter to build a desktop or cross-platform user interface.

Planned support:

- Import log packages
- Upload screenshots or videos
- Recognize timestamps with OCR
- Enter target timestamps
- Display matched log files
- Highlight target log lines
- Submit logs for AI analysis

---

## Architecture

```text
Flutter UI
   ↓
Rust Log Processing Core
   ↓
Python OCR Service
   ↓
AI Log Analysis
```

Flutter handles the user interface, Rust handles high-performance log extraction and searching, Python handles OCR timestamp recognition, and the AI module provides log analysis and issue summarization.

---

## Tech Stack

| Module | Technology | Purpose |
|---|---|---|
| UI | Flutter | Build a cross-platform UI |
| Log Processing | Rust | High-performance extraction, search, and indexing |
| OCR Service | Python / FastAPI / OCR Model | Recognize timestamps from screenshots or videos |
| Storage | SQLite | Store log indexes, file paths, and timestamp mappings |
| AI Analysis | AI Service | Analyze log snippets intelligently |
| Platform | Linux / Ubuntu | Main development and runtime environment |

---

## Recommended Project Structure

```text
logcat_agent/
├── flutter_app/              # Flutter client
│   ├── lib/
│   ├── pubspec.yaml
│   └── ...
│
├── rust_core/                # Rust log processing module
│   ├── src/
│   ├── Cargo.toml
│   └── ...
│
├── pythonai/                 # Python OCR and AI service
│   ├── app.py
│   ├── requirements.txt
│   └── ...
│
├── data/                     # Local data directory
│   ├── logs/
│   ├── cache/
│   └── index.db
│
├── README.md                 # Chinese documentation
├── README.en.md              # English documentation
└── .gitignore
```

---

## Use Cases

### Android Debugging

Suitable for Android testing, system development, and app development log debugging.

Examples:

- Locate logcat entries based on screen recording timestamps
- Find error points from large amounts of logs
- Analyze logs before and after crashes
- Summarize system logs and app logs with AI

### Test Log Analysis

Testers can use screen recording timestamps and log packages to quickly locate logs related to the issue occurrence time.

### AOSP and Framework Debugging

Suitable for Android system development scenarios involving logcat, kernel logs, and system service logs.

---

## Basic Workflow

```text
1. Import a log package
2. Rust extracts logs and builds indexes
3. Import a video or screenshot
4. Python OCR recognizes timestamps
5. Search log files by timestamp
6. Flutter displays matched log lines
7. Analyze log context with AI
8. Output possible causes and debugging suggestions
```

---

## Local Development

### 1. Clone the Project

```bash
git clone git@github.com:qli917/logcat_agent.git
cd logcat_agent
```

### 2. Start the Python OCR Service

```bash
cd pythonai
pip install -r requirements.txt
python app.py
```

If using FastAPI:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

### 3. Start the Flutter Client

```bash
cd flutter_app
flutter pub get
flutter run
```

### 4. Build the Rust Log Processing Module

```bash
cd rust_core
cargo build --release
```

---

## Development Status

This project is still under development. Current priorities include:

- [ ] Improve the Flutter log import UI
- [ ] Optimize Rust extraction speed for large files
- [ ] Build SQLite-based log timestamp indexes
- [ ] Improve OCR timestamp recognition accuracy
- [ ] Support fast log line lookup by timestamp
- [ ] Integrate AI log analysis
- [ ] Add error sample collection and model iteration support

---

## Roadmap

- Support more log timestamp formats
- Support searching across multiple log files
- Support automatic log context extraction
- Support automatic error classification
- Support dedicated crash and ANR analysis
- Support local model deployment
- Support Windows, Linux, and macOS desktop clients

---

## Project Goal

Logcat Agent is not just a simple log viewer. Its goal is to become an intelligent log analysis agent for Android development and testing scenarios.

It aims to automate the full workflow from:

```text
Screen recording timestamp → OCR timestamp recognition → Log locating → Context extraction → AI analysis
```

---

## Security Notes

Do not commit sensitive information to this repository, including credentials, private logs, private test data, environment files, or database files containing private information.

---

## License

License is not specified yet.
