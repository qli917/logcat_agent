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

- 🎥 Video timestamp recognition
- ⚡ High-speed ZIP / tar.lz4 extraction
- 🔍 Automatic Logcat location
- 📝 Sublime Text integration
- 🖥 Flutter Desktop UI
- 🤖 OCR powered by CRNN
- 📦 Android Export Log support

---

## 🎯 Why Logcat Agent

Traditional workflow:

```text
Recording
 ↓
Watch video
 ↓
Remember time
 ↓
Extract logs
 ↓
Search timestamp
 ↓
Search tag
 ↓
Locate issue
```

Logcat Agent:

```text
Recording
 ↓
Click
 ↓
Done
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
Locate Problem Frame
 ↓
OCR Timestamp
 ↓
Rust Extract Logs
 ↓
Python Search Logs
 ↓
Open Sublime At Exact Line
```

---

## 🎯 Use Cases

- Android App Development
- Android Framework
- AOSP Development
- ROM Development
- Kernel Development
- QA Testing
- System Debugging

---

## 📸 Screenshots

### Main Window

Add screenshots and demo GIF here.

---

## ⚡ Performance

Environment:

```text
Ubuntu
Intel i7
32GB RAM
NVMe SSD
```

Typical Results:

```text
OCR               < 1s
ZIP Extraction    Seconds
Log Location      Seconds
```

---

## 🗺 Roadmap

### Current
- [x] OCR Timestamp Recognition
- [x] Android Export Log Extraction
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

Repository:
https://github.com/qli917/logcat_agent