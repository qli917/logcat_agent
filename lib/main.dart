import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive_io.dart';
import 'package:bitsdojo_window/bitsdojo_window.dart';
import 'package:debugvideoagent/AppTitleBar.dart';
import 'package:desktop_drop/desktop_drop.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'src/rust/api/simple.dart';
import 'src/rust/frb_generated.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();

  await RustLib.init();

  try {
    await initPythonEngine();
    print("Python OCR 服务已启动");
  } catch (e) {
    print("Python OCR 启动失败: $e");
  }

  runApp(const MyApp());

  doWhenWindowReady(() {
    appWindow.minSize = const Size(1300, 800);
    appWindow.size = const Size(1600, 920);
    appWindow.alignment = Alignment.center;
    appWindow.title = "debugvideoagent";
    appWindow.show();
  });
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'debugvideoagent',
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        fontFamily: "Sans",
        scaffoldBackgroundColor: const Color(0xff07111f),
        colorSchemeSeed: Colors.blue,
      ),
      home: const DropArea(),
    );
  }
}

class SubtitleSegment {
  final double start;
  final double end;
  final String text;

  const SubtitleSegment({
    required this.start,
    required this.end,
    required this.text,
  });

  factory SubtitleSegment.fromJson(Map<String, dynamic> json) {
    return SubtitleSegment(
      start: (json['start'] as num?)?.toDouble() ?? 0,
      end: (json['end'] as num?)?.toDouble() ?? 0,
      text: (json['text'] ?? '').toString(),
    );
  }

  bool contains(Duration position) {
    final seconds = position.inMilliseconds / 1000.0;
    return seconds >= start && seconds <= end;
  }
}

class DropArea extends StatefulWidget {
  const DropArea({super.key});

  @override
  State<DropArea> createState() => _DropAreaState();
}

class _DropAreaState extends State<DropArea> {
  static const _tagKeywordCacheKey = "tag_keyword";
  static const _sourceDirCacheKey = "source_dir";

  late final Player player = Player();

  late final VideoController controller = VideoController(
    player,
    configuration: const VideoControllerConfiguration(
      enableHardwareAcceleration: false,
    ),
  );

  String? videoPath;
  String? zipPath;

  String? selectedZipDir;
  List<String> zipDirs = [];

  final sourceDirController = TextEditingController(
    text: Directory.current.path,
  );
  final tagController = TextEditingController();
  final rangeController = TextEditingController(text: "500");

  List<String> logs = [];
  List<SubtitleSegment> subtitles = [];
  String bugDescription = "";
  String? subtitlesPath;
  String voiceStatus = "";
  Map<String, dynamic>? _lastLogFlow;
  bool _isFlowLoading = false;
  static const int _flowPageSize = 100;

  bool _isProcessing = false;
  bool _isVoiceProcessing = false;
  bool _disposed = false;
  int _voiceJobId = 0;
  String? _transcribingVideoPath;

  double _actionOpacity = 0.2;
  Timer? _actionOpacityTimer;

  Duration _currentPosition = Duration.zero;
  Duration _duration = Duration.zero;
  bool _isPlaying = false;

  StreamSubscription<Duration>? _positionSub;
  StreamSubscription<Duration>? _durationSub;
  StreamSubscription<bool>? _playingSub;

  @override
  void initState() {
    super.initState();

    _loadCachedTagKeyword();
    _loadCachedSourceDir();
    tagController.addListener(_saveTagKeyword);

    _positionSub = player.stream.position.listen((position) {
      trySetState(() {
        _currentPosition = position;
      });
    });

    _durationSub = player.stream.duration.listen((duration) {
      trySetState(() {
        _duration = duration;
      });
    });

    _playingSub = player.stream.playing.listen((playing) {
      trySetState(() {
        _isPlaying = playing;
      });
    });

    if (player.platform is NativePlayer) {
      final nativePlayer = player.platform as NativePlayer;
      nativePlayer.setProperty('hwdec', 'no');
      nativePlayer.setProperty('ao', 'null');
    }
  }

  @override
  void dispose() {
    _disposed = true;

    _actionOpacityTimer?.cancel();
    _positionSub?.cancel();
    _durationSub?.cancel();
    _playingSub?.cancel();

    tagController.removeListener(_saveTagKeyword);
    sourceDirController.dispose();
    tagController.dispose();
    rangeController.dispose();

    try {
      stopPythonEngine();
    } catch (_) {}

    try {
      player.dispose();
    } catch (_) {}

    super.dispose();
  }

  void trySetState(VoidCallback fn) {
    try {
      if (!mounted || _disposed) return;
      setState(fn);
    } catch (_) {}
  }

  Future<void> _loadCachedTagKeyword() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final cachedTag = prefs.getString(_tagKeywordCacheKey);

      if (cachedTag == null || !mounted || _disposed) return;

