import 'package:bitsdojo_window/bitsdojo_window.dart';
import 'package:flutter/material.dart';

class AppTitleBar extends StatelessWidget {
  final List<String> zipDirs;
  final String? selectedZipDir;
  final TextEditingController tagController;
  final TextEditingController rangeController;
  final bool isProcessing;
  final bool hasLogFlow;
  final ValueChanged<String?> onZipDirChanged;
  final VoidCallback? onStart;
  final VoidCallback? onShowLogFlow;
  final VoidCallback onReset;

  const AppTitleBar({
    super.key,
    required this.zipDirs,
    required this.selectedZipDir,
    required this.tagController,
    required this.rangeController,
    required this.isProcessing,
    required this.hasLogFlow,
    required this.onZipDirChanged,
    required this.onStart,
    required this.onShowLogFlow,
    required this.onReset,
  });

  @override
  Widget build(BuildContext context) {
    return WindowTitleBarBox(
      child: Container(
        height: 42,
        color: const Color(0xff181818),
        child: Row(
          children: [
            const SizedBox(width: 18),

            SizedBox(
              width: 500,
              height: 32,
              child: DropdownButtonFormField<String>(
                value: selectedZipDir,
                isExpanded: true,
                dropdownColor: const Color(0xff111f34),
                decoration: InputDecoration(
                  hintText: "拖入ZIP后自动读取目录",
                  hintStyle: const TextStyle(
                    color: Colors.white38,
                    fontSize: 12,
                  ),
                  filled: true,
                  fillColor: const Color(0xff242424),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: const BorderSide(color: Color(0xff333333)),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: const BorderSide(color: Color(0xff333333)),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 6,
                  ),
                ),
                items: zipDirs
                    .map(
                      (dir) => DropdownMenuItem(
                        value: dir,
                        child: Text(
                          dir,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: Colors.white70,
                          ),
                        ),
                      ),
                    )
                    .toList(),
                onChanged: zipDirs.isEmpty ? null : onZipDirChanged,
              ),
            ),

            const SizedBox(width: 10),

            SizedBox(
              width: 220,
              height: 32,
              child: TextField(
                controller: tagController,
                style: const TextStyle(color: Colors.white70, fontSize: 12),
                decoration: InputDecoration(
                  hintText: "Tag关键词",
                  hintStyle: const TextStyle(
                    color: Colors.white38,
                    fontSize: 12,
                  ),
                  filled: true,
                  fillColor: const Color(0xff242424),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: const BorderSide(color: Color(0xff333333)),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: const BorderSide(color: Color(0xff333333)),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 6,
                  ),
                ),
              ),
            ),

            const SizedBox(width: 10),

            SizedBox(
              width: 90,
              height: 32,
              child: TextField(
                controller: rangeController,
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white70, fontSize: 12),
                decoration: InputDecoration(
                  hintText: "±ms",
                  hintStyle: const TextStyle(
                    color: Colors.white38,
                    fontSize: 12,
                  ),
                  filled: true,
                  fillColor: const Color(0xff242424),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: const BorderSide(color: Color(0xff333333)),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: const BorderSide(color: Color(0xff333333)),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 6,
                  ),
                ),
              ),
            ),

            const SizedBox(width: 10),

            SizedBox(
              height: 32,
              child: OutlinedButton.icon(
                onPressed: onShowLogFlow,
                icon: const Icon(Icons.account_tree_outlined, size: 15),
                label: const Text("日志流程图", style: TextStyle(fontSize: 12)),
                style: OutlinedButton.styleFrom(
                  foregroundColor: hasLogFlow ? Colors.white60 : Colors.white38,
                  side: const BorderSide(color: Color(0xff333333)),
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(6),
                  ),
                ),
              ),
            ),

            const SizedBox(width: 10),

            SizedBox(
              height: 32,
              child: OutlinedButton.icon(
                onPressed: onReset,
                icon: const Icon(Icons.refresh, size: 15),
                label: const Text("重置", style: TextStyle(fontSize: 12)),
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.white60,
                  side: const BorderSide(color: Color(0xff333333)),
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(6),
                  ),
                ),
              ),
            ),

            Expanded(child: MoveWindow(child: const SizedBox.expand())),

            MinimizeWindowButton(
              colors: WindowButtonColors(
                iconNormal: Colors.white54,
                mouseOver: const Color(0xff333333),
                mouseDown: const Color(0xff444444),
              ),
            ),

            MaximizeWindowButton(
              colors: WindowButtonColors(
                iconNormal: Colors.white54,
                mouseOver: const Color(0xff333333),
                mouseDown: const Color(0xff444444),
              ),
            ),

            CloseWindowButton(
              colors: WindowButtonColors(
                iconNormal: Colors.white54,
                mouseOver: Colors.red,
                mouseDown: Colors.redAccent,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
