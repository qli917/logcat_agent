# Logcat Agent

一个面向 Android 日志分析场景的智能 Logcat 辅助工具。
An intelligent Logcat assistant for Android log analysis.

---

## 项目简介 / Overview

**中文**

Logcat Agent 主要用于处理大型 Android 日志压缩包、视频时间戳识别、日志时间定位、关键行检索以及 AI 日志分析，目标是把繁琐的人工查日志流程自动化。

在 Android 开发、测试和问题排查过程中，经常会遇到以下问题：

* 日志压缩包很大，解压和检索速度慢
* 日志文件数量多，不知道目标时间点在哪个文件里
* 视频录屏里的时间戳需要人工查看
* 需要根据时间戳快速定位对应 log 行
* 日志内容复杂，人工分析耗时较长

Logcat Agent 通过 Flutter、Rust、Python 和 AI 分析能力组合，构建一个本地化的日志分析助手。

**English**

Logcat Agent is designed for processing large Android log packages, recognizing timestamps from videos or screenshots, locating log lines by time, searching key log entries, and analyzing logs with AI.

During Android development, testing, and debugging, developers often face problems such as:

* Large log packages are slow to unzip and search
* Too many log files make it hard to locate the target timestamp
* Timestamps in screen recordings need to be checked manually
* Log lines need to be located quickly by timestamp
* Complex logs require time-consuming manual analysis

Logcat Agent combines Flutter, Rust, Python, and AI capabilities to build a local intelligent log analysis assistant.

---

## 核心功能 / Core Features

### 1. 大日志压缩包处理 / Large Log Package Processing

**中文**

支持对大型 zip 日志包进行快速解压和索引，为后续检索做准备。

目标能力：

* 快速解压大型日志压缩包
* 自动扫描 log / txt 文件
* 建立时间戳索引
* 支持后续秒级检索

**English**

Supports fast extraction and indexing of large zip log packages for later searching.

Target capabilities:

* Fast extraction of large log packages
* Automatic scanning of log / txt files
* Timestamp index creation
* Fast search support after indexing

---

### 2. 时间戳检索 / Timestamp Search

**中文**

根据用户输入或 OCR 识别出的时间戳，快速定位到对应日志文件和目标行。

支持的时间格式示例：

```text
05-07 16:46:59.170
2026-05-07 16:46:59
16:46:59
```

**English**

Quickly locates the corresponding log file and target line based on a timestamp entered by the user or recognized by OCR.

Supported timestamp examples:

```text
05-07 16:46:59.170
2026-05-07 16:46:59
16:46:59
```

---

### 3. OCR 时间识别 / OCR Timestamp Recognition

**中文**

通过 Python OCR 服务识别截图或视频画面中的时间戳，用于自动匹配日志时间点。

当前方向：

* 视频帧截图
* 时间戳区域裁剪
* OCR 识别
* 时间格式修正
* 与日志时间自动匹配

**English**

Uses a Python OCR service to recognize timestamps from screenshots or video frames and automatically match them with log timestamps.

Current focus:

* Video frame extraction
* Timestamp region cropping
* OCR recognition
* Timestamp format correction
* Automatic matching with log timestamps

---

### 4. AI 日志分析 / AI Log Analysis

**中文**

调用 ChatGPT API，对定位到的日志片段进行分析，辅助判断问题原因。

可用于：

* 异常日志总结
* crash / ANR / error 分析
* 关键调用链提取
* 可疑日志解释
* 问题排查建议生成

**English**

Uses the ChatGPT API to analyze located log snippets and help identify possible causes of issues.

Can be used for:

* Error log summarization
* Crash / ANR / error analysis
* Key call chain extraction
* Suspicious log explanation
* Debugging suggestion generation

---

### 5. Flutter 可视化界面 / Flutter User Interface

**中文**

使用 Flutter 构建桌面端或跨平台操作界面，降低日志分析使用门槛。

计划支持：

* 导入 zip 日志包
* 上传截图或视频
* OCR 识别时间戳
* 输入目标时间点
* 展示匹配到的日志文件
* 高亮选中目标日志行
* 一键提交 AI 分析

**English**

Uses Flutter to build a desktop or cross-platform user interface, making log analysis easier to use.

Planned support:

* Import zip log packages
* Upload screenshots or videos
* Recognize timestamps with OCR
* Enter target timestamps
* Display matched log files
* Highlight target log lines
* Submit logs for AI analysis with one click

---

## 技术架构 / Architecture

```text
Flutter UI
   ↓
Rust Log Processing Core
   ↓
Python OCR Service
   ↓
ChatGPT API Log Analysis
```

**中文**

整体流程由 Flutter 负责界面交互，Rust 负责高性能日志解压和检索，Python 负责 OCR 时间戳识别，ChatGPT API 负责日志分析和问题总结。

**English**

Flutter handles the user interface, Rust handles high-performance log extraction and searching, Python handles OCR timestamp recognition, and the ChatGPT API provides log analysis and issue summarization.

---

## 技术栈 / Tech Stack

| 模块 / Module           | 技术 / Technology              | 作用 / Purpose                                                             |
| --------------------- | ---------------------------- | ------------------------------------------------------------------------ |
| 前端界面 / UI             | Flutter                      | 构建跨平台可视化界面 / Build a cross-platform UI                                   |
| 日志处理 / Log Processing | Rust                         | 高性能解压、检索、索引 / High-performance extraction, search, and indexing          |
| OCR 服务 / OCR Service  | Python / FastAPI / OCR Model | 识别截图或视频中的时间戳 / Recognize timestamps from screenshots or videos           |
| 数据存储 / Storage        | SQLite                       | 保存日志索引、文件路径、时间映射 / Store log indexes, file paths, and timestamp mappings |
| AI 分析 / AI Analysis   | ChatGPT API                  | 对日志片段进行智能分析 / Analyze log snippets intelligently                         |
| 平台环境 / Platform       | Linux / Ubuntu               | 当前主要开发和运行环境 / Main development and runtime environment                   |