      tagController.text = cachedTag;
    } catch (_) {}
  }

  Future<void> _saveTagKeyword() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_tagKeywordCacheKey, tagController.text);
    } catch (_) {}
  }

  Future<void> _loadCachedSourceDir() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final cachedSourceDir = prefs.getString(_sourceDirCacheKey);

      if (cachedSourceDir == null || !mounted || _disposed) return;
      if (!Directory(cachedSourceDir).existsSync()) return;

      sourceDirController.text = cachedSourceDir;
    } catch (_) {}
  }

  Future<void> _saveSourceDir(String path) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_sourceDirCacheKey, path);
    } catch (_) {}
  }

  Map<String, dynamic> _decodePythonJson(
    http.Response response,
    String apiName,
  ) {
    try {
      final decoded = jsonDecode(response.body);

      if (decoded is Map<String, dynamic>) {
        return decoded;
      }

      throw const FormatException("response is not a JSON object");
    } catch (_) {
      final preview = response.body.trim().replaceAll(RegExp(r"\s+"), " ");
      final message = response.statusCode == 404
          ? "Python 服务不支持 $apiName 接口，可能 5000 端口上运行的是旧版服务。请重启应用，或先停止占用 5000 端口的 python/flask 进程。"
          : "Python 返回的不是 JSON";

      throw Exception(
        "$message\nHTTP ${response.statusCode}\n${preview.length > 240 ? preview.substring(0, 240) : preview}",
      );
    }
  }

  Future<void> _ensureTranscribeApiReady() async {
    final response = await http
        .get(Uri.parse("http://127.0.0.1:5000/debug_path"))
        .timeout(const Duration(seconds: 5));
    final data = _decodePythonJson(response, "/debug_path");

    if (response.statusCode != 200 || !data.containsKey("subtitle_root")) {
      throw Exception("当前 Python 服务不支持语音字幕接口，请重启应用，或停止旧的 5000 端口服务后再试。");
    }
  }

  String fileName(String? path) {
    if (path == null || path.isEmpty) return "未加载";
    return path.split('/').last;
  }

  String _formatDuration(Duration d) {
    final minutes = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final seconds = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    final ms = d.inMilliseconds.remainder(1000).toString().padLeft(3, '0');
    return "$minutes:$seconds.$ms";
  }

  void _showActionButton() {
    if (_disposed || !mounted) return;

    _actionOpacityTimer?.cancel();

    trySetState(() {
      _actionOpacity = 1.0;
    });

    _actionOpacityTimer = Timer(const Duration(seconds: 2), () {
      if (_disposed || !mounted || _isProcessing) return;

      trySetState(() {
        _actionOpacity = 0.2;
      });
    });
  }

  Widget _buildFloatingStartButton() {
    return Positioned(
      right: 28,
      bottom: 76,
      child: MouseRegion(
        onEnter: (_) => _showActionButton(),
        child: AnimatedOpacity(
          opacity: _isProcessing ? 1.0 : _actionOpacity,
          duration: const Duration(milliseconds: 250),
          child: GestureDetector(
            onTapDown: (_) => _showActionButton(),
            onTap: _isProcessing
                ? null
                : () {
                    if (_disposed || !mounted) return;
                    unawaited(_startProcess());
                  },
            child: Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: const LinearGradient(
                  colors: [Color(0xff2563eb), Color(0xff38bdf8)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                boxShadow: [
                  BoxShadow(
                    color: Colors.blue.withOpacity(0.45),
                    blurRadius: 24,
                    offset: const Offset(0, 8),
                  ),
                ],
              ),
              child: Center(
                child: _isProcessing
                    ? const SizedBox(
                        width: 26,
                        height: 26,
                        child: CircularProgressIndicator(
                          strokeWidth: 3,
                          color: Colors.white,
                        ),
                      )
                    : Icon(
                        _isPlaying ? Icons.pause : Icons.play_arrow,
                        color: Colors.white,
                        size: 36,
                      ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _loadZipDirs(String path) async {
    try {
      final bytes = await File(path).readAsBytes();

      if (_disposed || !mounted) return;

      final archive = ZipDecoder().decodeBytes(bytes);
      final dirs = <String>{};

      for (final file in archive.files) {
        final name = file.name.replaceAll('\\', '/');
        final parts = name.split('/').where((e) => e.isNotEmpty).toList();

        if (parts.length >= 2) {
          for (int i = 1; i < parts.length; i++) {
            dirs.add(parts.sublist(0, i).join('/'));
          }
        }
      }

      final list = dirs.toList()..sort();

      trySetState(() {
        zipDirs = list;
        selectedZipDir = list.isNotEmpty ? list.first : null;
      });
    } catch (_) {
      trySetState(() {
        zipDirs = [];
        selectedZipDir = null;
      });
    }
  }

  Future<void> _pickVideo() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['mp4', 'avi', 'mov', 'mkv'],
      );

      if (_disposed || !mounted) return;

      if (result != null && result.files.single.path != null) {
        await _loadVideo(result.files.single.path!);
      }
    } catch (_) {}
  }

  Future<void> _loadVideo(String path) async {
    final voiceJobId = ++_voiceJobId;

    trySetState(() {
      videoPath = path;
      _currentPosition = Duration.zero;
      _duration = Duration.zero;
      subtitles.clear();
      bugDescription = "";
      subtitlesPath = null;
      voiceStatus = "等待自动识别语音字幕...";
      _isVoiceProcessing = false;
      _transcribingVideoPath = null;
      _lastLogFlow = null;
    });

    await player.open(Media(path), play: false);

    if (_disposed || !mounted || videoPath != path) return;

    unawaited(_extractBugVoice(sourceVideoPath: path, voiceJobId: voiceJobId));
  }

  void _resetConditions() {
    final subtitleFile = subtitlesPath;

    trySetState(() {
      _voiceJobId++;
      _isVoiceProcessing = false;
      _transcribingVideoPath = null;
      videoPath = null;
      _currentPosition = Duration.zero;
      _duration = Duration.zero;
      _isPlaying = false;
      subtitles.clear();
      bugDescription = "";
      subtitlesPath = null;
      voiceStatus = "";
      _lastLogFlow = null;
      logs.clear();
      tagController.clear();
      rangeController.text = "500";
    });

    try {
      player.stop();
    } catch (_) {}

    if (subtitleFile != null && subtitleFile.isNotEmpty) {
      try {
        final file = File(subtitleFile);
        if (file.existsSync()) {
          file.deleteSync();
        }
      } catch (_) {}
    }
  }

  String _currentSubtitleText() {
    final index = _subtitleIndexAt(_currentPosition);
    return index == -1 ? "" : subtitles[index].text;
  }

  int _subtitleIndexAt(Duration position) {
    for (var i = 0; i < subtitles.length; i++) {
      if (subtitles[i].contains(position)) {
        return i;
      }
    }

    return -1;
  }

  Future<void> _extractBugVoice({
    String? sourceVideoPath,
    int? voiceJobId,
  }) async {
    final targetVideoPath = sourceVideoPath ?? videoPath;
    final currentVoiceJobId = voiceJobId ?? ++_voiceJobId;

    if (_disposed || !mounted) return;

    if (_isVoiceProcessing && _transcribingVideoPath == targetVideoPath) {
      return;
    }

    if (targetVideoPath == null) {
      trySetState(() {
        logs.insert(0, "缺少视频\n请先拖入或选择视频文件");
      });
      return;
    }

    trySetState(() {
      _isVoiceProcessing = true;
      _transcribingVideoPath = targetVideoPath;
      voiceStatus = "正在检查 Python 语音服务...";
      logs.insert(0, "开始自动语音识别\n视频: ${fileName(targetVideoPath)}");
    });

    try {
      await _ensureTranscribeApiReady();

      if (_isStaleVoiceJob(currentVoiceJobId, targetVideoPath)) return;

      trySetState(() {
        voiceStatus = "正在从录屏中抽取音频...";
      });

      final audioPath = await extractAudioFromVideo(videoPath: targetVideoPath);

      if (_isStaleVoiceJob(currentVoiceJobId, targetVideoPath)) return;

      trySetState(() {
        voiceStatus = "正在识别语音字幕，首次加载 Whisper 可能较慢...";
      });

      final uri = Uri.parse(
        "http://127.0.0.1:5000/transcribe",
      ).replace(queryParameters: {'audio_path': audioPath});

      final response = await http.get(uri).timeout(const Duration(minutes: 5));

      if (_isStaleVoiceJob(currentVoiceJobId, targetVideoPath)) return;

      final data = _decodePythonJson(response, "/transcribe");

      if (response.statusCode != 200) {
        final error = data['error'] ?? "未知错误";
        throw Exception("语音识别失败: $error");
      }

      final rawSubtitles = data['subtitles'];
      final parsedSubtitles = rawSubtitles is List
          ? rawSubtitles
                .whereType<Map<String, dynamic>>()
                .map(SubtitleSegment.fromJson)
                .toList()
          : <SubtitleSegment>[];

      trySetState(() {
        subtitles = parsedSubtitles;
        bugDescription = (data['bug_description'] ?? '').toString();
        subtitlesPath = (data['subtitles_path'] ?? '').toString();
        voiceStatus = "";
        _isVoiceProcessing = false;
        _transcribingVideoPath = null;
        logs.insert(
          0,
          "语音识别完成\n音频: $audioPath\n字幕: ${subtitlesPath ?? ""}\n"
          "字幕片段: ${subtitles.length}\n\nBug描述:\n$bugDescription",
        );
      });
    } catch (e) {
      if (_disposed || !mounted) return;
      if (_isStaleVoiceJob(currentVoiceJobId, targetVideoPath)) return;

      trySetState(() {
        _isVoiceProcessing = false;
        _transcribingVideoPath = null;
        voiceStatus = "";
        logs.insert(0, "语音识别异常\n$e");
      });
    }
  }

  bool _isStaleVoiceJob(int voiceJobId, String targetVideoPath) {
    return _disposed ||
        !mounted ||
        voiceJobId != _voiceJobId ||
        videoPath != targetVideoPath;
  }

  Future<bool> _startProcess() async {
    if (_disposed || !mounted || _isProcessing) return false;

    _showActionButton();

    if (_isPlaying) {
      try {
        await player.pause();
      } catch (_) {}

      await Future.delayed(const Duration(milliseconds: 150));
    }

    if (videoPath == null || zipPath == null) {
      trySetState(() {
        logs.insert(0, "缺少文件\n请先拖入视频和 ZIP 文件");
      });
      return false;
    }

    final timeMs = _currentPosition.inMilliseconds.clamp(0, 1 << 31).toDouble();

    trySetState(() {
      _isProcessing = true;
    });

    String log = "";

    log += "开始处理\n";
    log += "视频: ${fileName(videoPath)}\n";
    log += "ZIP: ${fileName(zipPath)}\n";
    log += "当前时间: ${timeMs.toInt()} ms\n";
    log += "ZIP目录: ${selectedZipDir ?? "未选择"}\n";
    log +=
        "Tag: ${tagController.text.trim().isEmpty ? "无" : tagController.text.trim()}\n";
    log += "范围: ±${rangeController.text}ms\n\n";

    try {
      log += "[1/2] Python OCR 识别视频时间戳中...\n";

      final uri = Uri.parse("http://127.0.0.1:5000/ocr").replace(
        queryParameters: {
          'path': videoPath!,
          'time': timeMs.toString(),
          'search': '0',
        },
      );

      final response = await http.get(uri).timeout(const Duration(seconds: 20));

      if (_disposed || !mounted) return false;

      Map<String, dynamic> data;

      try {
        data = jsonDecode(response.body);
      } catch (_) {
        throw Exception("Python 返回的不是 JSON:\n${response.body}");
      }

      if (response.statusCode != 200) {
        final error = data['error'] ?? "未知错误";
        throw Exception("OCR失败: $error");
      }

      final timestamp = data['timestamp'] ?? "";
      final tag = tagController.text.trim();
      final logDir = await getLogDir(zipInnerDir: selectedZipDir ?? "");

      log += "OCR识别成功\n";
      log += "时间戳: $timestamp\n\n";
      log += "[2/2] Python 打开 Sublime 中...\n";

      final response2 = await http
          .post(
            Uri.parse("http://127.0.0.1:5000/open_by_timestamp"),
            headers: const {"Content-Type": "application/json"},
            body: jsonEncode({
              "timestamp": timestamp.toString(),
              "tag": tag,
              "log_dir": logDir,
            }),
          )
          .timeout(const Duration(seconds: 10));

      if (_disposed || !mounted) return false;

      Map<String, dynamic> openResult;

      try {
        openResult = _decodePythonJson(response2, "/open_by_timestamp");
      } catch (e) {
        openResult = {
          "success": false,
          "error": e.toString().replaceFirst("Exception: ", ""),
          "raw": response2.body,
          "status": response2.statusCode,
        };
      }

      if (response2.statusCode != 200 && response2.statusCode != 404) {
        throw Exception("Python 打开 Sublime 失败: ${response2.body}");
      }

      final hit = openResult["hit"];
      final flow = {
        "timestamp": timestamp,
        "tag": tag,
        "log_dir": logDir,
        "sublime": openResult,
        "hit_file": hit is Map ? (hit["file"] ?? "").toString() : "",
        "hit_line": hit is Map ? hit["line"] : 1,
      };
      final found = openResult["success"] == true;

      log += found ? "Python 已打开 Sublime\n" : "Python 未能定位日志\n";
      log += "日志目录: $logDir\n";
      log += "命中: ${hit ?? openResult["error"] ?? ""}\n";

      trySetState(() {
        _isProcessing = false;
        _lastLogFlow = flow;
        logs.insert(0, log);
      });

      _showActionButton();
      return true;
    } catch (e) {
      if (_disposed || !mounted) return false;

      log += "\n异常:\n$e";

      trySetState(() {
        _isProcessing = false;
        logs.insert(0, log);
      });

      _showActionButton();
      return false;
    }
  }

  Map<String, dynamic> _decodeRustSearchResult(String payload) {
    try {
      final decoded = jsonDecode(payload);

      if (decoded is Map) {
        return Map<String, dynamic>.from(decoded);
      }
    } catch (_) {}

    return {
      "success": false,
      "error": "Rust 返回的不是检索 JSON",
      "raw": payload,
      "hit": null,
      "current_file_tag_lines": <Map<String, dynamic>>[],
      "current_file_tag_total": 0,
    };
  }

  Widget _glassCard({
    required Widget child,
    EdgeInsets padding = const EdgeInsets.all(16),
  }) {
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: const Color(0xff0f1c2e).withOpacity(0.92),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xff1d3554)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.35),
            blurRadius: 24,
            offset: const Offset(0, 12),
          ),
        ],
      ),
      child: child,
    );
  }

  Widget _buildVideoArea() {
    if (videoPath == null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.video_file_outlined,
              size: 64,
              color: Color(0xff55aaff),
            ),
            const SizedBox(height: 16),
            const Text(
              "拖拽视频文件到这里",
              style: TextStyle(
                color: Colors.white70,
                fontSize: 20,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: _pickVideo,
              icon: const Icon(Icons.folder_open),
              label: const Text("选择视频"),
            ),
          ],
        ),
      );
    }

    return Column(
      children: [
        Expanded(
          child: Stack(
            fit: StackFit.expand,
            children: [
              Video(
                key: ValueKey(videoPath),
                controller: controller,

                // 关键：禁用 media_kit_video 默认控制条
                // 1.1.10 版本用这个方式
                controls: (_) => const SizedBox.shrink(),
              ),
              _buildVideoSubtitleOverlay(),
            ],
          ),
        ),
        _buildNativeProgressBar(),
      ],
    );
  }

  Widget _buildVideoSubtitleOverlay() {
    final text = _currentSubtitleText();
    final displayText = text.isEmpty
        ? (_isVoiceProcessing
              ? voiceStatus
              : videoPath == null
              ? ""
              : "等待自动识别字幕")
        : text;

    if (displayText.isEmpty) {
      return const SizedBox.shrink();
    }

    return IgnorePointer(
      child: Align(
        alignment: Alignment.bottomCenter,
        child: Container(
          margin: const EdgeInsets.fromLTRB(18, 0, 18, 18),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          constraints: const BoxConstraints(maxWidth: 780),
          decoration: BoxDecoration(
            color: const Color(0xff050b16).withValues(alpha: 0.62),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: const Color(0xff1d3554)),
          ),
          child: Text(
            displayText,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 15,
              height: 1.35,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildNativeProgressBar() {
    final durationMs = _duration.inMilliseconds <= 0
        ? 1
        : _duration.inMilliseconds;

    final positionMs = _currentPosition.inMilliseconds.clamp(0, durationMs);

    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      decoration: const BoxDecoration(
        color: Color(0xff050b16),
        border: Border(top: BorderSide(color: Color(0xff1d3554))),
      ),
      child: Row(
        children: [
          IconButton(
            onPressed: () {
              if (_isPlaying) {
                player.pause();
              } else {
                player.play();
              }
            },
            icon: Icon(
              _isPlaying ? Icons.pause : Icons.play_arrow,
              color: Colors.white70,
            ),
          ),
          Text(
            _formatDuration(Duration(milliseconds: positionMs)),
            style: const TextStyle(color: Colors.white54, fontSize: 12),
          ),
          Expanded(
            child: SliderTheme(
              data: SliderTheme.of(context).copyWith(
                trackHeight: 3,
                thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 7),
              ),
              child: Slider(
                value: positionMs.toDouble(),
                min: 0,
                max: durationMs.toDouble(),

                onChangeStart: (_) {
                  _showActionButton();
                },

                // 拖动时画面实时跟着走
                onChanged: (value) {
                  final target = Duration(milliseconds: value.toInt());

                  trySetState(() {
                    _currentPosition = target;
                  });

                  try {
                    player.seek(target);
                  } catch (_) {}
                },

                // 松手后再校准一次
                onChangeEnd: (value) {
                  final target = Duration(milliseconds: value.toInt());

                  trySetState(() {
                    _currentPosition = target;
                  });

                  try {
                    player.seek(target);
                  } catch (_) {}
                },
              ),
            ),
          ),
          Text(
            _formatDuration(_duration),
            style: const TextStyle(color: Colors.white54, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _buildVideoPanel() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 20, 10, 20),
      child: Column(
        children: [
          Expanded(
            child: _glassCard(
              padding: const EdgeInsets.all(14),
              child: Column(
                children: [
                  Row(
                    children: [
                      const Icon(
                        Icons.travel_explore,
                        color: Color(0xff3bbcff),
                        size: 20,
                      ),
                      const SizedBox(width: 8),
                      const Text(
                        "视频预览",
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 15,
                        ),
                      ),
                      const Spacer(),
                      if (_isVoiceProcessing)
                        const Row(
                          children: [
                            SizedBox(
                              width: 14,
                              height: 14,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                            SizedBox(width: 8),
                            Text(
                              "自动识别中",
                              style: TextStyle(
                                color: Colors.white54,
                                fontSize: 12,
                              ),
                            ),
                          ],
                        )
                      else if (subtitles.isNotEmpty)
                        const Row(
                          children: [
                            Icon(
                              Icons.subtitles_outlined,
                              color: Color(0xff38bdf8),
                              size: 16,
                            ),
                            SizedBox(width: 6),
                            Text(
                              "字幕已同步",
                              style: TextStyle(
                                color: Colors.white54,
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  Expanded(
                    child: Container(
                      width: double.infinity,
                      clipBehavior: Clip.antiAlias,
                      decoration: BoxDecoration(
                        color: Colors.black,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: const Color(0xff1d3554)),
                      ),
                      child: _buildVideoArea(),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRightPanel() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 20, 20, 20),
      child: Column(children: [Expanded(child: _buildLogCard())]),
    );
  }

  Future<void> _showLogFlowDialog() async {
    if (_lastLogFlow == null) {
      return;
    }

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) {
        return const AlertDialog(
          backgroundColor: Color(0xff0b1626),
          content: SizedBox(
            width: 260,
            child: Row(
              children: [
                SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                SizedBox(width: 12),
                Text(
                  "正在加载当前文件 Tag 汇总...",
                  style: TextStyle(color: Colors.white70, fontSize: 13),
                ),
              ],
            ),
          ),
        );
      },
    );

    await _loadTagSummaryIfNeeded();

    if (_disposed || !mounted || _lastLogFlow == null) return;

    Navigator.of(context, rootNavigator: true).pop();

    final flow = _lastLogFlow!;
    var visibleCount = _flowPageSize;

    showDialog(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return Dialog(
              backgroundColor: const Color(0xff0b1626),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
                side: const BorderSide(color: Color(0xff1d3554)),
              ),
              child: SizedBox(
                width: 980,
                height: 620,
                child: Column(
                  children: [
                    Container(
                      height: 54,
                      padding: const EdgeInsets.symmetric(horizontal: 18),
                      decoration: const BoxDecoration(
                        border: Border(
                          bottom: BorderSide(color: Color(0xff1d3554)),
                        ),
                      ),
                      child: Row(
                        children: [
                          const Icon(
                            Icons.account_tree_outlined,
                            color: Color(0xff38bdf8),
                            size: 20,
                          ),
                          const SizedBox(width: 10),
                          const Text(
                            "Tag日志汇总",
                            style: TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.bold,
                              fontSize: 16,
                            ),
                          ),
                          const Spacer(),
                          IconButton(
                            onPressed: () => Navigator.of(context).pop(),
                            icon: const Icon(
                              Icons.close,
                              color: Colors.white54,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Expanded(
                      child: SingleChildScrollView(
                        padding: const EdgeInsets.all(18),
                        child: _buildLogFlow(
                          flow,
                          visibleCount,
                          onLoadMore: (total) {
                            setDialogState(() {
                              visibleCount = (visibleCount + _flowPageSize)
                                  .clamp(_flowPageSize, total);
                            });
                          },
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Future<void> _loadTagSummaryIfNeeded() async {
    final flow = _lastLogFlow;
    if (flow == null || _isFlowLoading) return;

    final sublime = flow["sublime"];
    if (sublime is! Map) return;

    final hit = sublime["hit"];
    if (hit is! Map) return;

    final cachedLines = sublime["current_file_tag_lines"];
    if (cachedLines is List && cachedLines.isNotEmpty) return;

    final logDir = (flow["log_dir"] ?? "").toString();
    final tag = (flow["tag"] ?? "").toString();

    if (logDir.isEmpty || tag.trim().isEmpty) return;

    trySetState(() {
      _isFlowLoading = true;
    });

    try {
      final result = await processFiles(
        targetTimestamp: (flow["timestamp"] ?? "").toString(),
        zipPath: zipPath ?? "",
        zipInnerDir: selectedZipDir ?? "",
        tagKeyword: tag,
        rangeMs: int.tryParse(rangeController.text.trim()) ?? 0,
      );

      final decoded = _decodeRustSearchResult(result);
      final lines = decoded["current_file_tag_lines"];

      if (_disposed || !mounted || _lastLogFlow == null) return;

      final updatedSublime = Map<String, dynamic>.from(sublime);
      updatedSublime["current_file_tag_lines"] = lines is List
          ? lines
                .whereType<Map>()
                .map((item) => Map<String, dynamic>.from(item))
                .toList()
          : <Map<String, dynamic>>[];
      updatedSublime["current_file_tag_total"] =
          (updatedSublime["current_file_tag_lines"] as List).length;

      trySetState(() {
        _lastLogFlow = {...flow, "sublime": updatedSublime};
      });
    } finally {
      if (!_disposed && mounted) {
        trySetState(() {
          _isFlowLoading = false;
        });
      }
    }
  }

  Widget _buildLogFlow(
    Map<String, dynamic> flow,
    int visibleCount, {
    required void Function(int total) onLoadMore,
  }) {
    final sublime = flow["sublime"];
    final result = sublime is Map<String, dynamic>
        ? sublime
        : <String, dynamic>{};
    final hit = result["hit"] is Map<String, dynamic>
        ? result["hit"] as Map<String, dynamic>
        : <String, dynamic>{};
    final tagLines = result["current_file_tag_lines"] is List
        ? result["current_file_tag_lines"] as List
        : const [];
    final visibleItemsCount = tagLines.length < visibleCount
        ? tagLines.length
        : visibleCount;
    final success = result["success"] == true;
    final tag = (flow["tag"] ?? "").toString();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _tagLogSummary(
          tag: tag,
          timestamp: (flow["timestamp"] ?? "").toString(),
          file: (hit["file"] ?? "").toString(),
          hitLine: hit["line"],
          mode: (hit["mode"] ?? "").toString(),
          count: visibleItemsCount,
          success: success,
          error: (result["error"] ?? "").toString(),
        ),
        const SizedBox(height: 12),
        if (_isFlowLoading)
          _loadingSummary()
        else if (!success)
          _emptyTagLogPanel("未找到匹配日志")
        else if (tagLines.isEmpty)
          _emptyTagLogPanel("当前没有输入 Tag，或命中文件中没有同 Tag 的其他日志。")
        else
          _flowTagLines(
            tagLines,
            hit["line"],
            tag,
            (hit["file"] ?? "").toString(),
            visibleCount: visibleItemsCount,
            onLoadMore: onLoadMore,
            totalCount: tagLines.length,
          ),
      ],
    );
  }

  Widget _loadingSummary() {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xff102033),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xff1d3554)),
      ),
      child: const Row(
        children: [
          SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 12),
          Text(
            "正在加载当前文件 Tag 汇总...",
            style: TextStyle(color: Colors.white70, fontSize: 13),
          ),
        ],
      ),
    );
  }

  Widget _tagLogSummary({
    required String tag,
    required String timestamp,
    required String file,
    required dynamic hitLine,
    required String mode,
    required int count,
    required bool success,
    required String error,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xff102033),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: (success ? const Color(0xff38bdf8) : const Color(0xfffb7185))
              .withValues(alpha: 0.65),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                success ? Icons.manage_search : Icons.error_outline,
                color: success
                    ? const Color(0xff38bdf8)
                    : const Color(0xfffb7185),
                size: 18,
              ),
              const SizedBox(width: 8),
              Text(
                success ? "当前文件 Tag 汇总" : "检索失败",
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const Spacer(),
              Text(
                success ? "$count条" : error,
                style: TextStyle(
                  color: success ? Colors.white54 : const Color(0xfffb7185),
                  fontSize: 12,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          SelectableText(
            [
              "Tag: ${tag.isEmpty ? "无" : tag}",
              "时间戳: $timestamp",
              "模式: $mode",
              "命中行: $hitLine",
              "文件: $file",
            ].join("\n"),
            style: const TextStyle(
              color: Colors.white70,
              fontSize: 12,
              height: 1.45,
              fontFamily: "monospace",
            ),
          ),
        ],
      ),
    );
  }

  Widget _emptyTagLogPanel(String message) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xff102033),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xff1d3554)),
      ),
      child: Text(
        message,
        style: const TextStyle(color: Colors.white54, fontSize: 13),
      ),
    );
  }

  Future<void> _openLogHitInSublime(String file, int line) async {
    if (_disposed || !mounted || file.trim().isEmpty) return;

    try {
      final response = await http
          .post(
            Uri.parse("http://127.0.0.1:5000/open_log_hit"),
            headers: const {"Content-Type": "application/json"},
            body: jsonEncode({"file": file, "line": line}),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode != 200) {
        throw Exception(response.body);
      }
    } catch (e) {
      if (_disposed || !mounted) return;

      trySetState(() {
        logs.insert(0, "Sublime 跳转失败\n文件: $file\n行号: $line\n异常: $e");
      });
    }
  }

  Future<void> _openSourceForLogLine(String text) async {
    final sourceRoot = sourceDirController.text.trim();

    if (_disposed || !mounted || text.trim().isEmpty || sourceRoot.isEmpty) {
      return;
    }

    try {
      final response = await http
          .post(
            Uri.parse("http://127.0.0.1:5000/open_source_hit"),
            headers: const {"Content-Type": "application/json"},
            body: jsonEncode({"source_root": sourceRoot, "text": text}),
          )
          .timeout(const Duration(seconds: 8));

      if (response.statusCode != 200) {
        throw Exception(response.body);
      }

      final result = jsonDecode(response.body);
      if (result is Map) {
        trySetState(() {
          logs.insert(
            0,
            "源码跳转成功\n文件: ${result["file"]}\n行号: ${result["line"]}",
          );
        });
      }
    } catch (e) {
      if (_disposed || !mounted) return;

      trySetState(() {
        logs.insert(0, "源码跳转失败\n源码目录: $sourceRoot\n异常: $e");
      });
    }
  }

  Future<void> _pickSourceDirectory() async {
    try {
      final selectedDirectory = await FilePicker.platform.getDirectoryPath(
        dialogTitle: "选择项目源码目录",
        initialDirectory: sourceDirController.text.trim().isEmpty
            ? Directory.current.path
            : sourceDirController.text.trim(),
      );

      if (selectedDirectory == null || _disposed || !mounted) return;

      trySetState(() {
        sourceDirController.text = selectedDirectory;
      });

      await _saveSourceDir(selectedDirectory);
    } catch (e) {
      if (_disposed || !mounted) return;

      trySetState(() {
        logs.insert(0, "选择项目源码目录失败\n异常: $e");
      });
    }
  }

  Widget _flowTagLines(
    List<dynamic> tagLines,
    dynamic hitLine,
    String tag,
    String file, {
    required int visibleCount,
    required void Function(int total) onLoadMore,
    required int totalCount,
  }) {
    final hitLineNo = hitLine is num ? hitLine.toInt() : -1;
    final items = tagLines.toList().reversed.toList();
    final visibleItems = items.take(visibleCount).toList();
    final canLoadMore = visibleCount < items.length;

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xff26313d),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xff3b4652)),
      ),
      child: Column(
        children: [
          for (var i = 0; i < visibleItems.length; i++)
            _flowTagLine(
              item: visibleItems[i],
              tag: tag,
              file: file,
              isHit:
                  visibleItems[i] is Map &&
                  (visibleItems[i]["line"] is num) &&
                  (visibleItems[i]["line"] as num).toInt() == hitLineNo,
              isLast: i == visibleItems.length - 1 && !canLoadMore,
            ),
          if (canLoadMore)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
              child: SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: () {
                    onLoadMore(totalCount);
                  },
                  icon: const Icon(Icons.expand_more, size: 16),
                  label: Text("加载更多 (${visibleItems.length}/$totalCount)"),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _flowTagLine({
    required dynamic item,
    required String tag,
    required String file,
    required bool isHit,
    required bool isLast,
  }) {
    final data = item is Map ? item : const {};
    final line = data["line"] ?? "";
    final text = data["text"] ?? "";
    final lineNo = line is num ? line.toInt() : -1;

    return InkWell(
      onTap: file.trim().isEmpty || lineNo < 0
          ? null
          : () {
              unawaited(_openLogHitInSublime(file, lineNo));
            },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: isHit
              ? const Color(0xff1f3a2d).withValues(alpha: 0.9)
              : Colors.transparent,
          border: Border(
            bottom: BorderSide(
              color: isLast ? Colors.transparent : const Color(0xff3b4652),
            ),
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 56,
              child: Text(
                "$line:",
                textAlign: TextAlign.right,
                style: const TextStyle(
                  color: Color(0xffff5d63),
                  fontSize: 12,
                  fontFamily: "monospace",
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: SelectableText.rich(
                TextSpan(
                  children: _highlightTagSpans(text.toString(), tag, isHit),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton(
              tooltip: "打开源码",
              icon: const Icon(Icons.code, size: 18, color: Color(0xff86efac)),
              onPressed: text.toString().trim().isEmpty
                  ? null
                  : () {
                      unawaited(_openSourceForLogLine(text.toString()));
                    },
              constraints: const BoxConstraints.tightFor(width: 28, height: 28),
              padding: EdgeInsets.zero,
              visualDensity: VisualDensity.compact,
            ),
            IconButton(
              tooltip: "打开 Sublime",
              icon: const Icon(
                Icons.open_in_new,
                size: 18,
                color: Color(0xff7dd3fc),
              ),
              onPressed: file.trim().isEmpty || lineNo < 0
                  ? null
                  : () {
                      unawaited(_openLogHitInSublime(file, lineNo));
                    },
              constraints: const BoxConstraints.tightFor(width: 28, height: 28),
              padding: EdgeInsets.zero,
              visualDensity: VisualDensity.compact,
            ),
          ],
        ),
      ),
    );
  }

  List<TextSpan> _highlightTagSpans(String text, String tag, bool isHit) {
    final baseStyle = TextStyle(
      color: isHit ? const Color(0xffd1fae5) : const Color(0xffd7e0ea),
      fontSize: 12,
      height: 1.35,
      fontFamily: "monospace",
    );

    final query = tag.trim();

    if (query.isEmpty) {
      return [TextSpan(text: text, style: baseStyle)];
    }

    final lowerText = text.toLowerCase();
    final lowerQuery = query.toLowerCase();
    final spans = <TextSpan>[];
    var start = 0;

    while (true) {
      final index = lowerText.indexOf(lowerQuery, start);

      if (index < 0) {
        spans.add(TextSpan(text: text.substring(start), style: baseStyle));
        break;
      }

      if (index > start) {
        spans.add(
          TextSpan(text: text.substring(start, index), style: baseStyle),
        );
      }

      spans.add(
        TextSpan(
          text: text.substring(index, index + query.length),
          style: baseStyle.copyWith(
            color: const Color(0xffd8f3ff),
            backgroundColor: const Color(0xff2b5a70),
            fontWeight: FontWeight.w700,
          ),
        ),
      );

      start = index + query.length;
    }

    return spans;
  }

  Widget _buildLogCard() {
    return _glassCard(
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          Container(
            height: 54,
            padding: const EdgeInsets.symmetric(horizontal: 18),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Color(0xff1d3554))),
            ),
            child: const Row(
              children: [
                Icon(
                  Icons.assignment_outlined,
                  color: Color(0xff38bdf8),
                  size: 18,
                ),
                SizedBox(width: 8),
                Text(
                  "处理日志",
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                ),
              ],
            ),
          ),
          Expanded(
            child: logs.isEmpty
                ? const Center(
                    child: Text(
                      "暂无处理日志",
                      style: TextStyle(color: Colors.white38),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: logs.length,
                    itemBuilder: (context, index) {
                      return _logItem(index, logs[index]);
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _logItem(int index, String text) {
    final success = text.contains("成功") || text.contains("找到");
    final color = success ? const Color(0xff4ade80) : const Color(0xff93c5fd);

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 11,
            backgroundColor: color,
            child: Text(
              "${logs.length - index}",
              style: const TextStyle(fontSize: 11, color: Colors.white),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: SelectableText(
              text,
              style: TextStyle(
                color: success
                    ? const Color(0xff86efac)
                    : const Color(0xffbfdbfe),
                fontSize: 13,
                height: 1.55,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _handleDroppedFiles(List<dynamic> files) async {
    try {
      for (var file in files) {
        if (_disposed || !mounted) return;

        final path = file.path as String;

        if (path.endsWith('.mp4') ||
            path.endsWith('.avi') ||
            path.endsWith('.mov') ||
            path.endsWith('.mkv')) {
          await _loadVideo(path);

          if (_disposed || !mounted) return;
        } else if (path.endsWith('.zip')) {
          trySetState(() {
            zipPath = path;
            zipDirs = [];
            selectedZipDir = null;
            _lastLogFlow = null;
            logs.insert(0, "检测到ZIP文件\n${fileName(path)}\n\n开始自动解压...");
          });

          await _loadZipDirs(path);

          if (_disposed || !mounted) return;

          final unzipResult = await prepareLogsForZip(zipPath: path);

          if (_disposed || !mounted) return;

          trySetState(() {
            logs.insert(0, unzipResult);
          });
        }
      }
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return WindowBorder(
      color: const Color(0xff1d3554),
      width: 1,
      child: Scaffold(
        body: Column(
          children: [
            AppTitleBar(
              zipDirs: zipDirs,
              sourceDirController: sourceDirController,
              selectedZipDir: selectedZipDir,
              tagController: tagController,
              rangeController: rangeController,
              isProcessing: _isProcessing,
              hasLogFlow: _lastLogFlow != null,
              onZipDirChanged: (value) {
                trySetState(() {
                  selectedZipDir = value;
                });
              },
              onStart: null,
              onPickSourceDir: () {
                unawaited(_pickSourceDirectory());
              },
              onShowLogFlow: () {
                unawaited(_showLogFlowDialog());
              },
              onReset: _resetConditions,
            ),
            Expanded(
              child: Stack(
                children: [
                  DropTarget(
                    onDragDone: (detail) => _handleDroppedFiles(detail.files),
                    child: Container(
                      decoration: const BoxDecoration(
                        gradient: LinearGradient(
                          colors: [
                            Color(0xff050b16),
                            Color(0xff081426),
                            Color(0xff06101d),
                          ],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                      ),
                      child: Row(
                        children: [
                          Expanded(flex: 2, child: _buildVideoPanel()),
                          SizedBox(width: 620, child: _buildRightPanel()),
                        ],
                      ),
                    ),
                  ),
                  _buildFloatingStartButton(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
