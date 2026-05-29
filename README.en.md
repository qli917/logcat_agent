# Logcat Agent

> AI-Powered Android Video → Logcat Locator

Automatically locate Android logs from screen recordings.

Flutter • Rust • Python • OCR

---

## 🚀 Demo Flow

```text
🎥 Video Recording
        ↓
🤖 OCR Timestamp
        ↓
⚡ Rust Extraction
        ↓
🔍 Log Search
        ↓
📝 Sublime Jump
```

---

## ✨ Features

- 🎥 Recognize timestamps from videos
- ⚡ Extract large Android Export Logs with Rust
- 📦 Support ZIP and tar.lz4 logs
- 🔍 Locate Logcat entries by timestamp and tag
- 📝 Open Sublime Text at the exact log line
- 🖥 Flutter desktop UI
- 🤖 CRNN-based OCR model powered by PyTorch

---

## 🎯 Why Logcat Agent

Traditional Android debugging workflow:

```text
Screen recording
 ↓
Watch video manually
 ↓
Remember timestamp
 ↓
Extract log package
 ↓
Search timestamp
 ↓
Search tag
 ↓
Locate issue
```

Logcat Agent workflow:

```text
Screen recording
 ↓
Click
 ↓
Open exact log line
```

---

## 🏗 Architecture

```text
Flutter
   │
   ├── Video Player
   ├── Timeline
   └── Drag & Drop
   │
   ▼
Rust
   ├── ZIP Extract
   ├── tar.lz4 Extract
   └── Log Directory Builder
   │
   ▼
Python
   ├── OCR
   ├── Timestamp Parsing
   ├── Log Search
   └── Sublime Launcher
   │
   ▼
Sublime Text
```

---

## 🛠 Tech Stack

### Frontend

- Flutter
- media_kit
- desktop_drop
- flutter_rust_bridge

### Backend

- Rust
- Python

### AI

- PyTorch
- CRNN OCR

---

## 📋 Workflow

```text
Drag Video
 ↓
Drag Android Export Log
 ↓
Move to Problem Frame
 ↓
Recognize Timestamp via OCR
 ↓
Extract Logs with Rust
 ↓
Search Logs with Python
 ↓
Open Sublime at Exact Line
```

---

## 🎯 Use Cases

- Android App Development
- Android Framework Debugging
- AOSP Development
- ROM Development
- Kernel Debugging
- QA Testing
- System Debugging

---

## 📸 Screenshots

Add screenshots and demo GIF here.

---

## ⚡ Performance

Typical local workflow:

```text
OCR               < 1s
ZIP Extraction    Seconds
Log Location      Seconds
```

Performance depends on disk speed, log package size, and device hardware.

---

## 🗺 Roadmap

### Current

- [x] OCR Timestamp Recognition
- [x] Android Export Log Extraction
- [x] ZIP / tar.lz4 Support
- [x] Log Location
- [x] Sublime Integration

### Next

- [ ] ChatGPT Log Analysis
- [ ] AI Root Cause Analysis
- [ ] Multi Log Package Search
- [ ] Markdown Report Generation

### Future

- [ ] Android Log Agent
- [ ] Autonomous Debug Assistant
- [ ] AI-generated Debug Reports

---

## ⭐ Star

If this project helps you, please give it a Star.

https://github.com/qli917/logcat_agent
