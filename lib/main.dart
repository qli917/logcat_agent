import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive_io.dart';
import 'package:debugvideoagent/AppTitleBar.dart';
import 'package:desktop_drop/desktop_drop.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:bitsdojo_window/bitsdojo_window.dart';

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
  late final player = Player();

  late final controller = VideoController(
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

  String statusTitle = "准备就绪";
  String statusSubTitle = "拖入视频和 ZIP 后开始检索";

  bool _isProcessing = false;

  double _actionOpacity = 0.2;
  Timer? _actionOpacityTimer;

  @override
  void initState() {
    super.initState();

    if (player.platform is NativePlayer) {
      final nativePlayer = player.platform as NativePlayer;
      nativePlayer.setProperty('hwdec', 'no');
      nativePlayer.setProperty('ao', 'null');
    }
  }

  @override
  void dispose() {
    tagController.dispose();
    rangeController.dispose();
    _actionOpacityTimer?.cancel();
    stopPythonEngine();
    player.dispose();
    super.dispose();
  }

  String fileName(String? path) {
    if (path == null || path.isEmpty) return "未加载";
    return path.split('/').last;
  }

  void _showActionButton() {
    _actionOpacityTimer?.cancel();

    if (mounted) {
      setState(() {
        _actionOpacity = 1.0;
      });
    }

    _actionOpacityTimer = Timer(const Duration(seconds: 2), () {
      if (mounted && !_isProcessing) {
        setState(() {
          _actionOpacity = 0.2;
        });
      }
    });
  }

  Widget _buildFloatingStartButton() {
    return Positioned(
      right: 28,
      bottom: 28,
      child: MouseRegion(
        onEnter: (_) => _showActionButton(),
        child: AnimatedOpacity(
          opacity: _isProcessing ? 1.0 : _actionOpacity,
          duration: const Duration(milliseconds: 250),
          child: GestureDetector(
            onTapDown: (_) => _showActionButton(),
            onTap: _isProcessing ? null : _startProcess,
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
                    : const Icon(
                        Icons.play_arrow,
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

      setState(() {
        zipDirs = list;
        selectedZipDir = list.isNotEmpty ? list.first : null;
      });
    } catch (e) {
      setState(() {
        zipDirs = [];
        selectedZipDir = null;
      });
    }
  }

  Future<void> _pickZip() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['zip'],
    );

    if (result != null && result.files.single.path != null) {
      final path = result.files.single.path!;

      setState(() {
        zipPath = path;
        zipDirs = [];
        selectedZipDir = null;
      });

      await _loadZipDirs(path);
    }
  }

  Future<void> _pickVideo() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['mp4', 'avi', 'mov', 'mkv'],
    );

    if (result != null && result.files.single.path != null) {
      final path = result.files.single.path!;

      setState(() {
        videoPath = path;
      });

      await player.open(Media(path), play: false);
    }
  }

  void _resetConditions() {
    setState(() {
      selectedZipDir = zipDirs.isNotEmpty ? zipDirs.first : null;
      tagController.clear();
      rangeController.text = "500";
      logs.clear();
      statusTitle = "准备就绪";
      statusSubTitle = "检索条件已重置";
    });
  }

  Future<void> _startProcess() async {
    if (_isProcessing) return;

    _showActionButton();

    if (videoPath == null || zipPath == null) {
      setState(() {
        statusTitle = "缺少文件";
        statusSubTitle = "请先拖入视频和 ZIP 文件";
      });
      return;
    }

    final timeMs = player.state.position.inMilliseconds.toDouble();

    setState(() {
      _isProcessing = true;
      statusTitle = "处理中";
      statusSubTitle = "正在进行 OCR 和日志检索";
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
      log += "[1/2] OCR识别中...\n";

      final uri = Uri.parse("http://127.0.0.1:5000/ocr").replace(
        queryParameters: {'path': videoPath, 'time': timeMs.toString()},
      );

      final response = await http.get(uri).timeout(const Duration(seconds: 10));

      if (response.statusCode != 200) {
        String error;

        try {
          error = jsonDecode(response.body)['error'] ?? "未知错误";
        } catch (_) {
          error = response.body;
        }

        log += "OCR失败: $error\n";

        setState(() {
          _isProcessing = false;
          statusTitle = "OCR失败";
          statusSubTitle = error.toString();
          logs.insert(0, log);
        });

        _showActionButton();
        return;
      }

      final data = jsonDecode(response.body);
      final timestamp = data['timestamp'] as String;

      log += "OCR识别成功\n";
      log += "时间戳: $timestamp\n\n";

      log += "[2/2] Rust日志搜索中...\n";

      final rustResult = await processFiles(
        targetTimestamp: timestamp,
        zipPath: zipPath!,
        zipInnerDir: selectedZipDir ?? "",
        tagKeyword: tagController.text.trim(),
        rangeMs: int.tryParse(rangeController.text) ?? 500,
      );

      log += "\n搜索结果:\n";
      log += rustResult;

      setState(() {
        _isProcessing = false;
        statusTitle = rustResult.contains("⚠️") ? "未找到" : "搜索成功";
        statusSubTitle = rustResult.contains("⚠️")
            ? "日志中未匹配到结果"
            : "已完成检索并找到匹配结果";

        logs.insert(0, log);
      });

      _showActionButton();
    } catch (e) {
      log += "\n异常:\n$e";

      setState(() {
        _isProcessing = false;
        statusTitle = "流程异常";
        statusSubTitle = e.toString();
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

    return Video(controller: controller);
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
    for (var file in files) {
      final path = file.path as String;

      if (path.endsWith('.mp4') ||
          path.endsWith('.avi') ||
          path.endsWith('.mov') ||
          path.endsWith('.mkv')) {
        setState(() {
          videoPath = path;
        });

        await player.open(Media(path), play: false);
      } else if (path.endsWith('.zip')) {
        setState(() {
          zipPath = path;
          zipDirs = [];
          selectedZipDir = null;
          logs.insert(0, "检测到ZIP文件\n${fileName(path)}\n\n开始自动解压...");
        });

        await _loadZipDirs(path);

        final unzipResult = await prepareLogsForZip(zipPath: path);

        setState(() {
          logs.insert(0, unzipResult);
        });
      }
    }
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
                setState(() {
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