---

## 推荐项目结构 / Recommended Project Structure

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
├── pythonai/                 # Python OCR / AI service
│   ├── app.py
│   ├── requirements.txt
│   ├── timestamp_crnn.pt
│   ├── timestamp_crnn_best.pt
│   └── ...
│
├── data/                     # Local data directory
│   ├── logs/
│   ├── cache/
│   └── index.db
│
├── README.md
└── .gitignore
```

---

## 使用场景 / Use Cases

### Android 问题排查 / Android Debugging

**中文**

适用于 Android 测试、系统开发、APP 开发中的日志排查场景。

例如：

* 根据录屏时间找到对应 logcat
* 从大量日志中定位错误发生点
* 快速分析 crash 前后的日志
* 对系统日志、应用日志进行 AI 总结

**English**

Suitable for Android testing, system development, and app development log debugging.

Examples:

* Locate logcat entries based on screen recording timestamps
* Find error points from large amounts of logs
* Quickly analyze logs before and after crashes
* Summarize system logs and app logs with AI

---

### 测试日志分析 / Test Log Analysis

**中文**

测试人员可以通过录屏时间点和日志包，快速定位问题发生时刻对应的日志内容。

**English**

Testers can use screen recording timestamps and log packages to quickly locate logs related to the issue occurrence time.

---

### AOSP / Framework 开发排查 / AOSP and Framework Debugging

**中文**

适合 Android 系统开发中对 logcat、kernel log、系统服务日志进行辅助分析。

**English**

Suitable for Android system development scenarios involving logcat, kernel logs, and system service logs.

---

## 基本流程 / Basic Workflow

```text
1. 导入日志 zip 包 / Import a zip log package
2. Rust 解压并建立索引 / Rust extracts logs and builds indexes
3. 导入录屏或截图 / Import a video or screenshot
4. Python OCR 识别时间戳 / Python OCR recognizes timestamps
5. 根据时间戳检索日志文件 / Search log files by timestamp
6. Flutter 展示命中的日志行 / Flutter displays matched log lines
7. 调用 ChatGPT API 分析日志上下文 / Use ChatGPT API to analyze log context
8. 输出问题原因和排查建议 / Output possible causes and debugging suggestions
```

---

## 本地运行 / Local Development

### 1. 克隆项目 / Clone the Project

```bash
git clone git@github.com:qli917/logcat_agent.git
cd logcat_agent
```

---

### 2. 启动 Python OCR 服务 / Start the Python OCR Service

```bash
cd pythonai
pip install -r requirements.txt
python app.py
```

如果使用 FastAPI：

If using FastAPI:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

---

### 3. 启动 Flutter 客户端 / Start the Flutter Client

```bash
cd flutter_app
flutter pub get
flutter run
```

---

### 4. 构建 Rust 日志处理模块 / Build the Rust Log Processing Module

```bash
cd rust_core
cargo build --release
```

---

## 当前开发状态 / Development Status

项目仍在开发中，当前重点方向如下：
This project is still under development. Current priorities include:

* [ ] 完善 Flutter 日志导入界面 / Improve the Flutter log import UI
* [ ] 优化 Rust 大文件解压速度 / Optimize Rust extraction speed for large files
* [ ] 建立 SQLite 日志时间索引 / Build SQLite-based log timestamp indexes
* [ ] 优化 OCR 时间戳识别准确率 / Improve OCR timestamp recognition accuracy
* [ ] 支持按时间快速定位日志行 / Support fast log line lookup by timestamp
* [ ] 集成 ChatGPT API 日志分析 / Integrate ChatGPT API log analysis
* [ ] 增加错误样本收集和模型迭代能力 / Add error sample collection and model iteration support

---

## 后续计划 / Roadmap

* 支持更多日志时间格式 / Support more log timestamp formats
* 支持多日志文件联合检索 / Support searching across multiple log files
* 支持日志上下文自动截取 / Support automatic log context extraction
* 支持错误类型自动分类 / Support automatic error classification
* 支持 crash / ANR 专项分析 / Support dedicated crash / ANR analysis
* 支持模型本地化部署 / Support local model deployment
* 支持 Windows / Linux / macOS 桌面端 / Support Windows, Linux, and macOS desktop clients

---

## 项目目标 / Project Goal

**中文**

Logcat Agent 的目标不是简单做一个日志查看器，而是做一个面向 Android 开发和测试场景的智能日志分析 Agent。

它希望完成从：

```text
录屏时间点 → OCR 时间识别 → 日志定位 → 上下文提取 → AI 分析
```

这一整套自动化流程。

**English**

Logcat Agent is not just a simple log viewer. Its goal is to become an intelligent log analysis agent for Android development and testing scenarios.

It aims to automate the full workflow from:

```text
Screen recording timestamp → OCR timestamp recognition → Log locating → Context extraction → AI analysis
```

---

## 安全说明 / Security Notes

**中文**

请不要将以下敏感内容提交到仓库：

* API Key
* OpenAI / ChatGPT Token
* SSH 私钥
* 真实用户日志
* 私人测试数据
* `.env` 配置文件
* 包含隐私信息的数据库文件

**English**

Do not commit sensitive information to this repository, including:

* API keys
* OpenAI / ChatGPT tokens
* SSH private keys
* Real user logs
* Private test data
* `.env` files
* Database files containing private information

---

## License

当前暂未指定 License。
License is not specified yet.
