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

class DropArea extends StatefulWidget {
  const DropArea({super.key});

  @override
  State<DropArea> createState() => _DropAreaState();
}

class _DropAreaState extends State<DropArea> {
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

  final tagController = TextEditingController();
  final rangeController = TextEditingController(text: "500");

  List<String> logs = [];

  bool _isProcessing = false;
  bool _disposed = false;

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
                    _startProcess();
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
        final path = result.files.single.path!;

        trySetState(() {
          videoPath = path;
          _currentPosition = Duration.zero;
          _duration = Duration.zero;
        });

        await player.open(Media(path), play: false);
      }
    } catch (_) {}
  }

  void _resetConditions() {
    trySetState(() {
      selectedZipDir = zipDirs.isNotEmpty ? zipDirs.first : null;
      tagController.clear();
      rangeController.text = "500";
      logs.clear();
    });
  }

  Future<void> _startProcess() async {
    if (_disposed || !mounted || _isProcessing) return;

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
      return;
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
      log += "[1/2] Rust 解压日志中...\n";

      final rustResult = await processFiles(
        targetTimestamp: "",
        zipPath: zipPath!,
        zipInnerDir: selectedZipDir ?? "",
        tagKeyword: "",
        rangeMs: 0,
      );

      if (_disposed || !mounted) return;

      log += rustResult;
      log += "\n\n";

      final lines = rustResult
          .split('\n')
          .map((e) => e.trim())
          .where((e) => e.isNotEmpty)
          .toList();

      final logDir = lines.isNotEmpty ? lines.last : "";

      if (logDir.isEmpty || rustResult.contains("❌")) {
        throw Exception("日志解压失败，无法获取日志目录:\n$rustResult");
      }

      log += "[2/2] Python OCR + 日志检索中...\n";

      final uri = Uri.parse("http://127.0.0.1:5000/ocr").replace(
        queryParameters: {
          'path': videoPath!,
          'time': timeMs.toString(),
          'tag': tagController.text.trim(),
          'log_dir': logDir,
        },
      );

      final response = await http.get(uri).timeout(const Duration(seconds: 20));

      if (_disposed || !mounted) return;

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
      final sublime = data['sublime'];

      log += "OCR识别成功\n";
      log += "时间戳: $timestamp\n";
      log += "日志目录: $logDir\n\n";
      log += "Sublime检索结果:\n$sublime\n";

      trySetState(() {
        _isProcessing = false;
        logs.insert(0, log);
      });

      _showActionButton();
    } catch (e) {
      if (_disposed || !mounted) return;

      log += "\n异常:\n$e";

      trySetState(() {
        _isProcessing = false;
        logs.insert(0, log);
      });

      _showActionButton();
    }
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
          child: Video(
            key: ValueKey(videoPath),
            controller: controller,

            // 关键：禁用 media_kit_video 默认控制条
            // 1.1.10 版本用这个方式
            controls: (_) => const SizedBox.shrink(),
          ),
        ),
        _buildNativeProgressBar(),
      ],
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
                  const Row(
                    children: [
                      Icon(
                        Icons.travel_explore,
                        color: Color(0xff3bbcff),
                        size: 20,
                      ),
                      SizedBox(width: 8),
                      Text(
                        "视频预览",
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 15,
                        ),
                      ),
                      Icon(Icons.more_horiz, color: Colors.white70),
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
              "${index + 1}",
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
          trySetState(() {
            videoPath = path;
            _currentPosition = Duration.zero;
            _duration = Duration.zero;
          });

          await player.open(Media(path), play: false);

          if (_disposed || !mounted) return;
        } else if (path.endsWith('.zip')) {
          trySetState(() {
            zipPath = path;
            zipDirs = [];
            selectedZipDir = null;
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
              selectedZipDir: selectedZipDir,
              tagController: tagController,
              rangeController: rangeController,
              isProcessing: _isProcessing,
              onZipDirChanged: (value) {
                trySetState(() {
                  selectedZipDir = value;
                });
              },
              onStart: null,
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
