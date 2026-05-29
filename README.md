# Logcat Agent

AI-Powered Android Log Analysis Tool

Logcat Agent 是一个面向 Android 开发、测试、AOSP 与 Framework 工程师的日志定位工具。

核心目标：

```text
录屏 -> OCR识别时间戳 -> 自动解压日志 -> 定位对应日志 -> Sublime打开
```

## 为什么做这个项目

传统排查流程：

```text
查看录屏
 ↓
人工记录时间
 ↓
解压日志包
 ↓
搜索时间戳
 ↓
搜索Tag
 ↓
定位问题
```

当日志包达到数百 MB 甚至数 GB 时，定位问题会非常耗时。

Logcat Agent 将这一过程自动化。

## 当前功能

- 视频时间戳 OCR 识别
- Android Export Log 自动解压
- ZIP / tar.lz4 处理
- OCR 时间自动定位日志
- Tag 辅助搜索
- 一键跳转 Sublime Text
- Flutter 桌面端界面

## 技术架构

```text
Flutter
 │
 ├─ 视频播放
 ├─ 拖拽日志包
 └─ UI交互
 │
 ▼
Rust
 │
 ├─ ZIP解压
 ├─ tar.lz4解压
 └─ 日志目录整理
 │
 ▼
Python
 │
 ├─ CRNN OCR
 ├─ 时间戳识别
 ├─ 日志搜索
 └─ Sublime联动
 │
 ▼
Sublime Text
 │
 └─ 打开并定位日志
```

## 技术栈

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

### Platform

- Linux
- Ubuntu
- Android Logcat

## 工作流程

```text
拖入录屏
 ↓
拖入日志ZIP
 ↓
定位问题时间点
 ↓
OCR识别时间戳
 ↓
Rust自动解压日志
 ↓
Python搜索日志
 ↓
Sublime打开对应位置
```

## 项目定位

适用于：

- Android App 开发
- Android Framework
- AOSP 开发
- ROM 开发
- Kernel 开发
- 测试工程师
- 系统调试工程师

## Roadmap

### v1

- [x] Flutter桌面端
- [x] 视频时间戳OCR
- [x] ZIP日志解压
- [x] tar.lz4解压
- [x] Sublime联动

### v2

- [ ] AI日志分析
- [ ] ChatGPT集成
- [ ] 多日志包搜索
- [ ] 自动问题归因

### v3

- [ ] Agent模式
- [ ] 自动生成分析报告
- [ ] Android问题诊断助手

## Star

如果项目对你有帮助，欢迎 Star ⭐

Repository:
https://github.com/qli917/logcat_agent
